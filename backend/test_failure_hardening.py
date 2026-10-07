"""Concurrency and stale-worker regression tests for the persistent event state."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_store import EventError, EventStore

AGENT = 'def agent(obs):\n return {"farmer":["PASS"],"hands":[],"market":[]}\n'


class FailureHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = EventStore(root / "event.sqlite", root / "submissions")

    def tearDown(self):
        self.temp.cleanup()

    def _make_job(self):
        p = self.store.register_participant("FenceMe")
        self.store.open_submission_window(1)
        self.store.upload_submission(p["participant_id"], AGENT)
        self.store.lock_submission_window()
        self.store.start_evaluation_phase(1)
        return p, self.store.get_evaluation_jobs(1)[0]

    def test_parallel_registration_at_20_50_and_80(self):
        for count in (20, 50, 80):
            with self.subTest(participants=count):
                with tempfile.TemporaryDirectory() as temp:
                    root = Path(temp)
                    stores = [EventStore(root / "event.sqlite", root / "submissions") for _ in range(8)]
                    with ThreadPoolExecutor(max_workers=min(count, 32)) as pool:
                        results = list(pool.map(lambda i: stores[i % len(stores)].register_participant(f"Team_{i:03d}"), range(count)))
                    all_people = stores[0].list_participants()
                    self.assertEqual(len(all_people), count)
                    self.assertEqual(len({p["participant_id"] for p in all_people}), count)
                    self.assertEqual(len({p["username"].lower() for p in all_people}), count)
                    self.assertEqual(len(stores[0].get_standings()), count)

    def test_duplicate_username_and_transition_races_are_atomic(self):
        def register(name):
            try:
                return self.store.register_participant(name)
            except EventError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            created = list(pool.map(register, ("SameName", "samename")))
        self.assertEqual(sum(item is not None for item in created), 1)
        p = next(item for item in created if item)
        self.store.open_submission_window(1)
        self.store.upload_submission(p["participant_id"], AGENT)
        peer_store = EventStore(self.store.db_path, self.store.files_dir)

        def lock(store):
            try:
                return store.lock_submission_window()
            except EventError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            stores = (self.store, peer_store)
            self.assertEqual(sum(result is not None for result in pool.map(lock, stores)), 1)

        def start():
            try:
                return self.store.start_evaluation_phase(1)
            except EventError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(result is not None for result in pool.map(lambda _: start(), range(2))), 1)
        self.assertEqual(len(self.store.get_evaluation_jobs()), 1)

    def test_restart_recovery_fences_stale_worker_and_preserves_one_score(self):
        _, original = self._make_job()
        first_claim = self.store.claim_next_job(1)
        old_token = first_claim["claim_token"]

        restarted = EventStore(self.store.db_path, self.store.files_dir)
        self.assertEqual(restarted.recover_running_jobs(max_retries=2), 1)
        recovered = restarted.get_evaluation_jobs(1)[0]
        self.assertEqual(recovered["status"], "RETRYING")
        second_claim = restarted.claim_next_job(1)
        self.assertEqual(second_claim["attempts"], 2)

        self.assertFalse(restarted.finish_job(original["job_id"], "SUCCESS", 999, claim_token=old_token))
        self.assertTrue(restarted.finish_job(original["job_id"], "SUCCESS", 50, claim_token=second_claim["claim_token"]))
        self.assertFalse(restarted.finish_job(original["job_id"], "SUCCESS", 999, claim_token=second_claim["claim_token"]))

        conn = restarted._connect()
        try:
            raw = conn.execute("SELECT COUNT(*) FROM evaluation_results WHERE job_id=?", (original["job_id"],)).fetchone()[0]
            event_number = conn.execute("SELECT event_number FROM evaluation_results WHERE job_id=?", (original["job_id"],)).fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(raw, 1)
        self.assertEqual(event_number, 1)
        restarted.begin_result_processing(1)
        self.assertEqual(restarted.get_round_scores(1)[0]["score"], 50)

    def test_old_event_job_is_cancelled_on_restart_and_cannot_affect_new_event(self):
        old_participant, old_job = self._make_job()
        # A normal reset refuses queued work. Finish this event, then reproduce a
        # legacy orphan row left behind by the pre-event-number job writer.
        old_claim = self.store.claim_next_job(1)
        self.assertTrue(self.store.finish_job(old_job["job_id"], "SUCCESS", 10, claim_token=old_claim["claim_token"]))
        self.store.reset_event()

        current = self.store.register_participant("EventTwo")
        self.store.open_submission_window(1)
        self.store.upload_submission(current["participant_id"], AGENT)
        self.store.lock_submission_window()
        self.store.start_evaluation_phase(1)
        current_job = self.store.get_evaluation_jobs(1)[0]
        self.assertEqual(current_job["event_number"], 2)

        # Restore the exact dangerous shape: an active Event 1 row shares the
        # current participant/submission IDs but keeps its original event tag.
        conn = self.store._connect()
        try:
            conn.execute(
                "INSERT INTO evaluation_batches "
                "(event_number, round_number, batch_id, status, started_at, finished_at) "
                "VALUES (1, 1, ?, 'STARTED', ?, NULL)",
                (old_job["batch_id"], old_job["started_at"] or "legacy-start"),
            )
            conn.execute(
                "INSERT INTO evaluation_jobs "
                "(job_id, batch_id, participant_id, submission_id, round_number, event_number, seed, "
                "status, attempts, claim_token, started_at, score, error_type, error_message, updated_at) "
                "VALUES (?, ?, ?, ?, 1, 1, ?, 'RUNNING', 1, 'old-worker-token', ?, 999, NULL, NULL, ?)",
                (
                    "legacy-event-one-job", old_job["batch_id"], current["participant_id"],
                    current_job["submission_id"], old_job["seed"], old_job["started_at"], old_job["updated_at"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

        import evaluation_queue
        restarted = EventStore(self.store.db_path, self.store.files_dir)
        queue = evaluation_queue.EvaluationQueue(restarted)
        executed = []

        def fake_execute(job):
            executed.append((job["event_number"], job["job_id"]))
            restarted.finish_job(job["job_id"], "SUCCESS", 66, claim_token=job["claim_token"])

        queue._execute = fake_execute
        try:
            stale = restarted.get_evaluation_jobs(1, event_number=1)[0]
            self.assertEqual(stale["status"], "CANCELLED")
            self.assertIsNone(stale["claim_token"])
            self.assertEqual(stale["error_type"], "STALE_EVENT")
            self.assertIsNone(restarted.claim_job(stale["job_id"]))
            self.assertEqual(restarted.get_state()["evaluation_batches"], [
                batch for batch in restarted.get_state()["evaluation_batches"] if batch["event_number"] == 2
            ])

            queue.start(1)
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and restarted.get_evaluation_jobs(1)[0]["status"] != "SUCCESS":
                time.sleep(0.01)
            self.assertEqual(executed, [(2, current_job["job_id"])])
            self.assertEqual(restarted.get_evaluation_jobs(1)[0]["status"], "SUCCESS")
            self.assertFalse(restarted.finish_job(stale["job_id"], "SUCCESS", 999, claim_token="old-worker-token"))

            restarted.begin_result_processing(1)
            self.assertEqual(restarted.get_round_scores(1)[0]["score"], 66)
            restarted.complete_evaluation_phase(1)
            standings = restarted.get_standings()
            self.assertEqual(len(standings), 1)
            self.assertEqual(standings[0]["participant_id"], current["participant_id"])
            self.assertEqual(standings[0]["total_score"], 66)
            conn = restarted._connect()
            try:
                stale_results = conn.execute(
                    "SELECT COUNT(*) FROM evaluation_results WHERE job_id=?", (stale["job_id"],)
                ).fetchone()[0]
                self.assertEqual(stale_results, 0)
            finally:
                conn.close()
        finally:
            queue.pool.shutdown(wait=True)

    def test_reset_rejects_current_active_work_but_reconciles_stale_work(self):
        _, job = self._make_job()
        with self.assertRaises(EventError):
            self.store.reset_event()
        self.assertEqual(self.store.get_state()["event_number"], 1)
        self.assertEqual(self.store.get_evaluation_jobs(1)[0]["status"], "QUEUED")

        claim = self.store.claim_next_job(1)
        self.assertTrue(self.store.finish_job(job["job_id"], "SUCCESS", 5, claim_token=claim["claim_token"]))
        self.store.reset_event()
        self.assertEqual(self.store.get_state()["event_number"], 2)
        self.assertEqual(self.store.get_evaluation_jobs(), [])

    def test_stale_success_result_is_excluded_from_current_round_and_leaderboard(self):
        _, old_job = self._make_job()
        old_claim = self.store.claim_next_job(1)
        self.assertTrue(self.store.finish_job(old_job["job_id"], "SUCCESS", 12, claim_token=old_claim["claim_token"]))
        self.store.reset_event()

        participant = self.store.register_participant("CurrentLeaderboard")
        self.store.open_submission_window(1)
        self.store.upload_submission(participant["participant_id"], AGENT)
        self.store.lock_submission_window()
        self.store.start_evaluation_phase(1)
        current_job = self.store.get_evaluation_jobs(1)[0]

        conn = self.store._connect()
        try:
            conn.execute(
                "INSERT INTO evaluation_batches "
                "(event_number, round_number, batch_id, status, started_at, finished_at) "
                "VALUES (1, 1, ?, 'COMPLETED', ?, ?)",
                (old_job["batch_id"], old_job["started_at"] or "legacy-start", old_job["updated_at"]),
            )
            conn.execute(
                "INSERT INTO evaluation_jobs "
                "(job_id, batch_id, participant_id, submission_id, round_number, event_number, seed, "
                "status, attempts, claim_token, started_at, score, error_type, error_message, updated_at) "
                "VALUES (?, ?, ?, ?, 1, 1, ?, 'SUCCESS', 1, NULL, ?, 999, NULL, NULL, ?)",
                (
                    "legacy-success-event-one", old_job["batch_id"], participant["participant_id"],
                    current_job["submission_id"], old_job["seed"], old_job["started_at"], old_job["updated_at"],
                ),
            )
            conn.commit()
        finally:
            conn.close()

        claim = self.store.claim_next_job(1)
        self.assertEqual(claim["event_number"], 2)
        self.assertTrue(self.store.finish_job(current_job["job_id"], "SUCCESS", 66, claim_token=claim["claim_token"]))
        self.store.begin_result_processing(1)
        self.assertEqual(self.store.get_round_scores(1)[0]["score"], 66)
        self.store.complete_evaluation_phase(1)
        standings = self.store.get_standings()
        self.assertEqual(len(standings), 1)
        self.assertEqual(standings[0]["participant_id"], participant["participant_id"])
        self.assertEqual(standings[0]["total_score"], 66)

    def test_system_retry_budget_and_duplicate_reset_are_bounded(self):
        _, job = self._make_job()
        claim = self.store.claim_next_job(1)
        for _ in range(3):
            current = self.store.get_evaluation_jobs(1)[0]
            if current["status"] == "RUNNING":
                self.store.finish_job(job["job_id"], "SYSTEM_ERROR", error_type="SYSTEM_ERROR", error_message="infra", claim_token=claim["claim_token"])
            if self.store.get_evaluation_jobs(1)[0]["status"] == "SYSTEM_ERROR":
                self.store.retry_system_errors(1, max_retries=2)
                claim = self.store.claim_next_job(1)
                if claim is None:
                    break
        self.assertEqual(self.store.get_evaluation_jobs(1)[0]["attempts"], 3)
        self.assertEqual(self.store.get_evaluation_jobs(1)[0]["status"], "SYSTEM_ERROR")
        self.assertEqual(self.store.retry_system_errors(1, max_retries=2), 0)

        # Failed terminal jobs can be cancelled by starting a new event; duplicate resets cannot increment twice.
        first = self.store.reset_event()
        self.assertEqual(first["event_number"], 2)
        with self.assertRaises(EventError):
            self.store.reset_event()
        self.assertEqual(self.store.get_state()["event_number"], 2)
        next_event = self.store.register_participant("NewEventPlayer")
        with self.assertRaisesRegex(EventError, "stale event"):
            self.store.record_evaluation_result(
                participant_id=next_event["participant_id"], round_number=1, submission_id=None,
                seed=1, score=999, status="SUCCESS", event_number=1,
            )
        conn = self.store._connect()
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM evaluation_results").fetchone()[0], 0)
        finally:
            conn.close()

    def test_production_never_silently_selects_host_execution(self):
        import evaluation_queue

        with patch.dict(os.environ, {"KAGGRI_ENV": "production", "KAGGRI_USE_DOCKER": "0"}):
            with self.assertRaisesRegex(RuntimeError, "host execution is disabled"):
                evaluation_queue.ensure_evaluator_ready()

    def test_persistent_dispatcher_limits_active_workers_and_finishes_queue(self):
        import evaluation_queue

        count = max(5, evaluation_queue.MAX_WORKERS * 4)
        people = [self.store.register_participant(f"Queue_{i:02d}") for i in range(count)]
        self.store.open_submission_window(1)
        for p in people:
            self.store.upload_submission(p["participant_id"], AGENT)
        self.store.lock_submission_window()
        self.store.start_evaluation_phase(1)
        queue = evaluation_queue.EvaluationQueue(self.store)
        active = 0
        peak = 0
        guard = threading.Lock()

        def fake_execute(job):
            nonlocal active, peak
            with guard:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            self.store.finish_job(job["job_id"], "SUCCESS", 1, claim_token=job["claim_token"])
            with guard:
                active -= 1

        queue._execute = fake_execute
        try:
            queue.start(1)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                jobs = self.store.get_evaluation_jobs(1)
                if jobs and all(job["status"] == "SUCCESS" for job in jobs):
                    break
                time.sleep(0.02)
            self.assertTrue(all(job["status"] == "SUCCESS" for job in self.store.get_evaluation_jobs(1)))
            self.assertLessEqual(peak, evaluation_queue.MAX_WORKERS)
        finally:
            queue.pool.shutdown(wait=True)

    def test_worker_output_memory_is_capped_and_timeout_terminates_child(self):
        import evaluation_queue

        queue = evaluation_queue.EvaluationQueue(self.store)
        original_limit = evaluation_queue.TIMEOUT_SECONDS
        original_cap = evaluation_queue.MAX_OUTPUT_BYTES
        evaluation_queue.TIMEOUT_SECONDS = 1
        evaluation_queue.MAX_OUTPUT_BYTES = 2048
        try:
            result = queue._run_bounded([sys.executable, "-c", "import sys;sys.stdout.write('x'*1000000);print('FINAL_JSON')"])
            self.assertEqual(result["returncode"], 0)
            self.assertLessEqual(len(result["stdout"]), 2048)
            self.assertIn(b"FINAL_JSON", result["stdout"])
            with self.assertRaises(subprocess.TimeoutExpired):
                queue._run_bounded([sys.executable, "-c", "import time;time.sleep(5)"])
        finally:
            evaluation_queue.TIMEOUT_SECONDS = original_limit
            evaluation_queue.MAX_OUTPUT_BYTES = original_cap
            queue.pool.shutdown(wait=True)

    def test_submission_lock_and_reset_race_never_publish_partial_file(self):
        p = self.store.register_participant("UploadRace")
        self.store.open_submission_window(1)
        barrier = threading.Barrier(2)

        def upload():
            barrier.wait()
            try:
                return self.store.upload_submission(p["participant_id"], AGENT)
            except EventError:
                return None

        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(upload)
            barrier.wait()
            try:
                self.store.lock_submission_window()
            except EventError:
                pass
            submission = future.result()
        history = self.store.list_submissions(p["participant_id"])
        self.assertEqual(len(history), 1 if submission else 0)
        self.assertEqual(len(list(self.store.files_dir.rglob("*.tmp"))), 0)
        if history:
            active = self.store.get_active_submission(p["participant_id"], 1)
            self.assertEqual(active["submission_id"], history[0]["submission_id"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

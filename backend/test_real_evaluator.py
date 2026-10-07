"""Optional real Kaggriculture smoke test, enabled with KAGGRI_RUN_REAL_EVALUATOR=1."""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_store import EventStore
from evaluation_queue import EvaluationQueue


@unittest.skipUnless(os.environ.get("KAGGRI_RUN_REAL_EVALUATOR") == "1", "set KAGGRI_RUN_REAL_EVALUATOR=1 with Kaggle dependencies installed")
class RealEvaluatorSmoke(unittest.TestCase):
    def test_twenty_participants_three_rounds_real_evaluator_pipeline(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EventStore(root / "event.sqlite", root / "submissions")
            source = (Path(__file__).resolve().parent.parent / "NITW_Farm_AI_Challenge_v1" / "examples" / "starter_agent.py").read_text(encoding="utf-8")
            participants = [store.register_participant(f"Demo_{i:02d}") for i in range(20)]
            queue = EvaluationQueue(store)
            all_jobs = []
            elapsed = []
            try:
                for round_number in (1, 2, 3):
                    store.open_submission_window(round_number)
                    if round_number == 1:
                        for participant in participants:
                            store.upload_submission(participant["participant_id"], source)
                    store.lock_submission_window()
                    store.start_evaluation_phase(round_number)
                    round_jobs = store.get_evaluation_jobs(round_number)
                    self.assertEqual(len(round_jobs), 20)
                    self.assertEqual(len({job["participant_id"] for job in round_jobs}), 20)
                    self.assertEqual(len({job["job_id"] for job in round_jobs}), 20)
                    all_jobs.extend(round_jobs)
                    started = time.monotonic()
                    queue.start(round_number)
                    deadline = started + 300
                    while time.monotonic() < deadline:
                        round_jobs = store.get_evaluation_jobs(round_number)
                        if len(round_jobs) == 20 and all(job["status"] not in ("QUEUED", "RUNNING", "RETRYING") for job in round_jobs):
                            break
                        time.sleep(0.25)
                    elapsed.append(time.monotonic() - started)
                    self.assertEqual(len(round_jobs), 20)
                    self.assertTrue(all(job["status"] == "SUCCESS" for job in round_jobs), [job for job in round_jobs if job["status"] != "SUCCESS"])
                    store.begin_result_processing(round_number)
                    store.complete_evaluation_phase(round_number)
                    self.assertEqual(len(store.get_standings()), 20)
                store.publish_final_results()
                standings = store.get_standings()
                self.assertEqual(store.get_state()["status"], "FINAL_RESULTS")
                self.assertEqual(len(standings), 20)
                self.assertEqual(len(all_jobs), 60)
                self.assertEqual(len({job["job_id"] for job in all_jobs}), 60)
                for entry in standings:
                    self.assertAlmostEqual(entry["total_score"], entry["round1_score"] + entry["round2_score"] + entry["round3_score"])
                print(f"REAL_20X3 evaluation_seconds={sum(elapsed):.2f} wall_time_per_job={sum(elapsed)/60:.2f} successful=60 total_jobs=60")
            finally:
                queue.pool.shutdown(wait=True)

    def test_queue_runs_actual_720_step_kaggriculture_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EventStore(root / "event.sqlite", root / "submissions")
            p = store.register_participant("EvaluatorSmoke")
            store.open_submission_window(1)
            store.upload_submission(p["participant_id"], 'def agent(obs):\n return {"farmer":["PASS"],"hands":[],"market":[]}\n')
            store.lock_submission_window()
            store.start_evaluation_phase(1)
            queue = EvaluationQueue(store)
            queue.start(1)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                jobs = store.get_evaluation_jobs(1)
                if jobs and jobs[0]["status"] not in ("QUEUED", "RUNNING", "RETRYING"):
                    break
                time.sleep(0.25)
            self.assertEqual(jobs[0]["status"], "SUCCESS", jobs[0].get("error_message"))
            self.assertIsNotNone(jobs[0]["score"])
            queue.pool.shutdown(wait=True)

    def test_crash_and_malformed_action_are_isolated_to_their_jobs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            store = EventStore(root / "event.sqlite", root / "submissions")
            sources = {
                "CrashAgent": 'def agent(obs):\n raise RuntimeError("player boom")\n',
                "BadAction": 'def agent(obs):\n return {"farmer":["NOT_AN_ACTION"],"hands":[],"market":[]}\n',
            }
            participants = {}
            # Registration must precede opening the window.
            for name in sources:
                participants[name] = store.register_participant(name)
            store.open_submission_window(1)
            for name, source in sources.items():
                store.upload_submission(participants[name]["participant_id"], source)
            store.lock_submission_window()
            store.start_evaluation_phase(1)
            queue = EvaluationQueue(store)
            queue.start(1)
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                jobs = store.get_evaluation_jobs(1)
                if len(jobs) == 2 and all(j["status"] not in ("QUEUED", "RUNNING", "RETRYING") for j in jobs):
                    break
                time.sleep(0.25)
            states = {j["participant_id"]: j["status"] for j in jobs}
            self.assertEqual(states[participants["CrashAgent"]["participant_id"]], "PLAYER_ERROR")
            self.assertEqual(states[participants["BadAction"]["participant_id"]], "SUCCESS")
            queue.pool.shutdown(wait=True)

    def test_child_timeout_is_recorded_and_queue_continues(self):
        import evaluation_queue
        original_timeout = evaluation_queue.TIMEOUT_SECONDS
        evaluation_queue.TIMEOUT_SECONDS = 1
        try:
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                store = EventStore(root / "event.sqlite", root / "submissions")
                p = store.register_participant("SlowAgent")
                store.open_submission_window(1)
                store.upload_submission(p["participant_id"], 'import time\ndef agent(obs):\n time.sleep(30)\n return {"farmer":["PASS"],"hands":[],"market":[]}\n')
                store.lock_submission_window()
                store.start_evaluation_phase(1)
                queue = EvaluationQueue(store)
                queue.start(1)
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    jobs = store.get_evaluation_jobs(1)
                    if jobs and jobs[0]["status"] not in ("QUEUED", "RUNNING", "RETRYING"):
                        break
                    time.sleep(0.1)
                self.assertEqual(jobs[0]["status"], "TIMEOUT")
                queue.pool.shutdown(wait=True)
        finally:
            evaluation_queue.TIMEOUT_SECONDS = original_timeout


if __name__ == "__main__":
    unittest.main(verbosity=2)

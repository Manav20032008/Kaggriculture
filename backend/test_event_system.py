"""End-to-end state, persistence, version, queue and cumulative score simulation."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from event_store import EventError, EventStore

AGENT_V1 = 'def agent(obs):\n    return {"farmer": ["PASS"], "hands": [], "market": []}\n'
AGENT_V2 = 'def agent(obs):\n    return {"farmer": ["PASS"], "hands": [], "market": []}\n# v2\n'


class EventSimulation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.db = root / "event.sqlite"
        self.files = root / "submissions"
        self.store = EventStore(self.db, self.files)

    def tearDown(self):
        self.temp.cleanup()

    def reject(self, fn):
        with self.assertRaises(EventError):
            fn()

    def open_round(self, n):
        self.store.open_submission_window(n)

    def finish_round(self, n, base):
        self.store.lock_submission_window()
        self.store.start_evaluation_phase(n)
        self.reject(lambda: self.store.start_evaluation_phase(n))
        jobs = self.store.get_evaluation_jobs(n)
        for i, job in enumerate(jobs):
            if n == 1 and i == 0:
                self.store.finish_job(job["job_id"], "PLAYER_ERROR", 0, "PLAYER_ERROR", "agent crashed")
            elif n == 1 and i == 1:
                self.store.finish_job(job["job_id"], "TIMEOUT", 0, "TIMEOUT", "child timed out")
            elif n == 1 and i == 2:
                self.store.finish_job(job["job_id"], "SYSTEM_ERROR", None, "SYSTEM_ERROR", "worker unavailable")
            else:
                self.store.finish_job(job["job_id"], "SUCCESS", base + i)
        if n == 1:
            self.reject(lambda: self.store.begin_result_processing(n))
            self.assertEqual(self.store.retry_system_errors(n), 1)
            retry = next(j for j in self.store.get_evaluation_jobs(n) if j["status"] == "RETRYING")
            self.store.finish_job(retry["job_id"], "SUCCESS", base + 2)
        self.store.begin_result_processing(n)
        # API/store restart preserves state, frozen submissions, jobs and scores.
        restarted = EventStore(self.db, self.files)
        self.assertEqual(restarted.get_state()["status"], f"ROUND_{n}_PROCESSING_RESULTS")
        restarted.complete_evaluation_phase(n)
        return restarted.get_standings()

    def test_full_three_round_non_elimination_simulation(self):
        participants = [self.store.register_participant(f"Player_{i:02}") for i in range(80)]
        self.assertEqual(len(self.store.list_participants()), 80)
        self.reject(lambda: self.store.open_submission_window(4))
        self.open_round(1)
        for p in participants[:60]:
            self.store.upload_submission(p["participant_id"], AGENT_V1)
        with self.assertRaises(EventError):
            self.store.upload_submission(participants[60]["participant_id"], "def agent(:")
        # Multiple uploads are immutable version records; newest valid version wins within the round.
        second = self.store.upload_submission(participants[0]["participant_id"], AGENT_V2)
        self.assertEqual(second["version"], 2)
        self.store.lock_submission_window()
        self.assertEqual(len(self.store.list_participants()), 80)
        self.assertEqual(sum(s["status"] == "MISSING_SUBMISSION" for s in self.store.get_round_scores(1)), 20)
        with self.assertRaises(EventError):
            self.store.upload_submission(participants[0]["participant_id"], AGENT_V1)
        self.store.start_evaluation_phase(1)
        # Repeated evaluation start is rejected and the frozen id does not change.
        frozen = self.store.get_active_submission(participants[0]["participant_id"], 1)
        self.assertEqual(frozen["submission_id"], second["submission_id"])
        self.reject(lambda: self.store.start_evaluation_phase(1))
        jobs = self.store.get_evaluation_jobs(1)
        for i, job in enumerate(jobs):
            if i == 0: self.store.finish_job(job["job_id"], "PLAYER_ERROR", 0, "PLAYER_ERROR", "crash")
            elif i == 1: self.store.finish_job(job["job_id"], "TIMEOUT", 0, "TIMEOUT", "timeout")
            elif i == 2: self.store.finish_job(job["job_id"], "SYSTEM_ERROR", None, "SYSTEM_ERROR", "infra")
            else: self.store.finish_job(job["job_id"], "SUCCESS", 800 + i)
        self.reject(lambda: self.store.begin_result_processing(1))
        self.assertEqual(self.store.retry_system_errors(1), 1)
        retry = next(j for j in self.store.get_evaluation_jobs(1) if j["status"] == "RETRYING")
        self.store.finish_job(retry["job_id"], "SUCCESS", 802)
        self.store.begin_result_processing(1)
        self.store = EventStore(self.db, self.files)
        self.store.complete_evaluation_phase(1)
        r1 = self.store.get_standings()
        self.assertEqual(len(r1), 80)
        self.assertEqual(sum(p["round1_score"] == 0 for p in r1), 22)
        self.assertTrue(all(p["round2_score"] == p["round3_score"] == 0 for p in r1))

        self.open_round(2)
        for p in participants[60:]: self.store.upload_submission(p["participant_id"], AGENT_V1)
        for p in participants[3:13]: self.store.upload_submission(p["participant_id"], AGENT_V2)
        # Participant IDs survive a backend restart.
        self.store = EventStore(self.db, self.files)
        self.finish_round(2, 500)
        self.assertEqual(len(self.store.get_standings()), 80)
        self.assertEqual(self.store.get_active_submission(participants[0]["participant_id"], 2)["version"], 2)
        self.assertEqual(self.store.get_active_submission(participants[3]["participant_id"], 2)["version"], 2)
        self.assertEqual(self.store.get_active_submission(participants[3]["participant_id"], 1)["version"], 1)
        self.assertEqual(self.store.get_active_submission(participants[13]["participant_id"], 2)["version"], 1)
        self.assertIsNotNone(self.store.get_active_submission(participants[60]["participant_id"], 2))

        self.open_round(3)
        self.finish_round(3, 700)
        standings = self.store.get_standings()
        self.assertEqual(len(standings), 80)
        self.assertTrue(all(p["total_score"] == p["round1_score"] + p["round2_score"] + p["round3_score"] for p in standings))
        self.store.publish_final_results()
        self.assertEqual(self.store.get_state()["status"], "FINAL_RESULTS")
        self.reject(lambda: self.store.publish_final_results())
        self.reject(lambda: self.store.open_submission_window(4))

    def test_reset_is_guarded_and_old_job_cannot_leak(self):
        p = self.store.register_participant("ResetSafe")
        self.store.open_submission_window(1)
        self.store.upload_submission(p["participant_id"], AGENT_V1)
        self.store.lock_submission_window()
        self.store.start_evaluation_phase(1)
        job = self.store.get_evaluation_jobs(1)[0]
        with self.assertRaises(EventError) as error:
            self.store.reset_event()
        self.assertEqual(error.exception.status_code, 409)
        self.assertEqual(self.store.get_state()["status"], "ROUND_1_EVALUATING")

        # RUNNING and RETRYING are equally unsafe to reset around.
        first_attempt = self.store.claim_job(job["job_id"])
        with self.assertRaises(EventError):
            self.store.reset_event()
        self.store.finish_job(job["job_id"], "RETRYING", error_type="SYSTEM_ERROR", error_message="retry", claim_token=first_attempt["claim_token"])
        with self.assertRaises(EventError):
            self.store.reset_event()
        second_attempt = self.store.claim_job(job["job_id"])
        self.store.finish_job(job["job_id"], "SUCCESS", 81, claim_token=second_attempt["claim_token"])
        old_event = self.store.get_state()["event_number"]
        self.assertEqual(self.store.reset_event()["status"], "REGISTRATION")
        self.assertEqual(self.store.get_state()["event_number"], old_event + 1)
        # A late callback from an old worker is an update against a deleted ID and is ignored.
        self.assertFalse(self.store.finish_job(job["job_id"], "SUCCESS", 999, claim_token=second_attempt["claim_token"]))
        self.assertEqual(self.store.get_evaluation_jobs(), [])
        self.assertEqual(self.store.get_round_scores(), [])
        self.assertEqual(self.store.get_standings(), [])
        self.assertEqual(self.store.list_participants(), [])
        self.assertFalse(any(self.files.rglob("*.py")))
        with self.assertRaises(EventError):
            self.store.reset_event()

    def test_two_consecutive_event_runs_persist_independently(self):
        first = [self.store.register_participant(f"EventOne_{i}") for i in range(3)]
        self.store.open_submission_window(1)
        for participant in first:
            self.store.upload_submission(participant["participant_id"], AGENT_V1)
        self.finish_round(1, 100)
        self.open_round(2); self.finish_round(2, 200)
        self.open_round(3); self.finish_round(3, 300); self.store.publish_final_results()
        first_total = self.store.get_standings()[0]["total_score"]
        self.store = EventStore(self.db, self.files)
        self.assertEqual(self.store.get_state()["status"], "FINAL_RESULTS")
        next_state = self.store.reset_event()
        self.assertEqual(next_state["event_number"], 2)
        self.assertEqual(self.store.get_standings(), [])
        self.assertEqual(self.store.get_admin_overview()["participants"], 0)
        second = [self.store.register_participant(f"EventTwo_{i}") for i in range(3)]
        self.assertTrue({p["participant_id"] for p in first}.isdisjoint({p["participant_id"] for p in second}))
        self.assertNotEqual(first_total, 0)
        self.assertEqual(self.store.get_admin_overview()["participants"], 3)
        self.open_round(1)
        for participant in second:
            self.store.upload_submission(participant["participant_id"], AGENT_V1)
        self.finish_round(1, 400)
        self.open_round(2); self.finish_round(2, 500)
        self.open_round(3); self.finish_round(3, 600)
        self.store.publish_final_results()
        self.assertEqual(self.store.get_state()["status"], "FINAL_RESULTS")
        self.assertEqual(len(self.store.get_standings()), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

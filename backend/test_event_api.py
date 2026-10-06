"""HTTP/API integration check for admin protection and upload lifecycle."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from fastapi.testclient import TestClient
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False

from event_store import EventStore


@unittest.skipUnless(FASTAPI_AVAILABLE, "FastAPI/httpx are not installed in this Python environment")
class EventApiIntegration(unittest.TestCase):
    def test_admin_token_configuration_and_authentication(self):
        with tempfile.TemporaryDirectory() as temp:
            import event_api

            original_store = event_api.store
            event_api.store = EventStore(Path(temp) / "auth.sqlite", Path(temp) / "submissions")
            from main import app

            try:
                client = TestClient(app)
                with patch.dict(os.environ):
                    os.environ.pop("KAGGRI_ADMIN_TOKEN", None)
                    missing = client.post("/event/admin/open-submissions?round=1")
                    self.assertEqual(missing.status_code, 503)
                    self.assertIn("KAGGRI_ADMIN_TOKEN", missing.json()["detail"])

                with patch.dict(os.environ, {"KAGGRI_ADMIN_TOKEN": "  test-admin-token \t"}):
                    wrong = client.post(
                        "/event/admin/open-submissions?round=1",
                        headers={"X-Admin-Token": "incorrect-token"},
                    )
                    self.assertEqual(wrong.status_code, 401)
                    self.assertNotIn("test-admin-token", wrong.text)

                    correct = client.post(
                        "/event/admin/open-submissions?round=1",
                        headers={"X-Admin-Token": "test-admin-token"},
                    )
                    self.assertEqual(correct.status_code, 200, correct.text)
                    self.assertEqual(correct.json()["status"], "ROUND_1_SUBMISSION_OPEN")
            finally:
                event_api.store = original_store

    def test_protected_state_upload_and_round_transitions(self):
        with tempfile.TemporaryDirectory() as temp:
            os.environ["KAGGRI_ADMIN_TOKEN"] = "test-admin-token"
            import event_api
            event_api.store = EventStore(Path(temp) / "api.sqlite", Path(temp) / "submissions")
            from main import app
            client = TestClient(app)

            self.assertEqual(client.post("/event/admin/open-submissions?round=1").status_code, 401)
            admin = {"X-Admin-Token": "test-admin-token"}
            participant = client.post("/event/register", data={"username": "ApiTeam"})
            self.assertEqual(participant.status_code, 200)
            self.assertEqual(client.post("/event/admin/open-submissions?round=1", headers=admin).status_code, 200)
            pid = participant.json()["participant_id"]
            code = b'def agent(obs):\n return {"farmer":["PASS"],"hands":[],"market":[]}\n'
            first = client.post("/event/submissions", data={"participant_id": pid}, files={"agent": ("agent.py", code)})
            self.assertEqual(first.status_code, 200, first.text)
            second = client.post("/event/submissions", data={"participant_id": pid}, files={"agent": ("agent.py", code + b"# second\n")})
            self.assertEqual(second.json()["version"], 2)
            self.assertEqual(client.post("/event/admin/open-submissions?round=2", headers=admin).status_code, 409)
            self.assertEqual(client.post("/event/admin/lock-submissions", headers=admin).status_code, 200)
            rejected = client.post("/event/submissions", data={"participant_id": pid}, files={"agent": ("agent.py", code)})
            self.assertEqual(rejected.status_code, 403)
            with patch("evaluation_queue.get_queue"):
                self.assertEqual(client.post("/event/admin/start-evaluation?round=1", headers=admin).status_code, 200)
            self.assertEqual(client.post("/event/admin/start-evaluation?round=1", headers=admin).status_code, 409)
            job = event_api.store.get_evaluation_jobs(1)[0]
            event_api.store.finish_job(job["job_id"], "SUCCESS", 123)
            self.assertEqual(client.post("/event/admin/process-results?round=1", headers=admin).status_code, 200)
            self.assertEqual(client.post("/event/admin/complete-round?round=1", headers=admin).status_code, 200)
            self.assertEqual(client.get("/event/standings").json()["count"], 1)

            rejected_round_2 = client.post(
                "/event/admin/open-submissions?round=2",
                headers={"X-Admin-Token": "incorrect-token"},
            )
            self.assertEqual(rejected_round_2.status_code, 401)
            with patch.dict(os.environ, {"KAGGRI_ADMIN_TOKEN": "  test-admin-token \t"}):
                self.assertIsNone(event_api._require_admin(" test-admin-token \t"))
                opened_round_2 = client.post(
                    "/event/admin/open-submissions?round=2",
                    headers=admin,
                )
            self.assertEqual(opened_round_2.status_code, 200, opened_round_2.text)
            self.assertEqual(opened_round_2.json()["status"], "ROUND_2_SUBMISSION_OPEN")
            os.environ.pop("KAGGRI_ADMIN_TOKEN", None)


if __name__ == "__main__":
    unittest.main(verbosity=2)

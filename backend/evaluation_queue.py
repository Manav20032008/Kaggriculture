"""Persistent bounded queue; participant code runs only in a child process."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from NITW_Farm_AI_Challenge_v1.config import EPISODE_STEPS, MAX_RUNTIME_SECONDS, OPPONENT
from py_env import get_kaggle_python

ROOT = Path(__file__).resolve().parent.parent
MAX_WORKERS = max(1, int(os.environ.get("KAGGRI_MAX_WORKERS", "2")))
TIMEOUT_SECONDS = max(1, int(os.environ.get("KAGGRI_EVAL_TIMEOUT", str(MAX_RUNTIME_SECONDS))))
MAX_SYSTEM_RETRIES = max(0, int(os.environ.get("KAGGRI_SYSTEM_RETRIES", "2")))
USE_DOCKER = os.environ.get("KAGGRI_USE_DOCKER", "0").strip().lower() in {"1", "true", "yes"}


class EvaluationQueue:
    def __init__(self, store):
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="kaggriculture-eval")
        self.running: set[str] = set()
        self._recover()

    def _recover(self):
        # A process restart makes RUNNING jobs safe to retry from the frozen file.
        for job in self.store.get_evaluation_jobs():
            if job["status"] == "RUNNING":
                self.store.finish_job(job["job_id"], "RETRYING", error_type="SYSTEM_ERROR", error_message="Worker process restarted.")

    def start(self, round_number: int):
        for job in self.store.get_evaluation_jobs(round_number):
            if job["status"] in ("QUEUED", "RETRYING") and job["job_id"] not in self.running:
                self.running.add(job["job_id"])
                self.pool.submit(self._run, job["job_id"])

    def _run(self, job_id: str):
        try:
            job = self.store.claim_job(job_id)
            if job is None:
                return
            try:
                path = self.store.get_submission_path(job["submission_id"])
                command = [get_kaggle_python(), str(ROOT / "NITW_Farm_AI_Challenge_v1" / "app" / "worker.py"),
                           "--submission", str(path), "--seed", str(job["seed"]), "--steps", str(EPISODE_STEPS),
                           "--opponent", OPPONENT, "--timeout", str(TIMEOUT_SECONDS)]
                if USE_DOCKER:
                    command.append("--docker")
                proc = subprocess.run(
                    command,
                    capture_output=True, text=True, timeout=TIMEOUT_SECONDS + (10 if USE_DOCKER else 0), cwd=str(ROOT), encoding="utf-8", errors="replace",
                )
            except subprocess.TimeoutExpired:
                self.store.finish_job(job_id, "TIMEOUT", 0, "TIMEOUT", f"Evaluation exceeded {TIMEOUT_SECONDS} seconds.")
                return
            except Exception as exc:
                self._system_failure(job, f"{type(exc).__name__}: {exc}")
                return
            try:
                payload = json.loads(proc.stdout.strip().splitlines()[-1])
            except Exception:
                message = (proc.stderr or proc.stdout or f"Worker exited {proc.returncode} without valid JSON")[-4000:]
                self._system_failure(job, message)
                return
            status = str(payload.get("status", "")).lower()
            try:
                score = float(payload["reward"])
            except (KeyError, TypeError, ValueError):
                score = None
            if proc.returncode == 0 and score is not None and status in {"done", "success", "finished", "terminated", "active", ""}:
                self.store.finish_job(job_id, "SUCCESS", score)
            elif payload.get("error_type") == "TIMEOUT":
                self.store.finish_job(job_id, "TIMEOUT", 0, "TIMEOUT", str(payload.get("error", "Evaluation timed out")))
            elif payload.get("error_type") == "SYSTEM_ERROR":
                self._system_failure(job, str(payload.get("error", "Evaluator system error")))
            else:
                self.store.finish_job(job_id, "PLAYER_ERROR", 0, "PLAYER_ERROR", str(payload.get("error", "Agent evaluation failed")))
        finally:
            self.running.discard(job_id)
            latest = next((j for j in self.store.get_evaluation_jobs() if j["job_id"] == job_id), None)
            if latest and latest["status"] == "RETRYING":
                self.running.add(job_id)
                self.pool.submit(self._run, job_id)

    def _system_failure(self, job, message):
        status = "RETRYING" if job["attempts"] <= MAX_SYSTEM_RETRIES else "SYSTEM_ERROR"
        self.store.finish_job(job["job_id"], status, None, "SYSTEM_ERROR", message)


_queue = None


def get_queue(store):
    global _queue
    if _queue is None or _queue.store is not store:
        _queue = EvaluationQueue(store)
    return _queue

"""Persistent bounded dispatcher for isolated Kaggriculture evaluation jobs."""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from NITW_Farm_AI_Challenge_v1.config import EPISODE_STEPS, MAX_RUNTIME_SECONDS, OPPONENT
from py_env import get_kaggle_python
from runtime_config import DATA_DIR, is_production

ROOT = Path(__file__).resolve().parent.parent
MAX_WORKERS = max(1, int(os.environ.get("KAGGRI_MAX_WORKERS", "2")))
TIMEOUT_SECONDS = max(1, int(os.environ.get("KAGGRI_EVAL_TIMEOUT", str(MAX_RUNTIME_SECONDS))))
MAX_SYSTEM_RETRIES = max(0, int(os.environ.get("KAGGRI_SYSTEM_RETRIES", "2")))
USE_DOCKER = os.environ.get("KAGGRI_USE_DOCKER", "1" if is_production() else "0").strip().lower() in {"1", "true", "yes"}
MAX_OUTPUT_BYTES = 64 * 1024


def ensure_evaluator_ready() -> None:
    if is_production() and not USE_DOCKER:
        raise RuntimeError("Production evaluation requires KAGGRI_USE_DOCKER=1; host execution is disabled.")
    if is_production():
        docker = shutil.which("docker")
        if not docker:
            raise RuntimeError("Docker is required for production evaluation but the Docker CLI is unavailable.")
        try:
            check = subprocess.run([docker, "image", "inspect", "nitw-farm-ai-evaluator"], capture_output=True, timeout=10)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Docker availability check failed: {exc}") from exc
        if check.returncode != 0:
            raise RuntimeError("Docker is required, and the nitw-farm-ai-evaluator image is not available locally.")


class EvaluationQueue:
    def __init__(self, store):
        ensure_evaluator_ready()
        self.store = store
        self.pool = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="kaggriculture-eval")
        self._lock = threading.Lock()
        self._round_workers: dict[tuple[int, int], int] = {}
        self._recover()

    def _recover(self):
        self.store.recover_running_jobs(MAX_SYSTEM_RETRIES)

    def start(self, round_number: int):
        state = self.store.get_state()
        if state["current_round"] != round_number or not state["status"].endswith("_EVALUATING"):
            return
        key = (state["event_number"], round_number)
        with self._lock:
            if key in self._round_workers:
                return
            pending = sum(
                job["status"] in {"QUEUED", "RETRYING"}
                for job in self.store.get_evaluation_jobs(round_number, event_number=state["event_number"])
            )
            if not pending:
                return
            slots = min(MAX_WORKERS, pending)
            self._round_workers[key] = slots
            for _ in range(slots):
                self.pool.submit(self._drain_round, key)

    def _drain_round(self, key: tuple[int, int]):
        event_number, round_number = key
        try:
            while True:
                state = self.store.get_state()
                if state["event_number"] != event_number or state["status"] != f"ROUND_{round_number}_EVALUATING":
                    return
                job = self.store.claim_next_job(round_number)
                if job is None:
                    return
                try:
                    self._execute(job)
                except Exception as exc:
                    try:
                        self._system_failure(job, f"Unexpected worker error: {type(exc).__name__}: {exc}", job["claim_token"])
                    except Exception as persistence_error:
                        print(f"Could not persist evaluation failure for {job['job_id']}: {persistence_error}", file=sys.stderr)
        finally:
            with self._lock:
                remaining = self._round_workers.get(key, 1) - 1
                if remaining > 0:
                    self._round_workers[key] = remaining
                else:
                    self._round_workers.pop(key, None)

    def _execute(self, job):
        token = job["claim_token"]
        try:
            path = self.store.get_submission_path(job["submission_id"])
            command = [get_kaggle_python(), str(ROOT / "NITW_Farm_AI_Challenge_v1" / "app" / "worker.py"),
                       "--submission", str(path), "--seed", str(job["seed"]), "--steps", str(EPISODE_STEPS),
                       "--opponent", OPPONENT, "--timeout", str(TIMEOUT_SECONDS)]
            if USE_DOCKER:
                command.append("--docker")
            output = self._run_bounded(command)
        except subprocess.TimeoutExpired:
            self.store.finish_job(job["job_id"], "TIMEOUT", 0, "TIMEOUT", f"Evaluation exceeded {TIMEOUT_SECONDS} seconds.", token)
            return
        except Exception as exc:
            self._system_failure(job, f"{type(exc).__name__}: {exc}", token)
            return

        try:
            lines = output["stdout"].decode("utf-8", errors="replace").strip().splitlines()
            payload = json.loads(lines[-1]) if lines else None
        except Exception:
            payload = None
        if not isinstance(payload, dict):
            message = (output["stderr"] or output["stdout"] or f"Worker exited {output['returncode']} without valid JSON").decode("utf-8", errors="replace")[-4000:]
            self._system_failure(job, message, token)
            return

        try:
            score = float(payload["reward"])
        except (KeyError, TypeError, ValueError):
            score = None
        status = str(payload.get("status", "")).lower()
        if output["returncode"] == 0 and score is not None and status in {"done", "success", "finished", "terminated", "active", ""}:
            self.store.finish_job(job["job_id"], "SUCCESS", score, claim_token=token)
        elif payload.get("error_type") == "TIMEOUT":
            self.store.finish_job(job["job_id"], "TIMEOUT", 0, "TIMEOUT", str(payload.get("error", "Evaluation timed out")), token)
        elif payload.get("error_type") == "SYSTEM_ERROR":
            self._system_failure(job, str(payload.get("error", "Evaluator system error")), token)
        else:
            self.store.finish_job(job["job_id"], "PLAYER_ERROR", 0, "PLAYER_ERROR", str(payload.get("error", "Agent evaluation failed")), token)

    def _run_bounded(self, command):
        env = os.environ.copy()
        temp_dir = DATA_DIR / "tmp"
        env.update({"TMPDIR": str(temp_dir), "TMP": str(temp_dir), "TEMP": str(temp_dir)})
        proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=str(ROOT), env=env,
                                start_new_session=(os.name != "nt"))
        buffers = {"stdout": bytearray(), "stderr": bytearray()}

        def drain(name, stream):
            while True:
                chunk = stream.read(8192)
                if not chunk:
                    break
                buffers[name].extend(chunk)
                if len(buffers[name]) > MAX_OUTPUT_BYTES:
                    del buffers[name][:-MAX_OUTPUT_BYTES]

        readers = [threading.Thread(target=drain, args=(name, getattr(proc, name)), daemon=True)
                   for name in ("stdout", "stderr")]
        for reader in readers:
            reader.start()
        try:
            returncode = proc.wait(timeout=TIMEOUT_SECONDS + (10 if USE_DOCKER else 0))
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                proc.kill()
            else:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            proc.wait()
            for reader in readers:
                reader.join(timeout=2)
            proc.stdout.close()
            proc.stderr.close()
            raise
        for reader in readers:
            reader.join()
        proc.stdout.close()
        proc.stderr.close()
        return {"returncode": returncode, "stdout": bytes(buffers["stdout"]), "stderr": bytes(buffers["stderr"])}

    def _system_failure(self, job, message, token):
        status = "RETRYING" if job["attempts"] <= MAX_SYSTEM_RETRIES else "SYSTEM_ERROR"
        self.store.finish_job(job["job_id"], status, None, "SYSTEM_ERROR", message, token)


_queue = None
_queue_lock = threading.Lock()


def get_queue(store):
    global _queue
    with _queue_lock:
        if _queue is None or _queue.store is not store:
            if _queue is not None:
                _queue.pool.shutdown(wait=False, cancel_futures=True)
            _queue = EvaluationQueue(store)
        return _queue

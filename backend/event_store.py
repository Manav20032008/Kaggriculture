from __future__ import annotations

import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from NITW_Farm_AI_Challenge_v1.config import OFFICIAL_SEED

from agent_validation import validate_agent_source
from event_models import (
    ALL_STATES,
    FINAL_RESULTS,
    PARTICIPANT_ACTIVE,
    REGISTRATION,
    SCORE_MISSING,
    SCORE_PENDING,
    SCORE_RECORDED,
    SUBMISSION_VALID,
    TOTAL_ROUNDS,
    is_submission_open,
    parse_round_from_state,
    registration_allowed,
    round_state,
)


class EventError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


SCHEMA = """
CREATE TABLE IF NOT EXISTS event_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    status TEXT NOT NULL,
    current_round INTEGER,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_batches (
    round_number INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    participant_id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS submissions (
    submission_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    version INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_submissions_participant_version
    ON submissions(participant_id, version);

CREATE TABLE IF NOT EXISTS round_active_submissions (
    participant_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    submission_id TEXT,
    frozen_at TEXT NOT NULL,
    PRIMARY KEY (participant_id, round_number),
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id),
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id)
);

CREATE TABLE IF NOT EXISTS round_scores (
    participant_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    score REAL NOT NULL,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (participant_id, round_number),
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id)
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    evaluation_id TEXT PRIMARY KEY,
    participant_id TEXT NOT NULL,
    submission_id TEXT,
    round_number INTEGER NOT NULL,
    seed INTEGER,
    score REAL,
    status TEXT NOT NULL,
    error_type TEXT,
    error_message TEXT,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id),
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id)
);

CREATE TABLE IF NOT EXISTS evaluation_jobs (
    job_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    seed INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    score REAL,
    error_type TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(participant_id, round_number)
);

CREATE TABLE IF NOT EXISTS leaderboard_snapshots (
    through_round INTEGER NOT NULL,
    participant_id TEXT NOT NULL,
    rank INTEGER NOT NULL,
    round1_score REAL NOT NULL,
    round2_score REAL NOT NULL,
    round3_score REAL NOT NULL,
    total_score REAL NOT NULL,
    published_at TEXT NOT NULL,
    PRIMARY KEY (through_round, participant_id)
);
"""


class EventStore:
    def __init__(self, db_path: Path, files_dir: Path, compatibility_players_dir: Path | None = None):
        self.db_path = Path(db_path)
        self.files_dir = Path(files_dir)
        self.compatibility_players_dir = (
            Path(compatibility_players_dir) if compatibility_players_dir else None
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(SCHEMA)
                row = conn.execute("SELECT status FROM event_state WHERE id = 1").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO event_state (id, status, current_round, updated_at) VALUES (1, ?, NULL, ?)",
                        (REGISTRATION, _now()),
                    )
                conn.commit()
            finally:
                conn.close()

    def get_state(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT status, current_round, updated_at FROM event_state WHERE id = 1"
                ).fetchone()
                batches = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT round_number, batch_id, status, started_at, finished_at "
                        "FROM evaluation_batches ORDER BY round_number"
                    ).fetchall()
                ]
            finally:
                conn.close()
        return {
            "status": row["status"],
            "current_round": row["current_round"],
            "updated_at": row["updated_at"],
            "total_rounds": TOTAL_ROUNDS,
            "evaluation_batches": batches,
        }

    def _require_state(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute(
            "SELECT status, current_round, updated_at FROM event_state WHERE id = 1"
        ).fetchone()
        if row is None:
            raise EventError("Event state is missing.", 500)
        return row

    def _set_state(self, conn: sqlite3.Connection, status: str, current_round: int | None) -> None:
        if status not in ALL_STATES:
            raise EventError(f"Unknown event status: {status}", 500)
        conn.execute(
            "UPDATE event_state SET status = ?, current_round = ?, updated_at = ? WHERE id = 1",
            (status, current_round, _now()),
        )

    def register_participant(self, username: str) -> dict:
        username = (username or "").strip()
        if not username:
            raise EventError("Username cannot be empty.")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
            raise EventError("Username can contain only letters, numbers, '_' and '-'.")
        if len(username) > 32:
            raise EventError("Username must be at most 32 characters.")

        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                if not registration_allowed(state["status"]):
                    raise EventError(
                        f"Registration is not allowed during {state['status']}.",
                        403,
                    )
                existing = conn.execute(
                    "SELECT participant_id FROM participants WHERE username = ? COLLATE NOCASE",
                    (username,),
                ).fetchone()
                if existing:
                    raise EventError("Username is already registered.", 409)

                participant = {
                    "participant_id": _new_id("p"),
                    "username": username,
                    "created_at": _now(),
                    "status": PARTICIPANT_ACTIVE,
                }
                conn.execute(
                    "INSERT INTO participants (participant_id, username, created_at, status) "
                    "VALUES (:participant_id, :username, :created_at, :status)",
                    participant,
                )
                conn.commit()
                return participant
            finally:
                conn.close()

    def get_participant(self, participant_id: str) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT participant_id, username, created_at, status FROM participants "
                    "WHERE participant_id = ?",
                    (participant_id,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            raise EventError("Participant not found.", 404)
        return dict(row)

    def list_participants(self) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT participant_id, username, created_at, status FROM participants "
                    "ORDER BY username COLLATE NOCASE"
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def open_submission_window(self, round_number: int | None = None) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                status = state["status"]

                if round_number is not None and (round_number < 1 or round_number > TOTAL_ROUNDS):
                    raise EventError(
                        f"Round {round_number} does not exist. This event has exactly {TOTAL_ROUNDS} rounds.",
                        400,
                    )

                if status == REGISTRATION:
                    next_round = 1
                elif status == round_state(1, "COMPLETE"):
                    next_round = 2
                elif status == round_state(2, "COMPLETE"):
                    next_round = 3
                else:
                    raise EventError(
                        f"Cannot open a submission window from {status}.",
                        409,
                    )

                if round_number is not None and round_number != next_round:
                    if round_number == 2 and status != round_state(1, "COMPLETE"):
                        raise EventError(
                            "Cannot start Round 2 before Round 1 is complete.",
                            409,
                        )
                    if round_number == 3 and status != round_state(2, "COMPLETE"):
                        raise EventError(
                            "Cannot start Round 3 before Round 2 is complete.",
                            409,
                        )
                    raise EventError(
                        f"Cannot open Round {round_number} from {status}. Next allowed round is {next_round}.",
                        409,
                    )

                self._set_state(conn, round_state(next_round, "SUBMISSION_OPEN"), next_round)
                conn.commit()
            finally:
                conn.close()
        return self.get_state()

    def lock_submission_window(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                if not is_submission_open(state["status"]):
                    raise EventError(
                        f"Cannot lock submissions from {state['status']}.",
                        409,
                    )
                round_number = parse_round_from_state(state["status"])
                assert round_number is not None
                self._freeze_round_active(conn, round_number)
                self._ensure_missing_scores(conn, round_number)
                self._set_state(conn, round_state(round_number, "SUBMISSION_LOCKED"), round_number)
                conn.commit()
            finally:
                conn.close()
        return self.get_state()

    def start_evaluation_phase(self, round_number: int | None = None) -> dict:
        """Transition into EVALUATING. Does not run any matches."""
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                current = parse_round_from_state(state["status"])
                if current is None:
                    raise EventError(
                        f"Cannot start evaluation from {state['status']}.",
                        409,
                    )
                target = round_number if round_number is not None else current
                if target != current:
                    raise EventError(
                        f"Cannot start Round {target} evaluation from {state['status']}.",
                        409,
                    )
                if state["status"] != round_state(target, "SUBMISSION_LOCKED"):
                    if state["status"] == round_state(target, "EVALUATING"):
                        raise EventError(
                            f"Round {target} evaluation has already started.",
                            409,
                        )
                    if state["status"] == round_state(target, "COMPLETE"):
                        raise EventError(
                            f"Round {target} evaluation has already completed.",
                            409,
                        )
                    raise EventError(
                        f"Cannot start evaluation from {state['status']}. Lock submissions first.",
                        409,
                    )

                existing = conn.execute(
                    "SELECT batch_id, status FROM evaluation_batches WHERE round_number = ?",
                    (target,),
                ).fetchone()
                if existing:
                    raise EventError(
                        f"Round {target} evaluation batch already exists ({existing['batch_id']}).",
                        409,
                    )

                batch_id = _new_id("evalbatch")
                conn.execute(
                    "INSERT INTO evaluation_batches (round_number, batch_id, status, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, NULL)",
                    (target, batch_id, "STARTED", _now()),
                )
                rows = conn.execute(
                    "SELECT a.participant_id, a.submission_id FROM round_active_submissions a "
                    "WHERE a.round_number = ? AND a.submission_id IS NOT NULL",
                    (target,),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        "INSERT INTO evaluation_jobs "
                        "(job_id, batch_id, participant_id, submission_id, round_number, seed, status, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 'QUEUED', ?)",
                        (_new_id("job"), batch_id, row["participant_id"], row["submission_id"], target, OFFICIAL_SEED, _now()),
                    )
                self._set_state(conn, round_state(target, "EVALUATING"), target)
                conn.commit()
            finally:
                conn.close()
        return self.get_state()

    def complete_evaluation_phase(self, round_number: int | None = None) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                current = parse_round_from_state(state["status"])
                if current is None or state["status"] != round_state(current, "PROCESSING_RESULTS"):
                    raise EventError(
                        f"Cannot complete evaluation from {state['status']}.",
                        409,
                    )
                target = round_number if round_number is not None else current
                if target != current:
                    raise EventError(
                        f"Cannot complete Round {target} from {state['status']}.",
                        409,
                    )
                pending = conn.execute(
                    "SELECT COUNT(*) FROM evaluation_jobs WHERE round_number = ? "
                    "AND status IN ('QUEUED', 'RUNNING', 'RETRYING', 'SYSTEM_ERROR')", (target,)
                ).fetchone()[0]
                if pending:
                    raise EventError("Evaluation jobs are still pending.", 409)
                conn.execute(
                    "UPDATE evaluation_batches SET status = ?, finished_at = ? WHERE round_number = ?",
                    ("COMPLETED", _now(), target),
                )
                people = conn.execute("SELECT participant_id FROM participants").fetchall()
                totals = []
                for person in people:
                    pid = person["participant_id"]
                    scores = {r["round_number"]: float(r["score"]) for r in conn.execute(
                        "SELECT round_number, score FROM round_scores WHERE participant_id=?", (pid,)
                    ).fetchall()}
                    r1, r2, r3 = (scores.get(n, 0.0) for n in (1, 2, 3))
                    totals.append((pid, r1, r2, r3, r1 + r2 + r3))
                totals.sort(key=lambda x: (-x[4], conn.execute("SELECT username FROM participants WHERE participant_id=?", (x[0],)).fetchone()[0].lower()))
                published = _now()
                for rank, values in enumerate(totals, start=1):
                    conn.execute(
                        "INSERT OR REPLACE INTO leaderboard_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (target, values[0], rank, values[1], values[2], values[3], values[4], published),
                    )
                self._set_state(conn, round_state(target, "COMPLETE"), target)
                conn.commit()
            finally:
                conn.close()
        return self.get_state()

    def publish_final_results(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                if state["status"] != round_state(3, "COMPLETE"):
                    raise EventError(
                        f"Cannot publish final results from {state['status']}. Round 3 must be complete.",
                        409,
                    )
                self._set_state(conn, FINAL_RESULTS, 3)
                conn.commit()
            finally:
                conn.close()
        return self.get_state()

    def begin_result_processing(self, round_number: int | None = None) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                current = parse_round_from_state(state["status"])
                if current is None or state["status"] != round_state(current, "EVALUATING"):
                    raise EventError(f"Cannot process results from {state['status']}.", 409)
                target = round_number if round_number is not None else current
                if target != current:
                    raise EventError("Requested round does not match the active round.", 409)
                pending = conn.execute(
                    "SELECT COUNT(*) FROM evaluation_jobs WHERE round_number = ? "
                    "AND status IN ('QUEUED', 'RUNNING', 'RETRYING', 'SYSTEM_ERROR')", (target,)
                ).fetchone()[0]
                if pending:
                    raise EventError(f"{pending} evaluation jobs are still pending.", 409)
                jobs = conn.execute(
                    "SELECT participant_id, score, status, error_type FROM evaluation_jobs WHERE round_number = ?",
                    (target,),
                ).fetchall()
                for job in jobs:
                    score = float(job["score"] or 0)
                    score_status = SCORE_RECORDED if job["status"] == "SUCCESS" else job["status"]
                    conn.execute(
                        "UPDATE round_scores SET score = ?, status = ?, updated_at = ? "
                        "WHERE participant_id = ? AND round_number = ?",
                        (score, score_status, _now(), job["participant_id"], target),
                    )
                self._set_state(conn, round_state(target, "PROCESSING_RESULTS"), target)
                conn.commit()
            finally:
                conn.close()
        return self.get_state()

    def get_evaluation_jobs(self, round_number: int | None = None) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                sql = "SELECT * FROM evaluation_jobs"
                args = ()
                if round_number is not None:
                    sql += " WHERE round_number = ?"
                    args = (round_number,)
                rows = conn.execute(sql + " ORDER BY round_number, participant_id", args).fetchall()
            finally:
                conn.close()
        return [dict(row) for row in rows]

    def claim_job(self, job_id: str) -> dict | None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM evaluation_jobs WHERE job_id = ?", (job_id,)).fetchone()
                if row is None or row["status"] not in ("QUEUED", "RETRYING"):
                    conn.rollback()
                    return None
                conn.execute("UPDATE evaluation_jobs SET status='RUNNING', attempts=attempts+1, updated_at=? WHERE job_id=?", (_now(), job_id))
                conn.commit()
                return dict(conn.execute("SELECT * FROM evaluation_jobs WHERE job_id=?", (job_id,)).fetchone())
            finally:
                conn.close()

    def finish_job(self, job_id: str, status: str, score: float | None = None, error_type: str | None = None, error_message: str | None = None) -> None:
        if status not in {"SUCCESS", "PLAYER_ERROR", "TIMEOUT", "SYSTEM_ERROR", "RETRYING"}:
            raise EventError("Invalid evaluation job status.", 400)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("UPDATE evaluation_jobs SET status=?, score=?, error_type=?, error_message=?, updated_at=? WHERE job_id=?", (status, score, error_type, (error_message or "")[:4000] or None, _now(), job_id))
                row = conn.execute("SELECT * FROM evaluation_jobs WHERE job_id=?", (job_id,)).fetchone()
                if row is not None and status not in ("RETRYING", "RUNNING"):
                    conn.execute(
                        "INSERT INTO evaluation_results (evaluation_id, participant_id, submission_id, round_number, seed, score, status, error_type, error_message, started_at, finished_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (_new_id("eval"), row["participant_id"], row["submission_id"], row["round_number"], row["seed"], score, status, error_type, (error_message or "")[:4000] or None, row["updated_at"], _now()),
                    )
                conn.commit()
            finally:
                conn.close()

    def get_submission_path(self, submission_id: str) -> Path:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute("SELECT file_path FROM submissions WHERE submission_id=?", (submission_id,)).fetchone()
            finally:
                conn.close()
        if row is None:
            raise EventError("Submission not found.", 404)
        return Path(row["file_path"])

    def retry_system_errors(self, round_number: int) -> int:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                if state["status"] != round_state(round_number, "EVALUATING"):
                    raise EventError("System errors can be retried only while that round is evaluating.", 409)
                cur = conn.execute("UPDATE evaluation_jobs SET status='RETRYING', updated_at=? WHERE round_number=? AND status='SYSTEM_ERROR'", (_now(), round_number))
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def upload_submission(self, participant_id: str, source_text: str) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                if not is_submission_open(state["status"]):
                    raise EventError(
                        f"Submissions are not accepted during {state['status']}.",
                        403,
                    )
                round_number = parse_round_from_state(state["status"])
                assert round_number is not None

                participant = conn.execute(
                    "SELECT participant_id, username, created_at, status FROM participants "
                    "WHERE participant_id = ?",
                    (participant_id,),
                ).fetchone()
                if participant is None:
                    raise EventError("Participant not found.", 404)

                try:
                    validate_agent_source(source_text)
                except ValueError as exc:
                    raise EventError(str(exc), 400) from exc

                version_row = conn.execute(
                    "SELECT COALESCE(MAX(version), 0) AS max_version FROM submissions WHERE participant_id = ?",
                    (participant_id,),
                ).fetchone()
                version = int(version_row["max_version"]) + 1
                submission_id = _new_id("sub")
                dest_dir = self.files_dir / participant_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / f"{submission_id}.py"
                dest_path.write_text(source_text, encoding="utf-8")

                created_at = _now()
                conn.execute(
                    "INSERT INTO submissions "
                    "(submission_id, participant_id, round_number, version, file_path, created_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        submission_id,
                        participant_id,
                        round_number,
                        version,
                        str(dest_path),
                        created_at,
                        SUBMISSION_VALID,
                    ),
                )
                conn.commit()

                return {
                    "submission_id": submission_id,
                    "participant_id": participant_id,
                    "round_number": round_number,
                    "version": version,
                    "file_path": str(dest_path),
                    "created_at": created_at,
                    "status": SUBMISSION_VALID,
                }
            finally:
                conn.close()

    def list_submissions(self, participant_id: str) -> list[dict]:
        self.get_participant(participant_id)
        with self._lock:
            conn = self._connect()
            try:
                rows = conn.execute(
                    "SELECT submission_id, participant_id, round_number, version, file_path, created_at, status "
                    "FROM submissions WHERE participant_id = ? ORDER BY version ASC",
                    (participant_id,),
                ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def get_active_submission(self, participant_id: str, round_number: int) -> dict | None:
        if round_number < 1 or round_number > TOTAL_ROUNDS:
            raise EventError(
                f"Round {round_number} does not exist. This event has exactly {TOTAL_ROUNDS} rounds."
            )
        self.get_participant(participant_id)
        with self._lock:
            conn = self._connect()
            try:
                return self._resolve_active(conn, participant_id, round_number)
            finally:
                conn.close()

    def _resolve_active(self, conn: sqlite3.Connection, participant_id: str, round_number: int) -> dict | None:
        frozen = conn.execute(
            "SELECT s.submission_id, s.participant_id, s.round_number, s.version, s.file_path, s.created_at, s.status "
            "FROM round_active_submissions a "
            "LEFT JOIN submissions s ON s.submission_id = a.submission_id "
            "WHERE a.participant_id = ? AND a.round_number = ?",
            (participant_id, round_number),
        ).fetchone()
        if frozen is not None:
            if frozen["submission_id"] is None:
                return None
            return dict(frozen)

        row = conn.execute(
            "SELECT submission_id, participant_id, round_number, version, file_path, created_at, status "
            "FROM submissions "
            "WHERE participant_id = ? AND round_number <= ? AND status = ? "
            "ORDER BY round_number DESC, version DESC LIMIT 1",
            (participant_id, round_number, SUBMISSION_VALID),
        ).fetchone()
        return dict(row) if row else None

    def _freeze_round_active(self, conn: sqlite3.Connection, round_number: int) -> None:
        frozen_at = _now()
        participants = conn.execute("SELECT participant_id FROM participants").fetchall()
        for p in participants:
            pid = p["participant_id"]
            active = conn.execute(
                "SELECT submission_id FROM submissions "
                "WHERE participant_id = ? AND round_number <= ? AND status = ? "
                "ORDER BY round_number DESC, version DESC LIMIT 1",
                (pid, round_number, SUBMISSION_VALID),
            ).fetchone()
            submission_id = active["submission_id"] if active else None
            conn.execute(
                "INSERT INTO round_active_submissions (participant_id, round_number, submission_id, frozen_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT(participant_id, round_number) DO UPDATE SET "
                "submission_id = excluded.submission_id, frozen_at = excluded.frozen_at",
                (pid, round_number, submission_id, frozen_at),
            )

    def _ensure_missing_scores(self, conn: sqlite3.Connection, round_number: int) -> None:
        updated_at = _now()
        participants = conn.execute("SELECT participant_id FROM participants").fetchall()
        for p in participants:
            pid = p["participant_id"]
            existing = conn.execute(
                "SELECT score, status FROM round_scores WHERE participant_id = ? AND round_number = ?",
                (pid, round_number),
            ).fetchone()
            active = conn.execute(
                "SELECT submission_id FROM round_active_submissions "
                "WHERE participant_id = ? AND round_number = ?",
                (pid, round_number),
            ).fetchone()
            has_active = active is not None and active["submission_id"] is not None
            if existing:
                continue
            if has_active:
                conn.execute(
                    "INSERT INTO round_scores (participant_id, round_number, score, status, updated_at) "
                    "VALUES (?, ?, 0, ?, ?)",
                    (pid, round_number, SCORE_PENDING, updated_at),
                )
            else:
                conn.execute(
                    "INSERT INTO round_scores (participant_id, round_number, score, status, updated_at) "
                    "VALUES (?, ?, 0, ?, ?)",
                    (pid, round_number, SCORE_MISSING, updated_at),
                )

    def record_round_score(
        self,
        participant_id: str,
        round_number: int,
        score: float,
        status: str = SCORE_RECORDED,
    ) -> dict:
        if round_number < 1 or round_number > TOTAL_ROUNDS:
            raise EventError(
                f"Round {round_number} does not exist. This event has exactly {TOTAL_ROUNDS} rounds."
            )
        self.get_participant(participant_id)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO round_scores (participant_id, round_number, score, status, updated_at) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(participant_id, round_number) DO UPDATE SET "
                    "score = excluded.score, status = excluded.status, updated_at = excluded.updated_at",
                    (participant_id, round_number, float(score), status, _now()),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT participant_id, round_number, score, status, updated_at "
                    "FROM round_scores WHERE participant_id = ? AND round_number = ?",
                    (participant_id, round_number),
                ).fetchone()
            finally:
                conn.close()
        return dict(row)

    def record_evaluation_result(
        self,
        *,
        participant_id: str,
        round_number: int,
        submission_id: str | None,
        seed: int | None,
        score: float | None,
        status: str,
        error_type: str | None = None,
        error_message: str | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
    ) -> dict:
        """Persist a raw evaluation result. Does not execute a match."""
        if round_number < 1 or round_number > TOTAL_ROUNDS:
            raise EventError(
                f"Round {round_number} does not exist. This event has exactly {TOTAL_ROUNDS} rounds."
            )
        self.get_participant(participant_id)
        evaluation_id = _new_id("eval")
        started_at = started_at or _now()
        finished_at = finished_at or _now()
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT INTO evaluation_results ("
                    "evaluation_id, participant_id, submission_id, round_number, seed, score, "
                    "status, error_type, error_message, started_at, finished_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        evaluation_id,
                        participant_id,
                        submission_id,
                        round_number,
                        seed,
                        score,
                        status,
                        error_type,
                        error_message,
                        started_at,
                        finished_at,
                    ),
                )
                conn.commit()
                row = conn.execute(
                    "SELECT * FROM evaluation_results WHERE evaluation_id = ?",
                    (evaluation_id,),
                ).fetchone()
            finally:
                conn.close()
        return dict(row)

    def get_round_scores(self, round_number: int | None = None) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                if round_number is None:
                    rows = conn.execute(
                        "SELECT participant_id, round_number, score, status, updated_at "
                        "FROM round_scores ORDER BY round_number, participant_id"
                    ).fetchall()
                else:
                    if round_number < 1 or round_number > TOTAL_ROUNDS:
                        raise EventError(
                            f"Round {round_number} does not exist. This event has exactly {TOTAL_ROUNDS} rounds."
                        )
                    rows = conn.execute(
                        "SELECT participant_id, round_number, score, status, updated_at "
                        "FROM round_scores WHERE round_number = ? ORDER BY participant_id",
                        (round_number,),
                    ).fetchall()
            finally:
                conn.close()
        return [dict(r) for r in rows]

    def get_standings(self) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                snapshot = conn.execute("SELECT MAX(through_round) FROM leaderboard_snapshots").fetchone()[0]
                if snapshot is not None:
                    rows = conn.execute(
                        "SELECT s.participant_id, p.username, p.status, s.rank, s.round1_score, s.round2_score, s.round3_score, s.total_score "
                        "FROM leaderboard_snapshots s JOIN participants p USING(participant_id) "
                        "WHERE s.through_round=? ORDER BY s.rank", (snapshot,)
                    ).fetchall()
                    return [dict(row) for row in rows]
                participants = conn.execute(
                    "SELECT participant_id, username, created_at, status FROM participants "
                    "ORDER BY username COLLATE NOCASE"
                ).fetchall()
                scores = conn.execute(
                    "SELECT participant_id, round_number, score FROM round_scores"
                ).fetchall()
            finally:
                conn.close()

        by_participant: dict[str, dict[int, float]] = {}
        for row in scores:
            by_participant.setdefault(row["participant_id"], {})[row["round_number"]] = float(row["score"])

        standings = []
        for p in participants:
            rounds = by_participant.get(p["participant_id"], {})
            r1 = float(rounds.get(1, 0.0))
            r2 = float(rounds.get(2, 0.0))
            r3 = float(rounds.get(3, 0.0))
            total = r1 + r2 + r3
            standings.append(
                {
                    "participant_id": p["participant_id"],
                    "username": p["username"],
                    "status": p["status"],
                    "round1_score": r1,
                    "round2_score": r2,
                    "round3_score": r3,
                    "total_score": total,
                }
            )
        standings.sort(key=lambda row: (-row["total_score"], row["username"].lower()))
        return standings

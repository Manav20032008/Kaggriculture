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
    event_number INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS evaluation_batches (
    event_number INTEGER NOT NULL DEFAULT 1,
    round_number INTEGER NOT NULL,
    batch_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    PRIMARY KEY (event_number, round_number)
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
    event_number INTEGER NOT NULL DEFAULT 1,
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
    event_number INTEGER NOT NULL DEFAULT 1,
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
    job_id TEXT,
    event_number INTEGER NOT NULL DEFAULT 1,
    attempt INTEGER,
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id),
    FOREIGN KEY (submission_id) REFERENCES submissions(submission_id)
);

CREATE TABLE IF NOT EXISTS evaluation_jobs (
    job_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    participant_id TEXT NOT NULL,
    submission_id TEXT NOT NULL,
    round_number INTEGER NOT NULL,
    event_number INTEGER NOT NULL DEFAULT 1,
    seed INTEGER NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    claim_token TEXT,
    started_at TEXT,
    score REAL,
    error_type TEXT,
    error_message TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(event_number, participant_id, round_number)
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
        self.db_path = Path(db_path).expanduser().resolve()
        self.files_dir = Path(files_dir).expanduser().resolve()
        self.data_dir = self.db_path.parent.resolve()
        self.compatibility_players_dir = (
            Path(compatibility_players_dir).expanduser().resolve() if compatibility_players_dir else None
        )
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("PRAGMA journal_mode = WAL")
                conn.executescript(SCHEMA)
                legacy_submission_scope = "event_number" not in {
                    row["name"] for row in conn.execute("PRAGMA table_info(submissions)")
                }
                legacy_active_scope = "event_number" not in {
                    row["name"] for row in conn.execute("PRAGMA table_info(round_active_submissions)")
                }
                self._ensure_column(conn, "evaluation_jobs", "event_number", "INTEGER NOT NULL DEFAULT 1")
                self._ensure_column(conn, "evaluation_jobs", "claim_token", "TEXT")
                self._ensure_column(conn, "evaluation_jobs", "started_at", "TEXT")
                self._ensure_column(conn, "submissions", "event_number", "INTEGER NOT NULL DEFAULT 1")
                self._ensure_column(conn, "round_active_submissions", "event_number", "INTEGER NOT NULL DEFAULT 1")
                self._ensure_column(conn, "evaluation_results", "job_id", "TEXT")
                self._ensure_column(conn, "evaluation_results", "event_number", "INTEGER NOT NULL DEFAULT 1")
                self._ensure_column(conn, "evaluation_results", "attempt", "INTEGER")
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_evaluation_result_attempt "
                    "ON evaluation_results(job_id, attempt) WHERE job_id IS NOT NULL AND attempt IS NOT NULL"
                )
                columns = {row["name"] for row in conn.execute("PRAGMA table_info(event_state)")}
                if "event_number" not in columns:
                    conn.execute("ALTER TABLE event_state ADD COLUMN event_number INTEGER NOT NULL DEFAULT 1")
                row = conn.execute("SELECT status FROM event_state WHERE id = 1").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO event_state (id, status, current_round, event_number, updated_at) VALUES (1, ?, NULL, 1, ?)",
                        (REGISTRATION, _now()),
                    )
                state = conn.execute("SELECT event_number FROM event_state WHERE id = 1").fetchone()
                if legacy_submission_scope:
                    conn.execute("UPDATE submissions SET event_number=?", (state["event_number"],))
                if legacy_active_scope:
                    conn.execute("UPDATE round_active_submissions SET event_number=?", (state["event_number"],))
                self._migrate_event_scoped_tables(conn)
                state = conn.execute("SELECT event_number FROM event_state WHERE id = 1").fetchone()
                self._cancel_stale_jobs(conn, int(state["event_number"]))
                conn.execute(
                    "UPDATE evaluation_batches SET status='CANCELLED', finished_at=? "
                    "WHERE event_number != ? AND status='STARTED'",
                    (_now(), int(state["event_number"])),
                )
                conn.commit()
            finally:
                conn.close()

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, name: str, declaration: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if name not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _migrate_event_scoped_tables(conn: sqlite3.Connection) -> None:
        """Rebuild pre-event-scoped constraints while preserving all persisted rows."""
        batch_columns = {row["name"]: row for row in conn.execute("PRAGMA table_info(evaluation_batches)")}
        if "event_number" not in batch_columns:
            conn.execute("ALTER TABLE evaluation_batches ADD COLUMN event_number INTEGER NOT NULL DEFAULT 1")
        batch_pk = [
            row["name"] for row in sorted(
                (row for row in conn.execute("PRAGMA table_info(evaluation_batches)") if row["pk"]),
                key=lambda row: row["pk"],
            )
        ]
        if batch_pk != ["event_number", "round_number"]:
            conn.execute(
                "CREATE TABLE evaluation_batches_new ("
                "event_number INTEGER NOT NULL DEFAULT 1, round_number INTEGER NOT NULL, "
                "batch_id TEXT NOT NULL UNIQUE, status TEXT NOT NULL, started_at TEXT NOT NULL, "
                "finished_at TEXT, PRIMARY KEY (event_number, round_number))"
            )
            conn.execute(
                "INSERT INTO evaluation_batches_new "
                "(event_number, round_number, batch_id, status, started_at, finished_at) "
                "SELECT event_number, round_number, batch_id, status, started_at, finished_at FROM evaluation_batches"
            )
            conn.execute("DROP TABLE evaluation_batches")
            conn.execute("ALTER TABLE evaluation_batches_new RENAME TO evaluation_batches")

        job_columns = {row["name"] for row in conn.execute("PRAGMA table_info(evaluation_jobs)")}
        required = {
            "job_id", "batch_id", "participant_id", "submission_id", "round_number", "event_number",
            "seed", "status", "attempts", "claim_token", "started_at", "score", "error_type",
            "error_message", "updated_at",
        }
        if not required.issubset(job_columns):
            return
        old_unique = False
        for index in conn.execute("PRAGMA index_list(evaluation_jobs)"):
            if index["unique"]:
                columns = [row["name"] for row in conn.execute(f"PRAGMA index_info('{index['name']}')")]
                if columns == ["participant_id", "round_number"]:
                    old_unique = True
                    break
        if old_unique:
            conn.execute(
                "CREATE TABLE evaluation_jobs_new ("
                "job_id TEXT PRIMARY KEY, batch_id TEXT NOT NULL, participant_id TEXT NOT NULL, "
                "submission_id TEXT NOT NULL, round_number INTEGER NOT NULL, "
                "event_number INTEGER NOT NULL DEFAULT 1, seed INTEGER NOT NULL, status TEXT NOT NULL, "
                "attempts INTEGER NOT NULL DEFAULT 0, claim_token TEXT, started_at TEXT, score REAL, "
                "error_type TEXT, error_message TEXT, updated_at TEXT NOT NULL, "
                "UNIQUE(event_number, participant_id, round_number))"
            )
            columns = (
                "job_id,batch_id,participant_id,submission_id,round_number,event_number,seed,status,"
                "attempts,claim_token,started_at,score,error_type,error_message,updated_at"
            )
            conn.execute(f"INSERT INTO evaluation_jobs_new ({columns}) SELECT {columns} FROM evaluation_jobs")
            conn.execute("DROP TABLE evaluation_jobs")
            conn.execute("ALTER TABLE evaluation_jobs_new RENAME TO evaluation_jobs")

    @staticmethod
    def _cancel_stale_jobs(conn: sqlite3.Connection, current_event: int) -> int:
        now = _now()
        cur = conn.execute(
            "UPDATE evaluation_jobs SET status='CANCELLED', claim_token=NULL, error_type='STALE_EVENT', "
            "error_message='Cancelled because the job belongs to a different event.', updated_at=? "
            "WHERE event_number != ? AND status IN ('QUEUED','RUNNING','RETRYING','SYSTEM_ERROR')",
            (now, current_event),
        )
        return cur.rowcount

    def cancel_stale_jobs(self) -> int:
        """Mark old-event work terminal before recovery or reset can consider it."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                state = self._require_state(conn)
                count = self._cancel_stale_jobs(conn, int(state["event_number"]))
                conn.execute(
                    "UPDATE evaluation_batches SET status='CANCELLED', finished_at=? "
                    "WHERE event_number != ? AND status='STARTED'",
                    (_now(), int(state["event_number"])),
                )
                conn.commit()
                return count
            finally:
                conn.close()

    def get_state(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                row = conn.execute(
                    "SELECT status, current_round, event_number, updated_at FROM event_state WHERE id = 1"
                ).fetchone()
                batches = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT event_number, round_number, batch_id, status, started_at, finished_at "
                        "FROM evaluation_batches WHERE event_number=? ORDER BY round_number",
                        (row["event_number"],),
                    ).fetchall()
                ]
            finally:
                conn.close()
        return {
            "status": row["status"],
            "current_round": row["current_round"],
            "event_number": row["event_number"],
            "updated_at": row["updated_at"],
            "total_rounds": TOTAL_ROUNDS,
            "evaluation_batches": batches,
        }

    def _require_state(self, conn: sqlite3.Connection) -> sqlite3.Row:
        row = conn.execute(
            "SELECT status, current_round, event_number, updated_at FROM event_state WHERE id = 1"
        ).fetchone()
        if row is None:
            raise EventError("Event state is missing.", 500)
        return row

    @staticmethod
    def _job_submission_is_active(conn: sqlite3.Connection, job: sqlite3.Row) -> bool:
        match = conn.execute(
            "SELECT 1 FROM submissions s JOIN round_active_submissions a "
            "ON a.participant_id=s.participant_id AND a.round_number=? "
            "WHERE s.submission_id=? AND s.participant_id=? AND s.round_number<=? "
            "AND s.event_number=? AND a.event_number=? AND s.status=? AND a.submission_id=?",
            (
                job["round_number"], job["submission_id"], job["participant_id"], job["round_number"], job["event_number"],
                job["event_number"], SUBMISSION_VALID, job["submission_id"],
            ),
        ).fetchone()
        return match is not None

    @staticmethod
    def _job_batch_is_active(conn: sqlite3.Connection, job: sqlite3.Row) -> bool:
        return conn.execute(
            "SELECT 1 FROM evaluation_batches WHERE batch_id=? AND event_number=? "
            "AND round_number=? AND status='STARTED'",
            (job["batch_id"], job["event_number"], job["round_number"]),
        ).fetchone() is not None

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
                conn.execute("BEGIN IMMEDIATE")
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
                conn.execute("BEGIN IMMEDIATE")
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
                conn.execute("BEGIN IMMEDIATE")
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
                conn.execute("BEGIN IMMEDIATE")
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
                    "SELECT batch_id, status FROM evaluation_batches WHERE round_number = ? AND event_number = ?",
                    (target, state["event_number"]),
                ).fetchone()
                if existing:
                    raise EventError(
                        f"Round {target} evaluation batch already exists ({existing['batch_id']}).",
                        409,
                    )

                batch_id = _new_id("evalbatch")
                conn.execute(
                    "INSERT INTO evaluation_batches (event_number, round_number, batch_id, status, started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, NULL)",
                    (state["event_number"], target, batch_id, "STARTED", _now()),
                )
                rows = conn.execute(
                    "SELECT a.participant_id, a.submission_id FROM round_active_submissions a "
                    "JOIN submissions s ON s.submission_id=a.submission_id "
                    "WHERE a.round_number = ? AND a.event_number=? AND s.event_number=? "
                    "AND a.submission_id IS NOT NULL",
                    (target, state["event_number"], state["event_number"]),
                ).fetchall()
                for row in rows:
                    conn.execute(
                        "INSERT INTO evaluation_jobs "
                        "(job_id, batch_id, participant_id, submission_id, round_number, event_number, seed, status, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?)",
                        (_new_id("job"), batch_id, row["participant_id"], row["submission_id"], target, state["event_number"], OFFICIAL_SEED, _now()),
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
                conn.execute("BEGIN IMMEDIATE")
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
                    "SELECT COUNT(*) FROM evaluation_jobs WHERE round_number = ? AND event_number = ? "
                    "AND status IN ('QUEUED', 'RUNNING', 'RETRYING', 'SYSTEM_ERROR')",
                    (target, state["event_number"]),
                ).fetchone()[0]
                if pending:
                    raise EventError("Evaluation jobs are still pending.", 409)
                conn.execute(
                    "UPDATE evaluation_batches SET status = ?, finished_at = ? "
                    "WHERE round_number = ? AND event_number = ?",
                    ("COMPLETED", _now(), target, state["event_number"]),
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
                conn.execute("BEGIN IMMEDIATE")
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

    def get_admin_overview(self) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                participants = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
                submissions = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
                jobs = {row["status"]: row["count"] for row in conn.execute(
                    "SELECT status, COUNT(*) AS count FROM evaluation_jobs "
                    "WHERE event_number=? GROUP BY status",
                    (self._require_state(conn)["event_number"],),
                ).fetchall()}
                rounds = [dict(row) for row in conn.execute(
                    "SELECT through_round, COUNT(*) AS participants, MAX(published_at) AS published_at "
                    "FROM leaderboard_snapshots GROUP BY through_round ORDER BY through_round"
                ).fetchall()]
            finally:
                conn.close()
        return {"event": self.get_state(), "participants": participants, "submissions": submissions,
                "evaluation_jobs": jobs, "rounds": rounds}

    def reset_event(self) -> dict:
        """Clear the active run without deleting the database or unrelated files."""
        files: list[Path] = []
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                state = self._require_state(conn)
                self._cancel_stale_jobs(conn, int(state["event_number"]))
                registered = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
                if state["status"] == REGISTRATION and registered == 0:
                    raise EventError("A new empty event is already active; refusing to increment its event number again.", 409)
                pending = conn.execute(
                    "SELECT COUNT(*) FROM evaluation_jobs WHERE event_number=? "
                    "AND status IN ('QUEUED','RUNNING','RETRYING')",
                    (state["event_number"],),
                ).fetchone()[0]
                if pending:
                    raise EventError("Evaluation is currently queued or running. Wait for completion before resetting.", 409)
                files = [Path(row[0]) for row in conn.execute("SELECT file_path FROM submissions").fetchall()]
                root = self.files_dir.resolve()
                for path in files:
                    try:
                        path.resolve().relative_to(root)
                    except ValueError as exc:
                        raise EventError("Reset stopped because a submission path is outside the submissions directory.", 409) from exc
                conn.execute("DELETE FROM evaluation_results")
                conn.execute("DELETE FROM evaluation_jobs")
                conn.execute("DELETE FROM round_active_submissions")
                conn.execute("DELETE FROM round_scores")
                conn.execute("DELETE FROM leaderboard_snapshots")
                conn.execute("DELETE FROM evaluation_batches")
                conn.execute("DELETE FROM submissions")
                conn.execute("DELETE FROM participants")
                conn.execute(
                    "UPDATE event_state SET status=?, current_round=NULL, event_number=event_number+1, updated_at=? WHERE id=1",
                    (REGISTRATION, _now()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        for path in files:
            path.unlink(missing_ok=True)
        for directory in self.files_dir.iterdir():
            if directory.is_dir():
                try:
                    directory.rmdir()
                except OSError:
                    pass
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
                    "SELECT COUNT(*) FROM evaluation_jobs WHERE round_number = ? AND event_number = ? "
                    "AND status IN ('QUEUED', 'RUNNING', 'RETRYING', 'SYSTEM_ERROR')",
                    (target, state["event_number"]),
                ).fetchone()[0]
                if pending:
                    raise EventError(f"{pending} evaluation jobs are still pending.", 409)
                jobs = conn.execute(
                    "SELECT participant_id, score, status, error_type FROM evaluation_jobs "
                    "WHERE round_number = ? AND event_number = ?",
                    (target, state["event_number"]),
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

    def get_evaluation_jobs(self, round_number: int | None = None, event_number: int | None = None) -> list[dict]:
        with self._lock:
            conn = self._connect()
            try:
                if event_number is None:
                    event_number = int(self._require_state(conn)["event_number"])
                sql = "SELECT * FROM evaluation_jobs WHERE event_number = ?"
                args = (event_number,)
                if round_number is not None:
                    sql += " AND round_number = ?"
                    args += (round_number,)
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
                state = self._require_state(conn)
                if (
                    row["event_number"] != state["event_number"]
                    or state["status"] != round_state(row["round_number"], "EVALUATING")
                    or state["current_round"] != row["round_number"]
                    or not self._job_submission_is_active(conn, row)
                    or not self._job_batch_is_active(conn, row)
                ):
                    conn.rollback()
                    return None
                token = _new_id("lease")
                started_at = _now()
                conn.execute(
                    "UPDATE evaluation_jobs SET status='RUNNING', attempts=attempts+1, claim_token=?, started_at=?, updated_at=? "
                    "WHERE job_id=? AND status IN ('QUEUED','RETRYING')",
                    (token, started_at, started_at, job_id),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM evaluation_jobs WHERE job_id=?", (job_id,)).fetchone())
            finally:
                conn.close()

    def claim_next_job(self, round_number: int) -> dict | None:
        """Atomically claim one persisted job; workers never enqueue the whole batch in RAM."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                state = self._require_state(conn)
                if state["status"] != round_state(round_number, "EVALUATING"):
                    conn.rollback()
                    return None
                row = conn.execute(
                    "SELECT job_id FROM evaluation_jobs WHERE round_number=? AND event_number=? "
                    "AND status IN ('QUEUED','RETRYING') "
                    "AND EXISTS (SELECT 1 FROM submissions s JOIN round_active_submissions a "
                    "ON a.participant_id=s.participant_id AND a.round_number=evaluation_jobs.round_number "
                    "WHERE s.submission_id=evaluation_jobs.submission_id "
                    "AND s.participant_id=evaluation_jobs.participant_id "
                    "AND s.round_number<=evaluation_jobs.round_number "
                    "AND s.event_number=evaluation_jobs.event_number "
                    "AND a.event_number=evaluation_jobs.event_number "
                    "AND a.submission_id=evaluation_jobs.submission_id) "
                    "AND EXISTS (SELECT 1 FROM evaluation_batches b WHERE b.batch_id=evaluation_jobs.batch_id "
                    "AND b.event_number=evaluation_jobs.event_number AND b.round_number=evaluation_jobs.round_number "
                    "AND b.status='STARTED') "
                    "ORDER BY participant_id LIMIT 1",
                    (round_number, state["event_number"]),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                job_id = row["job_id"]
                token = _new_id("lease")
                started_at = _now()
                conn.execute(
                    "UPDATE evaluation_jobs SET status='RUNNING', attempts=attempts+1, claim_token=?, started_at=?, updated_at=? "
                    "WHERE job_id=? AND status IN ('QUEUED','RETRYING')",
                    (token, started_at, started_at, job_id),
                )
                conn.commit()
                return dict(conn.execute("SELECT * FROM evaluation_jobs WHERE job_id=?", (job_id,)).fetchone())
            finally:
                conn.close()

    def recover_running_jobs(self, max_retries: int) -> int:
        """Fence callbacks from the old process and requeue only within the retry budget."""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                state = self._require_state(conn)
                self._cancel_stale_jobs(conn, int(state["event_number"]))
                rows = conn.execute(
                    "SELECT job_id, attempts FROM evaluation_jobs WHERE event_number=? AND status='RUNNING'",
                    (state["event_number"],),
                ).fetchall()
                for row in rows:
                    status = "RETRYING" if row["attempts"] <= max_retries else "SYSTEM_ERROR"
                    conn.execute(
                        "UPDATE evaluation_jobs SET status=?, claim_token=NULL, error_type='SYSTEM_ERROR', "
                        "error_message='Worker process restarted.', updated_at=? WHERE job_id=? AND status='RUNNING'",
                        (status, _now(), row["job_id"]),
                    )
                conn.commit()
                return len(rows)
            finally:
                conn.close()

    def finish_job(self, job_id: str, status: str, score: float | None = None, error_type: str | None = None, error_message: str | None = None, claim_token: str | None = None) -> bool:
        if status not in {"SUCCESS", "PLAYER_ERROR", "TIMEOUT", "SYSTEM_ERROR", "RETRYING"}:
            raise EventError("Invalid evaluation job status.", 400)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM evaluation_jobs WHERE job_id=?", (job_id,)).fetchone()
                if row is None:
                    conn.rollback()
                    return False
                if row["status"] == "RUNNING" and (not claim_token or row["claim_token"] != claim_token):
                    conn.rollback()
                    return False
                if claim_token and row["claim_token"] != claim_token:
                    conn.rollback()
                    return False
                state = self._require_state(conn)
                if (
                    row["event_number"] != state["event_number"]
                    or state["status"] != round_state(row["round_number"], "EVALUATING")
                    or state["current_round"] != row["round_number"]
                    or not self._job_submission_is_active(conn, row)
                    or not self._job_batch_is_active(conn, row)
                ):
                    conn.rollback()
                    return False
                now = _now()
                conn.execute(
                    "UPDATE evaluation_jobs SET status=?, score=?, error_type=?, error_message=?, claim_token=NULL, updated_at=? WHERE job_id=?",
                    (status, score, error_type, (error_message or "")[:4000] or None, now, job_id),
                )
                row = conn.execute("SELECT * FROM evaluation_jobs WHERE job_id=?", (job_id,)).fetchone()
                if status not in ("RETRYING", "RUNNING"):
                    conn.execute(
                        "INSERT OR IGNORE INTO evaluation_results "
                        "(evaluation_id, participant_id, submission_id, round_number, seed, score, status, error_type, error_message, started_at, finished_at, job_id, event_number, attempt) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (_new_id("eval"), row["participant_id"], row["submission_id"], row["round_number"], row["seed"], score, status, error_type, (error_message or "")[:4000] or None, row["started_at"], now, job_id, row["event_number"], row["attempts"]),
                    )
                conn.commit()
                return True
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

    def retry_system_errors(self, round_number: int, max_retries: int = 2) -> int:
        with self._lock:
            conn = self._connect()
            try:
                state = self._require_state(conn)
                if state["status"] != round_state(round_number, "EVALUATING"):
                    raise EventError("System errors can be retried only while that round is evaluating.", 409)
                cur = conn.execute(
                    "UPDATE evaluation_jobs SET status='RETRYING', updated_at=? "
                    "WHERE round_number=? AND event_number=? AND status='SYSTEM_ERROR' AND attempts < ?",
                    (_now(), round_number, state["event_number"], max_retries + 1),
                )
                conn.commit()
                return cur.rowcount
            finally:
                conn.close()

    def upload_submission(self, participant_id: str, source_text: str) -> dict:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
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
                root = self.files_dir.resolve()
                dest_dir = (root / participant_id).resolve()
                try:
                    dest_dir.relative_to(root)
                except ValueError as exc:
                    raise EventError("Participant storage path is invalid.", 400) from exc
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest_path = dest_dir / f"{submission_id}.py"
                temp_path = dest_dir / f".{submission_id}.tmp"
                try:
                    with temp_path.open("x", encoding="utf-8", newline="") as agent_file:
                        agent_file.write(source_text)
                        agent_file.flush()
                    temp_path.replace(dest_path)
                except Exception:
                    temp_path.unlink(missing_ok=True)
                    raise

                created_at = _now()
                conn.execute(
                    "INSERT INTO submissions "
                    "(submission_id, participant_id, event_number, round_number, version, file_path, created_at, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        submission_id,
                        participant_id,
                        state["event_number"],
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
                event_number = int(self._require_state(conn)["event_number"])
                return self._resolve_active(conn, participant_id, round_number, event_number)
            finally:
                conn.close()

    def _resolve_active(self, conn: sqlite3.Connection, participant_id: str, round_number: int, event_number: int) -> dict | None:
        frozen = conn.execute(
            "SELECT s.submission_id, s.participant_id, s.round_number, s.version, s.file_path, s.created_at, s.status "
            "FROM round_active_submissions a "
            "LEFT JOIN submissions s ON s.submission_id = a.submission_id "
            "WHERE a.participant_id = ? AND a.round_number = ? AND a.event_number=? "
            "AND (s.event_number=? OR s.submission_id IS NULL)",
            (participant_id, round_number, event_number, event_number),
        ).fetchone()
        if frozen is not None:
            if frozen["submission_id"] is None:
                return None
            return dict(frozen)

        row = conn.execute(
            "SELECT submission_id, participant_id, round_number, version, file_path, created_at, status "
            "FROM submissions "
            "WHERE participant_id = ? AND event_number=? AND round_number <= ? AND status = ? "
            "ORDER BY round_number DESC, version DESC LIMIT 1",
            (participant_id, event_number, round_number, SUBMISSION_VALID),
        ).fetchone()
        return dict(row) if row else None

    def _freeze_round_active(self, conn: sqlite3.Connection, round_number: int) -> None:
        frozen_at = _now()
        event_number = int(self._require_state(conn)["event_number"])
        participants = conn.execute("SELECT participant_id FROM participants").fetchall()
        for p in participants:
            pid = p["participant_id"]
            active = conn.execute(
                "SELECT submission_id FROM submissions "
                "WHERE participant_id = ? AND event_number=? AND round_number <= ? AND status = ? "
                "ORDER BY round_number DESC, version DESC LIMIT 1",
                (pid, event_number, round_number, SUBMISSION_VALID),
            ).fetchone()
            submission_id = active["submission_id"] if active else None
            conn.execute(
                "INSERT INTO round_active_submissions (participant_id, event_number, round_number, submission_id, frozen_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(participant_id, round_number) DO UPDATE SET "
                "event_number = excluded.event_number, submission_id = excluded.submission_id, frozen_at = excluded.frozen_at",
                (pid, event_number, round_number, submission_id, frozen_at),
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
        event_number: int | None = None,
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
                conn.execute("BEGIN IMMEDIATE")
                state = self._require_state(conn)
                current_event = int(state["event_number"])
                if event_number is not None and event_number != current_event:
                    raise EventError("Evaluation result belongs to a stale event.", 409)
                if submission_id is not None:
                    relation = conn.execute(
                        "SELECT 1 FROM submissions s JOIN round_active_submissions a "
                        "ON a.participant_id=s.participant_id AND a.round_number=? "
                        "WHERE s.submission_id=? AND s.participant_id=? AND s.round_number<=? "
                        "AND s.event_number=? AND a.event_number=? "
                        "AND a.submission_id=?",
                        (round_number, submission_id, participant_id, round_number, current_event, current_event, submission_id),
                    ).fetchone()
                    if relation is None:
                        raise EventError("Evaluation result submission does not belong to this participant and round.", 409)
                conn.execute(
                    "INSERT INTO evaluation_results ("
                    "evaluation_id, participant_id, submission_id, round_number, seed, score, "
                    "status, error_type, error_message, started_at, finished_at, event_number"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                        current_event,
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

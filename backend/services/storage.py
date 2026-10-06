"""Minimal SQLite persistence for teams, submissions, and sandbox runs."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = ROOT / "data" / "kaggriculture.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PlatformStore:
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def connect(self):
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def session(self):
        db = self.connect()
        try:
            with db:
                yield db
        finally:
            db.close()

    def _initialize(self):
        with self.session() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS teams (
                    id INTEGER PRIMARY KEY,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS submissions (
                    id INTEGER PRIMARY KEY,
                    team_id INTEGER NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    file_path TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    validation_status TEXT NOT NULL,
                    validation_errors TEXT,
                    sandbox_score REAL,
                    official_score REAL,
                    runtime_seconds REAL,
                    is_active INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(team_id, version)
                );
                CREATE TABLE IF NOT EXISTS sandbox_runs (
                    id INTEGER PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    opponent TEXT NOT NULL,
                    seed INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    winner TEXT,
                    bot_money REAL,
                    opponent_money REAL,
                    runtime_seconds REAL,
                    replay_id TEXT,
                    error TEXT
                );
                CREATE TABLE IF NOT EXISTS evaluations (
                    id INTEGER PRIMARY KEY,
                    submission_id INTEGER NOT NULL REFERENCES submissions(id) ON DELETE CASCADE,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    rating REAL,
                    win_rate REAL,
                    average_final_money REAL,
                    average_money_differential REAL,
                    wins INTEGER,
                    ties INTEGER,
                    games INTEGER,
                    error TEXT
                );
            """)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(sandbox_runs)").fetchall()}
            if "replay_id" not in columns:
                db.execute("ALTER TABLE sandbox_runs ADD COLUMN replay_id TEXT")

    def _team_id(self, db, username: str) -> int:
        row = db.execute("SELECT id FROM teams WHERE username = ?", (username,)).fetchone()
        if row:
            return row["id"]
        cursor = db.execute("INSERT INTO teams(username, created_at) VALUES (?, ?)", (username, utc_now()))
        return cursor.lastrowid

    def create_submission(self, username: str, file_path: Path, *, valid: bool, errors: str | None = None) -> dict:
        with self.session() as db:
            team_id = self._team_id(db, username)
            row = db.execute("SELECT COALESCE(MAX(version), 0) + 1 AS version FROM submissions WHERE team_id = ?", (team_id,)).fetchone()
            version = row["version"]
            cursor = db.execute(
                """INSERT INTO submissions(team_id, version, file_path, created_at, validation_status, validation_errors)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (team_id, version, str(file_path), utc_now(), "valid" if valid else "invalid", errors),
            )
            return self.get_submission(cursor.lastrowid, db=db)

    def get_submission(self, submission_id: int, *, db=None) -> dict | None:
        owns = db is None
        db = db or self.connect()
        try:
            row = db.execute(
                """SELECT s.*, t.username FROM submissions s JOIN teams t ON t.id = s.team_id
                   WHERE s.id = ?""", (submission_id,),
            ).fetchone()
            return dict(row) if row else None
        finally:
            if owns:
                db.close()

    def list_submissions(self, username: str) -> list[dict]:
        with self.session() as db:
            rows = db.execute(
                """SELECT s.* FROM submissions s JOIN teams t ON t.id = s.team_id
                   WHERE t.username = ? ORDER BY s.version DESC""", (username,),
            ).fetchall()
            return [dict(row) for row in rows]

    def current_submission(self, username: str) -> dict | None:
        items = self.list_submissions(username)
        return items[0] if items else None

    def activate_submission(self, username: str, submission_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute(
                """SELECT s.id, s.team_id FROM submissions s JOIN teams t ON t.id = s.team_id
                   WHERE s.id = ? AND t.username = ? AND s.validation_status = 'valid'""",
                (submission_id, username),
            ).fetchone()
            if not row:
                return None
            db.execute("UPDATE submissions SET is_active = 0 WHERE team_id = ?", (row["team_id"],))
            db.execute("UPDATE submissions SET is_active = 1 WHERE id = ?", (submission_id,))
            return self.get_submission(submission_id, db=db)

    def record_sandbox(self, submission_id: int, result: dict) -> dict:
        with self.session() as db:
            db.execute(
                """INSERT INTO sandbox_runs(submission_id, created_at, opponent, seed, status, winner,
                   bot_money, opponent_money, runtime_seconds, replay_id, error) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (submission_id, utc_now(), result["opponent"], result["seed"], result["status"], result.get("winner"),
                 result.get("botFinalMoney"), result.get("opponentFinalMoney"), result.get("runtimeSeconds"), result.get("replayId"), result.get("error")),
            )
            db.execute(
                "UPDATE submissions SET sandbox_score = ?, runtime_seconds = ? WHERE id = ?",
                (result.get("botFinalMoney"), result.get("runtimeSeconds"), submission_id),
            )
            return self.get_submission(submission_id, db=db)

    def last_sandbox(self, submission_id: int) -> dict | None:
        with self.session() as db:
            row = db.execute("SELECT * FROM sandbox_runs WHERE submission_id = ? ORDER BY id DESC LIMIT 1", (submission_id,)).fetchone()
            return dict(row) if row else None

    def record_evaluation(self, submission_id: int, result: dict) -> dict:
        with self.session() as db:
            db.execute(
                """INSERT INTO evaluations(submission_id, created_at, status, rating, win_rate,
                   average_final_money, average_money_differential, wins, ties, games, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (submission_id, utc_now(), result.get("status", "complete"), result.get("rating"),
                 result.get("winRate"), result.get("averageFinalMoney"), result.get("averageMoneyDifferential"),
                 result.get("wins"), result.get("ties"), result.get("games"), result.get("error")),
            )
            db.execute("UPDATE submissions SET official_score = ? WHERE id = ?", (result.get("rating"), submission_id))
            return self.get_submission(submission_id, db=db)

    def leaderboard(self) -> list[dict]:
        with self.session() as db:
            rows = db.execute("""
                SELECT t.username AS team, s.version, s.official_score AS rating, e.win_rate,
                       e.average_final_money, e.games, e.created_at
                FROM submissions s
                JOIN teams t ON t.id = s.team_id
                JOIN evaluations e ON e.id = (
                    SELECT e2.id FROM evaluations e2 WHERE e2.submission_id = s.id ORDER BY e2.id DESC LIMIT 1
                )
                WHERE s.is_active = 1 AND s.official_score IS NOT NULL
                ORDER BY s.official_score DESC, e.win_rate DESC, e.average_final_money DESC, t.username COLLATE NOCASE
            """).fetchall()
            return [{"rank": index + 1, **dict(row)} for index, row in enumerate(rows)]

    def summary(self, username: str) -> dict:
        submissions = self.list_submissions(username)
        current = submissions[0] if submissions else None
        active = next((item for item in submissions if item["is_active"]), None)
        scored = [item["sandbox_score"] for item in submissions if item["sandbox_score"] is not None]
        return {
            "team": username,
            "currentSubmission": current,
            "activeSubmission": active,
            "currentVersion": f"v{current['version']}" if current else None,
            "validationStatus": current["validation_status"] if current else "not_uploaded",
            "lastTest": self.last_sandbox(current["id"]) if current else None,
            "bestScore": max(scored) if scored else None,
            "submissionCount": len(submissions),
        }


store = PlatformStore()

"""Runtime paths and environment flags shared by the event service."""
from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("KAGGRI_DATA_DIR", "").strip() or ROOT / "data").expanduser().resolve()
SUBMISSIONS_DIR = (DATA_DIR / "submissions").resolve()
DATABASE_PATH = (DATA_DIR / "event.sqlite").resolve()

for path in (DATA_DIR, SUBMISSIONS_DIR, DATA_DIR / "tmp"):
    path.mkdir(parents=True, exist_ok=True)


def is_production() -> bool:
    return os.environ.get("KAGGRI_ENV", "").strip().lower() == "production"


def configured_cors_origins() -> list[str]:
    raw = os.environ.get("KAGGRI_CORS_ORIGINS", "")
    origins = [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]
    if origins:
        return origins
    if is_production():
        return []
    return [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

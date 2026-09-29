from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

SUBMISSIONS_DIR = BASE_DIR / "submissions"
RESULTS_DIR = BASE_DIR / "results"

LEADERBOARD_FILE = RESULTS_DIR / "leaderboard.json"

GAME_NAME = "kaggriculture"
EPISODE_STEPS = 720

# Practice seed can be public. Change this before the official final.
OFFICIAL_SEED = 20260929

# The official opponent is Kaggriculture's built-in deterministic starter agent.
OPPONENT = "starter"

MAX_SUBMISSION_BYTES = 100_000
MAX_RUNTIME_SECONDS = 120

ALLOWED_SUBMISSION_FILENAME = "main.py"

SUBMISSIONS_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

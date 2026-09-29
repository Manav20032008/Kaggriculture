import sys
from pathlib import Path

# Add project root to Python import path.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from competition.engine import evaluate_submission


# Use the actual participant submission format.
submission = PROJECT_ROOT / "participant_starter" / "main.py"

print("Testing local evaluator...")
print(f"Submission: {submission}")
print("")


result = evaluate_submission(
    submission,
    "LOCAL_TEST",
    seed=20260929,
    use_docker=False,
)

print("\n=== RESULT ===")
print(result.to_dict())
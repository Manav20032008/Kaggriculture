from __future__ import annotations

from pathlib import Path

from config import LEADERBOARD_FILE, OFFICIAL_SEED
from competition.engine import evaluate_submission
from competition.leaderboard import Leaderboard


def evaluate_and_record(
    submission: Path,
    team: str,
    *,
    seed: int = OFFICIAL_SEED,
    use_docker: bool = True,
):
    """
    Evaluate a submission and record the result in the leaderboard.

    Returns:
        tuple:
            (EvaluationResult, leaderboard_rows)
    """

    result = evaluate_submission(
        submission,
        team,
        seed=seed,
        use_docker=use_docker,
    )

    leaderboard = Leaderboard(LEADERBOARD_FILE)

    rows = leaderboard.upsert(
        result.to_dict()
    )

    return result, rows
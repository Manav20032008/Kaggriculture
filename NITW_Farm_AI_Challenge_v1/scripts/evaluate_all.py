from pathlib import Path

from config import SUBMISSIONS_DIR, OFFICIAL_SEED
from competition.evaluator import evaluate_and_record


def main():
    teams = sorted(
        p for p in SUBMISSIONS_DIR.iterdir()
        if p.is_dir() and (p / "main.py").exists()
    )

    if not teams:
        print("No submissions found.")
        return

    for team_dir in teams:
        team = team_dir.name
        print(f"\nEvaluating {team}...")
        result, _ = evaluate_and_record(
            team_dir / "main.py",
            team,
            seed=OFFICIAL_SEED,
            use_docker=True,
        )
        print(
            f"{team}: {result.status} | "
            f"score={result.score} | "
            f"time={result.runtime_seconds:.2f}s"
        )


if __name__ == "__main__":
    main()

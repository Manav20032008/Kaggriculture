from __future__ import annotations

import argparse
import sys
from pathlib import Path


# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from config import OFFICIAL_SEED
from competition.evaluator import evaluate_and_record


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate a NITW Farm AI submission."
    )

    parser.add_argument(
        "submission",
        type=Path,
        help="Path to participant main.py",
    )

    parser.add_argument(
        "team",
        type=str,
        help="Team name",
    )

    parser.add_argument(
        "--seed",
        type=int,
        default=OFFICIAL_SEED,
        help="Evaluation seed",
    )

    parser.add_argument(
        "--trusted-local",
        action="store_true",
        help="Run locally instead of Docker. Development only.",
    )

    args = parser.parse_args()

    submission = args.submission.resolve()

    if not submission.exists():
        print(f"ERROR: Submission does not exist: {submission}")
        sys.exit(1)

    print("========================================")
    print(" NITW FARM AI CHALLENGE")
    print(" Submission Evaluation")
    print("========================================")
    print(f"Team:       {args.team}")
    print(f"Submission: {submission}")
    print(
        "Mode:       "
        f"{'TRUSTED LOCAL' if args.trusted_local else 'DOCKER'}"
    )
    print(f"Seed:       {args.seed}")
    print("")

    # evaluate_and_record returns TWO values:
    #
    #   result
    #   rows
    #
    result, rows = evaluate_and_record(
        submission=submission,
        team=args.team,
        seed=args.seed,
        use_docker=not args.trusted_local,
    )

    print("")
    print("=============== RESULT ===============")
    print(f"Team:       {result.team}")
    print(f"Score:      {result.score}")
    print(f"Reward:     {result.reward}")
    print(f"Status:     {result.status}")
    print(f"Runtime:    {result.runtime_seconds:.3f}s")
    print(f"Seed:       {result.seed}")

    if result.error:
        print(f"Error:      {result.error}")

    print("")
    print("============= LEADERBOARD =============")

    if rows:
        for index, row in enumerate(rows, start=1):
            print(
                f"{index:>2}. "
                f"{row.get('team', 'UNKNOWN'):<20} "
                f"{row.get('score', 0):>10}"
            )
    else:
        print("Leaderboard is empty.")

    print("========================================")

    if result.status != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--steps", type=int, default=720)
    parser.add_argument("--opponent", default="starter")
    args = parser.parse_args()

    try:
        from kaggle_environments import make

        submission = Path(args.submission)

        env = make(
            "kaggriculture",
            configuration={
                "episodeSteps": args.steps,
                "seed": args.seed,
            },
            debug=False,
        )

        env.run([str(submission), args.opponent])

        final = env.steps[-1]
        state = final[0]

        print(json.dumps({
            "status": state.status,
            "reward": float(state.reward),
        }))

    except Exception as exc:
        print(
            json.dumps({
                "status": "failed",
                "reward": 0,
                "error": f"{type(exc).__name__}: {exc}",
            })
        )
        sys.exit(1)


if __name__ == "__main__":
    main()

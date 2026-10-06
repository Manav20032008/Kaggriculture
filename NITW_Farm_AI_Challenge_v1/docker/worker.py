import argparse
import json
import sys
import traceback
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

    except Exception as exc:
        print(json.dumps({"status": "failed", "reward": 0, "error_type": "SYSTEM_ERROR",
                          "error": f"Evaluator setup failed: {type(exc).__name__}: {exc}"}))
        sys.exit(1)

    try:
        env.run([str(submission), args.opponent])
    except Exception as exc:
        details = traceback.format_exc()
        kind = "PLAYER_ERROR" if str(submission.resolve()) in details else "SYSTEM_ERROR"
        print(json.dumps({"status": "failed", "reward": 0, "error_type": kind,
                          "error": f"{type(exc).__name__}: {exc}\n{details[-3000:]}"}))
        sys.exit(1)

    tracebacks = []
    for frame in getattr(env, "logs", []) or []:
        if isinstance(frame, (list, tuple)) and frame:
            player_log = frame[0]
            stderr = player_log.get("stderr", "") if isinstance(player_log, dict) else ""
            if "Traceback (most recent call last)" in str(stderr):
                tracebacks.append(str(stderr)[-2000:])
    if tracebacks:
        print(json.dumps({"status": "failed", "reward": 0, "error_type": "PLAYER_ERROR",
                          "error": "Agent raised an exception:\n" + "\n".join(tracebacks[-3:])}))
        sys.exit(1)

    try:
        state = env.steps[-1][0]
        print(json.dumps({"status": state.status, "reward": float(state.reward)}))
    except Exception as exc:
        print(json.dumps({"status": "failed", "reward": 0, "error_type": "SYSTEM_ERROR",
                          "error": f"Evaluator result extraction failed: {type(exc).__name__}: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()

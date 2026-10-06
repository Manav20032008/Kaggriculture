import argparse
import json
import subprocess
import sys
import traceback
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--steps", type=int, default=720)
    parser.add_argument("--opponent", default="starter")
    parser.add_argument("--docker", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    submission = Path(args.submission)
    if args.docker:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
            import competition.engine as engine
            engine.MAX_RUNTIME_SECONDS = args.timeout
            _run_docker = engine._run_docker
            payload = _run_docker(submission, args.seed)
            print(json.dumps(payload))
            if payload.get("error_type") or str(payload.get("status", "")).lower() not in {"done", "success", "finished", "terminated", "active", ""}:
                sys.exit(1)
            return
        except subprocess.TimeoutExpired:
            print(json.dumps({"status": "failed", "reward": 0, "error_type": "TIMEOUT",
                              "error": f"Docker evaluation exceeded {args.timeout} seconds."}))
            sys.exit(1)
        except Exception as exc:
            print(json.dumps({"status": "failed", "reward": 0, "error_type": "SYSTEM_ERROR",
                              "error": f"Docker evaluator failed: {type(exc).__name__}: {exc}"}))
            sys.exit(1)

    try:
        from kaggle_environments import make
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
        # Attribute an exception to a player only when the traceback identifies
        # their frozen source file; unknown failures stay system errors.
        kind = "PLAYER_ERROR" if str(submission.resolve()) in details else "SYSTEM_ERROR"
        print(json.dumps({"status": "failed", "reward": 0, "error_type": kind,
                          "error": f"{type(exc).__name__}: {exc}\n{details[-3000:]}"}))
        sys.exit(1)

    try:
        # Kaggle can mark the episode DONE after replacing a crashed agent's
        # action with a no-op, so inspect the per-player runtime logs as well.
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
        state = env.steps[-1][0]
        print(json.dumps({"status": state.status, "reward": float(state.reward)}))
    except Exception as exc:
        print(json.dumps({"status": "failed", "reward": 0, "error_type": "SYSTEM_ERROR",
                          "error": f"Evaluator result extraction failed: {type(exc).__name__}: {exc}"}))
        sys.exit(1)


if __name__ == "__main__":
    main()

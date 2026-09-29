# NITW Farm AI Challenge

A small college-level competition platform for an AI/ML club event inspired by Kaggriculture.

## Architecture

Participants submit a `main.py` containing:

```python
def agent(obs):
    return {
        "farmer": ["PASS"],
        "hands": [],
        "market": []
    }
```

The official evaluator runs the submission against the built-in Kaggriculture `starter` agent for 720 turns and records the final reward.

For safety, submitted code should be evaluated inside Docker. The web server only stores submissions; it does not execute uploaded code.

## Requirements

- Python 3.10+
- Docker
- Internet during setup to install Python dependencies/build the evaluator image

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Build the evaluator image:

```bash
docker build -t nitw-farm-ai-evaluator .
```

Start the web server:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000
```

## Participant package

Give participants `participant_starter/main.py`.

They modify only the `agent(obs)` function.

## Evaluate a submission

From the project root:

```bash
python scripts/evaluate_submission.py submissions/TEAM_NAME/main.py --team "TEAM_NAME"
```

The evaluator creates a Docker container and runs the agent against the deterministic official seed.

## Re-evaluate all submissions

```bash
python scripts/evaluate_all.py
```

## Important

Do not execute untrusted participant code directly on the host. Use Docker for official evaluation.

The game mechanics themselves come from the Kaggriculture environment described in the supplied competition README.

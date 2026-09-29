# NITW Farm AI Challenge

A small college-level competition platform for an AI/ML club event inspired by Kaggriculture.

## Architecture

Participants submit a `main.py` containing their AI agent.

The official evaluator runs the submission against Kaggriculture's built-in `starter` agent for 720 turns and records the final reward.

For safety, submitted code is evaluated inside Docker with no network access and resource limits.

## Requirements

- Python 3.10+
- Docker
- Internet during setup to install dependencies/build the evaluator image

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
docker build -t nitw-farm-ai-evaluator .
```

## Start the web platform

From the project root:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Open:

```text
http://localhost:8000
```

The web flow is:

```text
Student uploads main.py
        ↓
Validate submission
        ↓
Docker sandbox
        ↓
Kaggriculture — 720 turns
        ↓
Final reward
        ↓
Leaderboard
```

## Participant package

Give participants `participant_starter/main.py`.

They modify their agent strategy and submit that file.

## Command-line evaluation

From the project root:

```bash
python scripts/evaluate_submission.py     submissions/TEAM_NAME/main.py     TEAM_NAME
```

For development only, trusted local evaluation is also available:

```bash
python scripts/evaluate_submission.py     participant_starter/main.py     TEST_TEAM     --trusted-local
```

## Re-evaluate all submissions

```bash
python scripts/evaluate_all.py
```

## Important

Do not execute untrusted participant code directly on the host. Official submissions should use Docker.

The official seed is configured in `config.py`. Change it before the real event if you want a fresh official evaluation seed.

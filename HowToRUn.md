# NITW Farm AI Challenge — Setup Guide

This guide is for running the NITW Farm AI Challenge platform on your own computer.

## 1. Requirements

Install:

* Python 3.11+
* Docker
* Git (optional)

Check:

```bash
python3 --version
docker --version
```

Docker must be running.

---

## 2. Extract the Project

Extract the ZIP file:

```text
NITW_Farm_AI_Challenge_v2_Web.zip
```

Open a terminal inside:

```text
NITW_Farm_AI_Challenge_v2_Web/NITW_Farm_AI_Challenge_v1
```

You should see:

```text
config.py
Dockerfile
requirements.txt
competition/
docker/
participant_starter/
web/
scripts/
submissions/
results/
```

---

## 3. Create a Python Environment

From the `NITW_Farm_AI_Challenge_v1` directory:

### Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Windows

```powershell
python -m venv .venv
.venv\Scripts\activate
```

---

## 4. Install Dependencies

Run:

```bash
pip install -r requirements.txt
```

Wait until installation finishes.

---

## 5. Build the Docker Evaluator

Run:

```bash
docker build -t nitw-farm-ai-evaluator .
```

This only needs to be done once.

Verify:

```bash
docker images | grep nitw-farm-ai-evaluator
```

---

## 6. Test Docker

Run:

```bash
python scripts/evaluate_submission.py participant_starter/main.py TEST_TEAM
```

The evaluator should run the Kaggriculture game inside Docker.

You should get something similar to:

```text
Mode:       DOCKER
Score:      3297.0
Reward:     3297.0
Status:     success
Runtime:    ...
Seed:       20260929
```

If this works, the evaluator is ready.

---

# 7. Start the Web Platform

Run:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

You should see:

```text
Uvicorn running on http://0.0.0.0:8000
```

Open your browser:

```text
http://localhost:8000
```

---

# 8. Test the Website

The website contains:

### Home

```text
http://localhost:8000/
```

Shows the challenge and leaderboard.

### Submit

```text
http://localhost:8000/submit
```

Upload:

```text
main.py
```

and enter a team name.

### Leaderboard

```text
http://localhost:8000/leaderboard
```

Shows the current rankings.

---

# 9. How a Participant Submits

The participant must upload a Python file named exactly:

```text
main.py
```

Example:

```text
main.py
```

The website will:

```text
Upload main.py
      ↓
Validate submission
      ↓
Run Docker evaluator
      ↓
Run Kaggriculture
      ↓
720 turns
      ↓
Calculate reward
      ↓
Save score
      ↓
Display result
      ↓
Update leaderboard
```

The participant does NOT need Docker on their own machine if they are only submitting through the organizer's website.

Docker is required on the machine running the competition server/evaluator.

---

# 10. Important: Keep the Server Terminal Open

While the website is running, keep this terminal open:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Do not close it.

To stop the server:

```text
Ctrl+C
```

---

# 11. Allow Another Person on the Same Wi-Fi

If your friend is running the server and another computer needs to access it:

### Find the server computer's IP

Linux:

```bash
hostname -I
```

Example:

```text
192.168.1.15
```

Then another computer on the same network can open:

```text
http://192.168.1.15:8000
```

The server must be started with:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

NOT:

```bash
uvicorn web.app:app --port 8000
```

---

# 12. Common Problems

## `No module named fastapi`

Run:

```bash
pip install -r requirements.txt
```

Make sure the virtual environment is activated.

---

## `No module named web`

Make sure you are inside:

```text
NITW_Farm_AI_Challenge_v1
```

Check:

```bash
pwd
ls
```

You should see:

```text
web/
competition/
config.py
requirements.txt
```

Then run:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8000
```

---

## Docker permission denied

Check:

```bash
docker ps
```

If Docker requires permission on Linux, add the user to the Docker group:

```bash
sudo usermod -aG docker $USER
```

Then log out and log back in.

Test again:

```bash
docker ps
```

---

## Docker image not found

Build it:

```bash
docker build -t nitw-farm-ai-evaluator .
```

Then verify:

```bash
docker images | grep nitw-farm-ai-evaluator
```

---

## Port 8000 already in use

Use another port:

```bash
uvicorn web.app:app --host 0.0.0.0 --port 8001
```

Then open:

```text
http://localhost:8001
```

---

# 13. For the Actual Event

The organizer should:

1. Start Docker.
2. Activate the Python environment.
3. Start Uvicorn.
4. Give participants the server URL.
5. Participants upload `main.py`.
6. The server evaluates submissions.
7. Scores appear on the leaderboard.

Do NOT give participants access to:

```text
competition/
docker/
results/
```

They only need the submission interface.

---

# Quick Start

After everything has been installed once, the organizer only needs:

```bash
cd NITW_Farm_AI_Challenge_v2_Web/NITW_Farm_AI_Challenge_v1

source .venv/bin/activate

uvicorn web.app:app --host 0.0.0.0 --port 8000
```

Then open:

```text
http://localhost:8000
```

For another computer on the same Wi-Fi:

```text
http://YOUR_SERVER_IP:8000
```

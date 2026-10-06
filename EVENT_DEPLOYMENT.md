# Event deployment

## 1. Prerequisites

- Windows, macOS, or Linux with Python 3.10+.
- Kaggle Environments installed in the Python interpreter used for evaluation.
- Node.js and npm for the React frontend.
- Docker Engine for production participant-code isolation (Docker mode is optional for local development).

## 2. Environment variables

Set these in the backend process environment. Keep the admin token private and do not commit `.env` files.

| Variable | Required | Default | Purpose |
| --- | --- | --- | --- |
| `KAGGRI_ADMIN_TOKEN` | Yes | None; admin controls return 503 when absent | Secret required in the `X-Admin-Token` header for event controls. |
| `KAGGRI_PYTHON` | Usually | Auto-detected | Python executable containing `kaggle_environments`. |
| `KAGGRI_MAX_WORKERS` | No | `2` | Maximum concurrent evaluator jobs. |
| `KAGGRI_EVAL_TIMEOUT` | No | Kaggriculture runtime limit (`120` seconds) | Per-agent evaluation timeout in seconds. |
| `KAGGRI_SYSTEM_RETRIES` | No | `2` | Automatic retries after system errors. |
| `KAGGRI_USE_DOCKER` | Recommended in production | `0` | Set to `1` to evaluate each submission in the `nitw-farm-ai-evaluator` container. |

Example PowerShell setup (choose a unique secret locally):

```powershell
$env:KAGGRI_ADMIN_TOKEN = "replace-with-a-private-random-token"
$env:KAGGRI_PYTHON = (Get-Command python).Source
$env:KAGGRI_MAX_WORKERS = "2"
$env:KAGGRI_USE_DOCKER = "1"
```

## 3. Backend startup

From the repository root, activate the Python environment with the evaluator dependencies installed, then run:

```powershell
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

The SQLite database is `data/event.sqlite`; immutable agent files are under `data/submissions/`.

## 4. Frontend startup and build

```powershell
cd frontend
npm ci
npm run dev
```

The development server uses Vite's configured API proxy. Verify a production build with `npm run build`; run lint with `npm run lint`.

## 5. Admin workflow

Enter the token configured in `KAGGRI_ADMIN_TOKEN` in the admin controls. The API expects it in the `X-Admin-Token` header. Keep the token only in the trusted admin browser session and never publish it.

## 6. Round workflow

1. Register participants while the event is in `REGISTRATION`.
2. Open the Round 1 submission window; participants upload `agent.py`.
3. Lock submissions, start evaluation, wait for all jobs to finish, process results, and complete the round.
4. Open each following round. Participants may upload a new version or leave submissions unchanged to continue with their previous valid agent.
5. Lock, evaluate, process, and complete each round in order. Publish final results after Round 3 completes.
6. Retry `SYSTEM_ERROR` jobs during the active evaluation phase when appropriate. Participant errors and timeouts are recorded separately.

The event has exactly three rounds and does not eliminate participants.

## 7. Database backup

Stop the backend before copying the database and submission files so the backup is consistent. Preserve both `data/event.sqlite` and the complete `data/submissions/` directory together. Keep the backup encrypted and access-controlled.

## 8. Database reset before the event

Only reset before registration begins and after preserving any required backup. Stop the backend, move `data/event.sqlite` and `data/submissions/` to a dated backup location, then start the backend to create a clean registration database. Never delete these files while an evaluation is running.

## 9. Recovery procedure

Stop the backend before restoring. Restore the SQLite database and matching submission files from the same backup, then restart the backend. On startup, queued work can resume; jobs recorded as running are marked for retry by the evaluation queue. Check event state and job statuses before taking further admin actions.

## 10. Docker production mode

Install and start Docker Engine outside this project, then build the evaluator image from the repository root:

```powershell
docker build -t nitw-farm-ai-evaluator -f NITW_Farm_AI_Challenge_v1/Dockerfile NITW_Farm_AI_Challenge_v1
```

Set `KAGGRI_USE_DOCKER=1` before starting the backend. The evaluator uses no network, one CPU, 512 MB memory, a process limit, a read-only root filesystem, a restricted temporary filesystem, and a read-only submission mount. Verify Docker availability and a real isolated evaluation before the event. Local child-process evaluation (`KAGGRI_USE_DOCKER=0`) is for trusted development agents only; AST validation is not a security sandbox.

## 11. Known limitations

- Docker execution must be verified on the deployment host; it is not assumed available.
- Without Docker, participant code runs in a child process on the backend host and can access host resources available to that account.
- The database and submission directory must be backed up and restored as a matched pair.
- Evaluations use the configured local Python/Kaggle Environments installation or Docker image; keep versions consistent for reproducible results.

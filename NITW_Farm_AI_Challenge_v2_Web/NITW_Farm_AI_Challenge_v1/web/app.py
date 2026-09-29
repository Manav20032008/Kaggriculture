from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from config import (
    LEADERBOARD_FILE,
    MAX_SUBMISSION_BYTES,
    SUBMISSIONS_DIR,
)
from competition.evaluator import evaluate_and_record
from competition.leaderboard import Leaderboard
from competition.validator import validate_agent_file, ValidationError


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="NITW Farm AI Challenge",
    version="2.0.0",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
leaderboard = Leaderboard(LEADERBOARD_FILE)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    rows = leaderboard.load()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "leaderboard": rows[:10],
        },
    )


@app.get("/leaderboard", response_class=HTMLResponse)
def show_leaderboard(request: Request):
    rows = leaderboard.load()
    return templates.TemplateResponse(
        request=request,
        name="leaderboard.html",
        context={
            "leaderboard": rows,
        },
    )


@app.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="submit.html",
        context={
            "error": None,
        },
    )


@app.post("/submit", response_class=HTMLResponse)
async def submit(
    request: Request,
    team: str = Form(...),
    file: UploadFile = File(...),
):
    team = team.strip()

    if not team:
        return templates.TemplateResponse(
            request=request,
            name="submit.html",
            context={"error": "Team name is required."},
            status_code=400,
        )

    safe_team = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in team
    )[:40]

    if not safe_team:
        return templates.TemplateResponse(
            request=request,
            name="submit.html",
            context={"error": "Invalid team name."},
            status_code=400,
        )

    if file.filename != "main.py":
        return templates.TemplateResponse(
            request=request,
            name="submit.html",
            context={
                "error": "Upload a file named exactly main.py.",
            },
            status_code=400,
        )

    data = await file.read()

    if len(data) > MAX_SUBMISSION_BYTES:
        return templates.TemplateResponse(
            request=request,
            name="submit.html",
            context={
                "error": "Submission is larger than 100 KB.",
            },
            status_code=400,
        )

    team_dir = SUBMISSIONS_DIR / safe_team
    team_dir.mkdir(parents=True, exist_ok=True)

    submission_path = team_dir / "main.py"
    submission_path.write_bytes(data)

    try:
        validate_agent_file(submission_path)
    except ValidationError as exc:
        submission_path.unlink(missing_ok=True)
        return templates.TemplateResponse(
            request=request,
            name="submit.html",
            context={
                "error": str(exc),
            },
            status_code=400,
        )

    # Docker evaluation is blocking work. Run it in a worker thread so
    # FastAPI can continue serving the leaderboard and other requests.
    result, rows = await asyncio.to_thread(
        evaluate_and_record,
        submission_path,
        safe_team,
    )

    return templates.TemplateResponse(
        request=request,
        name="result.html",
        context={
            "result": result,
            "leaderboard": rows,
        },
        status_code=200 if result.status == "success" else 500,
    )


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "nitw-farm-ai-challenge",
        "evaluator": "docker",
    }

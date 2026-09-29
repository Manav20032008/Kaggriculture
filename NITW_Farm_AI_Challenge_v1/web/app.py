from pathlib import Path
import shutil
import uuid

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from config import (
    LEADERBOARD_FILE,
    MAX_SUBMISSION_BYTES,
    SUBMISSIONS_DIR,
)
from competition.leaderboard import Leaderboard
from competition.validator import validate_agent_file, ValidationError


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(
    title="NITW Farm AI Challenge",
    version="1.0.0",
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
leaderboard = Leaderboard(LEADERBOARD_FILE)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    rows = leaderboard.load()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "leaderboard": rows[:10],
        },
    )


@app.get("/leaderboard", response_class=HTMLResponse)
def show_leaderboard(request: Request):
    rows = leaderboard.load()
    return templates.TemplateResponse(
        "leaderboard.html",
        {
            "request": request,
            "leaderboard": rows,
        },
    )


@app.get("/submit", response_class=HTMLResponse)
def submit_page(request: Request):
    return templates.TemplateResponse(
        "submit.html",
        {"request": request, "error": None},
    )


@app.post("/submit")
async def submit(
    request: Request,
    team: str = Form(...),
    file: UploadFile = File(...),
):
    team = team.strip()

    if not team:
        raise HTTPException(status_code=400, detail="Team name is required.")

    safe_team = "".join(
        c if c.isalnum() or c in "-_" else "_"
        for c in team
    )[:40]

    if not safe_team:
        raise HTTPException(status_code=400, detail="Invalid team name.")

    if file.filename != "main.py":
        raise HTTPException(
            status_code=400,
            detail="Upload a file named main.py.",
        )

    data = await file.read()

    if len(data) > MAX_SUBMISSION_BYTES:
        raise HTTPException(
            status_code=400,
            detail="Submission is larger than 100 KB.",
        )

    team_dir = SUBMISSIONS_DIR / safe_team
    team_dir.mkdir(parents=True, exist_ok=True)

    path = team_dir / "main.py"
    path.write_bytes(data)

    try:
        validate_agent_file(path)
    except ValidationError as exc:
        path.unlink(missing_ok=True)
        return templates.TemplateResponse(
            "submit.html",
            {
                "request": request,
                "error": str(exc),
            },
            status_code=400,
        )

    return RedirectResponse(
        url="/",
        status_code=303,
    )

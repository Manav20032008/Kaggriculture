import sys
from pathlib import Path
import shutil
import re
import threading
import math
import json
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware

# Fix Windows console charmap / emoji encoding issues
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ============================================================
# PROJECT PATHS
# ============================================================

BACKEND_DIR = Path(__file__).resolve().parent
ROOT = BACKEND_DIR.parent

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from py_env import get_kaggle_python
from agent_validation import validate_agent_source
from event_api import router as event_router, get_store

PLAYERS_DIR = ROOT / "players"
PLAYERS_DIR.mkdir(exist_ok=True)

EXAMPLES_DIR = ROOT / "NITW_Farm_AI_Challenge_v1" / "examples"
STARTER_DIR = ROOT / "NITW_Farm_AI_Participant_Starter"


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Kaggriculture AI Tournament API"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(event_router)


# ============================================================
# TOURNAMENT STATE MODEL
# ============================================================

def create_initial_state():
    current_players = []
    if PLAYERS_DIR.exists():
        for p in PLAYERS_DIR.iterdir():
            if p.is_dir() and (p / "agent.py").exists():
                current_players.append(p.name)
        current_players.sort(key=lambda s: s.lower())

    return {
        "status": "registration",  # "registration" | "starting" | "round_running" | "next_round" | "final" | "champion" | "error"
        "message": "Registration is open. Waiting for players to join.",
        "playersCount": len(current_players),
        "maxPlayers": 60,
        "registeredPlayers": current_players,
        "currentRound": 0,
        "totalRoundsEstimate": math.ceil(math.log2(len(current_players))) if len(current_players) > 1 else 0,
        "currentMatches": [],
        "roundsHistory": [],
        "byes": [],
        "eliminatedPlayers": [],
        "allMatches": [],
        "champion": None,
        "finalScore": None,
        "error": None,
        "isLive": False,
    }

tournament_state = create_initial_state()
state_lock = threading.Lock()
tournament_exec_lock = threading.Lock()


# ============================================================
# LIVE PROGRESS HANDLER
# ============================================================

def handle_tournament_progress(event: str, data: dict):
    """
    Callback triggered by tournament.py during execution.
    Updates tournament_state in real-time.
    """
    with state_lock:
        if event == "ROUND_START":
            round_num = data["round"]
            is_final = data.get("isFinal", False)
            tournament_state["status"] = "final" if is_final else "round_running"
            tournament_state["currentRound"] = round_num
            tournament_state["currentMatches"] = data["matches"]
            tournament_state["message"] = f"Round {round_num} {'(FINAL)' if is_final else 'in progress'} ({len(data['matches'])} matches)"

            if data.get("byePlayer"):
                bye_entry = {"round": round_num, "player": data["byePlayer"]}
                if bye_entry not in tournament_state["byes"]:
                    tournament_state["byes"].append(bye_entry)

        elif event == "MATCH_START":
            m_idx = data["matchIndex"]
            if m_idx < len(tournament_state["currentMatches"]):
                tournament_state["currentMatches"][m_idx]["status"] = "running"
            tournament_state["message"] = f"Round {data['round']}: {data['player1']} vs {data['player2']} playing..."

        elif event == "MATCH_END":
            m_idx = data["matchIndex"]
            if m_idx < len(tournament_state["currentMatches"]):
                tournament_state["currentMatches"][m_idx].update({
                    "status": "completed",
                    "p1Score": data["p1Score"],
                    "p2Score": data["p2Score"],
                    "winner": data["winner"],
                    "loser": data["loser"],
                    "tieReplays": data.get("tieReplays", 0),
                    "seed": data.get("seed"),
                })

            # Record eliminated player
            elim_entry = {
                "player": data["loser"],
                "eliminatedInRound": data["round"],
                "eliminatedBy": data["winner"],
            }
            if not any(e["player"] == data["loser"] for e in tournament_state["eliminatedPlayers"]):
                tournament_state["eliminatedPlayers"].append(elim_entry)

            # Record to allMatches
            tournament_state["allMatches"].append(data)
            tournament_state["message"] = f"Round {data['round']}: {data['winner']} defeated {data['loser']} ({data['p1Score']} - {data['p2Score']})"

        elif event == "ROUND_END":
            round_num = data["round"]
            round_matches = [dict(m) for m in tournament_state["currentMatches"]]
            round_bye = next((b["player"] for b in tournament_state["byes"] if b["round"] == round_num), None)
            
            # Archive round into roundsHistory if not already archived
            if not any(r["round"] == round_num for r in tournament_state["roundsHistory"]):
                tournament_state["roundsHistory"].append({
                    "round": round_num,
                    "matches": round_matches,
                    "byePlayer": round_bye,
                    "advancing": data["advancing"],
                })

            if data.get("remainingCount", 0) > 1:
                tournament_state["status"] = "next_round"
                tournament_state["message"] = f"Round {round_num} completed. Transitioning to Round {round_num + 1}..."

        elif event == "TOURNAMENT_END":
            champion_obj = data["champion"]
            tournament_state["status"] = "champion"
            tournament_state["champion"] = champion_obj
            tournament_state["isLive"] = False

            if data.get("finalMatch"):
                fm = data["finalMatch"]
                tournament_state["finalScore"] = {
                    "player1": fm["player1"],
                    "player2": fm["player2"],
                    "p1Score": fm["p1Score"],
                    "p2Score": fm["p2Score"],
                    "winner": fm["winner"],
                }
            tournament_state["message"] = f"Tournament Complete! Champion: {champion_obj['username']}"

        elif event == "TOURNAMENT_ERROR":
            tournament_state["status"] = "error"
            tournament_state["error"] = data["error"]
            tournament_state["isLive"] = False
            tournament_state["message"] = f"Tournament aborted: {data['error']}"


# ============================================================
# API ENDPOINTS
# ============================================================

@app.get("/")
def home():
    python_path = get_kaggle_python()
    return {
        "message": "Kaggriculture three-round event backend running",
        "pythonInterpreter": python_path,
        "status": get_store().get_state()["status"],
    }


@app.get("/players")
def get_players():
    players = []
    if PLAYERS_DIR.exists():
        for player_dir in PLAYERS_DIR.iterdir():
            if not player_dir.is_dir():
                continue
            agent_path = player_dir / "agent.py"
            if not agent_path.exists():
                continue
            players.append({"username": player_dir.name})

    players.sort(key=lambda player: player["username"].lower())

    with state_lock:
        tournament_state["playersCount"] = len(players)
        tournament_state["registeredPlayers"] = [p["username"] for p in players]

    return {
        "count": len(players),
        "maxPlayers": 60,
        "players": players,
    }


@app.post("/register")
async def register_player(
    username: str = Form(...),
    agent: UploadFile = File(...),
):
    raise HTTPException(status_code=410, detail="Legacy knockout registration is retired. Use /event/register and /event/submissions.")
    with state_lock:
        if tournament_state["status"] not in ("registration", "finished", "champion", "error"):
            raise HTTPException(
                status_code=403,
                detail="Registration is currently closed because a tournament is starting or active."
            )

    username = username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="Username cannot be empty.")

    if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
        raise HTTPException(
            status_code=400,
            detail="Username can contain only letters, numbers, '_' and '-'."
        )

    if not agent.filename:
        raise HTTPException(status_code=400, detail="No agent file uploaded.")

    if not agent.filename.lower().endswith(".py"):
        raise HTTPException(status_code=400, detail="Agent must be a .py file.")

    current_players = sum(
        1 for p in PLAYERS_DIR.iterdir()
        if p.is_dir() and (p / "agent.py").exists()
    )
    if current_players >= 60:
        raise HTTPException(status_code=409, detail="Maximum 60 players have already registered.")

    player_dir = PLAYERS_DIR / username
    if player_dir.exists() and (player_dir / "agent.py").exists():
        raise HTTPException(status_code=409, detail="Username is already registered.")

    # Read and validate agent code
    try:
        content = await agent.read()
        source_text = content.decode("utf-8")
        validate_agent_source(source_text)
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Agent file must be valid UTF-8 encoded text.")
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Validation failed: {e}")

    # Save agent file
    player_dir.mkdir(parents=True, exist_ok=True)
    agent_path = player_dir / "agent.py"

    try:
        agent_path.write_text(source_text, encoding="utf-8")
    except Exception as e:
        shutil.rmtree(player_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Could not save agent: {e}")

    # Refresh players count
    get_players()

    return {
        "success": True,
        "message": f"Player '{username}' registered successfully.",
        "player": {
            "username": username,
            "filePath": str(agent_path),
        },
    }


@app.post("/players/clear")
def clear_players():
    """Clear all registered players (allowed only when no tournament is running)."""
    raise HTTPException(status_code=410, detail="Legacy player reset is disabled for the official event.")
    with state_lock:
        if tournament_state["status"] in ("starting", "round_running", "next_round", "final"):
            raise HTTPException(status_code=403, detail="Cannot clear players while tournament is active.")

    for item in PLAYERS_DIR.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)

    with state_lock:
        tournament_state.update(create_initial_state())

    return {"success": True, "message": "All registered players have been cleared."}


@app.post("/demo/populate-sample-players")
def populate_sample_players(count: int = Query(default=4, ge=2, le=60)):
    """
    Demo utility to populate sample agents with varied strategies for testing.
    """
    raise HTTPException(status_code=410, detail="Public demo population is disabled for the official event.")
    with state_lock:
        if tournament_state["status"] in ("starting", "round_running", "next_round", "final"):
            raise HTTPException(status_code=403, detail="Cannot populate players while tournament is running.")

    # Available strategy templates
    templates = []
    if (EXAMPLES_DIR / "starter_agent.py").exists():
        templates.append((EXAMPLES_DIR / "starter_agent.py").read_text(encoding="utf-8"))
    if (EXAMPLES_DIR / "example_agent.py").exists():
        templates.append((EXAMPLES_DIR / "example_agent.py").read_text(encoding="utf-8"))
    if (STARTER_DIR / "main.py").exists():
        templates.append((STARTER_DIR / "main.py").read_text(encoding="utf-8"))
    if (EXAMPLES_DIR / "random_agent.py").exists():
        templates.append((EXAMPLES_DIR / "random_agent.py").read_text(encoding="utf-8"))

    if not templates:
        raise HTTPException(status_code=500, detail="No agent template files found.")

    sample_names = [
        "AlphaFarmer", "BetaBot", "CropMaster", "DeltaHarvester",
        "EchoPlanter", "FoxtrotAgri", "GrainGuru", "HarvestHero",
        "IrisTiller", "JasmineSeed", "KernelKing", "LeafLord",
        "MeadowManiac", "NitroGrower", "OasisOwner"
    ]

    created = 0
    for idx in range(count):
        name = sample_names[idx] if idx < len(sample_names) else f"Player_{idx+1}"
        pdir = PLAYERS_DIR / name
        pdir.mkdir(parents=True, exist_ok=True)
        template_code = templates[idx % len(templates)]
        (pdir / "agent.py").write_text(template_code, encoding="utf-8")
        created += 1

    get_players()
    return {"success": True, "message": f"Populated {created} sample players.", "count": created}


# ============================================================
# TOURNAMENT WORKER
# ============================================================

def run_tournament_background():
    try:
        from tournament import run_tournament, load_registered_players

        participants = load_registered_players()

        if len(participants) < 2:
            with state_lock:
                tournament_state["status"] = "registration"
                tournament_state["isLive"] = False
                tournament_state["message"] = "At least 2 players are required to run tournament."
                tournament_state["error"] = "Not enough players registered."
            return

        with state_lock:
            tournament_state["playersCount"] = len(participants)
            tournament_state["totalRoundsEstimate"] = math.ceil(math.log2(len(participants)))

        result = run_tournament(
            participants,
            seed=20260929,
            random_seed=42,
            on_progress=handle_tournament_progress,
        )

        with state_lock:
            if result.get("champion"):
                tournament_state["champion"] = result["champion"]
                tournament_state["status"] = "champion"
                tournament_state["isLive"] = False
                tournament_state["message"] = f"Tournament completed! Champion: {result['champion']['username']}"
            elif result.get("error"):
                tournament_state["status"] = "error"
                tournament_state["isLive"] = False
                tournament_state["error"] = result["error"]
                tournament_state["message"] = f"Tournament failed: {result['error']}"

    except Exception as e:
        with state_lock:
            tournament_state["status"] = "error"
            tournament_state["isLive"] = False
            tournament_state["message"] = f"Tournament execution error: {e}"
            tournament_state["error"] = str(e)


# ============================================================
# START TOURNAMENT
# ============================================================

@app.post("/start-tournament")
def start_tournament(background_tasks: BackgroundTasks):
    raise HTTPException(status_code=410, detail="The knockout tournament is retired. Use the protected /event/admin workflow.")
    acquired = tournament_exec_lock.acquire(blocking=False)
    if not acquired:
        raise HTTPException(
            status_code=409,
            detail="Tournament is already starting or running."
        )

    with state_lock:
        if tournament_state["status"] in ("starting", "round_running", "next_round", "final"):
            tournament_exec_lock.release()
            raise HTTPException(status_code=409, detail="Tournament is already active.")

        # Validate player count
        participants = [p.name for p in PLAYERS_DIR.iterdir() if p.is_dir() and (p / "agent.py").exists()]
        if len(participants) < 2:
            tournament_exec_lock.release()
            raise HTTPException(
                status_code=400,
                detail=f"At least 2 players required. Currently only {len(participants)} registered."
            )

        # Reset tournament progress state while keeping players
        tournament_state["status"] = "starting"
        tournament_state["isLive"] = True
        tournament_state["message"] = "Initializing tournament bracket..."
        tournament_state["playersCount"] = len(participants)
        tournament_state["registeredPlayers"] = participants
        tournament_state["totalRoundsEstimate"] = math.ceil(math.log2(len(participants)))
        tournament_state["currentRound"] = 0
        tournament_state["currentMatches"] = []
        tournament_state["roundsHistory"] = []
        tournament_state["byes"] = []
        tournament_state["eliminatedPlayers"] = []
        tournament_state["allMatches"] = []
        tournament_state["champion"] = None
        tournament_state["finalScore"] = None
        tournament_state["error"] = None

    def worker():
        try:
            run_tournament_background()
        finally:
            tournament_exec_lock.release()

    background_tasks.add_task(worker)

    return {
        "success": True,
        "message": f"Tournament started with {len(participants)} players.",
        "players": len(participants),
        "status": "starting",
    }


# ============================================================
# TOURNAMENT STATUS & RESET
# ============================================================

@app.get("/tournament/status")
def get_tournament_status():
    with state_lock:
        return dict(tournament_state)


@app.post("/tournament/reset")
def reset_tournament():
    raise HTTPException(status_code=410, detail="Public tournament reset is disabled for the official event.")
    with state_lock:
        if tournament_state["status"] in ("starting", "round_running", "next_round", "final"):
            raise HTTPException(status_code=403, detail="Cannot reset while tournament is actively running.")

        initial = create_initial_state()
        tournament_state.clear()
        tournament_state.update(initial)

    return {"success": True, "message": "Tournament reset to registration state."}

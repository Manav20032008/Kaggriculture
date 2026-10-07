from pathlib import Path
import hmac
import os

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile

from event_store import EventError, EventStore
from runtime_config import DATABASE_PATH, SUBMISSIONS_DIR

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = EventStore(
    db_path=DATABASE_PATH,
    files_dir=SUBMISSIONS_DIR,
    compatibility_players_dir=ROOT / "players",
)

router = APIRouter()
store = DEFAULT_STORE


def _configured_admin_token() -> str:
    """Read the one supported admin-token setting, normalizing env-file whitespace."""
    return os.environ.get("KAGGRI_ADMIN_TOKEN", "").strip()


def _require_admin(x_admin_token: str | None = Header(default=None)):
    expected = _configured_admin_token()
    if not expected:
        raise HTTPException(status_code=503, detail="Admin controls are disabled until KAGGRI_ADMIN_TOKEN is configured.")
    supplied = x_admin_token.strip() if x_admin_token else ""
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Invalid admin token.")


def get_store() -> EventStore:
    return store


def _public_record(record: dict | None) -> dict | None:
    """Remove participant IDs and storage paths from public API data."""
    if record is None:
        return None
    return {key: value for key, value in record.items() if key not in {"participant_id", "file_path"}}


def _raise(exc: EventError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/event/state")
def get_event_state():
    state = get_store().get_state()
    if state["status"].endswith("_EVALUATING"):
        from event_models import parse_round_from_state
        from evaluation_queue import get_queue
        try:
            get_queue(get_store()).start(parse_round_from_state(state["status"]))
        except RuntimeError:
            # Keep the state endpoint available for diagnosis; no unsafe fallback occurs.
            pass
    return state


@router.post("/event/register")
def register_participant(username: str = Form(...)):
    try:
        return get_store().register_participant(username)
    except EventError as exc:
        _raise(exc)


@router.get("/event/participants")
def list_participants():
    participants = get_store().list_participants()
    return {"count": len(participants), "participants": [_public_record(row) for row in participants]}


@router.get("/event/participants/{participant_id}")
def get_participant(participant_id: str):
    try:
        return _public_record(get_store().get_participant(participant_id))
    except EventError as exc:
        _raise(exc)


@router.post("/event/submissions")
async def upload_submission(
    participant_id: str = Form(...),
    agent: UploadFile = File(...),
):
    if not agent.filename or not agent.filename.lower().endswith(".py"):
        raise HTTPException(status_code=400, detail="Agent must be a .py file.")
    try:
        content = await agent.read(100_001)
        if len(content) > 100_000:
            raise HTTPException(status_code=400, detail="Agent file exceeds 100 KB limit.")
        source_text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Agent file must be valid UTF-8 encoded text.")
    try:
        return _public_record(get_store().upload_submission(participant_id, source_text))
    except EventError as exc:
        _raise(exc)


@router.get("/event/participants/{participant_id}/submissions")
def get_submission_history(participant_id: str):
    try:
        items = get_store().list_submissions(participant_id)
        return {"count": len(items), "submissions": [_public_record(item) for item in items]}
    except EventError as exc:
        _raise(exc)


@router.get("/event/participants/{participant_id}/active-submission")
def get_active_submission(participant_id: str, round: int = Query(..., ge=1, le=3)):
    try:
        active = get_store().get_active_submission(participant_id, round)
        return {
            "round_number": round,
            "active_submission": _public_record(active),
        }
    except EventError as exc:
        _raise(exc)


@router.get("/event/scores")
def get_round_scores(round: int | None = Query(default=None)):
    try:
        return {"scores": [_public_record(row) for row in get_store().get_round_scores(round)]}
    except EventError as exc:
        _raise(exc)


@router.get("/event/standings")
def get_standings():
    standings = get_store().get_standings()
    return {"count": len(standings), "standings": [_public_record(row) for row in standings]}


@router.get("/event/evaluation-jobs")
def evaluation_jobs(
    round: int | None = Query(default=None, ge=1, le=3),
    event_number: int | None = Query(default=None, ge=1),
):
    jobs = get_store().get_evaluation_jobs(round, event_number)
    counts = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    return {"count": len(jobs), "counts": counts, "jobs": [_public_record(job) for job in jobs]}


@router.post("/event/admin/open-submissions")
def admin_open_submissions(round: int | None = Query(default=None), _=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        return get_store().open_submission_window(round)
    except EventError as exc:
        _raise(exc)


@router.post("/event/admin/lock-submissions")
def admin_lock_submissions(_=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        return get_store().lock_submission_window()
    except EventError as exc:
        _raise(exc)


@router.post("/event/admin/start-evaluation")
def admin_start_evaluation(round: int | None = Query(default=None), _=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        from evaluation_queue import get_queue
        queue = get_queue(get_store())  # fail closed before changing event state
        state = get_store().start_evaluation_phase(round)
        queue.start(state["current_round"])
        return state
    except EventError as exc:
        _raise(exc)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.post("/event/admin/complete-round")
def admin_complete_round(round: int | None = Query(default=None), _=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        return get_store().complete_evaluation_phase(round)
    except EventError as exc:
        _raise(exc)


@router.post("/event/admin/process-results")
def admin_process_results(round: int | None = Query(default=None), _=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        return get_store().begin_result_processing(round)
    except EventError as exc:
        _raise(exc)


@router.post("/event/admin/retry-system-errors")
def admin_retry_system_errors(round: int = Query(..., ge=1, le=3), _=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    from evaluation_queue import MAX_SYSTEM_RETRIES
    count = get_store().retry_system_errors(round, MAX_SYSTEM_RETRIES)
    if count:
        from evaluation_queue import get_queue
        get_queue(get_store()).start(round)
    return {"round_number": round, "retried": count}


@router.post("/event/admin/publish-final")
def admin_publish_final(_=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        return get_store().publish_final_results()
    except EventError as exc:
        _raise(exc)


@router.get("/event/admin/overview")
def admin_event_overview(_=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    return get_store().get_admin_overview()


@router.post("/event/admin/reset")
def admin_reset_event(_=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    try:
        return get_store().reset_event()
    except EventError as exc:
        _raise(exc)


@router.post("/event/admin/test-participants")
def admin_add_test_participants(count: int = Query(..., ge=1, le=80), _=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    store = get_store()
    if store.get_state()["status"] != "REGISTRATION":
        raise HTTPException(status_code=409, detail="Test participants can be added only during registration.")
    existing = {p["username"] for p in store.list_participants()}
    added = []
    index = 1
    while len(added) < count:
        username = f"TEST_PLAYER_{index:03d}"
        index += 1
        if username in existing:
            continue
        try:
            added.append(store.register_participant(username))
        except EventError as exc:
            _raise(exc)
    return {"count": len(added), "participants": added}


@router.post("/event/admin/seed-test-agents")
def admin_seed_test_agents(_=Header(default=None, alias="X-Admin-Token")):
    _require_admin(_)
    store = get_store()
    if store.get_state()["status"] != "ROUND_1_SUBMISSION_OPEN":
        raise HTTPException(status_code=409, detail="Starter agents can be seeded only while Round 1 submissions are open.")
    starter = ROOT / "NITW_Farm_AI_Challenge_v1" / "examples" / "starter_agent.py"
    try:
        source = starter.read_text(encoding="utf-8")
    except OSError as exc:
        raise HTTPException(status_code=500, detail="The bundled starter agent is unavailable.") from exc
    added = []
    for participant in store.list_participants():
        if not participant["username"].startswith("TEST_PLAYER_"):
            continue
        if store.list_submissions(participant["participant_id"]):
            continue
        try:
            added.append({"username": participant["username"], **store.upload_submission(participant["participant_id"], source)})
        except EventError as exc:
            _raise(exc)
    return {"count": len(added), "submissions": added}

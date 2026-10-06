from pathlib import Path
import hmac
import os

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, UploadFile

from event_store import EventError, EventStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORE = EventStore(
    db_path=ROOT / "data" / "event.sqlite",
    files_dir=ROOT / "data" / "submissions",
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


def _raise(exc: EventError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


@router.get("/event/state")
def get_event_state():
    state = get_store().get_state()
    if state["status"].endswith("_EVALUATING"):
        from event_models import parse_round_from_state
        from evaluation_queue import get_queue
        get_queue(get_store()).start(parse_round_from_state(state["status"]))
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
    return {"count": len(participants), "participants": participants}


@router.get("/event/participants/{participant_id}")
def get_participant(participant_id: str):
    try:
        return get_store().get_participant(participant_id)
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
        return get_store().upload_submission(participant_id, source_text)
    except EventError as exc:
        _raise(exc)


@router.get("/event/participants/{participant_id}/submissions")
def get_submission_history(participant_id: str):
    try:
        items = get_store().list_submissions(participant_id)
        return {"participant_id": participant_id, "count": len(items), "submissions": items}
    except EventError as exc:
        _raise(exc)


@router.get("/event/participants/{participant_id}/active-submission")
def get_active_submission(participant_id: str, round: int = Query(..., ge=1, le=3)):
    try:
        active = get_store().get_active_submission(participant_id, round)
        return {
            "participant_id": participant_id,
            "round_number": round,
            "active_submission": active,
        }
    except EventError as exc:
        _raise(exc)


@router.get("/event/scores")
def get_round_scores(round: int | None = Query(default=None)):
    try:
        return {"scores": get_store().get_round_scores(round)}
    except EventError as exc:
        _raise(exc)


@router.get("/event/standings")
def get_standings():
    standings = get_store().get_standings()
    return {"count": len(standings), "standings": standings}


@router.get("/event/evaluation-jobs")
def evaluation_jobs(round: int | None = Query(default=None, ge=1, le=3)):
    jobs = get_store().get_evaluation_jobs(round)
    counts = {}
    for job in jobs:
        counts[job["status"]] = counts.get(job["status"], 0) + 1
    return {"count": len(jobs), "counts": counts, "jobs": jobs}


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
        state = get_store().start_evaluation_phase(round)
        from evaluation_queue import get_queue
        get_queue(get_store()).start(state["current_round"])
        return state
    except EventError as exc:
        _raise(exc)


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
    count = get_store().retry_system_errors(round)
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

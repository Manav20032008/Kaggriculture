import { useCallback, useEffect, useRef, useState } from "react";
import "./App.css";

const API = (import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "/api" : "")).replace(/\/$/, "");
const requestOptions = () => ({ signal: AbortSignal.timeout(10000) });
const initialPid = localStorage.getItem("kaggri-participant-id") || "";
const initialParticipantKey = new URLSearchParams(window.location.search).get("token") || "";
const routes = ["/", "/how-it-works", "/leaderboard", "/participate", "/dashboard", "/admin"];
const routeNames = { "/": "Overview", "/how-it-works": "How it works", "/leaderboard": "Leaderboard", "/participate": "Participate", "/dashboard": "Dashboard", "/admin": "Operations" };
const routeFromPath = () => routes.includes(window.location.pathname) ? window.location.pathname : "/";
const fmt = (value) => Number(value || 0).toLocaleString();

function Mark() {
  return <span className="sdc-mark" aria-hidden="true"><span>S</span><i /></span>;
}

function FieldArtwork() {
  return <svg className="field-art" viewBox="0 0 760 500" aria-hidden="true">
    <defs><linearGradient id="sky" x2="0" y2="1"><stop stopColor="#071b32"/><stop offset="1" stopColor="#102b33"/></linearGradient><linearGradient id="hill" x2="0" y2="1"><stop stopColor="#267047"/><stop offset="1" stopColor="#102d2d"/></linearGradient><pattern id="grid" width="28" height="28" patternUnits="userSpaceOnUse"><path d="M28 0H0V28" fill="none" stroke="#b7da9b" strokeOpacity=".12" strokeWidth="1"/></pattern></defs>
    <rect width="760" height="500" fill="url(#sky)"/><g fill="#8fdcff" opacity=".65"><circle cx="89" cy="70" r="1.4"/><circle cx="236" cy="52" r="1"/><circle cx="404" cy="92" r="1.5"/><circle cx="622" cy="48" r="1"/><circle cx="680" cy="129" r="1.2"/></g>
    <path d="M0 275 130 186l106 76 136-133 126 134 112-87 150 102v222H0Z" fill="#102b3e"/><path d="M0 330 166 244l116 82 124-94 123 92 102-65 129 77v164H0Z" fill="url(#hill)"/>
    <path d="M0 350 185 302l142 39 138-56 149 45 146-32v202H0Z" fill="#183b2d"/><path d="M0 350 185 302l142 39 138-56 149 45 146-32v202H0Z" fill="url(#grid)"/>
    <g opacity=".96"><path d="M35 381h216v105H35z" fill="#87502e"/><path d="M35 381h216v16H35z" fill="#b2783d"/><path d="M47 403h192v83H47z" fill="#563a2c"/><path d="M61 418h49v68H61z" fill="#172d31"/><path d="M71 427h29v37H71z" fill="#e6ae55"/><path d="M130 405h98v81h-98z" fill="#75472e"/><path d="M124 395h108v17H124z" fill="#d09148"/><path d="M146 428h22v25h-22zM190 428h22v25h-22z" fill="#f1b85d"/></g>
    <g fill="#80c85b"><path d="m298 410 15-39 15 39zm54 10 13-44 15 44zm290-10 18-49 18 49zm-60 6 15-41 15 41z"/></g><g fill="#367b49"><path d="M309 405v37m55-28v38m286-48v47m-62-34v39" stroke="#367b49" strokeWidth="8"/></g>
    <g fill="none" stroke="#8fe4d2" strokeOpacity=".56"><path d="M270 357h185v75H270z"/><path d="M281 368h163v53H281z"/><path d="M270 357v-18m185 18v-18M270 432v18m185-18v18"/></g><g fill="#8fe4d2"><circle cx="300" cy="386" r="4"/><circle cx="319" cy="386" r="4"/><circle cx="338" cy="386" r="4"/></g><path d="M357 387h77" stroke="#8fe4d2" strokeWidth="3" opacity=".65"/>
    <g transform="translate(502 198)"><path d="M0 0h180v94H0z" fill="#07141c" fillOpacity=".86" stroke="#70d9ca" strokeOpacity=".7"/><path d="M14 19h95" stroke="#d9b260" strokeWidth="3"/><path d="M14 38h148M14 55h119M14 72h137" stroke="#83cec4" strokeOpacity=".35" strokeWidth="5"/><circle cx="157" cy="37" r="8" fill="#e2b45a"/><circle cx="140" cy="55" r="8" fill="#9bd372"/><circle cx="157" cy="72" r="8" fill="#65d3c5"/></g>
    <path d="M0 494h760" stroke="#e4b660" strokeOpacity=".8" strokeWidth="3"/>
  </svg>;
}

function StatusBadge({ open, children }) { return <span className={`status-badge ${open ? "is-open" : ""}`}><i />{children}</span>; }

export default function App() {
  const [state, setState] = useState(null);
  const [standings, setStandings] = useState([]);
  const [jobs, setJobs] = useState({ counts: {}, jobs: [] });
  const [pid, setPid] = useState(initialPid);
  const [participant, setParticipant] = useState(null);
  const [history, setHistory] = useState([]);
  const [activeSubmission, setActiveSubmission] = useState(null);
  const [username, setUsername] = useState("");
  const [participantKey, setParticipantKey] = useState(initialParticipantKey);
  const [participantLoginError, setParticipantLoginError] = useState("");
  const [participantLoginBusy, setParticipantLoginBusy] = useState(false);
  const [file, setFile] = useState(null);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [apiError, setApiError] = useState("");
  const [busy, setBusy] = useState(false);
  const [adminOverview, setAdminOverview] = useState(null);
  const [adminAuthStatus, setAdminAuthStatus] = useState({ state: "idle", text: "" });
  const [testParticipantCount, setTestParticipantCount] = useState("20");
  const [route, setRoute] = useState(routeFromPath);
  const [menuOpen, setMenuOpen] = useState(false);
  const [focusLoginRequested, setFocusLoginRequested] = useState(false);
  const participantKeyInputRef = useRef(null);
  const participantLoginSectionRef = useRef(null);
  const autoLoginHandledRef = useRef(false);
  const queryParticipantKey = new URLSearchParams(window.location.search).get("token")?.trim() || "";

  const navigate = useCallback((path) => {
    if (!routes.includes(path)) return;
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
    setRoute(path); setMenuOpen(false); window.scrollTo({ top: 0, behavior: "smooth" });
  }, []);
  useEffect(() => { const onPop = () => setRoute(routeFromPath()); window.addEventListener("popstate", onPop); return () => window.removeEventListener("popstate", onPop); }, []);

  const api = useCallback(async (path, options = {}, admin = false) => {
    const headers = { ...(options.headers || {}) };
    if (admin) headers["X-Admin-Token"] = token;
    const response = await fetch(`${API}${path}`, { ...requestOptions(), ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Request failed");
    return body;
  }, [token]);

  const refresh = useCallback(async () => {
    try {
      const s = await fetch(`${API}/event/state`, requestOptions());
      if (!s.ok) throw new Error(`Event status request failed (${s.status})`);
      const nextState = await s.json(); setState(nextState); setApiError("");
      const selectedRound = nextState.current_round || 1;
      const [l, j] = await Promise.all([fetch(`${API}/event/standings`, requestOptions()), fetch(`${API}/event/evaluation-jobs?round=${selectedRound}`, requestOptions())]);
      if (l.ok) setStandings((await l.json()).standings || []);
      if (j.ok) setJobs(await j.json());
      if (pid) {
        const [p, h, a] = await Promise.all([fetch(`${API}/event/participants/${pid}`, requestOptions()), fetch(`${API}/event/participants/${pid}/submissions`, requestOptions()), fetch(`${API}/event/participants/${pid}/active-submission?round=${selectedRound}`, requestOptions())]);
        if (p.ok) setParticipant(await p.json());
        if (h.ok) setHistory((await h.json()).submissions || []);
        if (a.ok) setActiveSubmission((await a.json()).active_submission || null);
      } else { setParticipant(null); setHistory([]); setActiveSubmission(null); }
    } catch (err) { setApiError(err.message || "Backend is not reachable. Start the FastAPI server and refresh."); }
  }, [pid]);
  useEffect(() => { const first = setTimeout(refresh, 0); const id = setInterval(refresh, 12000); return () => { clearTimeout(first); clearInterval(id); }; }, [refresh]);
  useEffect(() => {
    if (!token.trim()) { setAdminOverview(null); setAdminAuthStatus({ state: "idle", text: "" }); return; }
    let cancelled = false;
    setAdminOverview(null);
    setAdminAuthStatus({ state: "checking", text: "Checking password…" });
    const timer = setTimeout(() => {
      api("/event/admin/overview", {}, true).then((overview) => {
        if (!cancelled) {
          setAdminOverview(overview);
          setAdminAuthStatus({ state: "valid", text: "Correct password" });
        }
      }).catch((err) => {
        if (cancelled) return;
        setAdminOverview(null);
        const invalid = /invalid admin token/i.test(err.message || "");
        setAdminAuthStatus(invalid
          ? { state: "invalid", text: "Invalid password" }
          : { state: "error", text: "Unable to validate token with the backend." });
      });
    }, 250);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [api, state?.updated_at, token]);

  async function register(e) {
    e.preventDefault(); setBusy(true); setMessage("");
    try { const form = new FormData(); form.append("username", username); const p = await api("/event/register", { method: "POST", body: form }); localStorage.setItem("kaggri-participant-id", p.participant_id); setPid(p.participant_id); setParticipant(p); setUsername(""); setMessage(`Registered ${p.username}. Upload your agent during an open submission window.`); navigate("/dashboard"); }
    catch (err) { setMessage(err.message); } finally { setBusy(false); }
  }
  const loginParticipant = useCallback(async (event, suppliedKey = participantKey) => {
    event?.preventDefault();
    const key = suppliedKey.trim();
    if (!key) { setParticipantLoginError("Enter your Participant Key to continue."); return; }
    setParticipantLoginBusy(true); setParticipantLoginError("");
    try {
      const verified = await api(`/event/participants/${encodeURIComponent(key)}`);
      if (!verified?.participant_id || verified.participant_id !== key) throw new Error("Participant not found.");
      localStorage.setItem("kaggri-participant-id", verified.participant_id);
      setPid(verified.participant_id); setParticipant(verified); setHistory([]); setActiveSubmission(null);
      setParticipantKey(key); setMessage(`Welcome back, ${verified.username}.`); navigate("/dashboard");
    } catch (err) {
      const detail = err.message || "Request failed";
      setParticipantLoginError(/participant not found|404|invalid|expired/i.test(detail)
        ? "That Participant Key is invalid or expired. Check the key and try again."
        : `We could not verify your Participant Key. Check your connection and try again. (${detail})`);
    } finally { setParticipantLoginBusy(false); }
  }, [api, navigate, participantKey]);

  useEffect(() => {
    if (route !== "/participate" || !queryParticipantKey || autoLoginHandledRef.current) return;
    autoLoginHandledRef.current = true;
    setParticipantKey(queryParticipantKey);
    void loginParticipant(null, queryParticipantKey);
  }, [loginParticipant, queryParticipantKey, route]);
  useEffect(() => {
    if (route !== "/participate" || !focusLoginRequested) return;
    participantLoginSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    participantKeyInputRef.current?.focus({ preventScroll: true });
    setFocusLoginRequested(false);
  }, [focusLoginRequested, route]);

  function openParticipantLogin() {
    setFocusLoginRequested(true);
    navigate("/participate");
  }
  async function upload(e) {
    e.preventDefault(); if (!file || !pid) return; setBusy(true); setMessage("");
    try { const form = new FormData(); form.append("participant_id", pid); form.append("agent", file); const sub = await api("/event/submissions", { method: "POST", body: form }); setMessage(`Submission received: Round ${sub.round_number}, version ${sub.version}. ID ${sub.submission_id}`); setFile(null); await refresh(); }
    catch (err) { setMessage(err.message); } finally { setBusy(false); }
  }
  async function adminAction(path) { setBusy(true); setMessage(""); try { await api(path, { method: "POST" }, true); setMessage("Event state updated."); await refresh(); } catch (err) { setMessage(err.message); } finally { setBusy(false); } }
  async function resetEvent() {
    const label = status === "FINAL_RESULTS" ? "Start a new test event" : "Reset the current event";
    if (!window.confirm(`${label}? This permanently clears current participants, submissions, scores and evaluation records.`)) return;
    setBusy(true); setMessage("");
    try { const next = await api("/event/admin/reset", { method: "POST" }, true); localStorage.removeItem("kaggri-participant-id"); setPid(""); setParticipant(null); setHistory([]); setActiveSubmission(null); setStandings([]); setJobs({ counts: {}, jobs: [] }); setAdminOverview(null); setMessage(`Event #${next.event_number} is ready for registration.`); await refresh(); }
    catch (err) { setMessage(err.message); } finally { setBusy(false); }
  }
  async function addTestParticipants() { setBusy(true); setMessage(""); try { const result = await api(`/event/admin/test-participants?count=${testParticipantCount}`, { method: "POST" }, true); setMessage(`${result.count} test participants added. Open Round 1, then seed the bundled starter agents.`); setAdminOverview(await api("/event/admin/overview", {}, true)); await refresh(); } catch (err) { setMessage(err.message); } finally { setBusy(false); } }
  async function seedTestAgents() { setBusy(true); setMessage(""); try { const result = await api("/event/admin/seed-test-agents", { method: "POST" }, true); setMessage(`${result.count} test participants received the bundled starter agent through the normal submission pipeline.`); setAdminOverview(await api("/event/admin/overview", {}, true)); await refresh(); } catch (err) { setMessage(err.message); } finally { setBusy(false); } }

  const status = state?.status || "LOADING";
  const round = state?.current_round;
  const isSubmissionOpen = status.endsWith("SUBMISSION_OPEN");
  const phaseLabel = status === "FINAL_RESULTS" ? "RESULTS PUBLISHED" : status.startsWith("ROUND_") ? status.replace(/^ROUND_\d+_/, "").replaceAll("_", " ") : status.replaceAll("_", " ");
  const leaderboardPublished = status === "FINAL_RESULTS" || status.endsWith("_COMPLETE") || (round !== null && round > 1);
  const currentStanding = standings.find((entry) => entry.participant_id === pid);
  const participantTotal = currentStanding?.total_score ?? 0;
  const jobCounts = jobs.counts || {};
  const runningJobs = (jobCounts.QUEUED || 0) + (jobCounts.RUNNING || 0) + (jobCounts.RETRYING || 0);
  const failedJobs = (jobCounts.PLAYER_ERROR || 0) + (jobCounts.TIMEOUT || 0) + (jobCounts.SYSTEM_ERROR || 0);
  const evaluationStatus = failedJobs ? "ERROR" : runningJobs ? "RUNNING" : jobCounts.SUCCESS ? "COMPLETED" : "WAITING";
  const adminActionForState = {
    REGISTRATION: ["OPEN SUBMISSIONS", "/event/admin/open-submissions?round=1"],
    ROUND_1_SUBMISSION_OPEN: ["LOCK SUBMISSIONS", "/event/admin/lock-submissions"], ROUND_1_SUBMISSION_LOCKED: ["START EVALUATION", "/event/admin/start-evaluation?round=1"], ROUND_1_EVALUATING: ["PROCESS RESULTS", "/event/admin/process-results?round=1"], ROUND_1_PROCESSING_RESULTS: ["PUBLISH RESULTS", "/event/admin/complete-round?round=1"], ROUND_1_COMPLETE: ["OPEN NEXT ROUND", "/event/admin/open-submissions?round=2"],
    ROUND_2_SUBMISSION_OPEN: ["LOCK SUBMISSIONS", "/event/admin/lock-submissions"], ROUND_2_SUBMISSION_LOCKED: ["START EVALUATION", "/event/admin/start-evaluation?round=2"], ROUND_2_EVALUATING: ["PROCESS RESULTS", "/event/admin/process-results?round=2"], ROUND_2_PROCESSING_RESULTS: ["PUBLISH RESULTS", "/event/admin/complete-round?round=2"], ROUND_2_COMPLETE: ["OPEN NEXT ROUND", "/event/admin/open-submissions?round=3"],
    ROUND_3_SUBMISSION_OPEN: ["LOCK SUBMISSIONS", "/event/admin/lock-submissions"], ROUND_3_SUBMISSION_LOCKED: ["START EVALUATION", "/event/admin/start-evaluation?round=3"], ROUND_3_EVALUATING: ["PROCESS RESULTS", "/event/admin/process-results?round=3"], ROUND_3_PROCESSING_RESULTS: ["PUBLISH RESULTS", "/event/admin/complete-round?round=3"], ROUND_3_COMPLETE: ["FINALIZE EVENT", "/event/admin/publish-final"],
  }[status];
  const roundProgress = [1, 2, 3].map((number) => { const complete = status === "FINAL_RESULTS" || (round && number < round) || status === `ROUND_${number}_COMPLETE`; const active = !complete && round === number && status.startsWith(`ROUND_${number}_`); return { number, complete, active, state: complete ? "COMPLETED" : active ? phaseLabel : "UPCOMING" }; });
  const nav = <>{["/", "/how-it-works", "/leaderboard", "/participate"].map((path) => <a key={path} href={path} className={route === path ? "active" : ""} onClick={(e) => { e.preventDefault(); navigate(path); }}>{routeNames[path]}</a>)}</>;

  const RoundRail = () => <div className="round-rail">{roundProgress.map(({ number, complete, active, state: label }, index) => <div className={`round-rail-step ${complete ? "complete" : ""} ${active ? "active" : ""}`} key={number}><div className="rail-number">{complete ? "✓" : `0${number}`}</div><div><small>ROUND 0{number}</small><strong>{label}</strong></div>{index < 2 && <i className="rail-line" />}</div>)}</div>;
  const LeaderboardTable = ({ limit }) => {
    const rows = limit ? standings.slice(0, limit) : standings;
    return leaderboardPublished ? <div className="score-grid" role="table" aria-label="Competition standings">
      <div className="score-row score-head" role="row"><span>RANK</span><span>PARTICIPANT</span><span>R1</span><span>R2</span><span>R3</span><span>TOTAL</span></div>
      {rows.map((entry, index) => <div className={`score-row ${index < 3 ? `medal-${index + 1}` : ""} ${entry.participant_id === pid ? "is-you" : ""}`} role="row" key={entry.participant_id}><span className="score-rank">{String(index + 1).padStart(2, "0")}</span><span className="score-name">{entry.username}{entry.participant_id === pid && <em>YOU</em>}</span><span data-label="R1">{fmt(entry.round1_score)}</span><span data-label="R2">{fmt(entry.round2_score)}</span><span data-label="R3">{fmt(entry.round3_score)}</span><b data-label="TOTAL">{fmt(entry.total_score)} <small>PTS</small></b></div>)}
      {!rows.length && <div className="empty-panel">No participants registered yet.</div>}
    </div> : <div className="empty-panel"><span className="empty-glyph">◌</span><strong>Scores publish after each round</strong><p>The leaderboard will update when the first round results are released.</p></div>;
  };
  const SubmissionForm = () => <div className="panel submission-card"><div className="panel-top"><div><span className="eyebrow">ROUND {String(round || 1).padStart(2, "0")} · SUBMISSION WINDOW</span><h2>{isSubmissionOpen ? "Put your agent on the field." : "Submission window is closed."}</h2></div><StatusBadge open={isSubmissionOpen}>{isSubmissionOpen ? "OPEN" : "LOCKED"}</StatusBadge></div>
    {!participant ? <div className="inline-empty">Register for the event before uploading an agent. <button className="text-link" onClick={() => navigate("/participate")}>Go to registration →</button></div> : isSubmissionOpen ? <form className="upload-form" onSubmit={upload}><label className={`drop-zone ${file ? "has-file" : ""}`} htmlFor="agent-file" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); setFile(e.dataTransfer.files?.[0] || null); }}><input id="agent-file" type="file" accept=".py" onChange={(e) => setFile(e.target.files?.[0] || null)} /><span className="upload-arrow">↑</span><strong>{file?.name || "Drop your agent.py here"}</strong><small>{file ? "Ready to submit" : "or select a Python file from your device"}</small><span className="choose-file">Browse files</span></label><div className="upload-context"><div className="active-agent"><small>ACTIVE AGENT</small><strong>{activeSubmission ? `VERSION ${activeSubmission.version}` : "NO VALID AGENT"}</strong><span>{round > 1 ? "A new upload replaces the active version." : "A valid Round 1 agent is needed to score."}</span></div><button className="button-primary" disabled={busy || !file}>{busy ? "UPLOADING…" : round > 1 ? "Upload new version" : "Submit agent"}<span>↗</span></button></div><p className="form-hint">Accepted format: .py · Maximum size 100 KB</p></form> : <div className="locked-state"><span className="lock-symbol">⌑</span><div><strong>SUBMISSIONS LOCKED</strong><p>Your latest valid agent remains active for this round. The event team will publish results after evaluation.</p></div></div>}
    {participant && round > 1 && <div className="carryover-note"><span>↻</span><div><strong>Continue with your previous valid agent</strong><small>No upload is needed. Submit a new version only if you want to update it.</small></div></div>}
  </div>;
  const RegisterCard = () => <div className="panel register-card"><span className="eyebrow">JOIN THE EVENT</span><h2>{participant ? `Welcome, ${participant.username}.` : "Your season starts here."}</h2>{participant ? <><p>Your participant profile is registered and will stay in the event through all three rounds.</p><button className="button-primary" onClick={() => navigate("/dashboard")}>Open your dashboard <span>↗</span></button></> : status === "REGISTRATION" ? <><p>Register once. Build your agent, submit during each round window, and improve your cumulative score.</p><form onSubmit={register}><label htmlFor="team-name">Participant or team name</label><input id="team-name" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={32} required placeholder="Your name or team" /><button className="button-primary" disabled={busy}>{busy ? "REGISTERING…" : "Register for FARMCraft"}<span>↗</span></button><small>Registration is open.</small></form></> : <div className="registration-closed" role="status"><strong>REGISTRATION CLOSED</strong><p>New participants can no longer register for this event. If you already have a Participant Key, use Participant Login.</p></div>}</div>;
  const ParticipantLoginCard = () => <section className="panel register-card participant-login-card" id="participant-login" ref={participantLoginSectionRef}><span className="eyebrow">EXISTING PARTICIPANTS</span><h2>Participant Login</h2><p>Enter the Participant Key issued when you registered. Your key is also saved in this browser after registration.</p><form onSubmit={(event) => loginParticipant(event)}><label htmlFor="participant-key">Participant Key / Token</label><input ref={participantKeyInputRef} id="participant-key" type="text" autoComplete="off" spellCheck="false" value={participantKey} onChange={(event) => { setParticipantKey(event.target.value); setParticipantLoginError(""); }} placeholder="Paste your Participant Key" /><button className="button-primary" disabled={participantLoginBusy || !participantKey.trim()}>{participantLoginBusy ? "VERIFYING KEY…" : "Open participant dashboard"}<span>↗</span></button></form>{participantLoginError && <p className="participant-login-error" role="alert">{participantLoginError}</p>}</section>;
  const HistoryTable = () => history.length ? <div className="history-list">{history.map((sub) => <div className="history-item" key={sub.submission_id}><span className="history-round">R{String(sub.round_number).padStart(2, "0")}</span><strong>Version {sub.version}</strong><span className="status-chip">{sub.status}</span><time>{new Date(sub.created_at).toLocaleString()}</time><code>{sub.submission_id}</code></div>)}</div> : <div className="empty-panel compact-empty">No agent versions on record yet.</div>;

  function AdminPage() {
    return <><PageIntro index="06" label="EVENT OPERATIONS" title="Control the event." desc="Protected organizer controls, aligned to the live event state." /><div className="admin-layout"><section className="panel admin-card"><div className="panel-top"><div><span className="eyebrow">ADMIN AUTHENTICATION</span><h2>Operations access</h2></div><StatusBadge>{status.replaceAll("_", " ")}</StatusBadge></div><label className="field-label" htmlFor="admin-token">Admin token</label><input className="text-input" id="admin-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="Enter configured admin token" />{adminAuthStatus.text && <p className={`admin-auth-feedback ${adminAuthStatus.state}`} role="status" aria-live="polite">{adminAuthStatus.text}</p>}<p className="subtle-copy">The token is sent only in the admin request header.</p>
      {adminOverview && <><div className="admin-stats"><div><small>EVENT</small><strong>#{adminOverview?.event?.event_number ?? state?.event_number ?? "—"}</strong></div><div><small>PARTICIPANTS</small><strong>{adminOverview?.participants ?? "—"}</strong></div><div><small>SUBMISSIONS</small><strong>{adminOverview?.submissions ?? "—"}</strong></div><div><small>EVALUATION JOBS</small><strong>{Object.values(adminOverview?.evaluation_jobs || {}).reduce((sum, value) => sum + value, 0)}</strong></div></div><div className="admin-actions">{adminActionForState ? <button className="button-primary" disabled={busy} onClick={() => adminAction(adminActionForState[1])}>{busy ? "WORKING…" : adminActionForState[0]} <span>↗</span></button> : <p className="subtle-copy">No state transition is available right now.</p>}{status.endsWith("_EVALUATING") && jobCounts.SYSTEM_ERROR > 0 && <button className="button-secondary" disabled={busy} onClick={() => adminAction(`/event/admin/retry-system-errors?round=${round}`)}>Retry system errors ({jobCounts.SYSTEM_ERROR})</button>}</div><div className="admin-test-tools"><div><span className="eyebrow">TEST EVENT TOOLS</span><small>Test participants use normal registration and submission records.</small></div><select aria-label="Test participant count" value={testParticipantCount} onChange={(e) => setTestParticipantCount(e.target.value)} disabled={busy || status !== "REGISTRATION"}>{[3, 10, 20, 50, 80].map((count) => <option key={count} value={count}>{count} participants</option>)}</select><button className="button-secondary" disabled={busy || status !== "REGISTRATION"} onClick={addTestParticipants}>Add test participants</button><button className="button-secondary" disabled={busy || status !== "ROUND_1_SUBMISSION_OPEN"} onClick={seedTestAgents}>Seed bundled starter agents</button><button className="button-secondary danger-button" disabled={busy || Boolean(Object.entries(adminOverview?.evaluation_jobs || {}).some(([name, count]) => ["QUEUED", "RUNNING", "RETRYING"].includes(name) && count))} onClick={resetEvent}>{status === "FINAL_RESULTS" ? "Start new test event" : "Reset current event"}</button></div></>}
    </section><aside className="admin-aside"><div className="panel admin-state-card"><span className="eyebrow">EVENT STATE</span><strong>{status.replaceAll("_", " ")}</strong><p>{round ? `Round ${round} of 3` : "Registration phase"} · state transitions are controlled by the backend.</p></div><div className="panel admin-state-card"><span className="eyebrow">EVALUATION SNAPSHOT</span><strong>{evaluationStatus}</strong><p>{fmt(runningJobs)} active · {fmt(failedJobs)} recorded errors</p></div></aside></div></>;
  }

  function PageIntro({ index, label, title, desc }) { return <section className="page-intro"><span className="eyebrow">{index} / {label}</span><h1>{title}</h1><p>{desc}</p></section>; }
  function RoundCards() { return <div className="round-cards">{[1, 2, 3].map((n) => <article className="panel round-card" key={n}><span className="round-card-number">0{n}</span><div><span className="eyebrow">ROUND 0{n}</span><h3>{["Build your first agent", "Refine your strategy", "Make your final run"][n - 1]}</h3><p>{["Submit a valid agent during the Round 1 window to earn a score. If you miss it, you remain eligible for the next round.", "Upload an improved version or continue with your latest valid agent. No participant is eliminated.", "Update your agent or keep playing the last valid version. Every participant stays in through the final round."][n - 1]}</p></div><span className="round-card-state">{roundProgress[n - 1].state}</span></article>)}</div>; }

  function HomePage() {
    const top = standings.slice(0, 5);
    return <><section className="home-hero"><div className="hero-copy-block"><div className="hero-overline"><span className="live-dot" /> NIT WARANGAL · AI AGENT COMPETITION</div><h1>BUILD YOUR AI FARM.<br /><span>OUTSMART THE FIELD.</span></h1><p>Engineer an agent for a living agricultural simulation. Adapt across three rounds. Climb on one cumulative score.</p><div className="hero-actions"><button className="button-primary" onClick={() => navigate(participant ? "/dashboard" : "/participate")}>{participant ? "Go to dashboard" : "Enter the competition"}<span>↗</span></button><button className="button-quiet" onClick={() => navigate("/how-it-works")}>Explore the format <span>↓</span></button></div><div className="hero-proof"><span><b>03</b> ROUNDS</span><i /><span><b>00</b> ELIMINATIONS</span><i /><span><b>Σ</b> CUMULATIVE SCORE</span></div></div><div className="hero-visual"><FieldArtwork/><div className="art-overlay"><div><small>EVENT CONTROL</small><strong>{round ? `ROUND 0${round}` : "SEASON 01"}</strong></div><StatusBadge open={isSubmissionOpen}>{phaseLabel}</StatusBadge></div><div className="visual-coordinates">FIELD // NITW · 17.98°N 79.53°E</div></div></section>
      <section className="live-strip"><div><span className="eyebrow">LIVE EVENT STATUS</span><strong>{status === "LOADING" ? "CONNECTING TO EVENT" : status.replaceAll("_", " ")}</strong></div><i /><div><span className="eyebrow">REGISTERED FIELD</span><strong>{fmt(standings.length)} <small>PARTICIPANTS</small></strong></div><i /><div><span className="eyebrow">FORMAT</span><strong>3 ROUNDS <small>· NO ELIMINATIONS</small></strong></div></section>
      <section className="home-section"><SectionTitle index="01" eyebrow="THE COMPETITION LOOP" title="Build. Submit. Improve." link="/how-it-works" onNavigate={navigate}/><div className="flow-grid">{[["01", "REGISTER", "Claim your participant profile for the event."],["02", "BUILD", "Create a Python agent for the Kaggriculture farm."],["03", "SUBMIT", "Upload only while the round window is open."],["04", "IMPROVE", "Update your agent or carry forward a valid version."],["05", "COMPETE", "Earn round scores. Your total carries across all three."]].map(([n, title, desc]) => <article className="flow-item" key={n}><span>{n}</span><h3>{title}</h3><p>{desc}</p></article>)}</div></section>
      <section className="home-section home-round-section"><SectionTitle index="02" eyebrow="A THREE-ROUND SEASON" title="Every round counts." link="/how-it-works" onNavigate={navigate}/>{RoundRail()}<div className="carryover-note"><span>↻</span><div><strong>No eliminations. No one is knocked out.</strong><small>Miss a submission or continue with a previous version; every registered participant stays eligible through Round 3.</small></div></div></section>
      <section className="home-section preview-section"><div><SectionTitle index="03" eyebrow="THE FIELD" title="Standings at a glance." link="/leaderboard" onNavigate={navigate}/><p className="section-description">Published scores are added across rounds. Rankings use cumulative score.</p><button className="button-secondary" onClick={() => navigate("/leaderboard")}>View full leaderboard <span>↗</span></button></div><div className="preview-board">{leaderboardPublished && top.length ? top.map((row, i) => <div className="preview-row" key={row.participant_id}><span className={`preview-rank rank-${i + 1}`}>{String(i + 1).padStart(2, "0")}</span><strong>{row.username}</strong><span>{fmt(row.total_score)} <small>PTS</small></span></div>) : <div className="preview-empty">First round scores appear here after results are published.</div>}</div></section>
      <section className="cta-band"><div><span className="eyebrow">READY TO TAKE THE FIELD?</span><h2>Bring your best agent.</h2><p>Registration, submission windows, and your round history live in one place.</p></div><button className="button-primary" onClick={() => navigate(participant ? "/dashboard" : "/participate")}>{participant ? "Open dashboard" : "Get started"}<span>↗</span></button></section></>;
  }
  function HowPage() { return <><PageIntro index="01" label="COMPETITION FORMAT" title="Three rounds. One season." desc="A clear, non-elimination format: build, submit during each window, and improve your cumulative result."/><div className="rules-banner"><span>Σ</span><div><small>FINAL SCORE</small><strong>ROUND 1 + ROUND 2 + ROUND 3</strong></div><p>Round scores are added together. All registered participants remain in the event through the final round.</p></div><RoundCards/><section className="rules-grid"><article className="panel rule-card"><span className="eyebrow">SUBMISSION WINDOWS</span><h2>Upload while a round is open.</h2><p>Each round has a controlled submission window. When it closes, submissions are frozen. Upload actions outside that window are rejected.</p></article><article className="panel rule-card"><span className="eyebrow">YOUR AGENT VERSION</span><h2>Improve or carry forward.</h2><p>In Rounds 2 and 3, you may upload a new valid agent or continue with your latest valid version. No upload is required to keep participating.</p></article><article className="panel rule-card"><span className="eyebrow">MISSED OR INVALID</span><h2>A setback, not an exit.</h2><p>A missing or failed Round 1 submission earns zero for Round 1. Your participant profile remains, and you can submit your first valid agent in Round 2.</p></article><article className="panel rule-card"><span className="eyebrow">EVALUATION</span><h2>Results follow the window.</h2><p>Evaluation starts after submissions lock. Participant agent failures and timeouts are recorded per entry; evaluator/system failures are tracked separately for organizer retry. Published round scores appear in your dashboard and the leaderboard.</p></article></section><div className="how-cta"><p>Ready to build your agent?</p><button className="button-primary" onClick={() => navigate(participant ? "/dashboard" : "/participate")}>{participant ? "View dashboard" : "Register / participate"}<span>↗</span></button></div></>; }
  function LeaderboardPage() { return <><PageIntro index="02" label="OFFICIAL STANDINGS" title="The field, in full." desc="Published standings from the event API, ordered by cumulative score across three rounds."/><div className="leaderboard-meta"><StatusBadge open={status.endsWith("_EVALUATING")}>{status.endsWith("_EVALUATING") ? "EVALUATION IN PROGRESS" : leaderboardPublished ? "PUBLISHED RESULTS" : "AWAITING FIRST RESULTS"}</StatusBadge><span>{fmt(standings.length)} PARTICIPANTS</span><span>UPDATED FROM EVENT STATE</span></div>{leaderboardPublished && standings.length >= 3 && <div className="podium">{[1, 0, 2].map((index) => standings[index] && <article className={`podium-place place-${index + 1}`} key={standings[index].participant_id}><span>0{index + 1}</span><strong>{standings[index].username}</strong><b>{fmt(standings[index].total_score)} <small>PTS</small></b><i>R{fmt(standings[index].round1_score)} · R{fmt(standings[index].round2_score)} · R{fmt(standings[index].round3_score)}</i></article>)}</div>}<section className="panel full-leaderboard"><div className="panel-top"><div><span className="eyebrow">ROUND-WISE PERFORMANCE</span><h2>Leaderboard</h2></div><span className="eyebrow">RANKED BY TOTAL</span></div><LeaderboardTable/></section><p className="leaderboard-footnote">Scores are displayed as published by the event system. During evaluation, the currently published standings remain visible.</p></>; }
  function ParticipatePage() { return <><PageIntro index="03" label="JOIN FARMCraft" title="Your agent. Your strategy." desc="Create a participant profile, prepare your Python agent, and submit during the active round window."/><div className="participate-grid participant-access-grid">{RegisterCard()}{ParticipantLoginCard()}<section className="panel prep-card"><span className="eyebrow">SUBMISSION CHECKLIST</span><h2>Before you upload.</h2><ol><li><span>01</span><div><strong>Prepare your agent</strong><p>Use the participant starter and check the current game rules and agent interface.</p></div></li><li><span>02</span><div><strong>Save as a Python file</strong><p>Submit your agent as a .py file, within the 100 KB upload limit.</p></div></li><li><span>03</span><div><strong>Check the event window</strong><p>Uploads are accepted only while the current round submission window is open.</p></div></li><li><span>04</span><div><strong>Track each round</strong><p>View active agent, immutable submission history, evaluation status, and scores in your dashboard.</p></div></li></ol><button className="text-link" onClick={() => navigate("/how-it-works")}>Read the competition format →</button></section></div><div className="participate-note"><span className="eyebrow">ROUND 2 & 3</span><p>Want to keep your current agent? You can submit nothing and continue using your previous valid version.</p></div></>; }
  function DashboardPage() { return <><PageIntro index="04" label="PARTICIPANT CONSOLE" title={participant ? `Welcome back, ${participant.username}.` : "Your competition console."} desc="Agent versions, evaluation updates, and cumulative progress across the three-round event."/>{participant ? <><div className="dashboard-summary"><div className="panel identity-card"><span className="avatar-block">{participant.username.slice(0, 1).toUpperCase()}</span><div><span className="eyebrow">REGISTERED PARTICIPANT</span><h2>{participant.username}</h2><code>{pid}</code></div></div><div className="panel total-card"><span className="eyebrow">CUMULATIVE SCORE</span><strong>{fmt(participantTotal)} <small>PTS</small></strong><span>Sum of published round scores</span></div><div className="panel total-card"><span className="eyebrow">CURRENT EVENT PHASE</span><strong>{round ? `ROUND 0${round}` : "REGISTRATION"}</strong><span>{phaseLabel}</span></div></div>{RoundRail()}<div className="dashboard-columns"><div>{SubmissionForm()}<section className="panel history-card"><div className="panel-top"><div><span className="eyebrow">IMMUTABLE RECORDS</span><h2>Submission history</h2></div><span className="record-count">{history.length} VERSIONS</span></div>{HistoryTable()}</section></div><aside className="dashboard-side"><section className="panel score-breakdown"><span className="eyebrow">ROUND SCORES</span><h2>Your points by round</h2>{[1,2,3].map((n) => { const score = currentStanding?.[`round${n}_score`] ?? 0; return <div className="score-break-row" key={n}><span>ROUND 0{n}</span><strong>{fmt(score)} <small>PTS</small></strong><i className={roundProgress[n - 1].complete ? "scored" : ""}/></div>; })}<div className="breakdown-total"><span>CUMULATIVE</span><strong>{fmt(participantTotal)}</strong></div></section><section className="panel eval-card"><div className="panel-top"><div><span className="eyebrow">ROUND {String(round || 1).padStart(2, "0")}</span><h2>Evaluation</h2></div><StatusBadge open={evaluationStatus === "RUNNING"}>{evaluationStatus}</StatusBadge></div><p>{evaluationStatus === "WAITING" ? "No evaluation activity to show yet." : `${fmt(jobCounts.SUCCESS)} complete · ${fmt(runningJobs)} active · ${fmt(failedJobs)} errors`}</p>{["QUEUED", "RUNNING", "SUCCESS", "PLAYER_ERROR", "TIMEOUT", "SYSTEM_ERROR"].map((key) => <div className="job-row" key={key}><span>{key.replaceAll("_", " ")}</span><b>{fmt(jobCounts[key])}</b></div>)}</section><section className="panel rank-card"><span className="eyebrow">CURRENT POSITION</span><strong>{currentStanding ? `#${standings.findIndex((entry) => entry.participant_id === pid) + 1}` : "—"}</strong><button className="text-link" onClick={() => navigate("/leaderboard")}>Open full standings →</button></section></aside></div></> : <div className="dashboard-unregistered">{RegisterCard()}<div className="panel"><span className="eyebrow">ALREADY REGISTERED?</span><p>Your profile is saved in this browser. If you used another device, return to Participate and register with the event team.</p><button className="button-secondary" onClick={() => navigate("/participate")}>Go to Participate</button></div></div>}</>; }

  return <div className="site-shell"><header className="site-header"><a className="brand-lockup" href="/" onClick={(e) => { e.preventDefault(); navigate("/"); }}><Mark/><span className="brand-text"><strong>FARMCraft</strong><small>SOFTWARE DEVELOPMENT CLUB <i>·</i> NIT WARANGAL</small></span></a><button className="menu-toggle" aria-label="Toggle navigation" aria-expanded={menuOpen} onClick={() => setMenuOpen(!menuOpen)}><span/><span/></button><nav className={`main-nav ${menuOpen ? "open" : ""}`}>{nav}</nav><button className={`header-cta ${route === "/dashboard" ? "selected" : ""}`} onClick={() => participant ? navigate("/dashboard") : openParticipantLogin()}>{participant ? "My dashboard" : "Participant login"}<span>↗</span></button></header>
    {apiError && <div className="api-alert" role="alert"><span>!</span><div><strong>EVENT CONNECTION UNAVAILABLE</strong><small>{apiError}</small></div></div>}
    {message && <div className="toast-message" role="status">{message}<button aria-label="Dismiss message" onClick={() => setMessage("")}>×</button></div>}
    <main className="main-content" key={route}>{route === "/" ? HomePage() : route === "/how-it-works" ? HowPage() : route === "/leaderboard" ? LeaderboardPage() : route === "/participate" ? ParticipatePage() : route === "/dashboard" ? DashboardPage() : AdminPage()}</main>
    <footer className="site-footer"><div className="footer-brand"><Mark/><div><strong>FARMCraft</strong><small>AN AI AGENT COMPETITION</small></div></div><div className="footer-organizer"><span>ORGANIZED BY</span><strong>Software Development Club</strong><small>NATIONAL INSTITUTE OF TECHNOLOGY WARANGAL</small></div><div className="footer-tagline">BUILD <i>·</i> SUBMIT <i>·</i> IMPROVE <i>·</i> COMPETE</div><a href="/admin" className="admin-entry" onClick={(e) => { e.preventDefault(); navigate("/admin"); }}>Organizer access ↗</a></footer>
  </div>;
}

function SectionTitle({ index, eyebrow, title, link, onNavigate }) { return <div className="section-title"><div><span className="eyebrow">{index} / {eyebrow}</span><h2>{title}</h2></div>{link && <button className="text-link" onClick={() => onNavigate(link)}>Explore <span>↗</span></button>}</div>; }

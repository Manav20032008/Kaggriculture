import { useCallback, useEffect, useState } from "react";
import "./App.css";

const API = import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.DEV ? "/api" : "");
const initialPid = localStorage.getItem("kaggri-participant-id") || "";

export default function App() {
  const [state, setState] = useState(null);
  const [standings, setStandings] = useState([]);
  const [jobs, setJobs] = useState({ counts: {}, jobs: [] });
  const [pid, setPid] = useState(initialPid);
  const [participant, setParticipant] = useState(null);
  const [history, setHistory] = useState([]);
  const [activeSubmission, setActiveSubmission] = useState(null);
  const [username, setUsername] = useState("");
  const [file, setFile] = useState(null);
  const [token, setToken] = useState("");
  const [message, setMessage] = useState("");
  const [apiError, setApiError] = useState("");
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const s = await fetch(`${API}/event/state`);
      if (!s.ok) throw new Error(`Event status request failed (${s.status})`);
      const nextState = await s.json();
      setState(nextState);
      setApiError("");
      const selectedRound = nextState.current_round || 1;
      const [l, j] = await Promise.all([
        fetch(`${API}/event/standings`),
        fetch(`${API}/event/evaluation-jobs?round=${selectedRound}`),
      ]);
      if (l.ok) setStandings((await l.json()).standings || []);
      if (j.ok) setJobs(await j.json());
      if (pid) {
        const [p, h, a] = await Promise.all([
          fetch(`${API}/event/participants/${pid}`),
          fetch(`${API}/event/participants/${pid}/submissions`),
          fetch(`${API}/event/participants/${pid}/active-submission?round=${selectedRound}`),
        ]);
        if (p.ok) setParticipant(await p.json());
        if (h.ok) setHistory((await h.json()).submissions || []);
        if (a.ok) setActiveSubmission((await a.json()).active_submission || null);
      } else {
        setParticipant(null); setHistory([]); setActiveSubmission(null);
      }
    } catch (err) { setApiError(err.message || "Backend is not reachable. Start the FastAPI server and refresh."); }
  }, [pid]);

  useEffect(() => { const first = setTimeout(refresh, 0); const id = setInterval(refresh, 12000); return () => { clearTimeout(first); clearInterval(id); }; }, [refresh]);

  async function api(path, options = {}, admin = false) {
    const headers = { ...(options.headers || {}) };
    if (admin) headers["X-Admin-Token"] = token;
    const response = await fetch(`${API}${path}`, { ...options, headers });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Request failed");
    return body;
  }

  async function register(e) {
    e.preventDefault(); setBusy(true); setMessage("");
    try {
      const form = new FormData(); form.append("username", username);
      const p = await api("/event/register", { method: "POST", body: form });
      localStorage.setItem("kaggri-participant-id", p.participant_id); setPid(p.participant_id); setParticipant(p); setUsername(""); setMessage(`Registered ${p.username}. Upload your agent during an open submission window.`);
    } catch (err) { setMessage(err.message); } finally { setBusy(false); }
  }

  async function upload(e) {
    e.preventDefault(); if (!file || !pid) return; setBusy(true); setMessage("");
    try {
      const form = new FormData(); form.append("participant_id", pid); form.append("agent", file);
      const sub = await api("/event/submissions", { method: "POST", body: form });
      setMessage(`Submission received: Round ${sub.round_number}, version ${sub.version}. ID ${sub.submission_id}`); setFile(null); await refresh();
    } catch (err) { setMessage(err.message); } finally { setBusy(false); }
  }

  async function adminAction(path) {
    setBusy(true); setMessage("");
    try { await api(path, { method: "POST" }, true); setMessage("Event state updated."); await refresh(); }
    catch (err) { setMessage(err.message); } finally { setBusy(false); }
  }

  const status = state?.status || "LOADING";
  const round = state?.current_round;
  const isSubmissionOpen = status.endsWith("SUBMISSION_OPEN");
  const phaseLabel = status === "FINAL_RESULTS" ? "RESULTS PUBLISHED" : status.startsWith("ROUND_")
    ? status.replace(/^ROUND_\d+_/, "").replaceAll("_", " ")
    : status.replaceAll("_", " ");
  const leaderboardPublished = status === "FINAL_RESULTS" || status.endsWith("_COMPLETE") || (round !== null && round > 1);
  const currentStanding = standings.find((entry) => entry.participant_id === pid);
  const participantTotal = currentStanding?.total_score ?? 0;
  const jobCounts = jobs.counts || {};
  const runningJobs = (jobCounts.QUEUED || 0) + (jobCounts.RUNNING || 0) + (jobCounts.RETRYING || 0);
  const failedJobs = (jobCounts.PLAYER_ERROR || 0) + (jobCounts.TIMEOUT || 0) + (jobCounts.SYSTEM_ERROR || 0);
  const evaluationStatus = failedJobs ? "ERROR" : runningJobs ? "RUNNING" : jobCounts.SUCCESS ? "COMPLETED" : "WAITING";
  const adminActionForState = {
    REGISTRATION: ["OPEN SUBMISSIONS", "/event/admin/open-submissions?round=1"],
    ROUND_1_SUBMISSION_OPEN: ["LOCK SUBMISSIONS", "/event/admin/lock-submissions"],
    ROUND_1_SUBMISSION_LOCKED: ["START EVALUATION", "/event/admin/start-evaluation?round=1"],
    ROUND_1_EVALUATING: ["PROCESS RESULTS", "/event/admin/process-results?round=1"],
    ROUND_1_PROCESSING_RESULTS: ["PUBLISH RESULTS", "/event/admin/complete-round?round=1"],
    ROUND_1_COMPLETE: ["OPEN NEXT ROUND", "/event/admin/open-submissions?round=2"],
    ROUND_2_SUBMISSION_OPEN: ["LOCK SUBMISSIONS", "/event/admin/lock-submissions"],
    ROUND_2_SUBMISSION_LOCKED: ["START EVALUATION", "/event/admin/start-evaluation?round=2"],
    ROUND_2_EVALUATING: ["PROCESS RESULTS", "/event/admin/process-results?round=2"],
    ROUND_2_PROCESSING_RESULTS: ["PUBLISH RESULTS", "/event/admin/complete-round?round=2"],
    ROUND_2_COMPLETE: ["OPEN NEXT ROUND", "/event/admin/open-submissions?round=3"],
    ROUND_3_SUBMISSION_OPEN: ["LOCK SUBMISSIONS", "/event/admin/lock-submissions"],
    ROUND_3_SUBMISSION_LOCKED: ["START EVALUATION", "/event/admin/start-evaluation?round=3"],
    ROUND_3_EVALUATING: ["PROCESS RESULTS", "/event/admin/process-results?round=3"],
    ROUND_3_PROCESSING_RESULTS: ["PUBLISH RESULTS", "/event/admin/complete-round?round=3"],
    ROUND_3_COMPLETE: ["FINALIZE EVENT", "/event/admin/publish-final"],
  }[status];

  const roundProgress = [1, 2, 3].map((number) => {
    const complete = status === "FINAL_RESULTS" || (round && number < round) || status === `ROUND_${number}_COMPLETE`;
    const active = !complete && round === number && status.startsWith(`ROUND_${number}_`);
    return { number, complete, active, state: complete ? "COMPLETED" : active ? phaseLabel : "UPCOMING" };
  });
  const selectUpload = (selected) => { if (selected) setFile(selected); };

  return <main className="event-page">
    <header className="hero-shell">
      <div className="hero-backdrop" aria-hidden="true"><span /><span /><span /></div>
      <div className="hero-brand">
        <div className="brand-emblem" aria-hidden="true"><svg viewBox="0 0 64 64" role="img"><path d="M32 53V28m0 8C19 37 12 29 12 17c12 0 20 7 20 19Zm0-8c0-12 8-19 20-19 0 12-7 20-20 20ZM22 53h20" /><circle cx="32" cy="10" r="3" /></svg></div>
        <div><span className="brand-kicker">STUDENT AI CHALLENGE</span><div className="brand-name">KAGGRICULTURE</div></div>
      </div>
      <div className="hero-copy"><div><p className="eyebrow">AI-POWERED AGRICULTURAL SIMULATION CHALLENGE</p><h1>Grow a smarter<br /><span>kind of farm.</span></h1><p className="hero-description">Build an agent. Navigate a living market. Compete across three rounds on one cumulative score.</p></div>
        <div className="hero-status"><span className={`status-indicator ${isSubmissionOpen ? "is-open" : ""}`} /><div><small>CURRENT EVENT STATE</small><strong>{round ? `ROUND ${round} · ` : ""}{phaseLabel}</strong></div><span className="hero-round-count">03 <small>ROUNDS</small></span></div>
      </div>
      <div className="field-lines" aria-hidden="true"><i /><i /><i /><i /><i /><i /><i /></div>
    </header>
    {apiError && <p className="notice error-notice" role="alert">{apiError}</p>}

    <section className="round-panel panel">
      <div className="section-heading"><div><span className="section-index">01 / EVENT</span><h2>Competition path</h2></div><span className="quiet-label">THREE ROUNDS · NO ELIMINATIONS</span></div>
      <div className="round-timeline">{roundProgress.map(({ number, complete, active, state: stepState }, index) => <div className={`round-step ${complete ? "is-complete" : ""} ${active ? "is-active" : ""}`} key={number}>
        <div className="round-node">{complete ? "✓" : active ? <span className="active-node" /> : "0" + number}</div>
        <div className="round-step-copy"><span>ROUND 0{number}</span><strong>{stepState}</strong>{active && <small>{phaseLabel}</small>}</div>
        {index < 2 && <div className="round-connector" aria-hidden="true"><span>›</span></div>}
      </div>)}</div>
      {(round === 2 || round === 3) && <p className="round-choice"><span aria-hidden="true">↗</span> Continue with your previous agent <i>or</i> upload a new version for this round.</p>}
    </section>

    <section className="dashboard-grid">
      <article className="participant-panel panel">
        <div className="section-heading"><div><span className="section-index">02 / YOUR ENTRY</span><h2>Participant dashboard</h2></div><span className="tiny-live"><i /> LIVE</span></div>
        {participant ? <>
          <div className="participant-identity"><div className="participant-avatar">{participant.username.slice(0, 1).toUpperCase()}</div><div><span className="quiet-label">REGISTERED PARTICIPANT</span><h3>{participant.username}</h3><code>{pid}</code></div></div>
          <div className="participant-metrics"><div><span>ACTIVE AGENT</span><strong>{activeSubmission ? `VERSION ${activeSubmission.version}` : "NOT SET"}</strong><small>{activeSubmission?.status || "Upload needed"}</small></div><div><span>CURRENT ROUND</span><strong>{round ? `ROUND 0${round}` : "ROUND 01"}</strong><small>{phaseLabel}</small></div></div>
          <div className="score-feature"><div><span>CUMULATIVE SCORE</span><small>Updated after each published round</small></div><strong>{Number(participantTotal).toLocaleString()}</strong><span className="score-mark">PTS</span></div>
        </> : <form onSubmit={register} className="register-form"><label htmlFor="team-name">Team name</label><input id="team-name" value={username} onChange={(e) => setUsername(e.target.value)} maxLength={32} required placeholder="Enter your participant name" /><button className="button-primary" disabled={busy || status !== "REGISTRATION"}>Register for the event <span>→</span></button><small>Registration is available before Round 1 opens.</small></form>}
        {message && <p className="notice message-notice" role="status">{message}</p>}
      </article>

      <article className="submission-panel panel">
        <div className="section-heading"><div><span className="section-index">03 / AGENT</span><h2>Submission station</h2></div><span className={`window-badge ${isSubmissionOpen ? "is-open" : ""}`}><i />{isSubmissionOpen ? "WINDOW OPEN" : "LOCKED"}</span></div>
        {participant ? <>
          <div className="submission-topline"><div><span className="quiet-label">ROUND {String(round || 1).padStart(2, "0")} SUBMISSION</span><h3>{isSubmissionOpen ? "Submit your agent" : "Submissions locked"}</h3></div><span className="file-type">.PY</span></div>
          {isSubmissionOpen ? <form onSubmit={upload} className="upload-form">
            <label className={`drop-zone ${file ? "has-file" : ""}`} htmlFor="agent-file" onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); selectUpload(e.dataTransfer.files?.[0]); }}>
              <input id="agent-file" type="file" accept=".py" onChange={(e) => selectUpload(e.target.files?.[0] || null)} />
              <span className="upload-symbol" aria-hidden="true">↑</span>
              <strong>{file ? file.name : "Drop your agent.py here"}</strong>
              <small>{file ? "File selected · ready to submit" : "or browse files from your device"}</small>
              {!file && <span className="browse-button">Choose file</span>}
            </label>
            {activeSubmission && <div className="version-note"><span>ACTIVE VERSION</span><strong>v{activeSubmission.version}</strong><small>New upload becomes the active agent after submission.</small></div>}
            <button className="button-primary submit-button" disabled={busy || !file}>{round > 1 ? "Upload new version" : "Submit agent"}<span>→</span></button>
            <p className="form-hint">Python file, up to 100 KB. Keep your previous version or upload a new one.</p>
          </form> : <div className="locked-state"><span className="lock-symbol">⌑</span><div><strong>SUBMISSIONS LOCKED</strong><p>The submission window is closed for this round. Your active valid agent remains on file.</p></div></div>}
          {(round === 2 || round === 3) && <div className="choice-rail"><span className="choice-icon">↻</span><p><strong>Keep your previous agent</strong><small>No upload is needed to continue with your latest valid version.</small></p><span className="choice-or">OR</span><p><strong>Upload a new version</strong><small>Choose a fresh .py file while submissions are open.</small></p></div>}
        </> : <p className="empty-state">Register during the event registration period to submit an agent.</p>}
      </article>

      <article className="history-panel panel">
        <div className="section-heading"><div><span className="section-index">04 / VERSIONS</span><h2>Submission history</h2></div><span className="immutable-tag">▣ IMMUTABLE RECORDS</span></div>
        {history.length ? <div className="data-scroll"><table className="history-table"><thead><tr><th>ROUND</th><th>VERSION</th><th>STATUS</th><th>SUBMITTED</th><th>RECORD</th></tr></thead><tbody>{history.map((submission) => <tr key={submission.submission_id}><td>R{String(submission.round_number).padStart(2, "0")}</td><td>V{submission.version}</td><td><span className="status-chip">{submission.status}</span></td><td>{new Date(submission.created_at).toLocaleString()}</td><td><code>{submission.submission_id}</code></td></tr>)}</tbody></table></div> : <p className="empty-state">Your submitted agent versions will appear here.</p>}
        <p className="immutable-note"><span>▣</span> Submitted versions are preserved as read-only records.</p>
      </article>

      <article className="evaluation-panel panel">
        <div className="section-heading"><div><span className="section-index">05 / EVALUATION</span><h2>Evaluation status</h2></div><span className={`eval-state state-${evaluationStatus.toLowerCase()}`}><i />{evaluationStatus}</span></div>
        <div className="evaluation-summary"><div className={`eval-orbit ${evaluationStatus === "RUNNING" ? "is-running" : ""}`}><span>{evaluationStatus === "COMPLETED" ? "✓" : evaluationStatus === "ERROR" ? "!" : "↗"}</span></div><div><strong>{evaluationStatus === "WAITING" ? "Awaiting evaluation" : evaluationStatus === "RUNNING" ? "Agents are on the field" : evaluationStatus === "ERROR" ? "Review required" : "Evaluation complete"}</strong><p>{evaluationStatus === "WAITING" ? "Evaluation status updates after the submission window closes." : `${jobCounts.SUCCESS || 0} completed · ${runningJobs} in progress · ${failedJobs} errors`}</p></div></div>
        <div className="job-count-row">{["QUEUED", "RUNNING", "SUCCESS", "PLAYER_ERROR", "TIMEOUT", "SYSTEM_ERROR"].map((key) => <span key={key}><small>{key.replace("PLAYER_ERROR", "PLAYER ERR")}</small><b>{jobCounts[key] || 0}</b></span>)}</div>
      </article>
    </section>

    <section className="leaderboard-panel panel">
      <div className="leaderboard-heading"><div><span className="section-index">06 / THE FIELD</span><h2>Competition leaderboard</h2><p>Every registered participant. One cumulative result.</p></div><span className="leaderboard-count">{standings.length.toString().padStart(2, "0")} <small>TEAMS</small></span></div>
      {leaderboardPublished ? <div className="data-scroll"><table className="leaderboard-table"><thead><tr><th>RANK</th><th>PARTICIPANT</th><th>R1</th><th>R2</th><th>R3</th><th>TOTAL SCORE</th></tr></thead><tbody>{standings.map((entry, index) => <tr className={`${index < 3 ? `rank-top rank-${index + 1}` : ""} ${entry.participant_id === pid ? "is-you" : ""}`} key={entry.participant_id}><td><span className="rank-number">{String(index + 1).padStart(2, "0")}</span></td><td><span className="team-cell"><i />{entry.username}{entry.participant_id === pid && <small>YOU</small>}</span></td><td>{Number(entry.round1_score).toLocaleString()}</td><td>{Number(entry.round2_score).toLocaleString()}</td><td>{Number(entry.round3_score).toLocaleString()}</td><td><strong className="total-score">{Number(entry.total_score).toLocaleString()}<small> PTS</small></strong></td></tr>)}</tbody></table></div> : <div className="leaderboard-empty"><span>⌁</span><p>Round 1 standings will appear when the first results are published.</p></div>}
      <div className="leaderboard-footer"><span><i /> ALL PARTICIPANTS REMAIN ACTIVE</span><span>RANKED BY CUMULATIVE SCORE</span></div>
    </section>

    <section className="admin-panel">
      <div className="admin-heading"><div><span className="section-index">OPERATIONS</span><h2>Admin control center</h2><p>Event actions are available according to the current state.</p></div><div className="admin-current"><small>CURRENT STATE</small><strong>{status.replaceAll("_", " ")}</strong></div></div>
      <div className="admin-controls"><label htmlFor="admin-token">ADMIN TOKEN<input id="admin-token" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" placeholder="Enter configured admin token" /></label>{adminActionForState ? <button className="button-primary" disabled={busy || !token} onClick={() => adminAction(adminActionForState[1])}>{busy ? "WORKING…" : adminActionForState[0]} <span>→</span></button> : <span className="quiet-label">NO ACTION AVAILABLE IN THIS STATE</span>}{status.endsWith("_EVALUATING") && jobCounts.SYSTEM_ERROR > 0 && <button className="button-secondary" disabled={busy || !token} onClick={() => adminAction(`/event/admin/retry-system-errors?round=${round}`)}>RETRY SYSTEM ERRORS ({jobCounts.SYSTEM_ERROR})</button>}</div>
    </section>
    <footer className="page-footer"><span>KAGGRICULTURE · AI-POWERED AGRICULTURAL SIMULATION</span><span>THREE ROUNDS. ONE CUMULATIVE SCORE.</span></footer>
  </main>;
}

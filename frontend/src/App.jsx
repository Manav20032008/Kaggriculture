import { useEffect, useState, useRef } from "react";
import "./App.css";

const API_BASE = import.meta.env.VITE_API_BASE || "http://127.0.0.1:8000";

function App() {
  // Registration Form State
  const [username, setUsername] = useState("");
  const [agentFile, setAgentFile] = useState(null);
  const [registerMessage, setRegisterMessage] = useState({ type: "", text: "" });
  const [registerLoading, setRegisterLoading] = useState(false);

  // Tournament & Players State
  const [players, setPlayers] = useState([]);
  const [tournamentState, setTournamentState] = useState({
    status: "registration",
    message: "Registration is open.",
    playersCount: 0,
    maxPlayers: 60,
    registeredPlayers: [],
    currentRound: 0,
    totalRoundsEstimate: 0,
    currentMatches: [],
    roundsHistory: [],
    byes: [],
    eliminatedPlayers: [],
    allMatches: [],
    champion: null,
    finalScore: null,
    error: null,
    isLive: false,
  });

  // UI Navigation Tabs
  const [activeTab, setActiveTab] = useState("bracket"); // "bracket" | "live" | "history" | "standings"
  const [actionLoading, setActionLoading] = useState(false);
  const [demoMenuOpen, setDemoMenuOpen] = useState(false);

  // ============================================================
  // LOAD PLAYERS & TOURNAMENT STATUS
  // ============================================================

  async function fetchPlayers() {
    try {
      const res = await fetch(`${API_BASE}/players`);
      if (res.ok) {
        const data = await res.json();
        setPlayers(data.players || []);
      }
    } catch (err) {
      console.warn("Could not reach backend /players:", err);
    }
  }

  async function fetchTournamentStatus() {
    try {
      const res = await fetch(`${API_BASE}/tournament/status`);
      if (res.ok) {
        const data = await res.json();
        setTournamentState(data);
      }
    } catch (err) {
      console.warn("Could not fetch /tournament/status:", err);
    }
  }

  // Initial load
  useEffect(() => {
    fetchPlayers();
    fetchTournamentStatus();
  }, []);

  // Polling loop: fast (1s) when tournament is active, slower (3s) during registration
  useEffect(() => {
    const isRunning =
      tournamentState.isLive ||
      ["starting", "round_running", "next_round", "final"].includes(tournamentState.status);

    const intervalMs = isRunning ? 1000 : 3000;
    const timer = setInterval(() => {
      fetchTournamentStatus();
      if (!isRunning) {
        fetchPlayers();
      }
    }, intervalMs);

    return () => clearInterval(timer);
  }, [tournamentState.status, tournamentState.isLive]);

  // ============================================================
  // ACTIONS
  // ============================================================

  async function handleRegister(event) {
    event.preventDefault();
    setRegisterMessage({ type: "", text: "" });

    if (!username.trim()) {
      setRegisterMessage({ type: "error", text: "Please enter a valid username." });
      return;
    }

    if (!agentFile) {
      setRegisterMessage({ type: "error", text: "Please upload your Python agent (.py) file." });
      return;
    }

    if (!agentFile.name.toLowerCase().endsWith(".py")) {
      setRegisterMessage({ type: "error", text: "Only .py Python files are accepted." });
      return;
    }

    const formData = new FormData();
    formData.append("username", username.trim());
    formData.append("agent", agentFile);

    try {
      setRegisterLoading(true);
      const res = await fetch(`${API_BASE}/register`, {
        method: "POST",
        body: formData,
      });

      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Registration failed.");
      }

      setRegisterMessage({
        type: "success",
        text: `✓ ${data.player.username} registered successfully!`,
      });

      setUsername("");
      setAgentFile(null);
      const fileInput = document.getElementById("agent-file-input");
      if (fileInput) fileInput.value = "";

      await fetchPlayers();
      await fetchTournamentStatus();
    } catch (err) {
      setRegisterMessage({ type: "error", text: `✕ ${err.message}` });
    } finally {
      setRegisterLoading(false);
    }
  }

  async function handleStartTournament() {
    try {
      setActionLoading(true);
      const res = await fetch(`${API_BASE}/start-tournament`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Failed to start tournament.");
      }
      setActiveTab("bracket");
      await fetchTournamentStatus();
    } catch (err) {
      alert(`Error starting tournament: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleResetTournament() {
    if (!window.confirm("Reset tournament back to registration phase?")) return;
    try {
      setActionLoading(true);
      const res = await fetch(`${API_BASE}/tournament/reset`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Reset failed.");
      }
      await fetchTournamentStatus();
      await fetchPlayers();
    } catch (err) {
      alert(`Reset error: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  }

  async function handlePopulateDemo(count) {
    try {
      setActionLoading(true);
      setDemoMenuOpen(false);
      const res = await fetch(`${API_BASE}/demo/populate-sample-players?count=${count}`, {
        method: "POST",
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Demo populate failed.");
      await fetchPlayers();
      await fetchTournamentStatus();
    } catch (err) {
      alert(`Error: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  }

  async function handleClearPlayers() {
    if (!window.confirm("Are you sure you want to clear all registered players?")) return;
    try {
      setActionLoading(true);
      const res = await fetch(`${API_BASE}/players/clear`, { method: "POST" });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Clear players failed.");
      await fetchPlayers();
      await fetchTournamentStatus();
    } catch (err) {
      alert(`Error: ${err.message}`);
    } finally {
      setActionLoading(false);
    }
  }

  // ============================================================
  // STATUS HELPERS & DERIVED BRACKET DATA
  // ============================================================

  const currentStatus = tournamentState.status || "registration";
  const isRegistrationPhase = currentStatus === "registration";
  const isTournamentActive = ["starting", "round_running", "next_round", "final"].includes(currentStatus);
  const isChampionPhase = currentStatus === "champion";
  const hasError = currentStatus === "error";

  // Build unified rounds data for dynamic bracket rendering
  const bracketRounds = [];

  // Completed rounds from history
  if (tournamentState.roundsHistory && tournamentState.roundsHistory.length > 0) {
    tournamentState.roundsHistory.forEach((r) => {
      bracketRounds.push({
        round: r.round,
        title: r.matches.length === 1 && !r.byePlayer ? "Final" : `Round ${r.round}`,
        matches: r.matches,
        byePlayer: r.byePlayer,
        isCompleted: true,
      });
    });
  }

  // If there's an active round currently running that isn't yet finalized into roundsHistory
  if (
    tournamentState.currentRound > 0 &&
    !bracketRounds.some((r) => r.round === tournamentState.currentRound) &&
    tournamentState.currentMatches &&
    tournamentState.currentMatches.length > 0
  ) {
    const isFinalRound = tournamentState.status === "final" || tournamentState.currentMatches.length === 1;
    const currentBye = tournamentState.byes?.find((b) => b.round === tournamentState.currentRound)?.player || null;
    bracketRounds.push({
      round: tournamentState.currentRound,
      title: isFinalRound ? "Championship Final" : `Round ${tournamentState.currentRound}`,
      matches: tournamentState.currentMatches,
      byePlayer: currentBye,
      isCompleted: false,
    });
  }

  return (
    <div className="app">
      {/* ============================================================ */}
      {/* HEADER */}
      {/* ============================================================ */}
      <header className="header">
        <div className="logo-section">
          <div className="logo-icon">🌾</div>
          <div className="logo-text">
            <span className="logo-title">Kaggriculture</span>
            <span className="logo-sub">AI Knockout Arena</span>
          </div>
        </div>

        {/* Status Pill */}
        <div className="status-pill-container">
          <div className={`status-pill status-${currentStatus}`}>
            <span className="status-dot"></span>
            <span className="status-label">
              {currentStatus === "registration" && "Registration Open"}
              {currentStatus === "starting" && "Tournament Starting..."}
              {currentStatus === "round_running" && `Round ${tournamentState.currentRound} Live`}
              {currentStatus === "next_round" && `Round ${tournamentState.currentRound} Complete`}
              {currentStatus === "final" && "Championship Final 🔥"}
              {currentStatus === "champion" && "Champion Crowned 🏆"}
              {currentStatus === "error" && "Tournament Error"}
            </span>
          </div>
        </div>

        {/* Header Actions */}
        <div className="header-actions">
          {isRegistrationPhase && (
            <div className="demo-dropdown-wrapper">
              <button
                className="btn-secondary btn-sm"
                onClick={() => setDemoMenuOpen(!demoMenuOpen)}
                disabled={actionLoading}
              >
                ⚡ Quick Demo Setup ▾
              </button>
              {demoMenuOpen && (
                <div className="demo-dropdown-menu">
                  <button onClick={() => handlePopulateDemo(3)}>Seed 3 Players (Odd + BYE)</button>
                  <button onClick={() => handlePopulateDemo(4)}>Seed 4 Players (2 Rounds)</button>
                  <button onClick={() => handlePopulateDemo(7)}>Seed 7 Players (Odd + BYE)</button>
                  <button onClick={() => handlePopulateDemo(8)}>Seed 8 Players (3 Rounds)</button>
                  <button onClick={() => handlePopulateDemo(15)}>Seed 15 Players (Full Bracket)</button>
                  <hr />
                  <button className="text-danger" onClick={handleClearPlayers}>
                    Clear All Registered
                  </button>
                </div>
              )}
            </div>
          )}

          {isRegistrationPhase && (
            <button
              className="btn-primary"
              onClick={handleStartTournament}
              disabled={actionLoading || players.length < 2}
              title={players.length < 2 ? "Need at least 2 registered players" : "Start knockout tournament"}
            >
              Start Tournament ({players.length} Players) →
            </button>
          )}

          {!isRegistrationPhase && (
            <button
              className="btn-secondary btn-sm"
              onClick={handleResetTournament}
              disabled={actionLoading || isTournamentActive}
              title={isTournamentActive ? "Tournament is currently running" : "Reset back to registration"}
            >
              🔄 Reset Tournament
            </button>
          )}
        </div>
      </header>

      {/* ============================================================ */}
      {/* TOURNAMENT PROGRESS STEPPER */}
      {/* ============================================================ */}
      <div className="stepper-bar">
        <div className="stepper-inner">
          <div className={`step-item ${isRegistrationPhase ? "step-active" : "step-done"}`}>
            <div className="step-circle">1</div>
            <span>Registration</span>
          </div>
          <div className="step-line"></div>
          <div className={`step-item ${currentStatus === "starting" ? "step-active" : isTournamentActive || isChampionPhase ? "step-done" : ""}`}>
            <div className="step-circle">2</div>
            <span>Starting</span>
          </div>
          <div className="step-line"></div>
          <div className={`step-item ${currentStatus === "round_running" || currentStatus === "next_round" ? "step-active" : isChampionPhase ? "step-done" : ""}`}>
            <div className="step-circle">3</div>
            <span>Knockout Rounds</span>
          </div>
          <div className="step-line"></div>
          <div className={`step-item ${currentStatus === "final" ? "step-active" : isChampionPhase ? "step-done" : ""}`}>
            <div className="step-circle">4</div>
            <span>Championship Final</span>
          </div>
          <div className="step-line"></div>
          <div className={`step-item ${isChampionPhase ? "step-active step-gold" : ""}`}>
            <div className="step-circle">🏆</div>
            <span>Champion</span>
          </div>
        </div>
      </div>

      {/* ============================================================ */}
      {/* LIVE TOURNAMENT BROADCAST BANNER */}
      {/* ============================================================ */}
      {tournamentState.message && (
        <div className={`broadcast-banner ${isTournamentActive ? "broadcast-live" : ""} ${isChampionPhase ? "broadcast-champion" : ""} ${hasError ? "broadcast-error" : ""}`}>
          <div className="broadcast-content">
            {isTournamentActive && <span className="pulse-beacon"></span>}
            <span className="broadcast-text">{tournamentState.message}</span>
            {tournamentState.currentRound > 0 && isTournamentActive && (
              <span className="broadcast-round-badge">
                Round {tournamentState.currentRound} of ~{tournamentState.totalRoundsEstimate || "?"}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ============================================================ */}
      {/* MAIN CONTENT AREA */}
      {/* ============================================================ */}
      <main className="main-content">
        {/* If Registration Phase, show the dual Hero + Registration form */}
        {isRegistrationPhase && (
          <div className="registration-layout">
            {/* HERO SECTION */}
            <section className="hero-pane">
              <span className="hero-tag">NIT WARANGAL • FARM AI CHALLENGE</span>
              <h1 className="hero-title">
                1V1 KNOCKOUT
                <br />
                <span className="gradient-text">AI TOURNAMENT</span>
              </h1>
              <p className="hero-desc">
                Deploy your Python farming AI. Compete in head-to-head Kaggriculture 1v1
                simulations. Survive single-elimination knockout rounds, dynamic market
                fluctuations, and random BYEs to emerge as the undisputed Champion.
              </p>

              <div className="stats-grid">
                <div className="stat-card">
                  <span className="stat-num">{players.length}</span>
                  <span className="stat-label">Registered / 60</span>
                </div>
                <div className="stat-card">
                  <span className="stat-num">1v1</span>
                  <span className="stat-label">Knockout Battle</span>
                </div>
                <div className="stat-card">
                  <span className="stat-num">720</span>
                  <span className="stat-label">Season Turns</span>
                </div>
                <div className="stat-card">
                  <span className="stat-num">BYE</span>
                  <span className="stat-label">Odd Round Relief</span>
                </div>
              </div>

              {/* Tournament Rules Card */}
              <div className="rules-mini-card">
                <h4>📜 Tournament Rules & Execution</h4>
                <ul>
                  <li><strong>Pairings:</strong> Random match pairing every round.</li>
                  <li><strong>Advancement:</strong> Higher coin balance advances to next round.</li>
                  <li><strong>Odd Count:</strong> Exactly 1 randomly drawn participant receives a BYE.</li>
                  <li><strong>Ties:</strong> Replayed automatically with alternate seed (up to 10 replays).</li>
                  <li><strong>Execution:</strong> Standardized Kaggriculture sandbox runner.</li>
                </ul>
              </div>
            </section>

            {/* REGISTRATION FORM & PLAYER ROSTER */}
            <section className="form-pane">
              <div className="card glass-card">
                <div className="card-header">
                  <h2>Register Player & Agent</h2>
                  <p className="card-subtitle">Upload your Python agent.py to join the knockout tree</p>
                </div>

                <form onSubmit={handleRegister} className="register-form">
                  <div className="form-group">
                    <label htmlFor="username-input">Player / Team Name</label>
                    <input
                      id="username-input"
                      type="text"
                      placeholder="e.g. AgriBot_99"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      disabled={registerLoading}
                      maxLength={32}
                    />
                  </div>

                  <div className="form-group">
                    <label>Agent Script (Python .py)</label>
                    <div className="file-dropzone">
                      <input
                        id="agent-file-input"
                        type="file"
                        accept=".py"
                        onChange={(e) => setAgentFile(e.target.files[0] || null)}
                        disabled={registerLoading}
                      />
                      <div className="file-dropzone-content">
                        <span className="file-icon">📁</span>
                        <span className="file-name">
                          {agentFile ? agentFile.name : "Choose agent.py file or drag here"}
                        </span>
                        <span className="file-hint">Must define def agent(obs): function</span>
                      </div>
                    </div>
                  </div>

                  <button type="submit" className="btn-primary btn-block" disabled={registerLoading}>
                    {registerLoading ? "Validating & Registering..." : "Register Player ➔"}
                  </button>

                  {registerMessage.text && (
                    <div className={`message-box ${registerMessage.type}`}>
                      {registerMessage.text}
                    </div>
                  )}
                </form>

                {/* Registered Roster */}
                <div className="roster-section">
                  <div className="roster-header">
                    <h3>Registered Contenders</h3>
                    <span className="roster-badge">{players.length} / 60</span>
                  </div>

                  {players.length === 0 ? (
                    <div className="roster-empty">
                      No players registered yet. Use form above or click <strong>Quick Demo Setup</strong> to seed test agents.
                    </div>
                  ) : (
                    <div className="roster-grid">
                      {players.map((p, idx) => (
                        <div className="roster-item" key={p.username}>
                          <span className="roster-num">{String(idx + 1).padStart(2, "0")}</span>
                          <span className="roster-name">{p.username}</span>
                          <span className="roster-status">READY</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            </section>
          </div>
        )}

        {/* If Tournament Started or Finished, show Tournament Arena & Bracket */}
        {!isRegistrationPhase && (
          <div className="tournament-layout">
            {/* CHAMPION PODIUM BANNER */}
            {isChampionPhase && tournamentState.champion && (
              <div className="champion-podium glass-card">
                <div className="champion-glow"></div>
                <div className="trophy-badge">🏆</div>
                <span className="champion-eyebrow">TOURNAMENT WINNER</span>
                <h1 className="champion-name">{tournamentState.champion.username}</h1>
                <p className="champion-details">
                  Defeated all challengers through {tournamentState.roundsHistory?.length || 1} rounds of fierce
                  competition to claim the Kaggriculture Trophy!
                </p>
                {tournamentState.finalScore && (
                  <div className="final-score-pill">
                    Final Match: <strong>{tournamentState.finalScore.player1}</strong> ({tournamentState.finalScore.p1Score})
                    vs <strong>{tournamentState.finalScore.player2}</strong> ({tournamentState.finalScore.p2Score})
                  </div>
                )}
              </div>
            )}

            {/* TAB SELECTOR */}
            <div className="tab-navigation">
              <button
                className={`tab-btn ${activeTab === "bracket" ? "tab-active" : ""}`}
                onClick={() => setActiveTab("bracket")}
              >
                🌳 Tournament Bracket
              </button>
              <button
                className={`tab-btn ${activeTab === "live" ? "tab-active" : ""}`}
                onClick={() => setActiveTab("live")}
              >
                ⚔️ Current Round Matches ({tournamentState.currentMatches?.length || 0})
              </button>
              <button
                className={`tab-btn ${activeTab === "history" ? "tab-active" : ""}`}
                onClick={() => setActiveTab("history")}
              >
                📜 Match History ({tournamentState.allMatches?.length || 0})
              </button>
              <button
                className={`tab-btn ${activeTab === "standings" ? "tab-active" : ""}`}
                onClick={() => setActiveTab("standings")}
              >
                👥 Contenders & Eliminations
              </button>
            </div>

            {/* TAB CONTENT: DYNAMIC TOURNAMENT BRACKET */}
            {activeTab === "bracket" && (
              <div className="bracket-container glass-card">
                <div className="bracket-header">
                  <h3>Knockout Bracket Tree</h3>
                  <span className="bracket-legend">
                    <span className="legend-item"><span className="legend-dot dot-win"></span> Winner</span>
                    <span className="legend-item"><span className="legend-dot dot-live"></span> In Progress</span>
                    <span className="legend-item"><span className="legend-dot dot-bye"></span> BYE Pass</span>
                  </span>
                </div>

                {bracketRounds.length === 0 ? (
                  <div className="empty-bracket">Pairing players for Round 1...</div>
                ) : (
                  <div className="bracket-scroller">
                    <div className="bracket-tree">
                      {bracketRounds.map((rnd, rIndex) => (
                        <div className="bracket-round-column" key={`rnd-${rnd.round}`}>
                          <div className="bracket-column-header">
                            <span className="round-badge">{rnd.title}</span>
                            <span className="round-count">{rnd.matches.length} Match{rnd.matches.length > 1 ? "es" : ""}</span>
                          </div>

                          <div className="bracket-column-matches">
                            {rnd.matches.map((m, mIdx) => {
                              const isCompleted = m.status === "completed";
                              const isRunning = m.status === "running";
                              const p1Won = isCompleted && m.winner === m.player1;
                              const p2Won = isCompleted && m.winner === m.player2;

                              return (
                                <div
                                  className={`bracket-match-card ${isRunning ? "match-running" : ""} ${isCompleted ? "match-completed" : ""}`}
                                  key={m.id || `m-${rIndex}-${mIdx}`}
                                >
                                  <div className="match-meta">
                                    <span className="match-id">{m.id || `Match ${mIdx + 1}`}</span>
                                    {isRunning && <span className="badge-live-pulse">LIVE</span>}
                                    {m.tieReplays > 0 && <span className="badge-replay">{m.tieReplays} Replay</span>}
                                  </div>

                                  {/* Player 1 Row */}
                                  <div className={`bracket-player-row ${p1Won ? "row-winner" : ""} ${isCompleted && !p1Won ? "row-loser" : ""}`}>
                                    <span className="player-indicator">{p1Won ? "🏆" : "👤"}</span>
                                    <span className="bracket-player-name" title={m.player1}>
                                      {m.player1}
                                    </span>
                                    <span className="bracket-player-score">
                                      {m.p1Score !== null && m.p1Score !== undefined ? m.p1Score : "—"}
                                    </span>
                                  </div>

                                  {/* Player 2 Row */}
                                  <div className={`bracket-player-row ${p2Won ? "row-winner" : ""} ${isCompleted && !p2Won ? "row-loser" : ""}`}>
                                    <span className="player-indicator">{p2Won ? "🏆" : "👤"}</span>
                                    <span className="bracket-player-name" title={m.player2}>
                                      {m.player2}
                                    </span>
                                    <span className="bracket-player-score">
                                      {m.p2Score !== null && m.p2Score !== undefined ? m.p2Score : "—"}
                                    </span>
                                  </div>
                                </div>
                              );
                            })}

                            {/* Render BYE card if present in this round */}
                            {rnd.byePlayer && (
                              <div className="bracket-bye-card">
                                <div className="bye-header">
                                  <span>🛡️ RANDOM BYE</span>
                                  <span className="badge-bye">ADVANCED</span>
                                </div>
                                <div className="bye-player-name">{rnd.byePlayer}</div>
                                <div className="bye-note">Odd player count — advances automatically</div>
                              </div>
                            )}
                          </div>
                        </div>
                      ))}

                      {/* Crown column if tournament is complete */}
                      {isChampionPhase && tournamentState.champion && (
                        <div className="bracket-round-column champion-column">
                          <div className="bracket-column-header">
                            <span className="round-badge gold-badge">Champion</span>
                          </div>
                          <div className="bracket-crown-card">
                            <div className="crown-icon">👑</div>
                            <div className="crown-name">{tournamentState.champion.username}</div>
                            <div className="crown-sub">Knockout Winner</div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB CONTENT: CURRENT ROUND LIVE ARENA */}
            {activeTab === "live" && (
              <div className="arena-container glass-card">
                <div className="arena-header">
                  <h3>Round {tournamentState.currentRound} Arena Matches</h3>
                  <span className="arena-status">{tournamentState.message}</span>
                </div>

                {(!tournamentState.currentMatches || tournamentState.currentMatches.length === 0) ? (
                  <div className="empty-matches">No active matches in this phase.</div>
                ) : (
                  <div className="matches-grid">
                    {tournamentState.currentMatches.map((m, idx) => (
                      <div className={`live-match-box ${m.status}`} key={m.id || idx}>
                        <div className="live-match-header">
                          <span className="live-match-num">{m.id || `Match ${idx + 1}`}</span>
                          <span className={`status-tag status-${m.status}`}>{m.status.toUpperCase()}</span>
                        </div>

                        <div className="live-duel">
                          <div className={`duel-player ${m.winner === m.player1 ? "duel-winner" : ""}`}>
                            <div className="duel-avatar">🌾</div>
                            <div className="duel-name">{m.player1}</div>
                            <div className="duel-score">
                              {m.p1Score !== null && m.p1Score !== undefined ? m.p1Score : "—"}
                            </div>
                          </div>

                          <div className="duel-vs">VS</div>

                          <div className={`duel-player ${m.winner === m.player2 ? "duel-winner" : ""}`}>
                            <div className="duel-avatar">🚜</div>
                            <div className="duel-name">{m.player2}</div>
                            <div className="duel-score">
                              {m.p2Score !== null && m.p2Score !== undefined ? m.p2Score : "—"}
                            </div>
                          </div>
                        </div>

                        {m.winner && (
                          <div className="duel-footer">
                            Winner: <strong>{m.winner}</strong>
                            {m.tieReplays > 0 && <span className="replay-note">({m.tieReplays} replay seed used)</span>}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* TAB CONTENT: COMPLETE MATCH HISTORY */}
            {activeTab === "history" && (
              <div className="history-container glass-card">
                <div className="history-header">
                  <h3>Complete Match History</h3>
                  <span>{tournamentState.allMatches?.length || 0} match(es) executed</span>
                </div>

                {(!tournamentState.allMatches || tournamentState.allMatches.length === 0) ? (
                  <div className="empty-matches">No matches recorded yet.</div>
                ) : (
                  <div className="history-table-scroller">
                    <table className="history-table">
                      <thead>
                        <tr>
                          <th>#</th>
                          <th>Round</th>
                          <th>Player 1</th>
                          <th>Player 2</th>
                          <th>Score 1</th>
                          <th>Score 2</th>
                          <th>Winner</th>
                          <th>Replays</th>
                          <th>Seed</th>
                        </tr>
                      </thead>
                      <tbody>
                        {tournamentState.allMatches.map((m, idx) => (
                          <tr key={idx}>
                            <td>{idx + 1}</td>
                            <td>Round {m.round}</td>
                            <td className={m.winner === m.player1 ? "table-win" : ""}>{m.player1}</td>
                            <td className={m.winner === m.player2 ? "table-win" : ""}>{m.player2}</td>
                            <td>{m.p1Score}</td>
                            <td>{m.p2Score}</td>
                            <td className="table-win-name">🏆 {m.winner}</td>
                            <td>{m.tieReplays || 0}</td>
                            <td><code>{m.seed || "—"}</code></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            )}

            {/* TAB CONTENT: CONTENDERS & ELIMINATIONS */}
            {activeTab === "standings" && (
              <div className="standings-layout">
                {/* Active Contenders */}
                <div className="standings-card glass-card">
                  <h3>🛡️ Active Contenders</h3>
                  <div className="standings-list">
                    {players
                      .filter((p) => !tournamentState.eliminatedPlayers?.some((e) => e.player === p.username))
                      .map((p) => (
                        <div className="standing-item alive-item" key={p.username}>
                          <span className="alive-dot"></span>
                          <span className="standing-name">{p.username}</span>
                          <span className="alive-tag">ALIVE</span>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Eliminated Players */}
                <div className="standings-card glass-card">
                  <h3>💀 Eliminated Players</h3>
                  {(!tournamentState.eliminatedPlayers || tournamentState.eliminatedPlayers.length === 0) ? (
                    <div className="empty-matches">No players eliminated yet.</div>
                  ) : (
                    <div className="standings-list">
                      {tournamentState.eliminatedPlayers.map((e) => (
                        <div className="standing-item elim-item" key={e.player}>
                          <span className="elim-icon">✕</span>
                          <div className="elim-info">
                            <span className="standing-name">{e.player}</span>
                            <span className="elim-detail">
                              Knocked out in Round {e.eliminatedInRound} by <strong>{e.eliminatedBy}</strong>
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                {/* BYE Awards */}
                <div className="standings-card glass-card">
                  <h3>⭐ BYE Recipients</h3>
                  {(!tournamentState.byes || tournamentState.byes.length === 0) ? (
                    <div className="empty-matches">No BYEs awarded yet.</div>
                  ) : (
                    <div className="standings-list">
                      {tournamentState.byes.map((b, idx) => (
                        <div className="standing-item bye-item" key={idx}>
                          <span className="bye-icon">🛡️</span>
                          <div className="elim-info">
                            <span className="standing-name">{b.player}</span>
                            <span className="elim-detail">Received BYE in Round {b.round} (odd count relief)</span>
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

export default App;

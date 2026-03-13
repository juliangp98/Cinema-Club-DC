import { useState, useEffect, useMemo, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ProfileMenu from "../components/ProfileMenu";

const SCORING_LABELS = {
  none: "No scoring",
  single: "1 🍿 per correct",
  ranked: "Ranked 🍿",
  confidence: "Confidence × 🍿",
};

const TYPE_LABELS = { standard: "Poll", prediction: "Prediction" };

export default function PollDetailPage({ user, setUser, apiBase }) {
  const { pollId } = useParams();
  const navigate = useNavigate();
  const [poll, setPoll] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showProfile, setShowProfile] = useState(false);
  const [tab, setTab] = useState("vote"); // 'vote' | 'results' | 'leaderboard'
  const [leaderboard, setLeaderboard] = useState([]);
  const [isAdmin, setIsAdmin] = useState(false);

  // Vote state: { [categoryId]: { option_id, confidence } }
  const [votes, setVotes] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  // Score winners state: { [categoryId]: optionId }
  const [winners, setWinners] = useState({});
  const [scoring, setScoring] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const settingsRef = useRef(null);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editType, setEditType] = useState("standard");
  const [editScoring, setEditScoring] = useState("none");
  const [savingSettings, setSavingSettings] = useState(false);

  useEffect(() => {
    fetchPoll();
  }, [pollId]);

  async function fetchPoll() {
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}`, { credentials: "include" });
      if (r.ok) {
        const data = await r.json();
        setPoll(data);

        // Check admin status
        const gr = await fetch(`${apiBase}/api/groups`, { credentials: "include" });
        if (gr.ok) {
          const groups = await gr.json();
          const g = groups.find(g => g.id === data.group_id);
          setIsAdmin(g?.role === "admin");
        }

        // Pre-fill votes from user's existing votes
        const existingVotes = {};
        let hasVoted = false;
        for (const cat of data.categories || []) {
          if (cat.user_votes && cat.user_votes.length > 0) {
            existingVotes[cat.id] = { ranked: cat.user_votes.map(v => v.option_id) };
            hasVoted = true;
          } else if (cat.user_vote) {
            existingVotes[cat.id] = {
              option_id: cat.user_vote.option_id,
              confidence: cat.user_vote.confidence || 1,
            };
            hasVoted = true;
          }
        }
        setVotes(existingVotes);
        if (hasVoted || data.status !== "open") {
          setTab(data.status === "scored" ? "results" : "results");
        }

        // Pre-fill winners for scoring
        const existingWinners = {};
        for (const cat of data.categories || []) {
          if (cat.correct_option_id) {
            existingWinners[cat.id] = cat.correct_option_id;
          }
        }
        setWinners(existingWinners);
      }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  async function fetchLeaderboard() {
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}/leaderboard`, { credentials: "include" });
      if (r.ok) setLeaderboard(await r.json());
    } catch { /* ignore */ }
  }

  useEffect(() => {
    if (tab === "leaderboard") fetchLeaderboard();
  }, [tab]);

  function setVoteForCategory(catId, optionId) {
    setVotes(prev => ({
      ...prev,
      [catId]: { ...prev[catId], option_id: optionId, confidence: prev[catId]?.confidence || 1 },
    }));
  }

  function toggleRankedVote(catId, optId) {
    setVotes(prev => {
      const ranked = [...(prev[catId]?.ranked || [])];
      const idx = ranked.indexOf(optId);
      if (idx !== -1) {
        ranked.splice(idx, 1);
      } else if (ranked.length < 3) {
        ranked.push(optId);
      }
      return { ...prev, [catId]: { ranked } };
    });
  }

  function setConfidence(catId, val) {
    setVotes(prev => ({
      ...prev,
      [catId]: { ...prev[catId], confidence: Math.max(1, Math.min(10, parseInt(val) || 1)) },
    }));
  }

  async function handleSubmitVotes() {
    setSubmitting(true);
    const voteList = [];
    for (const [catId, v] of Object.entries(votes)) {
      if (poll.scoring_mode === 'ranked') {
        (v.ranked || []).forEach((optId, idx) => {
          voteList.push({ category_id: parseInt(catId), option_id: optId, rank: idx + 1 });
        });
      } else if (v.option_id) {
        voteList.push({ category_id: parseInt(catId), option_id: v.option_id, confidence: v.confidence || 1 });
      }
    }

    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ votes: voteList }),
      });
      if (r.ok) {
        setSubmitted(true);
        setTab("results");
        fetchPoll();
      }
    } catch { /* ignore */ }
    finally { setSubmitting(false); }
  }

  async function handleScoreWinners() {
    setScoring(true);
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}/score`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ winners }),
      });
      if (r.ok) {
        fetchPoll();
        setTab("results");
      }
    } catch { /* ignore */ }
    finally { setScoring(false); }
  }

  async function handleUndoScoring() {
    if (!window.confirm("Undo scoring? Winner selections will be preserved for editing.")) return;
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: "closed" }),
      });
      if (r.ok) fetchPoll();
    } catch { /* ignore */ }
  }

  async function handleReopenVoting() {
    if (!window.confirm("Reopen voting? Members will be able to change their votes.")) return;
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: "open" }),
      });
      if (r.ok) fetchPoll();
    } catch { /* ignore */ }
  }

  async function handleClosePoll() {
    try {
      await fetch(`${apiBase}/api/polls/${pollId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status: "closed" }),
      });
      fetchPoll();
    } catch { /* ignore */ }
  }

  async function handleDeletePoll() {
    if (!window.confirm("Delete this poll? This cannot be undone.")) return;
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (r.ok) navigate("/polls");
    } catch { /* ignore */ }
  }

  function openSettings() {
    setEditTitle(poll.title);
    setEditDesc(poll.description || "");
    setEditType(poll.poll_type);
    setEditScoring(poll.scoring_mode);
    setShowSettings(true);
  }

  async function handleSaveSettings() {
    setSavingSettings(true);
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          title: editTitle.trim(),
          description: editDesc,
          poll_type: editType,
          scoring_mode: editScoring,
        }),
      });
      if (r.ok) {
        setShowSettings(false);
        fetchPoll();
      }
    } catch { /* ignore */ }
    finally { setSavingSettings(false); }
  }

  // Close settings popup on Escape / outside click (similar to ProfileMenu)
  useEffect(() => {
    if (!showSettings) return;
    function onKey(e) {
      if (e.key === "Escape") setShowSettings(false);
    }
    function onClick(e) {
      if (settingsRef.current && !settingsRef.current.contains(e.target)) {
        setShowSettings(false);
      }
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [showSettings]);

  function logout() {
    fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" })
      .then(() => window.location.reload());
  }

  const totalCategories = poll?.categories?.length || 0;
  const votedCategories = Object.values(votes).filter(v =>
    poll.scoring_mode === 'ranked' ? (v.ranked?.length > 0) : v.option_id
  ).length;
  const allVoted = votedCategories === totalCategories && totalCategories > 0;

  if (loading) return null;
  if (!poll) { navigate("/polls"); return null; }

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <header className="group-discovery-header">
          <button className="group-back-btn" onClick={() => navigate("/polls")}>
            &larr; Polls
          </button>
          <h1 className="group-discovery-title poll-detail-title">{poll.title}</h1>
          <div style={{ marginLeft: "auto", position: "relative" }}>
            <div
              className="user-avatar"
              style={{ background: user.avatar_color, color: "#0d0c09" }}
              onClick={() => setShowProfile(!showProfile)}
            >
              {user.name.slice(0, 2).toUpperCase()}
            </div>
            {showProfile && (
              <ProfileMenu
                user={user}
                apiBase={apiBase}
                onUpdate={u => setUser(u)}
                onLogout={logout}
                onClose={() => setShowProfile(false)}
              />
            )}
          </div>
        </header>

        {/* Poll info bar */}
        <div className="poll-info-bar">
          <span className={`poll-status-badge ${poll.status}`}>
            {poll.status === "open" ? "🟢 Open" : poll.status === "scored" ? "🏆 Scored" : "🔴 Closed"}
          </span>
          <div className="poll-info-right">
            <span className={`poll-type-badge ${poll.poll_type}`}>{TYPE_LABELS[poll.poll_type]}</span>
            <span className="poll-scoring-badge">{SCORING_LABELS[poll.scoring_mode]}</span>
            {isAdmin && (
              <div className="poll-settings-trigger">
                <button
                  className="poll-settings-pill"
                  onClick={openSettings}
                  title="Poll Settings"
                >
                  Poll Settings
                </button>
                {showSettings && (
                  <div className="poll-settings-menu" ref={settingsRef}>
                    <div className="poll-settings-header">
                      <h3 className="poll-settings-title">Poll Settings</h3>
                      <button className="poll-settings-close" onClick={() => setShowSettings(false)}>&times;</button>
                    </div>

                    <label className="poll-form-label">Title</label>
                    <input
                      className="poll-input"
                      value={editTitle}
                      onChange={e => setEditTitle(e.target.value)}
                      maxLength={200}
                    />

                    <label className="poll-form-label">Description</label>
                    <textarea
                      className="poll-textarea"
                      value={editDesc}
                      onChange={e => setEditDesc(e.target.value)}
                      placeholder="Optional"
                      rows={3}
                    />

                    <label className="poll-form-label">Type</label>
                    <div className="poll-radio-group">
                      {[["standard", "Poll"], ["prediction", "Prediction"]].map(([val, label]) => (
                        <label
                          key={val}
                          className={`poll-radio type-${val}${editType === val ? " active" : ""}`}
                        >
                          <input
                            type="radio"
                            name="settingsType"
                            value={val}
                            checked={editType === val}
                            onChange={() => setEditType(val)}
                          />
                          {label}
                        </label>
                      ))}
                    </div>

                    <label className="poll-form-label">Scoring</label>
                    <div className="poll-radio-group">
                      {Object.entries(SCORING_LABELS).map(([val, label]) => (
                        <label
                          key={val}
                          className={`poll-radio scoring-${val}${editScoring === val ? " active" : ""}`}
                        >
                          <input
                            type="radio"
                            name="settingsScoring"
                            value={val}
                            checked={editScoring === val}
                            onChange={() => setEditScoring(val)}
                          />
                          {label}
                        </label>
                      ))}
                    </div>

                    <div className="poll-settings-actions">
                      <button
                        className="poll-admin-action"
                        onClick={() => setShowSettings(false)}
                      >
                        Cancel
                      </button>
                      <button
                        className="poll-submit-btn"
                        onClick={handleSaveSettings}
                        disabled={savingSettings || !editTitle.trim()}
                      >
                        {savingSettings ? "Saving..." : "Save Changes"}
                      </button>
                    </div>

                    <hr className="poll-settings-divider" />

                    <button className="poll-delete-btn" onClick={handleDeletePoll}>
                      Delete Poll
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
          {poll.description && <p className="poll-description">{poll.description}</p>}
        </div>

        {/* Tabs */}
        <div className="poll-tabs">
          <button
            className={`poll-tab${tab === "vote" ? " active" : ""}`}
            onClick={() => setTab("vote")}
            disabled={poll.status !== "open"}
          >
            Vote {poll.status === "open" && `(${votedCategories}/${totalCategories})`}
          </button>
          <button
            className={`poll-tab${tab === "results" ? " active" : ""}`}
            onClick={() => setTab("results")}
          >
            Results
          </button>
          {poll.scoring_mode !== "none" && (
            <button
              className={`poll-tab${tab === "leaderboard" ? " active" : ""}`}
              onClick={() => setTab("leaderboard")}
            >
              🍿 Leaderboard
            </button>
          )}
        </div>

        {/* Vote Tab */}
        {tab === "vote" && poll.status === "open" && (
          <div className="poll-vote-view">
            {poll.categories.map((cat, i) => (
              <div key={cat.id} className="poll-category-card">
                <div className="poll-category-title">
                  <span className="poll-category-num">{i + 1}.</span>
                  {cat.title}
                </div>
                {poll.scoring_mode === "ranked" ? (
                  <div className="poll-options-grid">
                    <p className="poll-ranked-hint">Select up to 3 in ranked order (click to add, click again to remove)</p>
                    {cat.options.map(opt => {
                      const ranked = votes[cat.id]?.ranked || [];
                      const rankIdx = ranked.indexOf(opt.id);
                      const rank = rankIdx !== -1 ? rankIdx + 1 : null;
                      return (
                        <button
                          key={opt.id}
                          className={`poll-option-card${rank ? " selected" : ""}`}
                          onClick={() => toggleRankedVote(cat.id, opt.id)}
                        >
                          {rank && <span className="poll-rank-badge">#{rank}</span>}
                          {opt.text}
                        </button>
                      );
                    })}
                  </div>
                ) : (
                  <div className="poll-options-grid">
                    {cat.options.map(opt => (
                      <button
                        key={opt.id}
                        className={`poll-option-card${votes[cat.id]?.option_id === opt.id ? " selected" : ""}`}
                        onClick={() => setVoteForCategory(cat.id, opt.id)}
                      >
                        {opt.text}
                      </button>
                    ))}
                  </div>
                )}
                {poll.scoring_mode === "confidence" && votes[cat.id]?.option_id && (
                  <div className="poll-confidence-row">
                    <label className="poll-confidence-label">Confidence:</label>
                    <input
                      type="range"
                      min="1"
                      max="10"
                      value={votes[cat.id]?.confidence || 1}
                      onChange={e => setConfidence(cat.id, e.target.value)}
                      className="poll-confidence-slider"
                    />
                    <span className="poll-confidence-val">
                      {votes[cat.id]?.confidence || 1} 🍿
                    </span>
                  </div>
                )}
              </div>
            ))}

            <div className="poll-vote-actions">
              <button
                className="poll-submit-btn"
                onClick={handleSubmitVotes}
                disabled={submitting || !allVoted}
              >
                {submitting ? "Submitting..." : allVoted ? "Submit Votes" : `Pick all ${totalCategories} categories to submit`}
              </button>
              {isAdmin && (
                <button className="poll-admin-action" onClick={handleClosePoll}>
                  Close Voting
                </button>
              )}
            </div>
          </div>
        )}

        {/* Results Tab */}
        {tab === "results" && (
          <div className="poll-results-view">
            {poll.categories.map((cat, i) => {
              const dist = cat.vote_distribution || {};
              const totalVotes = Object.values(dist).reduce((a, b) => a + b, 0);
              const userVote = cat.user_vote;
              const userVotes = cat.user_votes || [];
              const correctId = cat.correct_option_id;
              const isRanked = poll.scoring_mode === 'ranked';

              return (
                <div key={cat.id} className="poll-category-card">
                  <div className="poll-category-title">
                    <span className="poll-category-num">{i + 1}.</span>
                    {cat.title}
                  </div>
                  <div className="poll-results-list">
                    {cat.options.map(opt => {
                      const count = dist[opt.id] || 0;
                      const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
                      const isWinner = correctId === opt.id;
                      const userRankedPick = isRanked ? userVotes.find(v => v.option_id === opt.id) : null;
                      const isUserPick = isRanked ? !!userRankedPick : userVote?.option_id === opt.id;
                      const isCorrect = isUserPick && isWinner;
                      const isWrong = isUserPick && correctId && !isWinner;

                      return (
                        <div
                          key={opt.id}
                          className={`poll-result-row${isWinner ? " winner" : ""}${isUserPick ? " user-pick" : ""}${isCorrect ? " correct" : ""}${isWrong ? " wrong" : ""}`}
                        >
                          <div className="poll-result-bar" style={{ width: `${pct}%` }} />
                          <span className="poll-result-label">
                            {isWinner && "🏆 "}{isCorrect && "✅ "}{isWrong && "❌ "}
                            {opt.text}
                            {isUserPick && !correctId && isRanked && ` ← your #${userRankedPick.rank} pick`}
                            {isUserPick && !correctId && !isRanked && " ← your pick"}
                          </span>
                          <span className="poll-result-count">
                            {count} ({pct}%)
                          </span>
                        </div>
                      );
                    })}
                  </div>
                  {isAdmin && poll.status === "closed" && (
                    <div className="poll-winner-select">
                      <label className="poll-form-label">Select winner:</label>
                      <select
                        value={winners[cat.id] || ""}
                        onChange={e => setWinners(prev => ({ ...prev, [cat.id]: parseInt(e.target.value) }))}
                        className="poll-input tiny"
                      >
                        <option value="">—</option>
                        {cat.options.map(opt => (
                          <option key={opt.id} value={opt.id}>{opt.text}</option>
                        ))}
                      </select>
                    </div>
                  )}
                </div>
              );
            })}

            {/* Admin actions */}
            {isAdmin && (
              <div className="poll-results-actions">
                <div className="poll-results-actions-left">
                  {poll.status === "open" && (
                    <button className="poll-admin-action" onClick={handleClosePoll}>
                      Close Voting
                    </button>
                  )}
                  {poll.status === "closed" && (
                    <button className="poll-admin-action" onClick={handleReopenVoting}>
                      🔓 Reopen Voting
                    </button>
                  )}
                  {poll.status === "scored" && (
                    <button className="poll-admin-action" onClick={handleUndoScoring}>
                      ✏️ Edit Winners
                    </button>
                  )}
                </div>
                <div className="poll-results-actions-right">
                  {poll.status === "closed" && (
                    <button
                      className="poll-submit-btn"
                      onClick={handleScoreWinners}
                      disabled={scoring || Object.keys(winners).length === 0}
                    >
                      {scoring ? "Scoring..." : "🏆 Score Winners & Award 🍿"}
                    </button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Leaderboard Tab */}
        {tab === "leaderboard" && (
          <div className="poll-leaderboard">
            {leaderboard.length === 0 && (
              <p className="poll-empty">No scores yet. Winners must be marked first.</p>
            )}
            {leaderboard.map((entry, i) => (
              <div key={entry.user.id} className={`poll-lb-row${entry.user.id === user.id ? " current-user" : ""}`}>
                <span className="poll-lb-rank">
                  {i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `#${i + 1}`}
                </span>
                <div
                  className="poll-lb-avatar"
                  style={{ background: entry.user.avatar_color, color: "#0d0c09" }}
                >
                  {entry.user.name.slice(0, 2).toUpperCase()}
                </div>
                <span className="poll-lb-name">{entry.user.name}</span>
                <span className="poll-lb-stats">
                  {entry.correct}/{entry.total} correct
                </span>
                <span className="poll-lb-kernels">
                  {entry.kernels} 🍿
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  );
}

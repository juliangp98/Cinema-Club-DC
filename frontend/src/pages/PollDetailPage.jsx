import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Sheet from "../ui/Sheet";
import Avatar from "../ui/Avatar";
import { Segmented } from "../ui/TicketRow";
import { PollDiscord } from "../ui/DiscordShare";
import { SCORING_LABELS, TYPE_LABELS } from "./PollsPage";
import "./Polls.css";

const STATUS = { open: "Open", closed: "Voting closed", scored: "Results in" };
const LAYOUTS = [{ status: "one", label: "One at a time" }, { status: "all", label: "All" }];
const LAYOUT_KEY = "cinemaclub_ballot_layout";

// One category's choices: single pick (± confidence) or ranked top 3. Options
// linked to a film show its poster (AI drafts link them).
function Choices({ cat, mode, vote, onPick, onRank, onConfidence, status }) {
  const ranked = vote?.ranked || [];
  return (
    <div className="pv-choices">
      {mode === "ranked" && <p className="pv-hint">Pick up to 3, in order. Tap again to remove.</p>}
      {cat.options.map(opt => {
        const rank = mode === "ranked" ? ranked.indexOf(opt.id) + 1 : 0;
        const on = mode === "ranked" ? rank > 0 : vote?.option_id === opt.id;
        let extra = {};
        try { extra = opt.extra || (opt.extra_data ? JSON.parse(opt.extra_data) : {}); } catch { /* none */ }
        return (
          <button key={opt.id} type="button" className={`pv-choice${on ? " on" : ""}`} aria-pressed={on}
                  onClick={() => (mode === "ranked" ? onRank(cat.id, opt.id) : onPick(cat.id, opt.id))}>
            {extra.poster_url ? <img src={extra.poster_url} alt="" loading="lazy" /> : <span className="pv-choice-dot" aria-hidden="true" />}
            <span className="pv-choice-text">{opt.text}{extra.year ? <span className="pv-choice-year"> ({extra.year})</span> : null}</span>
            {mode === "ranked" && rank > 0 && <span className="pv-rank">#{rank}</span>}
            {mode !== "ranked" && on && <span className="pv-check">✓</span>}
          </button>
        );
      })}
      {mode === "confidence" && vote?.option_id && (
        <label className="pv-confidence">
          <span>Confidence</span>
          <input type="range" min="1" max="10" value={vote.confidence || 1} onChange={e => onConfidence(cat.id, e.target.value)} />
          <strong>{vote.confidence || 1} 🍿</strong>
        </label>
      )}
      <span className={`pv-saved ${status || ""}`} aria-live="polite">
        {status === "saving" ? "Saving…" : status === "saved" ? "Saved ✓" : status === "error" ? "Couldn't save — tap again" : ""}
      </span>
    </div>
  );
}

// The ballot (R6a): progress, one category at a time or all at once (your
// choice, remembered), results with bars and winners, and the leaderboard.
// Organizers and admins get one Manage panel: status, winners, settings, Discord.
export default function PollDetailPage({ user, setUser, apiBase }) {
  const { pollId } = useParams();
  const navigate = useNavigate();
  const [poll, setPoll] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("vote"); // 'vote' | 'results' | 'leaderboard'
  const [leaderboard, setLeaderboard] = useState([]);
  const [isAdmin, setIsAdmin] = useState(false);       // can run this poll: organizer or admin (R5c)
  const [readOnly, setReadOnly] = useState(false);     // read-only members see polls but don't vote

  // Vote state: { [categoryId]: { option_id, confidence } }
  const [votes, setVotes] = useState({});
  // Per-category save status: { [categoryId]: 'saving' | 'saved' | 'error' }
  const [saveStatus, setSaveStatus] = useState({});

  // Score winners state: { [categoryId]: optionId }
  const [winners, setWinners] = useState({});
  // Per-category winner save status: { [categoryId]: 'saving' | 'saved' | 'error' }
  const [winnerSaveStatus, setWinnerSaveStatus] = useState({});
  const [scoring, setScoring] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editDesc, setEditDesc] = useState("");
  const [editType, setEditType] = useState("standard");
  const [editScoring, setEditScoring] = useState("none");
  const [savingSettings, setSavingSettings] = useState(false);

  useEffect(() => {
    fetchPoll();
  }, [pollId]);

  // Live refresh: poll data every 10s while poll is open or closed (scoring in progress)
  useEffect(() => {
    if (!poll || poll.status === 'scored') return;
    const interval = setInterval(() => {
      fetchPollQuiet();
    }, 10000);
    return () => clearInterval(interval);
  }, [poll?.status, pollId]);

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
          setIsAdmin(["admin", "organizer"].includes(g?.role));
          setReadOnly(g?.role === "viewer");
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

  async function fetchPollQuiet() {
    // Refresh poll data without resetting loading/vote state (for live updates)
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}`, { credentials: "include" });
      if (r.ok) {
        const data = await r.json();
        setPoll(data);
        // Update winners from server (in case another admin set them)
        const existingWinners = {};
        for (const cat of data.categories || []) {
          if (cat.correct_option_id) {
            existingWinners[cat.id] = cat.correct_option_id;
          }
        }
        setWinners(prev => ({ ...prev, ...existingWinners }));
      }
    } catch { /* ignore */ }
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

  // Auto-refresh leaderboard every 10s when viewing it
  useEffect(() => {
    if (tab !== "leaderboard") return;
    const interval = setInterval(fetchLeaderboard, 10000);
    return () => clearInterval(interval);
  }, [tab, pollId]);

  // Debounce timer ref for confidence slider
  const confidenceTimerRef = useRef({});

  // Read-only members land on Results (voting is for members and up).
  useEffect(() => { if (readOnly && tab === "vote") setTab("results"); }, [readOnly, tab]);

  async function saveVoteForCategory(catId, voteData) {
    if (readOnly) return;
    setSaveStatus(prev => ({ ...prev, [catId]: 'saving' }));
    const voteList = [];
    if (poll.scoring_mode === 'ranked') {
      (voteData.ranked || []).forEach((optId, idx) => {
        voteList.push({ category_id: catId, option_id: optId, rank: idx + 1 });
      });
    } else if (voteData.option_id) {
      voteList.push({ category_id: catId, option_id: voteData.option_id, confidence: voteData.confidence || 1 });
    }
    // Removing every ranked pick clears the category.
    const clear = voteList.length === 0 && poll.scoring_mode === 'ranked' ? [catId] : [];
    if (voteList.length === 0 && !clear.length) {
      setSaveStatus(prev => ({ ...prev, [catId]: undefined }));
      return;
    }
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}/vote`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ votes: voteList, clear }),
      });
      setSaveStatus(prev => ({ ...prev, [catId]: r.ok ? 'saved' : 'error' }));
      if (r.ok) fetchPollQuiet();   // your pick unlocks this category's vote split
    } catch {
      setSaveStatus(prev => ({ ...prev, [catId]: 'error' }));
    }
  }

  function setVoteForCategory(catId, optionId) {
    const newVote = { option_id: optionId, confidence: votes[catId]?.confidence || 1 };
    setVotes(prev => ({ ...prev, [catId]: newVote }));
    saveVoteForCategory(catId, newVote);
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
      const newVote = { ranked };
      // Save immediately
      saveVoteForCategory(catId, newVote);
      return { ...prev, [catId]: newVote };
    });
  }

  function setConfidence(catId, val) {
    const confidence = Math.max(1, Math.min(10, parseInt(val) || 1));
    setVotes(prev => ({
      ...prev,
      [catId]: { ...prev[catId], confidence },
    }));
    // Debounce confidence saves (slider drags rapidly)
    clearTimeout(confidenceTimerRef.current[catId]);
    confidenceTimerRef.current[catId] = setTimeout(() => {
      setVotes(current => {
        const v = current[catId];
        if (v?.option_id) saveVoteForCategory(catId, v);
        return current;
      });
    }, 400);
  }

  async function saveWinnerForCategory(catId, optionId) {
    setWinnerSaveStatus(prev => ({ ...prev, [catId]: 'saving' }));
    try {
      const r = await fetch(`${apiBase}/api/polls/${pollId}/categories/${catId}/winner`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ option_id: optionId || null }),
      });
      setWinnerSaveStatus(prev => ({ ...prev, [catId]: r.ok ? 'saved' : 'error' }));
    } catch {
      setWinnerSaveStatus(prev => ({ ...prev, [catId]: 'error' }));
    }
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



  const totalCategories = poll?.categories?.length || 0;
  const votedCategories = Object.values(votes).filter(v =>
    poll?.scoring_mode === 'ranked' ? (v.ranked?.length > 0) : v.option_id
  ).length;


  const [layout, setLayout] = useState(() => {
    try { const v = localStorage.getItem(LAYOUT_KEY); if (v === "one" || v === "all") return v; } catch { /* private mode */ }
    return window.innerWidth < 768 ? "one" : "all";
  });
  const [current, setCurrent] = useState(0);
  const chooseLayout = v => { if (!v) return; setLayout(v); try { localStorage.setItem(LAYOUT_KEY, v); } catch { /* private mode */ } };

  if (loading) return null;
  if (!poll) { navigate("/polls"); return null; }

  const cats = poll.categories || [];
  const mode = poll.scoring_mode;
  const isPicked = c => (mode === "ranked" ? votes[c.id]?.ranked?.length > 0 : !!votes[c.id]?.option_id);
  const idx = Math.min(current, Math.max(0, cats.length - 1));
  const nextOpen = () => {
    const after = cats.findIndex((c, i) => i > idx && !isPicked(c));
    const any = after === -1 ? cats.findIndex(c => !isPicked(c)) : after;
    setCurrent(any === -1 ? Math.min(idx + 1, cats.length - 1) : any);
  };
  const canVote = poll.status === "open" && !readOnly;
  const choicesFor = cat => (
    <Choices cat={cat} mode={mode} vote={votes[cat.id]} status={saveStatus[cat.id]}
             onPick={setVoteForCategory} onRank={toggleRankedVote} onConfidence={setConfidence} />
  );
  const tabs = [
    ...(canVote ? [{ status: "vote", label: `Vote ${votedCategories}/${totalCategories}` }] : []),
    { status: "results", label: "Results" },
    ...(mode !== "none" ? [{ status: "leaderboard", label: "🍿 Leaderboard" }] : []),
  ];

  return (
    <div className="page narrow polls">
      <PageHeader title={poll.title} back={{ to: "/polls", label: "Polls" }}
                  subtitle={`${STATUS[poll.status] || poll.status} · ${TYPE_LABELS[poll.poll_type] || "Poll"} · ${SCORING_LABELS[mode]} · ${totalCategories} ${totalCategories === 1 ? "category" : "categories"}`} />
      {poll.description && <p className="pv-desc">{poll.description}</p>}
      {readOnly && poll.status === "open" && <p className="pv-hint">You're read-only in this club: you can follow the poll and its results, but not vote.</p>}

      {isAdmin && (
        <section className="pv-manage" aria-label="Manage this poll">
          <div className="pv-manage-row">
            <span className="pv-label">Manage</span>
            {poll.status === "open" && <button className="btn btn-sm" onClick={handleClosePoll}>Close voting</button>}
            {poll.status === "closed" && <button className="btn btn-sm" onClick={handleReopenVoting}>Reopen voting</button>}
            {poll.status === "scored" && <button className="btn btn-sm" onClick={handleUndoScoring}>Edit winners</button>}
            {poll.status !== "scored" && mode !== "none" && (
              <button className="btn btn-sm btn-primary" onClick={handleScoreWinners} disabled={scoring || Object.keys(winners).length === 0}
                      title="Mark winners on the Results tab first">
                {scoring ? "Finalizing…" : "🏆 Finalize scores"}
              </button>
            )}
            <button className="btn btn-sm btn-ghost" onClick={openSettings}>Settings</button>
          </div>
          {poll.status !== "scored" && mode !== "none" && (
            <p className="pv-hint">Mark each category's winner on the Results tab, then finalize to award 🍿.</p>
          )}
          {poll.discord && <PollDiscord poll={poll} apiBase={apiBase} onChange={fetchPollQuiet} />}
        </section>
      )}

      <div className="pv-tabs">
        <Segmented label="View" options={tabs} value={tab} onChange={v => v && setTab(v)} />
        {tab === "vote" && <Segmented label="Ballot layout" options={LAYOUTS} value={layout} onChange={chooseLayout} />}
      </div>

      {tab === "vote" && canVote && (
        <div className="pv-ballot">
          <div className="pv-progress big" aria-label={`${votedCategories} of ${totalCategories} picked`}>
            <span className="pv-progress-bar"><span style={{ width: `${totalCategories ? (votedCategories / totalCategories) * 100 : 0}%` }} /></span>
            <span className="pv-progress-text">{votedCategories === totalCategories ? "All picked ✓ — change anything until voting closes" : `${votedCategories} of ${totalCategories} picked · saves as you go`}</span>
          </div>

          {layout === "one" ? (
            <>
              <div className="pv-jump" role="tablist" aria-label="Categories">
                {cats.map((c, i) => (
                  <button key={c.id} type="button" role="tab" aria-selected={i === idx} title={c.title}
                          className={`pv-jump-dot${i === idx ? " current" : ""}${isPicked(c) ? " done" : ""}`} onClick={() => setCurrent(i)}>
                    {i + 1}
                  </button>
                ))}
              </div>
              {cats[idx] && (
                <article className="pv-cat one">
                  <h2 className="pv-cat-title"><span>{idx + 1} / {cats.length}</span>{cats[idx].title}</h2>
                  {choicesFor(cats[idx])}
                  <div className="pv-step">
                    <button className="btn" disabled={idx === 0} onClick={() => setCurrent(idx - 1)}>‹ Back</button>
                    <button className="btn btn-primary" disabled={cats.every(isPicked) && idx === cats.length - 1} onClick={nextOpen}>
                      {cats.every(isPicked) ? "Next ›" : "Next unpicked ›"}
                    </button>
                  </div>
                </article>
              )}
            </>
          ) : (
            cats.map((c, i) => (
              <article key={c.id} className={`pv-cat${isPicked(c) ? " done" : ""}`}>
                <h2 className="pv-cat-title"><span>{i + 1}</span>{c.title}</h2>
                {choicesFor(c)}
              </article>
            ))
          )}
        </div>
      )}

      {tab === "results" && (
        <div className="pv-results">
          {cats.map((cat, i) => {
            const splitHidden = !cat.vote_distribution;
            const dist = cat.vote_distribution || {};
            const totalVotes = Object.values(dist).reduce((a, b) => a + b, 0);
            const userVotes = cat.user_votes || [];
            const correctId = cat.correct_option_id;
            const isRanked = mode === "ranked";
            return (
              <article key={cat.id} className="pv-cat">
                <h2 className="pv-cat-title"><span>{i + 1}</span>{cat.title}</h2>
                {splitHidden && <p className="pv-hint">Pick yours to see how everyone voted.</p>}
                <div className="pv-bars">
                  {cat.options.map(opt => {
                    const count = dist[opt.id] || 0;
                    const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
                    const isWinner = correctId === opt.id;
                    const mine = isRanked ? userVotes.find(v => v.option_id === opt.id) : null;
                    const isMine = isRanked ? !!mine : cat.user_vote?.option_id === opt.id;
                    return (
                      <div key={opt.id} className={`pv-bar${isWinner ? " winner" : ""}${isMine ? " mine" : ""}${isMine && correctId ? (isWinner ? " right" : " wrong") : ""}`}>
                        <span className="pv-bar-fill" style={{ width: `${splitHidden ? 0 : pct}%` }} />
                        <span className="pv-bar-label">
                          {isWinner && "🏆 "}{opt.text}
                          {isMine && <span className="pv-bar-you">{isRanked ? `your #${mine.rank}` : "your pick"}{correctId ? (isWinner ? " ✓" : " ✗") : ""}</span>}
                        </span>
                        {!splitHidden && <span className="pv-bar-count">{count} · {pct}%</span>}
                      </div>
                    );
                  })}
                </div>
                {isAdmin && poll.status !== "scored" && mode !== "none" && (
                  <label className="pv-winner">
                    <span>Winner</span>
                    <select className="group-role-select" value={winners[cat.id] || ""}
                            onChange={e => {
                              const val = e.target.value ? parseInt(e.target.value) : null;
                              setWinners(prev => { const next = { ...prev }; if (val) next[cat.id] = val; else delete next[cat.id]; return next; });
                              saveWinnerForCategory(cat.id, val);
                            }}>
                      <option value="">—</option>
                      {cat.options.map(opt => <option key={opt.id} value={opt.id}>{opt.text}</option>)}
                    </select>
                    <span className={`pv-saved ${winnerSaveStatus[cat.id] || ""}`}>
                      {winnerSaveStatus[cat.id] === "saving" ? "Saving…" : winnerSaveStatus[cat.id] === "saved" ? "Saved ✓" : winnerSaveStatus[cat.id] === "error" ? "Couldn't save" : ""}
                    </span>
                  </label>
                )}
              </article>
            );
          })}
        </div>
      )}

      {tab === "leaderboard" && (
        <div className="pv-board">
          {leaderboard.length === 0 && <p className="pv-empty">No scores yet — winners are marked after voting closes.</p>}
          {leaderboard.map((entry, i) => (
            <div key={entry.user.id} className={`pv-board-row${entry.user.id === user.id ? " me" : ""}`}>
              <span className="pv-board-rank">{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `#${i + 1}`}</span>
              <Avatar user={entry.user} size={28} />
              <span className="pv-board-name">{entry.user.name}</span>
              <span className="pv-board-stats">{entry.correct}/{entry.total} correct</span>
              <span className="pv-board-kernels">{entry.kernels} 🍿</span>
            </div>
          ))}
        </div>
      )}

      {showSettings && (
        <Sheet label="Poll settings" onClose={() => setShowSettings(false)} className="share-sheet">
          <div className="share-sheet-body">
            <h2 className="ui-section-title"><span className="deco share-sheet-title">Poll settings</span></h2>
            <label className="share-label" htmlFor="ps-title">Title</label>
            <input id="ps-title" className="share-input" value={editTitle} maxLength={200} onChange={e => setEditTitle(e.target.value)} />
            <label className="share-label" htmlFor="ps-desc">Description</label>
            <textarea id="ps-desc" className="share-input" rows={3} value={editDesc} onChange={e => setEditDesc(e.target.value)} placeholder="Optional" />
            <span className="share-label">Type</span>
            <Segmented label="Type" options={[{ status: "standard", label: "Opinion" }, { status: "prediction", label: "Prediction" }]}
                       value={editType} onChange={v => v && setEditType(v)} />
            <span className="share-label">Scoring</span>
            <select className="share-input" value={editScoring} onChange={e => setEditScoring(e.target.value)}>
              {Object.entries(SCORING_LABELS).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <div className="share-sheet-foot">
              <button className="btn btn-ghost pv-danger" onClick={handleDeletePoll}>Delete poll</button>
              <button className="btn" onClick={() => setShowSettings(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSaveSettings} disabled={savingSettings || !editTitle.trim()}>
                {savingSettings ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </Sheet>
      )}
    </div>
  );
}

import { useState, useEffect, useRef } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { changed, getJson, send } from "../api";
import PageHeader from "../ui/PageHeader";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import { Segmented } from "../ui/TicketRow";
import { PollDiscord } from "../ui/DiscordShare";
import { dayDateAt } from "../dates";
import { SCORING_LABELS, TYPE_LABELS, REVEAL_LABELS, POLL_STATUS as STATUS, untilText } from "../components/PollList";
import "./Polls.css";

const LAYOUTS = [{ status: "one", label: "One at a time" }, { status: "all", label: "All" }];
const LAYOUT_KEY = "cinemaclub_ballot_layout";
const ORDINAL = n => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : { 1: "st", 2: "nd", 3: "rd" }[n % 10] || "th"}`;
const signed = n => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;

// One category's choices: single pick (± confidence) or ranked top 3. Options
// linked to a film show its poster (AI drafts link them). A live poll's
// decided category is locked: its answer, and how your pick did.
function Choices({ cat, mode, vote, onPick, onRank, onConfidence, status }) {
  const ranked = vote?.ranked || [];
  if (cat.locked) {
    const answer = cat.options.find(o => o.id === cat.correct_option_id);
    return (
      <div className="pv-choices">
        <p className="pv-locked">🔒 The answer's in: <strong>🏆 {answer?.text}</strong>
          {cat.your_kernels !== undefined ? <> · you {cat.your_kernels > 0 ? "got it" : "missed it"} ({signed(cat.your_kernels)} 🍿)</>
                                           : <> · no pick from you</>}
        </p>
      </div>
    );
  }
  return (
    <div className="pv-choices">
      {mode === "ranked" && <p className="ui-hint">Pick up to 3, in order. Tap again to remove.</p>}
      {cat.options.map(opt => {
        const rank = mode === "ranked" ? ranked.indexOf(opt.id) + 1 : 0;
        const on = mode === "ranked" ? rank > 0 : vote?.option_id === opt.id;
        const extra = opt.extra || {};
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
      {mode === "confidence" && vote?.option_id && (
        <p className="ui-hint pv-stake">Right: +{vote.confidence || 1} 🍿 · Wrong: −{vote.confidence || 1} 🍿</p>
      )}
      <span className={`pv-saved ${status || ""}`} aria-live="polite">
        {status === "saving" ? "Saving…" : status === "saved" ? "Saved ✓" : status === "error" ? "Couldn't save — tap again" : ""}
      </span>
    </div>
  );
}

// The ballot (R6a): progress, one category at a time or all at once (your
// choice, remembered), results with bars and answers, and the leaderboard.
// Answers reach members all at once when the poll's finalized, or — a live
// poll — each as it's set. Organizers and admins get one Manage panel:
// voting, answers, finalizing, editing, Discord.
export default function PollDetailPage({ user, apiBase }) {
  const { pollId } = useParams();
  const navigate = useNavigate();
  const [poll, setPoll] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("vote"); // 'vote' | 'results' | 'leaderboard'
  const [leaderboard, setLeaderboard] = useState([]);
  const [isAdmin, setIsAdmin] = useState(false);       // can run this poll: organizer or admin (R5c)
  const [readOnly, setReadOnly] = useState(false);     // read-only members see polls but don't vote

  // Vote state: { [categoryId]: { option_id, confidence } | { ranked: [optionId] } }
  const [votes, setVotes] = useState({});
  // Per-category save status: { [categoryId]: 'saving' | 'saved' | 'error' }
  const [saveStatus, setSaveStatus] = useState({});

  // Answers organizers have saved: { [categoryId]: optionId }
  const [winners, setWinners] = useState({});
  const [winnerSaveStatus, setWinnerSaveStatus] = useState({});
  const [scoring, setScoring] = useState(false);
  const [manageError, setManageError] = useState("");

  useEffect(() => {
    fetchPoll();
  }, [pollId]);

  // Live refresh while voting's open or answers are coming in.
  useEffect(() => {
    if (!poll || poll.status === "scored") return;
    const interval = setInterval(fetchPollQuiet, 10000);
    return () => clearInterval(interval);
  }, [poll?.status, pollId]);

  const savedAnswers = data => Object.fromEntries((data.categories || []).filter(c => c.saved_answer).map(c => [c.id, c.saved_answer]));

  async function fetchPoll() {
    setLoading(true);
    try {
      const data = await getJson(`${apiBase}/api/polls/${pollId}`, { cache: false });
      setPoll(data);

      const groups = await getJson(`${apiBase}/api/groups`).catch(() => null);
      if (groups) {
        const g = groups.find(g => g.id === data.group_id);
        setIsAdmin(["admin", "organizer"].includes(g?.role));
        setReadOnly(g?.role === "viewer");
      }

      // Your picks so far.
      const existingVotes = {};
      let hasVoted = false;
      for (const cat of data.categories || []) {
        if (cat.user_votes && cat.user_votes.length > 0) {
          existingVotes[cat.id] = { ranked: cat.user_votes.map(v => v.option_id) };
          hasVoted = true;
        } else if (cat.user_vote) {
          existingVotes[cat.id] = { option_id: cat.user_vote.option_id, confidence: cat.user_vote.confidence || 1 };
          hasVoted = true;
        }
      }
      setVotes(existingVotes);
      if (hasVoted || data.status !== "open") setTab("results");
      setWinners(savedAnswers(data));
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }

  async function fetchPollQuiet() {
    // Refresh without resetting your ballot (live answers, the vote split, another organizer's answers).
    try {
      const data = await getJson(`${apiBase}/api/polls/${pollId}`, { cache: false });
      setPoll(data);
      setWinners(prev => {
        const next = savedAnswers(data);
        for (const [id, s] of Object.entries(winnerSaveStatus)) if (s === "saving" && prev[id]) next[id] = prev[id];
        return next;
      });
    } catch { /* ignore */ }
  }

  async function fetchLeaderboard() {
    // Organizers can preview an all-at-once poll's standings before they finalize.
    const preview = isAdmin && poll && poll.reveal !== "live" && poll.status !== "scored" ? "?preview=1" : "";
    try {
      setLeaderboard(await getJson(`${apiBase}/api/polls/${pollId}/leaderboard${preview}`, { cache: false }));
    } catch { /* ignore */ }
  }

  useEffect(() => {
    if (tab !== "leaderboard") return;
    fetchLeaderboard();
    const interval = setInterval(fetchLeaderboard, 10000);
    return () => clearInterval(interval);
  }, [tab, pollId, isAdmin, poll?.status]);

  // Debounce timer ref for the confidence slider
  const confidenceTimerRef = useRef({});

  // Read-only members land on Results (voting is for members and up).
  useEffect(() => { if (readOnly && tab === "vote") setTab("results"); }, [readOnly, tab]);

  async function saveVoteForCategory(catId, voteData) {
    if (readOnly) return;
    setSaveStatus(prev => ({ ...prev, [catId]: "saving" }));
    const voteList = [];
    if (poll.scoring_mode === "ranked") {
      (voteData.ranked || []).forEach((optId, idx) => voteList.push({ category_id: catId, option_id: optId, rank: idx + 1 }));
    } else if (voteData.option_id) {
      voteList.push({ category_id: catId, option_id: voteData.option_id, confidence: voteData.confidence || 1 });
    }
    // Removing every ranked pick clears the category.
    const clear = voteList.length === 0 && poll.scoring_mode === "ranked" ? [catId] : [];
    if (voteList.length === 0 && !clear.length) {
      setSaveStatus(prev => ({ ...prev, [catId]: undefined }));
      return;
    }
    try {
      await send(`${apiBase}/api/polls/${pollId}/vote`, "POST", { votes: voteList, clear });
      setSaveStatus(prev => ({ ...prev, [catId]: "saved" }));
      fetchPollQuiet();   // your pick unlocks this category's vote split
    } catch (e) {
      setSaveStatus(prev => ({ ...prev, [catId]: "error" }));
      if (e.data?.code === "closed") fetchPoll();      // the deadline passed while you were picking
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
      if (idx !== -1) ranked.splice(idx, 1);
      else if (ranked.length < 3) ranked.push(optId);
      const newVote = { ranked };
      saveVoteForCategory(catId, newVote);
      return { ...prev, [catId]: newVote };
    });
  }

  function setConfidence(catId, val) {
    const confidence = Math.max(1, Math.min(10, parseInt(val) || 1));
    setVotes(prev => ({ ...prev, [catId]: { ...prev[catId], confidence } }));
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
    setWinnerSaveStatus(prev => ({ ...prev, [catId]: "saving" }));
    try {
      await send(`${apiBase}/api/polls/${pollId}/categories/${catId}/winner`, "PUT", { option_id: optionId || null });
      setWinnerSaveStatus(prev => ({ ...prev, [catId]: "saved" }));
      fetchPollQuiet();   // a live poll shows it (and locks it) right away
    } catch {
      setWinnerSaveStatus(prev => ({ ...prev, [catId]: "error" }));
    }
  }

  async function manage(fn) {
    setManageError("");
    try { await fn(); fetchPoll(); } catch (e) { setManageError(e.data?.error || "That didn't work — try again."); }
  }

  async function handleFinalize() {
    const answered = Object.keys(winners).length;
    const missing = (poll.categories || []).length - answered;
    const note = missing > 0 ? ` ${missing} ${missing === 1 ? "category has" : "categories have"} no answer and won't count.` : "";
    if (!window.confirm(`Finalize the results? Kernels go to members' totals and everyone who voted gets their result in the bell.${note}`)) return;
    setScoring(true);
    await manage(async () => { await send(`${apiBase}/api/polls/${pollId}/score`, "POST", {}); setTab("results"); changed("kernels"); });
    setScoring(false);
  }

  const handleEditAnswers = () => {
    if (!window.confirm("Edit the answers? Results are hidden again and the kernels come off members' totals until you finalize again.")) return;
    manage(() => send(`${apiBase}/api/polls/${pollId}`, "PUT", { status: "closed" }).then(d => { changed("kernels"); return d; }));
  };
  const handleReopenVoting = () => {
    if (!window.confirm("Reopen voting? Members can change their picks.")) return;
    manage(() => send(`${apiBase}/api/polls/${pollId}`, "PUT", { status: "open" }));
  };
  const handleClosePoll = () => manage(() => send(`${apiBase}/api/polls/${pollId}`, "PUT", { status: "closed" }));

  const [layout, setLayout] = useState(() => {
    try { const v = localStorage.getItem(LAYOUT_KEY); if (v === "one" || v === "all") return v; } catch { /* private mode */ }
    return window.innerWidth < 768 ? "one" : "all";
  });
  const [current, setCurrent] = useState(0);
  const chooseLayout = v => { if (!v) return; setLayout(v); try { localStorage.setItem(LAYOUT_KEY, v); } catch { /* private mode */ } };

  if (loading) return null;
  if (!poll) { navigate("/play#polls"); return null; }

  const cats = poll.categories || [];
  const mode = poll.scoring_mode;
  const live = poll.reveal === "live" && mode !== "none";
  const isPicked = c => (mode === "ranked" ? votes[c.id]?.ranked?.length > 0 : !!votes[c.id]?.option_id);
  const isDone = c => isPicked(c) || c.locked;          // nothing left to do there
  const totalCategories = cats.length;
  const votedCategories = cats.filter(isPicked).length;
  const doneCategories = cats.filter(isDone).length;
  const idx = Math.min(current, Math.max(0, cats.length - 1));
  const nextOpen = () => {
    const after = cats.findIndex((c, i) => i > idx && !isDone(c));
    const any = after === -1 ? cats.findIndex(c => !isDone(c)) : after;
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
  const score = poll.your_score;
  const answered = Object.keys(winners).length;
  const previewing = isAdmin && !live && poll.status !== "scored";

  return (
    <div className="page polls">
      <PageHeader title={poll.title} back={{ to: "/play#polls", label: "Play" }} tour="poll"
                  meta={[{ label: STATUS[poll.status] || poll.status, gold: poll.status === "open" },
                         { label: TYPE_LABELS[poll.poll_type] || "Poll" }, { label: SCORING_LABELS[mode] },
                         ...(mode !== "none" ? [{ label: `Answers: ${REVEAL_LABELS[live ? "live" : "final"].toLowerCase()}` }] : []),
                         { label: `${totalCategories} ${totalCategories === 1 ? "category" : "categories"}` }]} />
      {poll.description && <p className="pv-desc">{poll.description}</p>}
      {poll.status === "open" && poll.closes_at && (
        <p className="pv-closes">⏰ Voting closes {dayDateAt(poll.closes_at)} — {untilText(poll.closes_at)}</p>
      )}
      {readOnly && poll.status === "open" && <p className="ui-hint">You're read-only in this club: you can follow the poll and its results, but not vote.</p>}

      {isAdmin && (
        <section className="pv-manage" aria-label="Manage this poll">
          <div className="pv-manage-row">
            <span className="pv-label">Manage</span>
            {poll.status === "open" && <button className="btn btn-sm" onClick={handleClosePoll}>Close voting</button>}
            {poll.status === "closed" && <button className="btn btn-sm" onClick={handleReopenVoting}>Reopen voting</button>}
            {poll.status === "scored" && <button className="btn btn-sm" onClick={handleEditAnswers}>Edit answers</button>}
            {poll.status !== "scored" && mode !== "none" && (
              <button className="btn btn-sm btn-primary" onClick={handleFinalize} disabled={scoring || answered === 0}
                      title={answered === 0 ? "Set the answers on the Results tab first" : undefined}>
                {scoring ? "Finalizing…" : "🏆 Finalize results"}
              </button>
            )}
            <Link className="btn btn-sm btn-ghost" to={`/polls/${poll.id}/edit`}>Edit poll</Link>
          </div>
          {poll.status !== "scored" && mode !== "none" && (
            <p className="ui-hint">
              {live ? `Set each answer on the Results tab as it's announced (${answered} of ${totalCategories} so far): members see it right away and that category stops taking votes. Finalize at the end to add the kernels to everyone's totals.`
                    : `Set each answer on the Results tab (${answered} of ${totalCategories} so far). Members see the answers and standings when you finalize.`}
            </p>
          )}
          {manageError && <p className="share-error">{manageError}</p>}
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
            <span className="pv-progress-bar"><span style={{ width: `${totalCategories ? (doneCategories / totalCategories) * 100 : 0}%` }} /></span>
            <span className="pv-progress-text">
              {doneCategories === totalCategories ? "All picked ✓ — change anything until voting closes" : `${votedCategories} of ${totalCategories} picked · saves as you go`}
              {live && poll.decided > 0 ? ` · ${poll.decided} answered` : ""}
            </span>
          </div>

          {layout === "one" ? (
            <>
              <div className="pv-jump" role="tablist" aria-label="Categories">
                {cats.map((c, i) => (
                  <button key={c.id} type="button" role="tab" aria-selected={i === idx} title={c.title}
                          className={`pv-jump-dot${i === idx ? " current" : ""}${isDone(c) ? " done" : ""}`} onClick={() => setCurrent(i)}>
                    {c.locked ? "🔒" : i + 1}
                  </button>
                ))}
              </div>
              {cats[idx] && (
                <article className="pv-cat one">
                  <h2 className="pv-cat-title"><span>{idx + 1} / {cats.length}</span>{cats[idx].title}</h2>
                  {choicesFor(cats[idx])}
                  <div className="pv-step">
                    <button className="btn" disabled={idx === 0} onClick={() => setCurrent(idx - 1)}>‹ Back</button>
                    <button className="btn btn-primary" disabled={cats.every(isDone) && idx === cats.length - 1} onClick={nextOpen}>
                      {cats.every(isDone) ? "Next ›" : "Next unpicked ›"}
                    </button>
                  </div>
                </article>
              )}
            </>
          ) : (
            cats.map((c, i) => (
              <article key={c.id} className={`pv-cat${isDone(c) ? " done" : ""}`}>
                <h2 className="pv-cat-title"><span>{i + 1}</span>{c.title}</h2>
                {choicesFor(c)}
              </article>
            ))
          )}
        </div>
      )}

      {tab === "results" && (
        <div className="pv-results">
          {score && (
            <p className="pv-score">
              <strong>{signed(score.kernels)} 🍿</strong> · {score.correct} of {score.total} right · {ORDINAL(score.place)} of {score.of}
              {poll.status !== "scored" && <span> · so far, {poll.decided} of {totalCategories} answered</span>}
            </p>
          )}
          {mode !== "none" && poll.status !== "scored" && !isAdmin && (
            <p className="ui-hint">{live ? "Answers show here as they're set." : "Answers show here when the results are finalized."}</p>
          )}
          {cats.map((cat, i) => {
            const splitHidden = !cat.vote_distribution;
            const dist = cat.vote_distribution || {};
            const totalVotes = Object.values(dist).reduce((a, b) => a + b, 0);
            const userVotes = cat.user_votes || [];
            const correctId = cat.correct_option_id;
            const isRanked = mode === "ranked";
            return (
              <article key={cat.id} className="pv-cat">
                <h2 className="pv-cat-title"><span>{i + 1}</span>{cat.title}{cat.locked && <span className="pv-cat-locked">🔒 answered</span>}</h2>
                {splitHidden && <p className="ui-hint">Pick yours to see how everyone voted.</p>}
                <div className="pv-bars">
                  {cat.options.map(opt => {
                    const count = dist[opt.id] || 0;
                    const pct = totalVotes > 0 ? Math.round((count / totalVotes) * 100) : 0;
                    const isWinner = correctId === opt.id;
                    const mine = isRanked ? userVotes.find(v => v.option_id === opt.id) : null;
                    const isMine = isRanked ? !!mine : cat.user_vote?.option_id === opt.id;
                    const earned = isMine && correctId && cat.your_kernels !== undefined && (isWinner || !isRanked) ? ` ${signed(cat.your_kernels)} 🍿` : "";
                    return (
                      <div key={opt.id} className={`pv-bar${isWinner ? " winner" : ""}${isMine ? " mine" : ""}${isMine && correctId ? (isWinner ? " right" : " wrong") : ""}`}>
                        <span className="pv-bar-fill" style={{ width: `${splitHidden ? 0 : pct}%` }} />
                        <span className="pv-bar-label">
                          {isWinner && "🏆 "}{opt.text}
                          {isMine && <span className="pv-bar-you">{isRanked ? `your #${mine.rank}` : "your pick"}{correctId ? (isWinner ? " ✓" : " ✗") : ""}{earned}</span>}
                        </span>
                        {!splitHidden && <span className="pv-bar-count">{count} · {pct}%</span>}
                      </div>
                    );
                  })}
                </div>
                {isAdmin && poll.status !== "scored" && mode !== "none" && (
                  <label className="pv-winner">
                    <span>Answer</span>
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
                      {winnerSaveStatus[cat.id] === "saving" ? "Saving…" : winnerSaveStatus[cat.id] === "saved" ? (live ? "Saved ✓ — members see it now" : "Saved ✓") : winnerSaveStatus[cat.id] === "error" ? "Couldn't save" : ""}
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
          {previewing && leaderboard.length > 0 && (
            <p className="ui-hint">A preview from the answers you've set — members see the standings when you finalize.</p>
          )}
          {leaderboard.length === 0 && (
            <p className="pv-empty">
              {poll.status === "scored" ? "Nobody picked in the answered categories." : live ? "Standings appear as answers come in." : "Standings appear when the results are finalized."}
            </p>
          )}
          {leaderboard.map((entry, i) => (
            <div key={entry.user.id} className={`pv-board-row${entry.user.id === user.id ? " me" : ""}`}>
              <span className="pv-board-rank">{i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `#${i + 1}`}</span>
              <Avatar user={entry.user} size={28} link />
              <PersonLink user={entry.user} className="pv-board-name" />
              <span className="pv-board-stats">{entry.correct} of {entry.total} right</span>
              <span className="pv-board-kernels">{signed(entry.kernels)} 🍿</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

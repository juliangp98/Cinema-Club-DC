import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useJson } from "../api";
import "../pages/Polls.css";

export const SCORING_LABELS = {
  none: "Plain vote",
  single: "1 🍿 per correct pick",
  ranked: "Ranked top 3",
  confidence: "Confidence × 🍿",
};
export const TYPE_LABELS = { standard: "Opinion", prediction: "Prediction" };
export const POLL_STATUS = { open: "Open", closed: "Voting closed", scored: "Results in" };
const PAST_SHOWN = 3;

// The club's polls on Play (R15 — they used to have their own page): open ones
// as cards with your progress, then the latest past ones, the rest a tap away.
export default function PollList({ apiBase, groupId, canRun }) {
  const navigate = useNavigate();
  const { data: polls, error } = useJson(groupId ? `${apiBase}/api/groups/${groupId}/polls` : null);
  const [allPast, setAllPast] = useState(false);
  if (error) return <p className="pv-empty">Couldn't load polls right now.</p>;
  if (!polls) return <p className="pv-empty">Loading…</p>;

  const open = polls.filter(p => p.status === "open");
  const past = polls.filter(p => p.status !== "open");
  const shownPast = allPast ? past : past.slice(0, PAST_SHOWN);
  const card = p => <PollCard key={p.id} poll={p} onOpen={() => navigate(`/polls/${p.id}`)} />;
  return (
    <>
      {open.length === 0 ? (
        <p className="pv-empty">No open polls.{canRun && <> <Link to="/polls/new">Start one →</Link></>}</p>
      ) : <div className="pv-cards">{open.map(card)}</div>}
      {past.length > 0 && (
        <>
          <h3 className="pv-past-title">Past polls</h3>
          <div className="pv-cards">{shownPast.map(card)}</div>
          {past.length > PAST_SHOWN && (
            <button type="button" className="btn btn-sm" aria-expanded={allPast} onClick={() => setAllPast(v => !v)}>
              {allPast ? "Show fewer" : `Show all ${past.length} past polls`}
            </button>
          )}
        </>
      )}
    </>
  );
}

function PollCard({ poll: p, onOpen }) {
  const total = p.category_count || 0;
  const picked = Math.min(p.you_picked || 0, total);
  const open = p.status === "open";
  const action = !open ? (p.status === "scored" ? "See results" : "See votes") : picked === 0 ? "Vote" : picked < total ? "Continue" : "Change picks";
  return (
    <article className={`pv-card status-${p.status}`}>
      <button type="button" className="pv-card-main" onClick={onOpen}>
        <span className={`ui-badge ${{ open: "go", scored: "gold" }[p.status] || ""}`}>{POLL_STATUS[p.status] || p.status}</span>
        <span className="pv-card-title">{p.title}</span>
        <span className="pv-card-meta">
          {TYPE_LABELS[p.poll_type] || "Poll"} · {SCORING_LABELS[p.scoring_mode]} · {total} {total === 1 ? "category" : "categories"}
          {" · "}{p.voters || 0} voted
        </span>
        {open && total > 0 && (
          <span className="pv-progress" aria-label={`You've picked ${picked} of ${total}`}>
            <span className="pv-progress-bar"><span style={{ width: `${(picked / total) * 100}%` }} /></span>
            <span className="pv-progress-text">{picked === total ? "All picked ✓" : `${picked} of ${total} picked`}</span>
          </span>
        )}
      </button>
      <button type="button" className={`btn btn-sm${open && picked < total ? " btn-primary" : ""}`} onClick={onOpen}>{action}</button>
    </article>
  );
}

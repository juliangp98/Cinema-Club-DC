import { useState, useEffect } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import { useShell } from "../shell/AppShell";
import "./Polls.css";

export const SCORING_LABELS = {
  none: "Plain vote",
  single: "1 🍿 per correct pick",
  ranked: "Ranked top 3",
  confidence: "Confidence × 🍿",
};
export const TYPE_LABELS = { standard: "Opinion", prediction: "Prediction" };
const STATUS = { open: "Open", closed: "Voting closed", scored: "Results in" };

// The club's polls (R6a): open ones first as cards with your progress, then
// closed and scored ones. Organizers and admins start new ones from here.
export default function PollsPage({ apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const shell = useShell();
  const [polls, setPolls] = useState(null);
  const [failed, setFailed] = useState(false);
  const canRun = ["organizer", "admin"].includes(shell?.role);

  useEffect(() => {
    if (!activeGroupId) return;
    fetch(`${apiBase}/api/groups/${activeGroupId}/polls`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setPolls)
      .catch(() => setFailed(true));
  }, [apiBase, activeGroupId]);

  if (!activeGroupId) {
    return (
      <div className="page narrow">
        <PageHeader title="Polls" />
        <p className="pv-empty">Polls belong to a club. <Link to="/groups">Find a club →</Link></p>
      </div>
    );
  }

  const open = (polls || []).filter(p => p.status === "open");
  const past = (polls || []).filter(p => p.status !== "open");

  return (
    <div className="page narrow polls">
      <PageHeader title="Polls" subtitle={shell?.group ? `${shell.group.name}'s predictions and votes` : undefined}
                  actions={canRun && <Link className="btn btn-primary" to="/polls/new">＋ New poll</Link>} />

      {failed && <p className="pv-empty">Couldn't load polls right now.</p>}
      {!polls && !failed && <p className="pv-empty">Loading…</p>}

      {polls && (
        <>
          <SectionTitle>Open</SectionTitle>
          {open.length === 0 ? (
            <p className="pv-empty">No open polls.{canRun && <> <Link to="/polls/new">Start one →</Link></>}</p>
          ) : (
            <div className="pv-cards">{open.map(p => <PollCard key={p.id} poll={p} onOpen={() => navigate(`/polls/${p.id}`)} />)}</div>
          )}
          {past.length > 0 && (
            <>
              <SectionTitle>Past</SectionTitle>
              <div className="pv-cards">{past.map(p => <PollCard key={p.id} poll={p} onOpen={() => navigate(`/polls/${p.id}`)} />)}</div>
            </>
          )}
        </>
      )}
    </div>
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
        <span className={`pv-status ${p.status}`}>{STATUS[p.status] || p.status}</span>
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

import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Feed from "./Feed";
import { useJson } from "../api";
import TriviaCard from "../ui/TriviaCard";
import BingoCard from "../ui/BingoCard";
import { useShell } from "../shell/AppShell";

// The club feed as its own page (R10c): everything the club did, one kind
// at a time if you like, with what's new since you last looked, the open
// polls up top (Polls' phone tab went to the Feed), today's trivia when the
// club has it on (R10d), and Monday recaps.

const FILTERS = [[null, "All"], ["screenings", "Screenings"], ["watchlists", "Watchlists"], ["polls", "Polls"],
                 ["kernels", "Kernels"], ["games", "Games"], ["recaps", "Weekly recaps"]];

function OpenPolls({ apiBase, groupId }) {
  const { data } = useJson(`${apiBase}/api/club/week?group_id=${groupId}`);
  const polls = data?.polls || [];
  if (!polls.length) return null;
  const toVote = polls.filter(p => !p.you_voted).length;
  return (
    <section className="feed-polls" aria-label="Open polls">
      <div className="feed-polls-head">
        <strong>🗳️ Open polls</strong>
        {toVote > 0 && <span className="feed-polls-nudge">{toVote} waiting for your vote</span>}
        <Link to="/polls" className="feed-polls-all">All polls →</Link>
      </div>
      <ul className="feed-polls-list">
        {polls.map(p => (
          <li key={p.id}>
            <Link to={`/polls/${p.id}`}>{p.title}</Link>
            {p.you_voted ? <span className="chip">✓ Voted</span>
              : <Link to={`/polls/${p.id}`} className="chip gold" aria-label={`Vote in ${p.title}`}>Vote</Link>}
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function FeedPage({ user, apiBase, groupId }) {
  const [params, setParams] = useSearchParams();
  const { role } = useShell() || {};
  const type = FILTERS.some(([k]) => k === params.get("type")) ? params.get("type") : null;

  if (!groupId) {
    return (
      <div className="page">
        <PageHeader title="Club feed" />
        <p className="pv-empty">The feed shows what your club is up to. <Link to="/groups">Find or start a club</Link> to see it.</p>
      </div>
    );
  }
  return (
    <div className="page feed-full">
      <PageHeader title="Club feed" />
      <OpenPolls apiBase={apiBase} groupId={groupId} />
      <TriviaCard apiBase={apiBase} groupId={groupId} role={role} />
      <BingoCard apiBase={apiBase} groupId={groupId} role={role} />
      <div className="feed-filters" role="group" aria-label="Show">
        {FILTERS.map(([k, label]) => (
          <button key={label} type="button" className={`chip filter-choice${type === k ? " gold" : ""}`} aria-pressed={type === k}
                  onClick={() => setParams(k ? { type: k } : {}, { replace: true })}>
            {label}
          </button>
        ))}
      </div>
      <Feed key={`${groupId}:${type || "all"}`} user={user} apiBase={apiBase} groupId={groupId} filter={type}
            divider={!type} endless />
    </div>
  );
}

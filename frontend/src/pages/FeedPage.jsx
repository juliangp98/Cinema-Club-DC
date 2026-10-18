import { Link, useSearchParams } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import Feed from "./Feed";
import { useJson } from "../api";
import ToggleChip from "../ui/ToggleChip";
import { GamesRail, GamesStrip } from "../ui/GamesSummary";

// The club feed as its own page (R10c): everything the club did, one kind
// at a time if you like, with what's new since you last looked, and Monday
// recaps. The games live on the Play page; here they're a side rail on wide
// screens and one row of chips on phones (R10 Play), so the feed starts at
// the top.

const FILTERS = [[null, "All"], ["screenings", "Screenings"], ["watchlists", "Watchlists"], ["polls", "Polls"],
                 ["kernels", "Kernels"], ["games", "Games"], ["recaps", "Weekly recaps"]];

export default function FeedPage({ user, apiBase, groupId }) {
  const [params, setParams] = useSearchParams();
  const type = FILTERS.some(([k]) => k === params.get("type")) ? params.get("type") : null;
  const { data: summary } = useJson(groupId ? `${apiBase}/api/play?group_id=${groupId}` : null);

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
      <PageHeader title="Club feed" tour="feed" />
      <GamesStrip summary={summary} className="feed-strip" />
      <div className="feed-layout">
        <div className="feed-col">
          <div className="feed-filters" id="feed-filters" role="group" aria-label="Show">
            {FILTERS.map(([k, label]) => (
              <ToggleChip key={label} on={type === k} onClick={() => setParams(k ? { type: k } : {}, { replace: true })}>
                {label}
              </ToggleChip>
            ))}
          </div>
          <Feed key={`${groupId}:${type || "all"}`} user={user} apiBase={apiBase} groupId={groupId} filter={type}
                divider={!type} endless />
        </div>
        <aside className="games-rail" aria-label="Games">
          <GamesRail summary={summary} />
        </aside>
      </div>
    </div>
  );
}

import { Link } from "react-router-dom";
import Panel from "../ui/Panel";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import TheatreLink from "../ui/TheatreLink";

// The Club Overview's side column (R15): who's in the club and the month's
// numbers (club_stats.overview).

const STRIP = 12;

export function MembersStrip({ members, onAll }) {
  if (!members?.length) return null;
  return (
    <Panel as="div" tone="tile" title={`Members · ${members.length}`} kicker
           aside={<button type="button" className="ui-section-link" onClick={onAll}>All →</button>}>
      <div className="club-strip-faces">
        {members.slice(0, STRIP).map(m => <Avatar key={m.user.id} user={m.user} size={34} link />)}
        {members.length > STRIP && <button type="button" className="club-strip-more" onClick={onAll}>+{members.length - STRIP}</button>}
      </div>
    </Panel>
  );
}

export function ClubStats({ stats, onBoard }) {
  if (!stats) return null;
  const { month_label: month, member_screenings: seen, screenings_together: together, most_wanted: wanted,
          busiest_theatre: busiest, top } = stats;
  return (
    <Panel as="div" tone="tile" title={`${month} in the club`} kicker className="club-stats">
      <ul className="rail-list">
        <li>🎟️ {seen} screening{seen === 1 ? "" : "s"}{together > 0 && ` · ${together} together`}</li>
        {wanted && (
          <li>🎯 Most wanted: <Link to={`/films/${wanted.movie.id}`}>{wanted.movie.title}</Link>
            <span className="ui-hint"> · {wanted.wanters} want it</span></li>
        )}
        {busiest && <li>🏛️ Busiest: <TheatreLink theatre={busiest.theatre} short /><span className="ui-hint"> · {busiest.screenings}</span></li>}
      </ul>
      {top.length > 0 && (
        <ol className="club-stats-top" aria-label={`Top in ${month}`}>
          {top.map((t, i) => (
            <li key={t.user.id}>{["🥇", "🥈", "🥉"][i]} <PersonLink user={t.user} /> <span className="ui-hint">🍿 {t.kernels}</span></li>
          ))}
        </ol>
      )}
      <button type="button" className="ui-section-link" onClick={onBoard}>Leaderboard →</button>
    </Panel>
  );
}

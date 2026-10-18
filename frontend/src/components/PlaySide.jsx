import { Link } from "react-router-dom";
import Panel from "../ui/Panel";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import { KernelBar } from "./ClubBoard";
import { SkippedPosts, useGamePosts } from "./GamePostsWaiting";
import { kernelParts } from "../kernels";

// Play's side column (R15, layout A): your kernels, this month's standings
// (top five and you), this week's movers — and, for organizers and admins,
// the games they run. On phones a strip of your numbers sits on top instead.

const rankOf = (rows, id) => (rows ? rows.findIndex(r => r.user.id === id) : -1);
// Trivia's kernels by difficulty (R15): "+1 easy · +2 medium · +3 hard".
const byLevel = t => ["easy", "medium", "hard"].filter(k => k in t).map(k => `+${t[k]} ${k}`).join(" · ");

function earnList(r) {
  return [
    `Check in after a screening: +${r.went} (+${r.planned} more if you'd said you were going)`,
    `Be first going to a screening: +1 for each member who joins (up to ${r.trailblazer_max})`,
    `Crew night — ${r.crew_min}+ members check in to the same screening: +${r.crew} each`,
    "Right picks in scored polls",
    r.trivia && `Trivia question of the day: ${byLevel(r.trivia)} for a right answer`,
    r.trivia_anytime && `Anytime trivia: ${byLevel(r.trivia_anytime.each)} each, up to ${r.trivia_anytime.per_day} a day`,
    ...(r.games || []).map(g => `${g.label}: ${g.by_step ? "3, 2 or 1 by how much you needed to see" : `+${g.each} a right call`}, up to ${g.per_day} a day`),
    r.bingo && `Repertory bingo: +${r.bingo.line} for a line, +${r.bingo.full} for the full card`,
    `Members can give you kernels for what you do (up to ${r.give} a week each), or take a few back`,
  ].filter(Boolean);
}

export function YourKernels({ k, month, viewerId }) {
  if (!k) return null;
  const i = rankOf(month, viewerId);
  const mine = month?.[i];
  return (
    <Panel as="div" tone="tile" title="Your kernels" kicker id="kernels">
      <span className="rail-big">🍿 {k.kernels}</span>
      <KernelBar breakdown={k} total={k.kernels} most={k.kernels} />
      <span className="ui-hint">{kernelParts(k)}</span>
      {mine && <span className="ui-hint">This month: 🍿 {mine.kernels} · #{mine.place} in the club</span>}
      <span className="ui-hint">This week: {k.allowance.give_left} to give · {k.allowance.take_left} to take (on the feed's 🍿 Kernels buttons)</span>
      <details className="play-earn">
        <summary>How to earn kernels</summary>
        <ul>{earnList(k.rules).map(e => <li key={e}>{e}</li>)}</ul>
      </details>
    </Panel>
  );
}

function BoardRow({ row, place, viewerId, value }) {
  return (
    <li className={row.user.id === viewerId ? "me" : ""}>
      <span className="club-rank">{place}</span>
      <Avatar user={row.user} size={26} link />
      <PersonLink user={row.user} className="play-board-name" />
      <strong>{value}</strong>
    </li>
  );
}

export function MonthBoard({ month, viewerId }) {
  if (!month?.length) return null;
  const i = rankOf(month, viewerId);
  return (
    <Panel as="div" tone="tile" title="This month" kicker>
      <ol className="play-board">
        {month.slice(0, 5).map(row => <BoardRow key={row.user.id} row={row} place={row.place} viewerId={viewerId} value={`🍿 ${row.kernels}`} />)}
        {i >= 5 && <><li className="play-board-gap" aria-hidden="true">⋯</li>
          <BoardRow row={month[i]} place={month[i].place} viewerId={viewerId} value={`🍿 ${month[i].kernels}`} /></>}
      </ol>
      <Link to="/club?tab=leaderboard" className="ui-section-link">Full leaderboard →</Link>
    </Panel>
  );
}

export function Movers({ week, viewerId }) {
  if (!week) return null;
  const up = week.filter(r => r.kernels > 0).slice(0, 3);
  return (
    <Panel as="div" tone="tile" title="This week's movers" kicker>
      {up.length ? (
        <ol className="play-board">
          {up.map(row => <BoardRow key={row.user.id} row={row} place={row.place} viewerId={viewerId} value={`+${row.kernels}`} />)}
        </ol>
      ) : <p className="ui-hint">No kernels yet this week — be the first.</p>}
    </Panel>
  );
}

// Phones: your numbers in one row, above the games.
export function KernelStrip({ k, month, viewerId }) {
  if (!k) return null;
  const i = rankOf(month, viewerId);
  return (
    <nav className="games-strip play-strip" aria-label="Your kernels">
      <a href="#kernels" className="chip gold">🍿 {k.kernels}</a>
      {i >= 0 && <Link to="/club?tab=leaderboard" className="chip">#{month[i].place} this month</Link>}
      <span className="chip">{k.allowance.give_left} to give</span>
    </nav>
  );
}

// For organizers and admins: what's waiting for an OK, what was skipped but
// can still go up, and where the game settings are.
export function GamesRunPanel({ apiBase, slug }) {
  const { posts, busy, act, error } = useGamePosts(apiBase, slug);
  const waiting = posts?.waiting.length || 0;
  return (
    <Panel as="div" tone="tile" title="Running the games" kicker className="play-run">
      {waiting > 0 ? (
        <Link to="/club?tab=settings#game-posts" className="chip gold">👀 {waiting} waiting for your OK →</Link>
      ) : posts && <span className="ui-hint">Nothing waiting for an OK.</span>}
      {error && <p className="share-error" role="alert">{error}</p>}
      <SkippedPosts skipped={posts?.skipped} busy={busy} act={act} />
      <span className="play-run-links">
        <Link to="/club?tab=settings#settings-games">Game switches</Link> ·{" "}
        <Link to="/club?tab=settings#settings-discord">Discord posts</Link>
      </span>
    </Panel>
  );
}

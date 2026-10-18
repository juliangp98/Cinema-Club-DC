import { Link } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import TriviaCard from "../ui/TriviaCard";
import BingoCard from "../ui/BingoCard";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import PollList from "../components/PollList";
import { kernelParts } from "../kernels";
import { useJson } from "../api";
import { useShell } from "../shell/AppShell";
import useHashScroll from "../useHashScroll";

// Play (R10): the one home for the club's games — trivia, bingo, polls (R15:
// all of them, here — /polls leads here) — and your kernels with the
// standings. The feed's rail and strip (and /play in Discord) lead here.

function Kernels({ apiBase, groupId, viewerId }) {
  const { data: k } = useJson(`${apiBase}/api/kernels?group_id=${groupId}`);
  const board = useJson(`${apiBase}/api/groups/${groupId}/leaderboard`).data?.rows;
  if (!k) return null;
  const r = k.rules;
  const earn = [
    `Check in after a screening: +${r.went} (+${r.planned} more if you'd said you were going)`,
    `Be first going to a screening: +1 for each member who joins (up to ${r.trailblazer_max})`,
    `Crew night — ${r.crew_min}+ members check in to the same screening: +${r.crew} each`,
    "Right picks in scored polls",
    r.trivia && `Trivia question of the day: +${r.trivia} for a right answer`,
    r.trivia_anytime && `Anytime trivia: +${r.trivia_anytime.each} each, up to ${r.trivia_anytime.per_day} a day`,
    r.bingo && `Repertory bingo: +${r.bingo.line} for a line, +${r.bingo.full} for the full card`,
    `Members can give you kernels for what you do (up to ${r.give} a week each), or take a few back`,
  ].filter(Boolean);
  return (
    <div className="play-kernels">
      <div className="play-kernels-total">
        <span className="rail-big">🍿 {k.kernels}</span>
        <span className="ui-hint">{kernelParts(k)}</span>
        <span className="ui-hint">This week: {k.allowance.give_left} to give · {k.allowance.take_left} to take (on the feed's 🍿 Kernels buttons)</span>
      </div>
      <details className="play-earn">
        <summary>How to earn kernels</summary>
        <ul>{earn.map(e => <li key={e}>{e}</li>)}</ul>
      </details>
      {board?.length > 0 && (
        <>
          <ol className="play-board">
            {board.slice(0, 5).map((row, i) => (
              <li key={row.user.id} className={row.user.id === viewerId ? "me" : ""}>
                <span className="club-rank">{i + 1}</span>
                <Avatar user={row.user} size={26} link />
                <PersonLink user={row.user} className="play-board-name" />
                <strong>🍿 {row.kernels}</strong>
              </li>
            ))}
          </ol>
          <p className="play-links"><Link to="/club?tab=leaderboard">Full leaderboard →</Link></p>
        </>
      )}
    </div>
  );
}

export default function PlayPage({ user, apiBase, groupId }) {
  const { role } = useShell() || {};
  const canRun = role === "organizer" || role === "admin";
  // /play#polls and friends land on that game once the page has drawn (the
  // summary — the feed rail's, so usually cached — says the games are in).
  const { data: summary } = useJson(groupId ? `${apiBase}/api/play?group_id=${groupId}` : null);
  useHashScroll(!!summary);

  if (!groupId) {
    return (
      <div className="page narrow">
        <PageHeader title="Play" />
        <p className="pv-empty">Trivia, bingo and polls happen in a club. <Link to="/groups">Find or start a club</Link> to play.</p>
      </div>
    );
  }
  return (
    <div className="page narrow play-page">
      <PageHeader title="Play" />
      <section id="trivia" className="play-section">
        <SectionTitle>Trivia</SectionTitle>
        <TriviaCard apiBase={apiBase} groupId={groupId} role={role} offNote />
      </section>
      <section id="bingo" className="play-section">
        <SectionTitle>Bingo</SectionTitle>
        <BingoCard apiBase={apiBase} groupId={groupId} role={role} offNote />
      </section>
      <section id="polls" className="play-section">
        <SectionTitle link={canRun ? { to: "/polls/new", label: "＋ New poll" } : undefined}>Polls</SectionTitle>
        <PollList apiBase={apiBase} groupId={groupId} canRun={canRun} />
      </section>
      <section id="kernels" className="play-section">
        <SectionTitle>Kernels</SectionTitle>
        <Kernels apiBase={apiBase} groupId={groupId} viewerId={user.id} />
      </section>
    </div>
  );
}

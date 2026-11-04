import { Link } from "react-router-dom";
import Panel from "./Panel";
import MiniBingo from "./MiniBingo";

// What there is to play today (R10 Play), from /api/play: the feed's side
// rail on wide screens, and one row of chips on phones (and the Club page),
// each leading to its game on the Play page. Games the club has off are left out.

// Everything waiting on you, most pressing first: invites and your turn in
// challenges and tournaments, today's trivia, polls to vote in. Each with
// where to go and the one thing to do there. Play's Today and the feed's rail.
export function waitingItems(summary) {
  if (!summary) return [];
  const { trivia, polls } = summary;
  const ch = summary.challenges;
  return [
    ...(ch?.invites || []).map(c => ({ key: `ci${c.id}`, icon: "⚔️", text: `${c.by} challenged you: ${c.game}`,
                                       to: `/challenges/${c.id}`, action: "Answer" })),
    ...(ch?.tournaments || []).map(t => ({ key: `tt${t.id}`, icon: "🏆", text: `${t.by} invited you to a tournament`,
                                           to: `/tournaments/${t.id}`, action: "Answer" })),
    ...(ch?.your_turn || []).map(c => ({ key: `ct${c.id}`, icon: "⚔️", text: `Your turn: ${c.game}`,
                                         to: `/challenges/${c.id}`, action: "Play" })),
    trivia?.to_answer && { key: "t", icon: "🧠", text: "Today's trivia question", to: "/play/trivia", action: "Answer" },
    trivia?.waiting && { key: "w", icon: "🎲", text: "Your anytime question", to: "/play/trivia", action: "Answer" },
    ...polls.filter(p => !p.you_voted).map(p => ({ key: `p${p.id}`, icon: "🗳️", text: p.title, to: `/polls/${p.id}`, action: "Vote" })),
  ].filter(Boolean);
}

export function GamesRail({ summary }) {
  if (!summary) return null;
  const { trivia, bingo, kernels } = summary;
  const todo = waitingItems(summary).slice(0, 8);
  return (
    <div className="games-rail-inner">
      <Panel as="div" tone="tile" title="To do" kicker>
        {todo.length ? <ul className="rail-list">{todo.map(t => (
          <li key={t.key}><Link to={t.to}>{t.icon} {t.action === "Vote" ? `Vote: ${t.text}` : t.text}</Link></li>
        ))}</ul>
          : <p className="ui-hint">You're all caught up{trivia?.anytime ? " — " : "."}
              {trivia?.anytime && <Link to="/play/trivia">play an anytime question</Link>}</p>}
      </Panel>
      {bingo && (
        <Panel as={Link} to="/play/bingo" tone="tile" className="rail-bingo">
          <span className="rail-bingo-text"><span className="ui-panel-title kicker">Bingo · {bingo.month_label}</span>
            <span className="rail-big">{bingo.filled}/8{bingo.full ? " 🎉🎉" : bingo.line ? " 🎉" : ""}</span></span>
          <MiniBingo cells={bingo.cells} />
        </Panel>
      )}
      <Panel as={Link} to="/play/kernels" tone="tile" title="Your kernels" kicker>
        <span className="rail-big">🍿 {kernels.kernels}</span>
        {kernels.today?.total > 0 && <span className="ui-hint rail-today">🎯 {kernels.today.total} still to earn today</span>}
        <span className="ui-hint">{kernels.allowance.give_left} to give and {kernels.allowance.take_left} to take this week</span>
      </Panel>
      <Link to="/play" className="btn btn-sm rail-play">Go to Play →</Link>
    </div>
  );
}

export function GamesStrip({ summary, className = "" }) {
  if (!summary) return null;
  const { trivia, bingo, polls, kernels } = summary;
  const toVote = polls.filter(p => !p.you_voted).length;
  const ch = summary.challenges;
  const waiting = (ch?.invites.length || 0) + (ch?.your_turn.length || 0) + (ch?.tournaments?.length || 0);
  return (
    <nav className={`games-strip ${className}`} aria-label="Games">
      {trivia && (
        <Link to="/play/trivia" className={`chip${trivia.to_answer || trivia.waiting ? " gold" : ""}`}>
          🧠 {trivia.to_answer ? "1 to answer" : trivia.waiting ? "Your question" : trivia.answered ? (trivia.correct ? "✓ Got it" : "Answered") : "Trivia"}
        </Link>
      )}
      {bingo && <Link to="/play/bingo" className="chip">🎱 {bingo.filled}/8{bingo.line ? " 🎉" : ""}</Link>}
      {polls.length > 0 && (
        <Link to="/play/polls" className={`chip${toVote ? " gold" : ""}`}>🗳️ {toVote ? `${toVote} to vote` : "Polls"}</Link>
      )}
      {waiting > 0 && <Link to="/play/challenges" className="chip gold">⚔️ {waiting} waiting</Link>}
      <Link to="/play/kernels" className="chip">🍿 {kernels.kernels}</Link>
      {kernels.today?.total > 0 && <Link to="/play/games" className="chip gold">🎯 {kernels.today.total} left today</Link>}
      <Link to="/play" className="chip">Play →</Link>
    </nav>
  );
}

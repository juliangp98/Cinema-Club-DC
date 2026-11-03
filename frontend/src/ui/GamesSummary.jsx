import { Link } from "react-router-dom";
import Panel from "./Panel";
import MiniBingo from "./MiniBingo";

// What there is to play today (R10 Play), from /api/play: the feed's side
// rail on wide screens, and one row of chips on phones (and the Club page),
// each leading to its game on the Play page. Games the club has off are left out.

export function GamesRail({ summary }) {
  if (!summary) return null;
  const { trivia, bingo, polls, kernels } = summary;
  const toVote = polls.filter(p => !p.you_voted);
  const ch = summary.challenges;
  const todo = [
    ...(ch?.invites || []).map(c => <Link key={`ci${c.id}`} to={`/challenges/${c.id}`}>⚔️ {c.by} challenged you: {c.game}</Link>),
    ...(ch?.tournaments || []).map(t => <Link key={`tt${t.id}`} to={`/tournaments/${t.id}`}>🏆 {t.by} invited you to a tournament</Link>),
    ...(ch?.your_turn || []).map(c => <Link key={`ct${c.id}`} to={`/challenges/${c.id}`}>⚔️ Your turn: {c.game}</Link>),
    trivia?.to_answer && <Link key="t" to="/play#trivia">🧠 Today's trivia question</Link>,
    trivia?.waiting && <Link key="w" to="/play#trivia">🎲 Your anytime question</Link>,
    ...toVote.slice(0, 3).map(p => <Link key={p.id} to={`/polls/${p.id}`}>🗳️ Vote: {p.title}</Link>),
  ].filter(Boolean);
  return (
    <div className="games-rail-inner">
      <Panel as="div" tone="tile" title="To do" kicker>
        {todo.length ? <ul className="rail-list">{todo.map(l => <li key={l.key}>{l}</li>)}</ul>
          : <p className="ui-hint">You're all caught up{trivia?.anytime ? " — " : "."}
              {trivia?.anytime && <Link to="/play#trivia">play an anytime question</Link>}</p>}
      </Panel>
      {bingo && (
        <Panel as={Link} to="/play#bingo" tone="tile" className="rail-bingo">
          <span className="rail-bingo-text"><span className="ui-panel-title kicker">Bingo · {bingo.month_label}</span>
            <span className="rail-big">{bingo.filled}/8{bingo.full ? " 🎉🎉" : bingo.line ? " 🎉" : ""}</span></span>
          <MiniBingo cells={bingo.cells} />
        </Panel>
      )}
      <Panel as={Link} to="/play#kernels" tone="tile" title="Your kernels" kicker>
        <span className="rail-big">🍿 {kernels.kernels}</span>
        {kernels.today?.total > 0 && <span className="ui-hint rail-today">🎯 {kernels.today.total} still to earn today</span>}
        <span className="ui-hint">{kernels.allowance.give_left} to give · {kernels.allowance.take_left} to take this week</span>
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
        <Link to="/play#trivia" className={`chip${trivia.to_answer || trivia.waiting ? " gold" : ""}`}>
          🧠 {trivia.to_answer ? "1 to answer" : trivia.waiting ? "Your question" : trivia.answered ? (trivia.correct ? "✓ Got it" : "Answered") : "Trivia"}
        </Link>
      )}
      {bingo && <Link to="/play#bingo" className="chip">🎱 {bingo.filled}/8{bingo.line ? " 🎉" : ""}</Link>}
      {polls.length > 0 && (
        <Link to="/play#polls" className={`chip${toVote ? " gold" : ""}`}>🗳️ {toVote ? `${toVote} to vote` : "Polls"}</Link>
      )}
      {waiting > 0 && <Link to="/play#challenges" className="chip gold">⚔️ {waiting} waiting</Link>}
      <Link to="/play#kernels" className="chip">🍿 {kernels.kernels}</Link>
      {kernels.today?.total > 0 && <Link to="/play#games" className="chip gold">🎯 {kernels.today.total} left today</Link>}
      <Link to="/play" className="chip">Play →</Link>
    </nav>
  );
}

import { Link } from "react-router-dom";

// What there is to play today (R10 Play), from /api/play: the feed's side
// rail on wide screens, and one row of chips on phones (and the Club page),
// each leading to its game on the Play page. Games the club has off are left out.

function MiniBingo({ cells }) {
  return (
    <span className="mini-bingo" aria-hidden="true">
      {cells.map((on, i) => <span key={i} className={on ? "on" : ""} />)}
    </span>
  );
}

export function GamesRail({ summary }) {
  if (!summary) return null;
  const { trivia, bingo, polls, kernels } = summary;
  const toVote = polls.filter(p => !p.you_voted);
  const todo = [
    trivia?.to_answer && <Link key="t" to="/play#trivia">🧠 Today's trivia question</Link>,
    trivia?.waiting && <Link key="w" to="/play#trivia">🎲 Your anytime question</Link>,
    ...toVote.slice(0, 3).map(p => <Link key={p.id} to={`/polls/${p.id}`}>🗳️ Vote: {p.title}</Link>),
  ].filter(Boolean);
  return (
    <div className="games-rail-inner">
      <div className="rail-section">
        <div className="rail-head">To do</div>
        {todo.length ? <ul className="rail-list">{todo.map(l => <li key={l.key}>{l}</li>)}</ul>
          : <p className="rail-quiet">You're all caught up{trivia?.anytime ? " — " : "."}
              {trivia?.anytime && <Link to="/play#trivia">play an anytime question</Link>}</p>}
      </div>
      {bingo && (
        <Link to="/play#bingo" className="rail-section rail-bingo">
          <span className="rail-bingo-text"><span className="rail-head">Bingo · {bingo.month_label}</span>
            <span className="rail-big">{bingo.filled}/8{bingo.full ? " 🎉🎉" : bingo.line ? " 🎉" : ""}</span></span>
          <MiniBingo cells={bingo.cells} />
        </Link>
      )}
      <Link to="/play#kernels" className="rail-section">
        <span className="rail-head">Your kernels</span>
        <span className="rail-big">🍿 {kernels.kernels}</span>
        <span className="rail-quiet">{kernels.allowance.give_left} to give · {kernels.allowance.take_left} to take this week</span>
      </Link>
      <Link to="/play" className="btn btn-sm rail-play">Go to Play →</Link>
    </div>
  );
}

export function GamesStrip({ summary, className = "" }) {
  if (!summary) return null;
  const { trivia, bingo, polls, kernels } = summary;
  const toVote = polls.filter(p => !p.you_voted).length;
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
      <Link to="/play#kernels" className="chip">🍿 {kernels.kernels}</Link>
      <Link to="/play" className="chip">Play →</Link>
    </nav>
  );
}

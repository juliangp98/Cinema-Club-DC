import { useState } from "react";
import { Link } from "react-router-dom";
import Panel from "../ui/Panel";
import Poster from "../ui/Poster";
import { send, useJson } from "../api";

// The quiz games (R15, quizzes.py): each its own switch in Club settings.
// QUIZ_GAMES mirrors quizzes.GAMES for the settings switches; Play shows the
// ones that are on, each playing in place (privately — the same rounds as
// /games in Discord).
export const QUIZ_GAMES = [
  { key: "higher_lower", label: "↕️ Higher or lower",
    hint: "A film and its year — did the next one come out before or after? +1 kernel a right call, up to 5 a day; a miss ends the run." },
  { key: "who_said", label: "🗣️ Who said it",
    hint: "A line from a film and four of its characters. +1 kernel for the right one, up to 5 a day." },
];
const LETTERS = "ABCD";

function Film({ f, hideYear }) {
  return (
    <div className="quiz-film">
      <Poster movie={{ title: f.title, poster_url: f.poster_url }} className="quiz-film-poster" />
      <span className="quiz-film-title">{f.title}</span>
      <span className="quiz-film-year">{hideYear ? "?" : f.year}</span>
    </div>
  );
}

function Result({ r }) {
  if (!r.last) return null;
  return (
    <p className="quiz-result" role="status">
      {r.last.right ? `✅ Right!${r.last.paid ? ` +${r.last.paid} 🍿` : ""}` : "❌ Not quite."}
      {r.done && r.kind === "higher_lower" && ` Streak: ${r.score}.`}
    </p>
  );
}

function HigherLower({ r, busy, onAnswer }) {
  return (
    <>
      <div className="quiz-pair">
        <Film f={r.current} />
        <span className="quiz-vs" aria-hidden="true">vs</span>
        <Film f={r.next} hideYear={!r.done} />
      </div>
      <Result r={r} />
      {!r.done && (
        <div className="quiz-answers" role="group" aria-label={`Did ${r.next.title} come out before or after ${r.current.year}?`}>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onAnswer("before")}>⬅️ Before {r.current.year}</button>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onAnswer("after")}>After {r.current.year} ➡️</button>
        </div>
      )}
      {!r.done && <p className="ui-hint">Streak: {r.score}</p>}
    </>
  );
}

function WhoSaid({ r, busy, onAnswer }) {
  return (
    <>
      <blockquote className="quiz-quote">“{r.quote}”</blockquote>
      <p className="ui-hint">Who says it in <strong>{r.film.title}</strong>{r.film.year ? ` (${r.film.year})` : ""}?</p>
      <div className="trivia-options" role="group" aria-label="Characters">
        {r.options.map((o, i) => (
          <button key={o} type="button" disabled={r.done || busy} onClick={() => onAnswer(i)}
                  className={`trivia-option${r.done && i === r.answer ? " right" : ""}`}>
            <span className="trivia-letter">{LETTERS[i]}</span> {o}
          </button>
        ))}
      </div>
      <Result r={r} />
    </>
  );
}

function Game({ g, apiBase, groupId }) {
  const [r, setR] = useState(g.round);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function call(path, body) {
    setBusy(true);
    setError(null);
    try { setR(await send(`${apiBase}/api/quizzes/${path}`, "POST", { group_id: groupId, ...body })); }
    catch (e) { setError(e.data?.error || "Couldn't do that — try again."); }
    finally { setBusy(false); }
  }
  const Round = g.kind === "higher_lower" ? HigherLower : WhoSaid;
  return (
    <Panel tone="gold" className="quiz-game" title={`${g.emoji} ${g.label}`}
           hint={`+${g.each} 🍿 a right call · ${r ? r.left_today : g.cap - g.earned_today} left today${g.best ? ` · best ${g.best}` : ""}`}
           actions={(!r || r.done) && (
             <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={() => call("start", { kind: g.kind })}>
               {r ? "🔁 Play again" : "▶ Play"}
             </button>
           )}>
      {!r && <p className="ui-hint">{g.blurb}</p>}
      {r && <Round r={r} busy={busy} onAnswer={choice => call("answer", { round_id: r.id, choice })} />}
      {error && <p className="trivia-error" role="status">{error}</p>}
    </Panel>
  );
}

export default function QuizGames({ apiBase, groupId, canRun }) {
  const { data } = useJson(groupId ? `${apiBase}/api/quizzes?group_id=${groupId}` : null);
  if (!data) return null;
  if (!data.games.length) {
    return canRun ? (
      <p className="ui-note">🎮 No quiz games are on yet. <Link to="/club?tab=settings#settings-games">Turn them on in Club settings</Link></p>
    ) : <p className="ui-note">🎮 No quiz games are on in this club yet.</p>;
  }
  return <div className="quiz-games">{data.games.map(g => <Game key={g.kind} g={g} apiBase={apiBase} groupId={groupId} />)}</div>;
}

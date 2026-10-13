import { useState } from "react";
import { Link } from "react-router-dom";
import { useJson } from "../api";

// Club trivia (R10d), only once a club admin turns it on (admins see where to
// do that; everyone else sees nothing): the question of the day, and — if the
// club allows it — anytime questions, one at a time. One try each; the
// answer shows once you've answered.
const LETTERS = "ABCD";

export default function TriviaCard({ apiBase, groupId, role }) {
  const { data, reload } = useJson(`${apiBase}/api/trivia/today?group_id=${groupId}`);
  const [shown, setShown] = useState(null);          // a question answered or asked for since loading
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  if (!data.enabled) {
    return role === "admin" ? (
      <p className="trivia-off">🧠 Movie trivia is off for the club. <Link to="/club?tab=settings">Turn it on in Club settings</Link></p>
    ) : null;
  }
  const daily = data.question;
  const q = shown || (daily && !daily.mine ? daily : data.waiting || daily);
  const canPlay = role !== "viewer";
  if (!q && !data.anytime) return null;

  async function post(path, body) {
    setBusy(true);
    setError(null);
    const r = await fetch(`${apiBase}/api/trivia/${path}`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: groupId, ...body }),
    }).catch(() => null);
    const d = await r?.json().catch(() => null);
    if (r?.ok && d) setShown(d);
    else { setError(d?.error || "Couldn't do that — try again."); reload(); }
    setBusy(false);
  }
  const another = data.anytime && canPlay && (
    <button type="button" className="btn btn-sm" disabled={busy} onClick={() => post("another", {})}>
      🎲 {q ? "Another question" : "Play a question"}
    </button>
  );

  if (!q) {                         // anytime only, nothing asked yet
    return (
      <section className="trivia-card" aria-label="Movie trivia">
        <div className="trivia-head"><strong>🎲 Movie trivia</strong>
          <span className="trivia-hint">A question whenever you like · +1 🍿 for a right one (up to 5 a day)</span></div>
        {another}
        {error && <p className="trivia-error" role="status">{error}</p>}
      </section>
    );
  }
  const answered = !!q.mine;
  const earned = q.earned ?? (q.anytime ? null : q.kernels);
  const y = data.yesterday;
  return (
    <section className="trivia-card" aria-labelledby="trivia-title">
      <div className="trivia-head">
        <strong id="trivia-title">{q.anytime ? "🎲 Anytime trivia" : "🧠 Question of the day"}</strong>
        <span className="trivia-hint">
          {answered ? (q.anytime || !data.anytime ? "" : "Want more? Play an anytime question")
            : q.anytime && q.kernels_left_today === 0 ? "One try · just for fun (today's anytime kernels are used up)"
            : `One try · +${q.kernels} 🍿 if you're right`}
        </span>
      </div>
      <p className="trivia-q">{q.prompt}</p>
      <div className="trivia-options" role="group" aria-label="Answers">
        {q.options.map((o, i) => {
          const state = !answered ? "" : i === q.answer ? " right" : i === q.mine.choice ? " wrong" : "";
          return (
            <button key={o} type="button" className={`trivia-option${state}`} disabled={answered || busy || !canPlay}
                    aria-pressed={answered && i === q.mine.choice} onClick={() => post("answer", { question_id: q.id, choice: i })}>
              <span className="trivia-letter">{LETTERS[i]}</span> {o}
            </button>
          );
        })}
      </div>
      {answered && (
        <p className="trivia-result" role="status">
          {q.mine.correct ? `✅ Right!${earned ? ` +${earned} 🍿` : ""}` : `❌ It was ${q.options[q.answer]}.`}
          {!q.anytime && ` ${q.stats.correct} of ${q.stats.answered} got it so far.`}
          {q.movie && <> <Link to={`/films/${q.movie.id}`}>About the film →</Link></>}
        </p>
      )}
      {answered && another}
      {!canPlay && !answered && <p className="trivia-hint">Read-only members can't answer.</p>}
      {error && <p className="trivia-error" role="status">{error}</p>}
      {y && !q.anytime && (
        <p className="trivia-yesterday">
          Yesterday: {y.prompt} → <strong>{y.options[y.answer]}</strong> ({y.stats.correct} of {y.stats.answered} got it)
        </p>
      )}
    </section>
  );
}

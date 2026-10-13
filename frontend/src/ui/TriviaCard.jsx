import { useState } from "react";
import { Link } from "react-router-dom";
import { useJson } from "../api";

// The club's question of the day (R10d) — only when a club admin has turned
// trivia on (admins see where to do that; everyone else sees nothing). One try
// each; the answer and the tally show once you've answered.
const LETTERS = "ABCD";

export default function TriviaCard({ apiBase, groupId, role }) {
  const { data, reload } = useJson(`${apiBase}/api/trivia/today?group_id=${groupId}`);
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  if (!data) return null;
  if (!data.enabled) {
    return role === "admin" ? (
      <p className="trivia-off">🧠 Daily movie trivia is off for the club. <Link to="/club?tab=settings">Turn it on in Club settings</Link></p>
    ) : null;
  }
  const q = result || data.question;
  if (!q) return null;
  const answered = !!q.mine;
  const canAnswer = role !== "viewer";

  async function pick(i) {
    setBusy(true);
    setError(null);
    const r = await fetch(`${apiBase}/api/trivia/answer`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: groupId, question_id: q.id, choice: i }),
    }).catch(() => null);
    const d = await r?.json().catch(() => null);
    if (r?.ok && d) setResult(d);
    else { setError(d?.error || "Couldn't save that — try again."); reload(); }
    setBusy(false);
  }

  const y = data.yesterday;
  return (
    <section className="trivia-card" aria-labelledby="trivia-title">
      <div className="trivia-head">
        <strong id="trivia-title">🧠 Daily trivia</strong>
        <span className="trivia-hint">{answered ? "See you tomorrow" : `One try · +${q.kernels} 🍿 if you're right`}</span>
      </div>
      <p className="trivia-q">{q.prompt}</p>
      <div className="trivia-options" role="group" aria-label="Answers">
        {q.options.map((o, i) => {
          const state = !answered ? "" : i === q.answer ? " right" : i === q.mine.choice ? " wrong" : "";
          return (
            <button key={o} type="button" className={`trivia-option${state}`} disabled={answered || busy || !canAnswer}
                    aria-pressed={answered && i === q.mine.choice} onClick={() => pick(i)}>
              <span className="trivia-letter">{LETTERS[i]}</span> {o}
            </button>
          );
        })}
      </div>
      {answered && (
        <p className="trivia-result" role="status">
          {q.mine.correct ? `✅ Right! +${q.kernels} 🍿` : `❌ It was ${q.options[q.answer]}.`}{" "}
          {q.stats.correct} of {q.stats.answered} got it so far.
          {q.movie && <> <Link to={`/films/${q.movie.id}`}>About the film →</Link></>}
        </p>
      )}
      {!canAnswer && !answered && <p className="trivia-hint">Read-only members can't answer.</p>}
      {error && <p className="trivia-error" role="status">{error}</p>}
      {y && (
        <p className="trivia-yesterday">
          Yesterday: {y.prompt} → <strong>{y.options[y.answer]}</strong> ({y.stats.correct} of {y.stats.answered} got it)
        </p>
      )}
    </section>
  );
}

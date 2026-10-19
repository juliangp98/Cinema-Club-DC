import { dayDateTime, monthDay } from "../dates";

// A bingo card's nine squares (R10e; shared since 7g): what each asks for,
// and the screening — or the Letterboxd diary entry (🏠) — that filled it.
// Your card on Play, and anyone's (the club strip, a member's page).
export default function BingoGrid({ squares, label = "Your card", compact = false }) {
  return (
    <ol className={`bingo-grid${compact ? " compact" : ""}`} aria-label={label}>
      {squares.map(s => (
        <li key={s.key} className={`bingo-cell${s.done ? " done" : ""}${s.home ? " home" : ""}${s.key === "free" ? " free" : ""}`}
            title={s.by ? `${s.by.title} · ${dayDateTime(s.by.start_time)} · ${s.by.theatre}`
              : s.home ? `${s.home.title} · watched at home ${monthDay(`${s.home.watched_on}T12:00:00`)}` : s.hint}>
          <span className="bingo-emoji" aria-hidden="true">{s.emoji}</span>
          <span className="bingo-label">{s.label}</span>
          {s.key !== "free" && (
            <span className="bingo-sub">{s.by ? `✓ ${s.by.title}` : s.home ? `🏠 ${s.home.title}` : s.hint}</span>
          )}
          <span className="sr-only">{s.done ? "— done" : "— not yet"}</span>
        </li>
      ))}
    </ol>
  );
}

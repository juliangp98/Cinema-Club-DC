import { Link } from "react-router-dom";
import { runsClub } from "../roles";
import { useJson } from "../api";
import { dayDateTime } from "../dates";
import Panel from "./Panel";

// Repertory bingo (R10e): this month's club card, filled in from your
// check-ins — only once a club organizer or admin turns bingo on (they see where
// to do that; everyone else sees nothing).
export default function BingoCard({ apiBase, groupId, role, offNote = false }) {
  const { data } = useJson(`${apiBase}/api/bingo?group_id=${groupId}`);
  if (!data) return null;
  if (!data.enabled) {
    return runsClub(role) ? (
      <p className="ui-note">🎱 Repertory bingo is off for the club. <Link to="/club?tab=settings#settings-games">Turn it on in Club settings</Link></p>
    ) : offNote ? <p className="ui-note">🎱 Repertory bingo isn't on in this club yet — a club organizer or admin can turn it on.</p> : null;
  }
  const status = data.full ? "🎉 Full card!" : data.line ? "🎉 Bingo! Now fill the whole card" : `${data.filled} of 8 — any line of 3 is bingo`;
  return (
    <Panel tone="gold" className="bingo-card" aria-labelledby="bingo-title" titleId="bingo-title"
           title={`🎱 Repertory bingo · ${data.month_label}`} hint={status}>
      <ol className="bingo-grid" aria-label="Your card">
        {data.squares.map(s => (
          <li key={s.key} className={`bingo-cell${s.done ? " done" : ""}${s.key === "free" ? " free" : ""}`}
              title={s.by ? `${s.by.title} · ${dayDateTime(s.by.start_time)} · ${s.by.theatre}` : s.hint}>
            <span className="bingo-emoji" aria-hidden="true">{s.emoji}</span>
            <span className="bingo-label">{s.label}</span>
            {s.key !== "free" && (
              <span className="bingo-sub">{s.by ? `✓ ${s.by.title}` : s.hint}</span>
            )}
            <span className="sr-only">{s.done ? "— done" : "— not yet"}</span>
          </li>
        ))}
      </ol>
      <p className="ui-hint">
        Fills in by itself when you check in ("Went") to a screening this month. First line +{data.rules.line} 🍿,
        the full card +{data.rules.full} 🍿{data.kernels ? ` · you've earned ${data.kernels}` : ""}.
      </p>
      {data.club.length > 0 && (
        <p className="ui-hint">The club: {data.club.slice(0, 6).map(r => `${r.user.name} ${r.filled}/8${r.full ? " 🎉🎉" : r.line ? " 🎉" : ""}`).join(" · ")}</p>
      )}
    </Panel>
  );
}

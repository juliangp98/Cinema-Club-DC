import { useEffect, useState } from "react";
import { useJson } from "../api";

// Screening notes (R10f): quick tags about the screening itself from members
// who checked in — only once a club admin turns notes on. The same tags as
// backend/notes.py.
export const NOTE_TAGS = {
  print: ["🎞️", "Gorgeous print"], worn: ["📼", "Worn print"], sound: ["🔊", "Great sound"],
  sound_trouble: ["🔇", "Sound trouble"], projection: ["⚠️", "Projection trouble"], packed: ["👥", "Packed house"],
  crowd: ["😂", "Great crowd"], roomy: ["🪑", "Plenty of seats"], qa: ["🎤", "Great Q&A or intro"],
};

// In the screening drawer: tap to add or remove yours; everyone's counts.
export default function ScreeningNotes({ apiBase, groupId, showtimeId }) {
  const { data } = useJson(groupId && showtimeId ? `${apiBase}/api/notes?group_id=${groupId}&showtime_id=${showtimeId}` : null);
  const [view, setView] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => { setView(data); }, [data]);
  if (!view?.enabled) return null;
  const used = view.tags.some(t => t.count);
  if (!view.can_add && !used) return null;

  async function toggle(tag) {
    setError(null);
    const r = await fetch(`${apiBase}/api/notes`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: groupId, showtime_id: showtimeId, tag }),
    }).catch(() => null);
    const d = await r?.json().catch(() => null);
    if (r?.ok && d) setView(d);
    else setError(d?.error || "Couldn't save that — try again.");
  }
  const shown = view.can_add ? view.tags : view.tags.filter(t => t.count);
  return (
    <div className="screening-notes">
      <div className="drawer-section-label">{view.can_add ? "How was the screening?" : "From members who were there"}</div>
      <div className="screening-notes-tags" role="group" aria-label="Screening notes">
        {shown.map(t => (
          <button key={t.key} type="button" className={`chip${t.mine ? " gold" : ""}`} disabled={!view.can_add}
                  aria-pressed={t.mine} onClick={() => toggle(t.key)}>
            {t.emoji} {t.label}{t.count ? <span className="mood-count">{t.count}</span> : null}
          </button>
        ))}
      </div>
      {error && <p className="trivia-error" role="status">{error}</p>}
    </div>
  );
}

// On a theatre page: what the club's members say about its screenings lately.
export function TheatreNotes({ apiBase, groupId, slug }) {
  const { data } = useJson(groupId ? `${apiBase}/api/theatres/${slug}/notes?group_id=${groupId}` : null);
  if (!data?.tags?.length) return null;
  return (
    <p className="theatre-notes">
      <strong>What the club says</strong> ({data.screenings} screening{data.screenings === 1 ? "" : "s"} lately):{" "}
      {data.tags.slice(0, 5).map(t => `${t.emoji} ${t.label} ×${t.count}`).join(" · ")}
    </p>
  );
}

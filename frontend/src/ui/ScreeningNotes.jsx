import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useJson } from "../api";
import { SectionTitle } from "./PageHeader";
import Poster from "./Poster";
import { dayDate } from "../dates";

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

// On a theatre page: what the club's members say about its screenings
// lately — a tile per note (heads-up ones marked), and the screenings they
// noted most recently.
export function TheatreNotes({ apiBase, groupId, slug }) {
  const { data } = useJson(groupId ? `${apiBase}/api/theatres/${slug}/notes?group_id=${groupId}` : null);
  if (!data?.tags?.length) return null;
  const top = Math.max(...data.tags.map(t => t.count));
  return (
    <section className="shelf theatre-notes" aria-labelledby="theatre-notes-title">
      <SectionTitle action={<span className="theatre-notes-span">{data.screenings} screening{data.screenings === 1 ? "" : "s"} · last 6 months</span>}>
        <span id="theatre-notes-title">What the club says</span>
      </SectionTitle>
      <p className="shelf-blurb">From members who checked in here — the print, the sound, the crowd.</p>
      <ul className="note-tiles">
        {data.tags.map(t => (
          <li key={t.key} className={`note-tile${t.heads_up ? " heads-up" : ""}`}>
            <span className="note-tile-emoji" aria-hidden="true">{t.emoji}</span>
            <span className="note-tile-label">{t.label}{t.heads_up && <span className="note-tile-flag">Heads-up</span>}</span>
            <span className="note-tile-count">×{t.count}</span>
            <span className="note-tile-bar" aria-hidden="true"><span style={{ width: `${Math.round((t.count / top) * 100)}%` }} /></span>
          </li>
        ))}
      </ul>
      {data.recent?.length > 0 && (
        <>
          <div className="note-recent-head">Lately</div>
          <ul className="note-recent">
            {data.recent.map(r => (
              <li key={r.screening.showtime_id}>
                <Link to={`/calendar?showtime=${r.screening.showtime_id}`} className="note-recent-item">
                  <Poster movie={{ title: r.screening.title, poster_url: r.screening.poster_url }} className="note-recent-poster" />
                  <span className="note-recent-text">
                    <span className="note-recent-title">{r.screening.title}</span>
                    <span className="note-recent-when">{dayDate(r.screening.start_time)}{r.screening.format_label ? ` · ${r.screening.format_label}` : ""}</span>
                    <span className="note-recent-tags">{r.tags.slice(0, 3).map(t => `${t.emoji} ${t.label}`).join(" · ")}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

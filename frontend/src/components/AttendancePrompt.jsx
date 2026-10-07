import { useEffect, useState } from "react";

function formatDay(iso) {
  return new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "numeric", day: "numeric" });
}

// "Did you make it?" — screenings you RSVP'd going to that ended a couple of
// hours ago (within the past week). Answering "Went" offers a jump into that
// screening's discussion. The same question reaches Discord members by DM.
export default function AttendancePrompt({ apiBase, refreshKey, onAnswer, onOpenShowtime }) {
  const [items, setItems] = useState([]);
  const [logged, setLogged] = useState(null);   // the screening just marked "went"
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    fetch(`${apiBase}/api/attendance/pending`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(setItems)
      .catch(() => setItems([]));
  }, [apiBase, refreshKey]);

  async function answer(item, status) {
    if (!(await onAnswer(item.showtime_id, status))) return;
    setItems(prev => prev.filter(i => i.showtime_id !== item.showtime_id));
    setLogged(status === "went" ? item : null);
  }

  if (hidden || (!items.length && !logged)) return null;
  return (
    <section className="attendance-prompt" aria-label="Did you make it?">
      <div className="attendance-prompt-head">
        <span className="attendance-prompt-title">🎬 Did you make it?</span>
        <button className="attendance-prompt-close" onClick={() => setHidden(true)} aria-label="Hide for now">
          &times;
        </button>
      </div>
      {logged && (
        <div className="attendance-prompt-done">
          🍿 Logged <strong>{logged.title}</strong> to your watch history.{" "}
          <button className="attendance-link" onClick={() => onOpenShowtime(logged.showtime_id)}>
            Share your take in the discussion →
          </button>
        </div>
      )}
      {items.map(item => (
        <div key={item.showtime_id} className="attendance-item">
          <span className="attendance-item-text">
            <strong>{item.title}</strong> · {formatDay(item.start_time)} · {item.theatre}
            {item.format_label ? ` · ${item.format_label}` : ""}
          </span>
          <div className="attendance-item-actions">
            <button className="rsvp-btn att-opt-went" onClick={() => answer(item, "went")}>Went</button>
            <button className="rsvp-btn att-opt-missed" onClick={() => answer(item, "missed")}>Didn't go</button>
          </div>
        </div>
      ))}
    </section>
  );
}

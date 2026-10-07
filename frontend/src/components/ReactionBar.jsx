import { useState } from "react";

const CINEMA_EMOJIS = [
  "\u{1F37F}", "\u{1F3AC}", "\u{1F44F}", "\u{1F602}", "\u{1F622}",
  "\u{1F631}", "\u{1F525}", "\u{1F480}", "\u2764\uFE0F", "\u{1F44E}",
  "\u{1F44D}", "\u{1F60D}", "\u{1F914}", "\u{1F634}",
  "\u{1F1FA}\u{1F1F8}", "\u{1F1F2}\u{1F1FD}", "\u{1F1EF}\u{1F1F5}",
  "\u{1F1F0}\u{1F1F7}", "\u{1F1EB}\u{1F1F7}", "\u{1F1EE}\u{1F1F9}",
  "\u{1F1EC}\u{1F1E7}",
  "\u{1FAC3}", "\u{1FAC4}", "\u{1F930}",
];

// Club mode: who reacted. Public mode (groupId null): anonymous totals (shown
// from 3 up) plus your own; `beforeReact` makes a guest profile if needed.
export default function ReactionBar({ reactions, showtimeId, groupId, apiBase, onUpdate, beforeReact }) {
  const [showPicker, setShowPicker] = useState(false);

  async function toggleReaction(emoji) {
    if (beforeReact && !(await beforeReact())) return;
    try {
      const r = await fetch(`${apiBase}/api/reactions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ showtime_id: showtimeId, group_id: groupId, emoji }),
      });
      if (r.ok) {
        const data = await r.json();
        onUpdate(data);
      }
    } catch {
      // ignore
    }
    setShowPicker(false);
  }

  // Convert reactions object to sorted array
  const reactionList = Object.entries(reactions || {})
    .map(([emoji, data]) => ({ emoji, ...data }))
    .filter(r => r.count > 0 || r.user_reacted)
    .sort((a, b) => (b.count || 0) - (a.count || 0));

  return (
    <div className="reaction-bar">
      <div className="reaction-row">
        {reactionList.map(r => (
          <button
            key={r.emoji}
            className={`reaction-pill${r.user_reacted ? " active" : ""}`}
            onClick={() => toggleReaction(r.emoji)}
            title={r.users.length ? r.users.map(u => u.name).join(", ") : r.count ? `${r.count} people` : "You"}
          >
            <span className="reaction-emoji">{r.emoji}</span>
            {r.count > 0 && <span className="reaction-count">{r.count}</span>}
          </button>
        ))}
        <button
          className="reaction-add-btn"
          onClick={() => setShowPicker(!showPicker)}
          title="Add reaction"
        >
          +
        </button>
      </div>

      {showPicker && (
        <div className="reaction-picker">
          {CINEMA_EMOJIS.map(emoji => (
            <button
              key={emoji}
              className="reaction-picker-item"
              onClick={() => toggleReaction(emoji)}
            >
              {emoji}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

import { useState, useEffect, useRef, useCallback } from "react";

function timeAgo(iso) {
  const now = new Date();
  const d = new Date(iso);
  const diff = Math.floor((now - d) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// A cheap fingerprint, so a poll that changes nothing doesn't re-render (or scroll).
const signature = list => list.map(m => `${m.id}:${m.body.length}:${m.body.slice(-8)}`).join("|");

export default function ChatSection({ showtimeId, groupId, apiBase, onViewProfile, discordThreadUrl }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef(null);
  const lastSignature = useRef("");

  // The whole (≤100) list each time, so edits and deletions made in the
  // screening's Discord thread show up too, not just new messages.
  const fetchMessages = useCallback(async () => {
    const params = new URLSearchParams({ showtime_id: showtimeId });
    if (groupId) params.set("group_id", groupId);
    try {
      const r = await fetch(`${apiBase}/api/messages?${params}`, { credentials: "include" });
      if (r.ok) {
        const data = await r.json();
        const sig = signature(data);
        if (sig !== lastSignature.current) {
          lastSignature.current = sig;
          setMessages(data);
        }
      }
    } catch {
      // ignore
    }
  }, [showtimeId, groupId, apiBase]);

  // Initial fetch
  useEffect(() => {
    lastSignature.current = "";
    fetchMessages();
  }, [fetchMessages]);

  // Poll every 10s while the tab is visible; catch up as soon as it's shown again.
  useEffect(() => {
    function poll() {
      if (!document.hidden) fetchMessages();
    }
    const interval = setInterval(poll, 10000);
    document.addEventListener("visibilitychange", poll);
    return () => {
      clearInterval(interval);
      document.removeEventListener("visibilitychange", poll);
    };
  }, [fetchMessages]);

  // Keep the newest message in view by scrolling ONLY the messages container.
  // scrollIntoView would bubble up and scroll the whole drawer to the bottom
  // on open, hiding the title/poster — so scroll the container's own scrollTop.
  const didInitialScroll = useRef(false);
  useEffect(() => {
    const container = messagesEndRef.current?.parentElement;
    if (!container) return;
    // Skip the first populate so an opened drawer rests at the top.
    if (!didInitialScroll.current) {
      didInitialScroll.current = true;
      return;
    }
    container.scrollTop = container.scrollHeight;
  }, [messages]);

  async function handleSend(e) {
    e.preventDefault();
    const body = input.trim();
    if (!body) return;

    setSending(true);
    try {
      const r = await fetch(`${apiBase}/api/messages`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ showtime_id: showtimeId, group_id: groupId, body }),
      });
      if (r.ok) {
        const msg = await r.json();
        setMessages(prev => {
          const next = [...prev, msg];
          lastSignature.current = signature(next);
          return next;
        });
        setInput("");
      }
    } catch {
      // ignore
    } finally {
      setSending(false);
    }
  }

  async function handleDelete(m) {
    if (!window.confirm(m.via_discord ? "Delete this comment here and in Discord?" : "Delete this comment?")) return;
    try {
      const r = await fetch(`${apiBase}/api/messages/${m.id}`, { method: "DELETE", credentials: "include" });
      if (r.ok) {
        setMessages(prev => {
          const next = prev.filter(x => x.id !== m.id);
          lastSignature.current = signature(next);
          return next;
        });
      }
    } catch {
      // ignore
    }
  }

  return (
    <div className="chat-section">
      {discordThreadUrl && (
        <a className="chat-discord-link" href={discordThreadUrl} target="_blank" rel="noreferrer">
          💬 Also in Discord — this discussion is mirrored in its #movies thread →
        </a>
      )}
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">No messages yet. Start the conversation!</div>
        )}
        {messages.map(m => (
          <div key={m.id} className="chat-bubble">
            <div
              className="chat-avatar clickable"
              style={{ background: m.user.avatar_color, color: "var(--ink)" }}
              onClick={() => onViewProfile?.(m.user.id)}
            >
              {m.user.name.slice(0, 2).toUpperCase()}
            </div>
            <div className="chat-bubble-content">
              <div className="chat-bubble-header">
                <span
                  className="chat-name clickable"
                  onClick={() => onViewProfile?.(m.user.id)}
                >{m.user.name}</span>
                {m.via_discord && <span className="chat-via" title="Posted in the Discord thread">via Discord</span>}
                <span className="chat-time">{timeAgo(m.created_at)}</span>
                {m.can_delete && (
                  <button type="button" className="chat-delete" onClick={() => handleDelete(m)}
                          aria-label="Delete comment" title="Delete">&times;</button>
                )}
              </div>
              <div className="chat-body">{m.body}</div>
            </div>
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>
      <form className="chat-input-row" onSubmit={handleSend}>
        <input
          className="chat-input"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder="Type a message..."
          maxLength={2000}
        />
        <button className="chat-send-btn" type="submit" disabled={sending || !input.trim()}>
          Send
        </button>
      </form>
    </div>
  );
}

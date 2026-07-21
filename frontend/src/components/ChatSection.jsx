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

export default function ChatSection({ showtimeId, groupId, apiBase, onViewProfile }) {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef(null);
  const lastTimestamp = useRef(null);

  const fetchMessages = useCallback(async (since) => {
    const params = new URLSearchParams({ showtime_id: showtimeId });
    if (groupId) params.set("group_id", groupId);
    if (since) params.set("since", since);

    try {
      const r = await fetch(`${apiBase}/api/messages?${params}`, { credentials: "include" });
      if (r.ok) {
        const data = await r.json();
        if (since && data.length > 0) {
          setMessages(prev => [...prev, ...data]);
        } else if (!since) {
          setMessages(data);
        }
        if (data.length > 0) {
          lastTimestamp.current = data[data.length - 1].created_at;
        }
      }
    } catch {
      // ignore
    }
  }, [showtimeId, groupId, apiBase]);

  // Initial fetch
  useEffect(() => {
    lastTimestamp.current = null;
    fetchMessages();
  }, [fetchMessages]);

  // Poll every 10s
  useEffect(() => {
    const interval = setInterval(() => {
      if (lastTimestamp.current) {
        fetchMessages(lastTimestamp.current);
      }
    }, 10000);
    return () => clearInterval(interval);
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
        setMessages(prev => [...prev, msg]);
        lastTimestamp.current = msg.created_at;
        setInput("");
      }
    } catch {
      // ignore
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="chat-section">
      <span className="drawer-section-label">Discussion</span>
      <div className="chat-messages">
        {messages.length === 0 && (
          <div className="chat-empty">No messages yet. Start the conversation!</div>
        )}
        {messages.map(m => (
          <div key={m.id} className="chat-bubble">
            <div
              className="chat-avatar clickable"
              style={{ background: m.user.avatar_color, color: "#0d0c09" }}
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
                <span className="chat-time">{timeAgo(m.created_at)}</span>
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

import { useState, useEffect, useRef, useCallback } from "react";
import { useShell } from "../shell/AppShell";
import { shareToDiscord } from "../ui/DiscordShare";

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

// "Ask" for comments remembers the last choice of the "also post in Discord" box.
const LAST_CHOICE = "cinemaclub_comment_to_discord";
function readLast() { try { return localStorage.getItem(LAST_CHOICE) !== "0"; } catch { return true; } }
function writeLast(on) { try { localStorage.setItem(LAST_CHOICE, on ? "1" : "0"); } catch { /* private mode */ } }

// `discord` (the screening's Discord block; absent outside the Discord
// server's group) turns on the Discord choices: with a thread, an "also post
// in the Discord thread" box; without one, "Start a Discord thread".
export default function ChatSection({ showtimeId, groupId, apiBase, onViewProfile, discordThreadUrl, discord, readOnly = false }) {
  const shell = useShell();
  const pref = shell?.user?.share_prefs?.comment || "ask";
  const [threadUrl, setThreadUrl] = useState(discordThreadUrl);
  const [threadPending, setThreadPending] = useState(!!discord?.thread_pending);
  const [toDiscord, setToDiscord] = useState(() => (pref === "always" ? true : pref === "never" ? false : readLast()));
  const [threadError, setThreadError] = useState("");
  useEffect(() => { setThreadUrl(discordThreadUrl); }, [discordThreadUrl]);
  useEffect(() => { setThreadPending(!!discord?.thread_pending); }, [discord?.thread_pending]);
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
        body: JSON.stringify({ showtime_id: showtimeId, group_id: groupId, body,
                               ...(discord ? { to_discord: !!threadUrl && toDiscord } : {}) }),
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

  async function startThread() {
    setThreadError("");
    try {
      const r = await shareToDiscord(apiBase, { kind: "thread", group_id: groupId, showtime_id: showtimeId });
      if (r.thread_url) setThreadUrl(r.thread_url);
      else setThreadPending(true);
    } catch (e) {
      setThreadError(e.message);
    }
  }

  function chooseToDiscord(on) {
    setToDiscord(on);
    if (pref === "ask") writeLast(on);
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
      {threadUrl ? (
        <a className="chat-discord-link" href={threadUrl} target="_blank" rel="noreferrer">
          💬 Also in Discord — this discussion has a thread in #movies →
        </a>
      ) : discord && (
        <div className="chat-discord-start">
          {threadPending
            ? <span>Starting a Discord thread… the last comments will be copied in.</span>
            : <>
                <span>Comments stay on the site.</span>
                <button type="button" className="share-link" onClick={startThread}>Start a Discord thread</button>
              </>}
          {threadError && <span className="share-error">{threadError}</span>}
        </div>
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
      {readOnly ? (
        <p className="chat-readonly">You're read-only in this club, so you can follow the discussion but not post.</p>
      ) : (
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
      )}
      {discord && threadUrl && (
        <label className="chat-to-discord">
          <input type="checkbox" checked={toDiscord} onChange={e => chooseToDiscord(e.target.checked)} />
          Also post in the Discord thread
        </label>
      )}
    </div>
  );
}

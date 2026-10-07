import { useState, useEffect, useCallback, useRef } from "react";
import { useNavigate } from "react-router-dom";
import ShowtimeDrawer from "../components/ShowtimeDrawer";
import ProfileMenu from "../components/ProfileMenu";
import GroupSwitcher from "../components/GroupSwitcher";
import UserProfileDrawer from "../components/UserProfileDrawer";
import AttendancePrompt from "../components/AttendancePrompt";
import ReactionBar from "../components/ReactionBar";
import ChatSection from "../components/ChatSection";
import MainNav from "../components/MainNav";
import { accountLabel } from "../accountLabel";

function timeAgo(iso) {
  const diff = Math.max(0, Math.floor((Date.now() - new Date(iso)) / 1000));
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 7 * 86400) return `${Math.floor(diff / 86400)}d ago`;
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function formatWhen(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day} · ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

// "You, Ana +2" — the viewer reads as "You".
function names(users, viewerId, max = 2) {
  const labels = users.map(u => (u.id === viewerId ? "You" : u.name));
  if (labels.length <= max) {
    return labels.length === 2 ? `${labels[0]} and ${labels[1]}` : labels.join("");
  }
  return `${labels.slice(0, max).join(", ")} +${labels.length - max}`;
}

const pluralVerb = (users, viewerId, one, many) =>
  users.length === 1 && users[0].id !== viewerId ? one : many;

const ACTIVITY = {
  rsvp: a => (a.detail === "maybe" ? "might go" : "is going"),
  went: () => "went",
  comment: () => "commented",
  reaction: a => `reacted ${a.detail}`,
};

function Avatars({ users, onViewProfile, max = 5 }) {
  return (
    <span className="feed-avatars">
      {users.slice(0, max).map(u => (
        <button
          key={u.id}
          type="button"
          className="feed-avatar"
          style={{ background: u.avatar_color }}
          title={u.discord_only ? `${u.name} (Discord)` : u.name}
          onClick={() => onViewProfile(u.id)}
        >
          {u.name.slice(0, 2).toUpperCase()}
        </button>
      ))}
    </span>
  );
}

function CardHead({ at, children }) {
  return (
    <div className="feed-card-top">
      <span className="feed-kicker">{children}</span>
      <time className="feed-time" dateTime={at}>{timeAgo(at)}</time>
    </div>
  );
}

function ScreeningCard({ card, viewerId, groupId, apiBase, expanded, onToggle, onOpen, onViewProfile, onReactions }) {
  const s = card.showtime;
  const past = new Date(s.start_time) < new Date();
  const going = s.attendees || [];
  const maybes = s.maybes || [];
  let headline;
  if (past && card.went.length) headline = `🍿 ${names(card.went, viewerId)} went`;
  else if (past && going.length) headline = `🎟️ ${names(going, viewerId)} ${pluralVerb(going, viewerId, "was", "were")} going`;
  else if (going.length || maybes.length) {
    headline = [
      going.length && `🎟️ ${names(going, viewerId)} ${pluralVerb(going, viewerId, "is", "are")} going`,
      maybes.length && `${names(maybes, viewerId)} maybe`,
    ].filter(Boolean).join(" · ");
  } else headline = "💬 Talking about";
  const latest = card.activity[0];
  const reactions = Object.entries(s.reactions || {});
  const people = [...new Map([...card.went, ...going, ...maybes].map(u => [u.id, u])).values()];

  return (
    <article className="feed-card">
      <CardHead at={card.at}>{headline}</CardHead>
      <div className="feed-card-main">
        {s.movie.poster_url && (
          <button type="button" className="feed-poster" onClick={onOpen} aria-label={`Open ${s.movie.title}`}>
            <img src={s.movie.poster_url} alt="" loading="lazy" />
          </button>
        )}
        <div className="feed-card-body">
          <button type="button" className="feed-title" onClick={onOpen}>{s.movie.title}</button>
          <div className="feed-meta">
            {formatWhen(s.start_time)} · {s.theatre.short_name || s.theatre.name}
            {s.format_label ? ` · ${s.format_label}` : ""}
          </div>
          {people.length > 0 && <Avatars users={people} onViewProfile={onViewProfile} />}
          {latest && (
            <div className="feed-activity">
              {latest.user.id === viewerId ? "You" : latest.user.name} {ACTIVITY[latest.kind]?.(latest)}
            </div>
          )}
        </div>
      </div>

      {expanded ? (
        <div className="feed-discussion">
          <ReactionBar reactions={s.reactions || {}} showtimeId={s.id} groupId={groupId} apiBase={apiBase} onUpdate={onReactions} />
          <ChatSection showtimeId={s.id} groupId={groupId} apiBase={apiBase} onViewProfile={onViewProfile}
                       discordThreadUrl={s.discord_thread_url} />
        </div>
      ) : (
        <>
          {card.latest_comment && (
            <button type="button" className="feed-comment" onClick={onToggle}>
              <span className="feed-comment-author">
                {card.latest_comment.user.id === viewerId ? "You" : card.latest_comment.user.name}
              </span>{" "}
              {card.latest_comment.body}
            </button>
          )}
          {reactions.length > 0 && (
            <div className="feed-reactions">
              {reactions.map(([emoji, r]) => (
                <span key={emoji} className={`feed-reaction${r.user_reacted ? " mine" : ""}`}>{emoji} {r.count}</span>
              ))}
            </div>
          )}
        </>
      )}

      <div className="feed-actions">
        <button type="button" className="feed-action" onClick={onToggle} aria-expanded={expanded}>
          {expanded ? "Hide discussion" : `💬 Discuss${s.message_count ? ` (${s.message_count})` : ""}`}
        </button>
        <button type="button" className="feed-action" onClick={onOpen}>Open screening</button>
        {s.discord_thread_url && (
          <a className="feed-action" href={s.discord_thread_url} target="_blank" rel="noreferrer">In Discord ↗</a>
        )}
      </div>
    </article>
  );
}

function WatchlistCard({ card, viewerId, onOpenShowtime, onViewProfile }) {
  const { movie, users, next } = card;
  const youAdded = users.some(u => u.id === viewerId);
  const whose = users.length === 1 ? (youAdded ? "your watchlist" : "their watchlist") : "their watchlists";
  const others = card.wanters - users.length;
  return (
    <article className="feed-card">
      <CardHead at={card.at}>🎯 {names(users, viewerId)} added this to {whose}</CardHead>
      <div className="feed-card-main">
        {movie.poster_url && (
          <span className="feed-poster"><img src={movie.poster_url} alt="" loading="lazy" /></span>
        )}
        <div className="feed-card-body">
          <span className="feed-title static">
            {movie.title}{movie.release_year ? ` (${movie.release_year})` : ""}
          </span>
          <div className="feed-meta">
            {next ? `Next: ${formatWhen(next.start_time)} · ${next.theatre}` : "No showings scheduled yet"}
          </div>
          <Avatars users={users} onViewProfile={onViewProfile} />
          {(others > 0 || (card.viewer_wants && !youAdded)) && (
            <div className="feed-activity">
              {others > 0 && `${others} more ${others === 1 ? "member wants" : "members want"} to see it`}
              {others > 0 && card.viewer_wants && !youAdded && " · "}
              {card.viewer_wants && !youAdded && "on your watchlist too"}
            </div>
          )}
        </div>
      </div>
      {next && (
        <div className="feed-actions">
          <button type="button" className="feed-action" onClick={() => onOpenShowtime(next.showtime_id)}>
            Open next showing
          </button>
        </div>
      )}
    </article>
  );
}

const POLL_HEADLINE = {
  open: p => `🗳️ New poll${p.creator ? ` from ${p.creator}` : ""}`,
  closed: () => "🔒 Voting closed",
  scored: () => "🏆 Results are in",
};

function PollCard({ card, onOpenPoll }) {
  const p = card.poll;
  const open = p.status === "open";
  return (
    <article className="feed-card">
      <CardHead at={card.at}>{(POLL_HEADLINE[p.status] || POLL_HEADLINE.open)(p)}</CardHead>
      <div className="feed-card-body">
        <button type="button" className="feed-title" onClick={onOpenPoll}>{p.title}</button>
        <div className="feed-meta">
          {p.categories} {p.categories === 1 ? "category" : "categories"} · {card.voters} voted
        </div>
        {open && !card.you_voted && <div className="feed-activity nudge">You haven't voted yet</div>}
      </div>
      <div className="feed-actions">
        <button type="button" className="feed-action" onClick={onOpenPoll}>
          {open ? (card.you_voted ? "Change your picks" : "Vote") : p.status === "scored" ? "See results" : "See poll"}
        </button>
      </div>
    </article>
  );
}

function JoinedCard({ card, viewerId, onViewProfile }) {
  const viaDiscord = card.users.filter(u => u.discord_only).length;
  return (
    <article className="feed-card">
      <CardHead at={card.at}>👋 {names(card.users, viewerId, 3)} joined the club</CardHead>
      <div className="feed-card-body">
        <Avatars users={card.users} onViewProfile={onViewProfile} max={8} />
        {viaDiscord > 0 && (
          <div className="feed-activity">
            {viaDiscord === card.users.length ? "via Discord" : `${viaDiscord} via Discord`}
          </div>
        )}
      </div>
    </article>
  );
}

export default function Feed({ user, setUser, apiBase, groupId, setGroupId }) {
  const navigate = useNavigate();
  const [cards, setCards] = useState([]);
  const [nextOffset, setNextOffset] = useState(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(null);     // one open discussion at a time
  const [selected, setSelected] = useState(null);     // showtimes for the drawer
  const [profileUserId, setProfileUserId] = useState(null);
  const [showProfile, setShowProfile] = useState(false);
  const [attendanceKey, setAttendanceKey] = useState(0);
  const loadedRef = useRef(0);
  const groupRef = useRef(groupId);   // responses for a group we've left are dropped
  groupRef.current = groupId;

  const fetchPage = useCallback(async (offset) => {
    const r = await fetch(`${apiBase}/api/feed?group_id=${groupId}&offset=${offset}`, { credentials: "include" });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }, [apiBase, groupId]);

  // (Re)load everything currently shown, so updates land in place.
  const reload = useCallback(async () => {
    const forGroup = groupId;
    try {
      const pages = Math.max(1, Math.ceil(loadedRef.current / 20));
      const results = await Promise.all(Array.from({ length: pages }, (_, i) => fetchPage(i * 20)));
      if (forGroup !== groupRef.current) return;
      const seen = new Set();
      const all = results.flatMap(p => p.cards).filter(c => !seen.has(c.key) && seen.add(c.key));
      setCards(all);
      loadedRef.current = all.length;
      setNextOffset(results[results.length - 1].next_offset);
      setDays(results[0].days);
      setError(false);
    } catch {
      if (forGroup === groupRef.current) setError(true);
    } finally {
      if (forGroup === groupRef.current) setLoading(false);
    }
  }, [fetchPage, groupId]);

  useEffect(() => {
    loadedRef.current = 0;
    setCards([]);
    setExpanded(null);
    setError(false);
    setLoading(true);
    reload();
  }, [reload]);

  // Catch up when coming back to the tab.
  useEffect(() => {
    const onVisible = () => { if (!document.hidden) reload(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [reload]);

  async function loadMore() {
    const forGroup = groupId;
    try {
      const page = await fetchPage(nextOffset);
      if (forGroup !== groupRef.current) return;
      setCards(prev => {
        const have = new Set(prev.map(c => c.key));
        const all = [...prev, ...page.cards.filter(c => !have.has(c.key))];
        loadedRef.current = all.length;
        return all;
      });
      setNextOffset(page.next_offset);
    } catch {
      setError(true);
    }
  }

  function toggleDiscussion(key) {
    // Closing a discussion refreshes its preview (new comments, counts).
    if (expanded === key) reload();
    setExpanded(expanded === key ? null : key);
  }

  const patchShowtime = useCallback((id, patch) => {
    setCards(prev => prev.map(c => (c.showtime?.id === id ? { ...c, showtime: { ...c.showtime, ...patch } } : c)));
    setSelected(prev => (prev ? prev.map(s => (s.id === id ? { ...s, ...patch } : s)) : prev));
  }, []);

  const openShowtime = useCallback((stId) => {
    fetch(`${apiBase}/api/showtimes/${stId}?group_id=${groupId}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(data => { if (data) setSelected([data]); })
      .catch(() => { /* ignore */ });
  }, [apiBase, groupId]);

  async function handleRsvp(showtimeId, status) {
    const r = await fetch(`${apiBase}/api/rsvp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ showtime_id: showtimeId, status, group_id: groupId }),
    });
    if (r.ok) {
      patchShowtime(showtimeId, await r.json());
      reload();
    }
  }

  async function handleAttendance(showtimeId, status) {
    const r = await fetch(`${apiBase}/api/attendance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ showtime_id: showtimeId, status }),
    });
    if (!r.ok) return false;
    patchShowtime(showtimeId, { user_attendance: status });
    setAttendanceKey(k => k + 1);
    reload();
    return true;
  }

  async function logout() {
    await fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" });
    setUser(null);
  }

  function renderCard(card) {
    const common = { card, viewerId: user.id, onViewProfile: setProfileUserId };
    switch (card.type) {
      case "screening":
        return (
          <ScreeningCard
            key={card.key}
            {...common}
            groupId={groupId}
            apiBase={apiBase}
            expanded={expanded === card.key}
            onToggle={() => toggleDiscussion(card.key)}
            onOpen={() => setSelected([card.showtime])}
            onReactions={reactions => patchShowtime(card.showtime.id, { reactions })}
          />
        );
      case "watchlist":
        return <WatchlistCard key={card.key} {...common} onOpenShowtime={openShowtime} />;
      case "poll":
        return <PollCard key={card.key} {...common} onOpenPoll={() => navigate(`/polls/${card.poll.id}`)} />;
      case "joined":
        return <JoinedCard key={card.key} {...common} />;
      default:
        return null;
    }
  }

  return (
    <div className="feed-page">
      <header className="header feed-header">
        <span
          className="header-logo"
          onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}
          style={{ cursor: "pointer" }}
        >
          CINEMA CLUB DC
        </span>
        <div className="header-sep" />
        <MainNav />
        <div className="header-spacer" />
        <GroupSwitcher apiBase={apiBase} activeGroupId={groupId} setGroupId={setGroupId} />
        <div className="header-sep" />
        <div style={{ position: "relative" }}>
          <div
            className="user-avatar"
            style={{ background: user.avatar_color, color: "#0d0c09" }}
            title={`${user.name} — ${accountLabel(user)}`}
            onClick={() => setShowProfile(!showProfile)}
          >
            {user.name.slice(0, 2).toUpperCase()}
          </div>
          {showProfile && (
            <ProfileMenu
              user={user}
              apiBase={apiBase}
              onUpdate={setUser}
              onLogout={logout}
              onClose={() => setShowProfile(false)}
            />
          )}
        </div>
      </header>

      <main className="feed-main">
        <AttendancePrompt
          apiBase={apiBase}
          refreshKey={attendanceKey}
          onAnswer={handleAttendance}
          onOpenShowtime={openShowtime}
        />

        {loading && !cards.length && <div className="feed-empty">Loading…</div>}
        {error && <div className="feed-empty">Couldn't load the feed. <button type="button" className="attendance-link" onClick={reload}>Try again</button></div>}
        {!loading && !error && !cards.length && (
          <div className="feed-empty">
            <p>Nothing here yet. RSVP to a screening, add films to your watchlist, or start a discussion and it'll show up here.</p>
            <button type="button" className="feed-action" onClick={() => navigate("/calendar")}>Browse the calendar</button>
          </div>
        )}

        {cards.map(renderCard)}

        {nextOffset != null && (
          <button type="button" className="feed-more" onClick={loadMore}>Load more</button>
        )}
        {nextOffset == null && cards.length > 0 && (
          <div className="feed-end">That's everything from the last {days} days.</div>
        )}
      </main>

      {selected && (
        <ShowtimeDrawer
          showtimes={selected}
          user={user}
          groupId={groupId}
          apiBase={apiBase}
          onClose={() => setSelected(null)}
          onRsvp={handleRsvp}
          onAttendance={handleAttendance}
          onViewProfile={setProfileUserId}
        />
      )}

      {profileUserId && (
        <UserProfileDrawer
          userId={profileUserId}
          viewerId={user.id}
          apiBase={apiBase}
          onClose={() => setProfileUserId(null)}
          onAttendanceChange={() => { setAttendanceKey(k => k + 1); reload(); }}
          onOpenShowtime={id => { setProfileUserId(null); openShowtime(id); }}
        />
      )}
    </div>
  );
}

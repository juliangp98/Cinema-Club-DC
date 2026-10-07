import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import ShowtimeDrawer from "../components/ShowtimeDrawer";
import UserProfileDrawer from "../components/UserProfileDrawer";
import ReactionBar from "../components/ReactionBar";
import ChatSection from "../components/ChatSection";
import { AvatarFace } from "../ui/Avatar";
import Poster from "../ui/Poster";

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
  rsvp: (a, you) => (a.detail === "maybe" ? "might go" : you ? "are going" : "is going"),
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
          <AvatarFace user={u} />
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
        <button type="button" className="feed-poster" onClick={onOpen} aria-label={`Open ${s.movie.title}`}>
          <Poster movie={s.movie} className="feed-poster-img" />
        </button>
        <div className="feed-card-body">
          <button type="button" className="feed-title" onClick={onOpen}>{s.movie.title}</button>
          <div className="feed-meta">
            {formatWhen(s.start_time)} · {s.theatre.short_name || s.theatre.name}
            {s.format_label ? ` · ${s.format_label}` : ""}
          </div>
          {people.length > 0 && <Avatars users={people} onViewProfile={onViewProfile} />}
          {latest && (
            <div className="feed-activity">
              {latest.user.id === viewerId ? "You" : latest.user.name} {ACTIVITY[latest.kind]?.(latest, latest.user.id === viewerId)}
            </div>
          )}
        </div>
      </div>

      {expanded ? (
        <div className="feed-discussion">
          <ReactionBar reactions={s.reactions || {}} showtimeId={s.id} groupId={groupId} apiBase={apiBase} onUpdate={onReactions} />
          <ChatSection showtimeId={s.id} groupId={groupId} apiBase={apiBase} onViewProfile={onViewProfile}
                       discordThreadUrl={s.discord_thread_url} discord={s.discord} />
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
        <Link className="feed-poster" to={`/films/${movie.id}`} aria-label={movie.title}>
          <Poster movie={movie} className="feed-poster-img" />
        </Link>
        <div className="feed-card-body">
          <Link className="feed-title" to={`/films/${movie.id}`}>
            {movie.title}{movie.release_year ? ` (${movie.release_year})` : ""}
          </Link>
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

// The club's recent activity. Lives in the top bar's activity panel (R3c);
// "Did you make it?" moved to Discover.
export default function Feed({ user, apiBase, groupId }) {
  const navigate = useNavigate();
  const [cards, setCards] = useState([]);
  const [nextOffset, setNextOffset] = useState(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(null);     // one open discussion at a time
  const [selected, setSelected] = useState(null);     // showtimes for the drawer
  const [profileUserId, setProfileUserId] = useState(null);
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
    reload();
    return true;
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

      <div className="feed-main">
        {loading && !cards.length && <div className="feed-empty">Loading…</div>}
        {error && <div className="feed-empty">Couldn't load the feed. <button type="button" className="attendance-link" onClick={reload}>Try again</button></div>}
        {!loading && !error && !cards.length && (
          <div className="feed-empty">
            <p>Nothing here yet. RSVP to a screening, add films to your watchlist, or start a discussion and it'll show up here.</p>
            <button type="button" className="feed-action" onClick={() => navigate("/")}>Find something to see</button>
          </div>
        )}

        {cards.map(renderCard)}

        {nextOffset != null && (
          <button type="button" className="feed-more" onClick={loadMore}>Load more</button>
        )}
        {nextOffset == null && cards.length > 0 && (
          <div className="feed-end">That's everything from the last {days} days.</div>
        )}
      </div>

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
          onAttendanceChange={reload}
          onOpenShowtime={id => { setProfileUserId(null); openShowtime(id); }}
        />
      )}
    </div>
  );
}

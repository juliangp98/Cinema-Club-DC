import { useState, useEffect, useCallback, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import ShowtimeDrawer from "../components/ShowtimeDrawer";
import UserProfileDrawer from "../components/UserProfileDrawer";
import ReactionBar from "../components/ReactionBar";
import ChatSection from "../components/ChatSection";
import { AvatarFace, initialsStyle } from "../ui/Avatar";
import Poster from "../ui/Poster";
import TheatreLink from "../ui/TheatreLink";
import { ago, dayDateTime } from "../dates";
import { rsvp, attend } from "../api";

const timeAgo = ago, formatWhen = dayDateTime;

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
  kernels: (a, you, viewerId) => {
    const to = a.detail.to.id === viewerId ? "you" : a.detail.to.name;
    return a.detail.amount > 0 ? `gave ${to} ${a.detail.amount} 🍿` : `took ${-a.detail.amount} 🍿 from ${to}`;
  },
};

// Kernels members give each other for what they did on a screening (R10b).
const DID = { went: "went", going: "is going", maybe: "might go", commented: "commented", reacted: "reacted" };
const signed = n => (n > 0 ? `+${n}` : String(n));

function KernelPanel({ people, allowance, error, busy, onToss }) {
  return (
    <div className="kernel-panel">
      <p className="kernel-allowance">
        This week you have <strong>{allowance.give_left}</strong> to give · <strong>{allowance.take_left}</strong> to take
        <span className="kernel-hint"> — up to 3 each per screening (or take 1). Resets Monday.</span>
      </p>
      <ul className="kernel-rows">
        {people.map(p => (
          <li key={p.user.id} className="kernel-row">
            <span className="kernel-who"><strong>{p.user.name}</strong> {DID[p.did]}</span>
            <span className="kernel-net" title="Kernels from members for this screening">🍿 {signed(p.net)}</span>
            <span className="kernel-buttons" role="group" aria-label={`Kernels for ${p.user.name}`}>
              <button type="button" className="kernel-btn" onClick={() => onToss(p.user.id, -1)}
                      disabled={busy || p.mine <= -1 || (p.mine <= 0 && allowance.take_left < 1)}
                      aria-label={p.mine > 0 ? `Give ${p.user.name} one less kernel` : `Take a kernel from ${p.user.name}`}>−</button>
              <span className="kernel-mine" aria-live="polite">{p.mine ? `${signed(p.mine)} from you` : "0 from you"}</span>
              <button type="button" className="kernel-btn" onClick={() => onToss(p.user.id, 1)}
                      disabled={busy || p.mine >= 3 || (p.mine >= 0 && allowance.give_left < 1)}
                      aria-label={p.mine < 0 ? `Give back the kernel you took from ${p.user.name}` : `Give ${p.user.name} a kernel`}>+</button>
            </span>
          </li>
        ))}
      </ul>
      {error && <p className="kernel-error" role="status">{error}</p>}
    </div>
  );
}

function Avatars({ users, onViewProfile, max = 5 }) {
  return (
    <span className="feed-avatars">
      {users.slice(0, max).map(u => (
        <button
          key={u.id}
          type="button"
          className="feed-avatar"
          style={initialsStyle(u.avatar_color)}
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

function ScreeningCard({ card, viewerId, groupId, apiBase, expanded, onToggle, onOpen, onViewProfile, onReactions,
                        allowance, onToss }) {
  const [kernelsOpen, setKernelsOpen] = useState(false);
  const [kernelError, setKernelError] = useState(null);
  const [kernelBusy, setKernelBusy] = useState(false);     // one give/take at a time, so answers land in order
  const kernelPeople = card.kernels?.people || [];
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
            {formatWhen(s.start_time)} · <TheatreLink theatre={s.theatre} short />
            {s.format_label ? ` · ${s.format_label}` : ""}
          </div>
          {people.length > 0 && <Avatars users={people} onViewProfile={onViewProfile} />}
          {latest && (
            <div className="feed-activity">
              {latest.user.id === viewerId ? "You" : latest.user.name} {ACTIVITY[latest.kind]?.(latest, latest.user.id === viewerId, viewerId)}
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

      {kernelsOpen && kernelPeople.length > 0 && allowance && (
        <KernelPanel people={kernelPeople} allowance={allowance} error={kernelError} busy={kernelBusy}
                     onToss={async (uid, delta) => {
                       setKernelBusy(true);
                       setKernelError(await onToss(card.showtime.id, uid, delta));
                       setKernelBusy(false);
                     }} />
      )}

      <div className="feed-actions">
        <button type="button" className="feed-action" onClick={onToggle} aria-expanded={expanded}>
          {expanded ? "Hide discussion" : `💬 Discuss${s.message_count ? ` (${s.message_count})` : ""}`}
        </button>
        {kernelPeople.length > 0 && allowance && (
          <button type="button" className="feed-action" aria-expanded={kernelsOpen}
                  onClick={() => { setKernelsOpen(o => !o); setKernelError(null); }}>
            🍿 Kernels
          </button>
        )}
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

// Who got bingo on a month's card (R10e).
function BingoFeedCard({ card, viewerId, onViewProfile }) {
  const lines = card.winners.filter(w => w.kind === "line").map(w => w.user);
  const full = card.winners.filter(w => w.kind === "full").map(w => w.user);
  return (
    <article className="feed-card feed-recap">
      <CardHead at={card.at}>🎱 Repertory bingo · {card.month_label}</CardHead>
      <div className="feed-card-body">
        <Avatars users={card.winners.map(w => w.user)} onViewProfile={onViewProfile} max={8} />
        {full.length > 0 && <div className="feed-activity">🎉🎉 {names(full, viewerId, 3)} filled the whole card</div>}
        {lines.length > 0 && <div className="feed-activity">🎉 {names(lines, viewerId, 3)} got bingo</div>}
      </div>
    </article>
  );
}

// Monday's "last week in the club" (R10c).
function RecapCard({ card, viewerId, onViewProfile, onOpenShowtime }) {
  const r = card.recap;
  const monday = new Date(`${r.week_of}T00:00`);
  const from = new Date(monday.getTime() - 7 * 864e5);
  const span = `${from.toLocaleDateString(undefined, { month: "short", day: "numeric" })} – ${
    new Date(monday.getTime() - 864e5).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
  const plural = (n, one, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  return (
    <article className="feed-card feed-recap">
      <CardHead at={card.at}>📅 Last week in the club · {span}</CardHead>
      <ul className="recap-lines">
        {r.checkins > 0 && (
          <li>🍿 {plural(r.people_out, "member")} went out — {plural(r.checkins, "check-in")}
            {r.crew_nights > 0 && `, ${plural(r.crew_nights, "crew night")}`}</li>
        )}
        {r.top && (
          <li>
            🏆 Most seen:{" "}
            <button type="button" className="linkish" onClick={() => onOpenShowtime(r.top.screening.showtime_id)}>
              {r.top.screening.title}
            </button>{" "}
            ({r.top.screening.theatre}) — {names(r.top.users, viewerId, 3)}
          </li>
        )}
        {r.kernels.length > 0 && (
          <li>🍿 Most kernels from members: {r.kernels.map((k, i) => (
            <span key={k.user.id}>{i > 0 && ", "}
              <button type="button" className="linkish" onClick={() => onViewProfile(k.user.id)}>
                {k.user.id === viewerId ? "you" : k.user.name}
              </button> +{k.amount}</span>
          ))}</li>
        )}
        {r.polls.map(p => (
          <li key={p.id}>🗳️ <Link to={`/polls/${p.id}`}>{p.title}</Link> was scored{p.winner && ` — ${p.winner} came out on top`}</li>
        ))}
        {(r.plans > 0 || r.comments > 0) && (
          <li>{[r.plans > 0 && `🎟️ ${plural(r.plans, "plan")} made`, r.comments > 0 && `💬 ${plural(r.comments, "comment")}`]
            .filter(Boolean).join(" · ")}</li>
        )}
        {r.bingo?.length > 0 && <li>🎱 Bingo: {names(r.bingo, viewerId, 4)}</li>}
        {r.joined.length > 0 && <li>👋 Welcome, {names(r.joined, viewerId, 4)}</li>}
      </ul>
    </article>
  );
}

const seenKey = g => `cinemaclub_feed_seen_${g}`;
function readSeen(g) { try { return localStorage.getItem(seenKey(g)); } catch { return null; } }
function writeSeen(g, iso) { try { localStorage.setItem(seenKey(g), iso); } catch { /* private mode */ } }

// The club's recent activity: the Feed page (R10c: `filter` one kind,
// `divider` "new since your last visit", `endless` scrolling), a short
// preview on the Club page (`limit`), and the bell's Club tab.
export default function Feed({ user, apiBase, groupId, filter = null, limit = null, divider = false, endless = false }) {
  const navigate = useNavigate();
  const [cards, setCards] = useState([]);
  const [nextOffset, setNextOffset] = useState(null);
  const [days, setDays] = useState(90);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [expanded, setExpanded] = useState(null);     // one open discussion at a time
  const [selected, setSelected] = useState(null);     // showtimes for the drawer
  const [profileUserId, setProfileUserId] = useState(null);
  const [allowance, setAllowance] = useState(null);   // this week's kernels to give / take
  const [lastSeen] = useState(() => (divider ? readSeen(groupId) : null));   // as of this visit
  const [loadingMore, setLoadingMore] = useState(false);
  const sentinel = useRef(null);
  const loadedRef = useRef(0);
  const groupRef = useRef(groupId);   // responses for a group we've left are dropped
  groupRef.current = groupId;

  const fetchPage = useCallback(async (offset) => {
    const r = await fetch(`${apiBase}/api/feed?group_id=${groupId}&offset=${offset}${filter ? `&type=${filter}` : ""}`,
                          { credentials: "include" });
    if (!r.ok) throw new Error(String(r.status));
    return r.json();
  }, [apiBase, groupId, filter]);

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
      setAllowance(results[0].allowance || null);
      if (divider && all[0] && (!readSeen(groupId) || all[0].at > readSeen(groupId))) writeSeen(groupId, all[0].at);
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
    if (loadingMore) return;
    const forGroup = groupId;
    setLoadingMore(true);
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
    } finally {
      setLoadingMore(false);
    }
  }

  // Endless scrolling: the next page loads as the end comes into view.
  useEffect(() => {
    if (!endless || nextOffset == null || !sentinel.current || typeof IntersectionObserver === "undefined") return undefined;
    const io = new IntersectionObserver(entries => { if (entries[0].isIntersecting) loadMore(); }, { rootMargin: "400px" });
    io.observe(sentinel.current);
    return () => io.disconnect();
  });

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
    const d = await rsvp(apiBase, showtimeId, status, groupId).catch(() => null);
    if (d) {
      patchShowtime(showtimeId, d);
      reload();
    }
  }

  async function handleAttendance(showtimeId, status) {
    if (!(await attend(apiBase, showtimeId, status).catch(() => null))) return false;
    patchShowtime(showtimeId, { user_attendance: status });
    reload();
    return true;
  }

  // Give (+1) or take (−1) a kernel; returns an error message, or null.
  async function toss(showtimeId, userId, delta) {
    const r = await fetch(`${apiBase}/api/kernels/toss`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: groupId, showtime_id: showtimeId, user_id: userId, delta }),
    }).catch(() => null);
    const d = await r?.json().catch(() => null);
    if (!r?.ok || !d) return d?.error || "Couldn't do that — try again in a bit.";
    setAllowance(d.allowance);
    setCards(prev => prev.map(c => (c.showtime?.id !== showtimeId ? c : {
      ...c, kernels: { ...c.kernels, people: c.kernels.people.map(p => (p.user.id === userId ? { ...p, mine: d.mine, net: d.net } : p)) },
    })));
    return null;
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
            allowance={allowance}
            onToss={toss}
          />
        );
      case "watchlist":
        return <WatchlistCard key={card.key} {...common} onOpenShowtime={openShowtime} />;
      case "poll":
        return <PollCard key={card.key} {...common} onOpenPoll={() => navigate(`/polls/${card.poll.id}`)} />;
      case "joined":
        return <JoinedCard key={card.key} {...common} />;
      case "recap":
        return <RecapCard key={card.key} {...common} onOpenShowtime={openShowtime} />;
      case "bingo":
        return <BingoFeedCard key={card.key} {...common} />;
      default:
        return null;
    }
  }

  return (
    <div className="feed-page">

      <div className="feed-main">
        {loading && !cards.length && <div className="feed-empty">Loading…</div>}
        {error && <div className="feed-empty">Couldn't load the feed. <button type="button" className="attendance-link" onClick={reload}>Try again</button></div>}
        {!loading && !error && !cards.length && (filter ? (
          <div className="feed-empty"><p>Nothing like that in the last {days} days.</p></div>
        ) : (
          <div className="feed-empty">
            <p>Nothing here yet. RSVP to a screening, add films to your watchlist, or start a discussion and it'll show up here.</p>
            <button type="button" className="feed-action" onClick={() => navigate("/")}>Find something to see</button>
          </div>
        ))}

        {(limit ? cards.slice(0, limit) : cards).map((card, i, shown) => (
          divider && lastSeen && i > 0 && card.at <= lastSeen && shown[i - 1].at > lastSeen ? (
            <div key={card.key} className="feed-seen-group">
              <div className="feed-divider" role="separator">New since your last visit ↑</div>
              {renderCard(card)}
            </div>
          ) : renderCard(card)
        ))}

        {!limit && nextOffset != null && (
          <button type="button" ref={sentinel} className="feed-more" onClick={loadMore} disabled={loadingMore}>
            {loadingMore ? "Loading…" : "Load more"}
          </button>
        )}
        {!limit && nextOffset == null && cards.length > 0 && (
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

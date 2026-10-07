import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import SearchBox from "../ui/SearchBox";
import AttendancePrompt from "../components/AttendancePrompt";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { useShell } from "../shell/AppShell";
import { groupParam } from "../scope";
import "./DiscoverPage.css";

const SURPRISE_WHEN = [["tonight", "Tonight"], ["weekend", "This weekend"], ["week", "This week"]];
// Home page order (R3c): planning-friendly sections near the top. "@…" are the
// non-shelf sections; shelves not listed become "more ways to browse" chips.
const LAYOUT = ["friends", "rare", "@doubles", "@spotlights", "classics", "awards", "arthouse",
                "one-night", "on-film", "big-screen", "events", "opening", "last-chance"];

const timeLabel = iso => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const dayLabel = iso => new Date(iso).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

function Surprise({ apiBase, groupId }) {
  const [when, setWhen] = useState("tonight");
  const [pick, setPick] = useState(null);
  const [seen, setSeen] = useState([]);
  const [state, setState] = useState("idle");   // idle | loading | empty

  async function spin(nextWhen = when, exclude = seen) {
    setState("loading");
    const qs = new URLSearchParams({ when: nextWhen, exclude: exclude.join(",") });
    const r = await fetch(`${apiBase}/api/discover/surprise?${groupParam(groupId)}${qs}`, { credentials: "include" }).catch(() => null);
    if (r?.ok) {
      const p = await r.json();
      setPick(p);
      setSeen([...exclude, p.movie.id]);
      setState("idle");
    } else {
      setPick(null);
      setState("empty");
    }
  }

  return (
    <section className="surprise">
      <div className="surprise-head">
        <span className="deco surprise-title">Surprise me</span>
        <div className="surprise-when" role="group" aria-label="When">
          {SURPRISE_WHEN.map(([k, label]) => (
            <button key={k} type="button" className={`chip${when === k ? " gold" : ""}`}
                    onClick={() => { setWhen(k); setSeen([]); if (pick) spin(k, []); }}>
              {label}
            </button>
          ))}
        </div>
      </div>
      {pick ? (
        <div className="surprise-pick">
          <Link to={`/films/${pick.movie.id}`} className="surprise-poster">
            {pick.movie.poster_url ? <img src={pick.movie.poster_url} alt="" /> : <span>{pick.movie.title}</span>}
          </Link>
          <div className="surprise-text">
            <Link to={`/films/${pick.movie.id}`} className="surprise-film">
              {pick.movie.title}{pick.movie.year ? ` (${pick.movie.year})` : ""}
            </Link>
            <div className="surprise-next">
              {dayLabel(pick.next.start_time)} · {timeLabel(pick.next.start_time)} · {pick.next.theatre}
              {pick.next.format_label ? ` · ${pick.next.format_label}` : ""}
            </div>
            {pick.when !== when && <div className="surprise-note">Nothing left {when === "tonight" ? "tonight" : "then"} — here's one this week.</div>}
            {pick.reasons.length > 0 && (
              <div className="surprise-reasons">{pick.reasons.map(r => <span key={r} className="chip gold">{r}</span>)}</div>
            )}
            <div className="surprise-actions">
              <Link className="btn btn-primary btn-sm" to={`/films/${pick.movie.id}`}>See showings</Link>
              <button className="btn btn-sm" onClick={() => spin()} disabled={state === "loading"}>🎲 Spin again</button>
            </div>
          </div>
        </div>
      ) : (
        <div className="surprise-empty">
          <p>{state === "empty" ? "Nothing left to suggest for then — try a wider window." : "Can't decide? Let the projector pick."}</p>
          <button className="btn btn-primary" onClick={() => spin()} disabled={state === "loading"}>
            🎲 {state === "loading" ? "Picking…" : "Pick a film"}
          </button>
        </div>
      )}
    </section>
  );
}

// "You, Bo +2" — the viewer reads as "You", listed first.
function whoGoing(users, viewerId) {
  const sorted = [...users].sort((a, b) => (b.id === viewerId) - (a.id === viewerId));
  const labels = sorted.map(u => (u.id === viewerId ? "You" : u.name));
  const shown = labels.slice(0, 2).join(", ");
  return labels.length > 2 ? `${shown} +${labels.length - 2}` : labels.length === 2 ? labels.join(" and ") : shown;
}

// "This week in the club": what members are going to, open polls, and new
// comments, with a way into the full activity panel.
function ClubWeek({ apiBase, groupId, viewerId, refreshKey, onOpenShowtime, onOpenActivity }) {
  const [week, setWeek] = useState(null);
  useEffect(() => {
    let live = true;
    fetch(`${apiBase}/api/club/week?group_id=${groupId}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(d => { if (live) setWeek(d); })
      .catch(() => {});
    return () => { live = false; };
  }, [apiBase, groupId, refreshKey]);
  if (!week) return null;

  const { plans, polls, comments } = week;
  const empty = !plans.length && !polls.length && !comments.count;
  return (
    <section className="club-week" aria-label="This week in the club">
      <div className="club-week-head">
        <span className="deco club-week-title">This week in the club</span>
        <button type="button" className="shelf-all" onClick={onOpenActivity}>All activity →</button>
      </div>
      {empty ? (
        <p className="club-week-empty">Nothing planned yet this week. Find something below and be the first to RSVP.</p>
      ) : (
        <div className="club-week-row">
          {plans.map(p => (
            <button key={p.showtime_id} type="button" className={`club-week-item${p.you_going ? " mine" : ""}`}
                    onClick={() => onOpenShowtime(p.showtime_id)}>
              {p.movie.poster_url
                ? <img className="club-week-poster" src={p.movie.poster_url} alt="" loading="lazy" />
                : <span className="club-week-icon">🎟️</span>}
              <span className="club-week-text">
                <span className="club-week-name">{p.movie.title}</span>
                <span className="club-week-meta">{dayLabel(p.start_time)} · {timeLabel(p.start_time)} · {p.theatre}</span>
                <span className="club-week-who">🎟️ {whoGoing(p.going, viewerId)} going</span>
              </span>
            </button>
          ))}
          {polls.map(p => (
            <Link key={p.id} to={`/polls/${p.id}`} className="club-week-item">
              <span className="club-week-icon">🗳️</span>
              <span className="club-week-text">
                <span className="club-week-name">{p.title}</span>
                <span className={`club-week-meta${p.you_voted ? "" : " nudge"}`}>{p.you_voted ? "You voted ✓" : "Open poll · vote"}</span>
              </span>
            </Link>
          ))}
          {comments.count > 0 && (
            <button type="button" className="club-week-item" onClick={onOpenActivity}>
              <span className="club-week-icon">💬</span>
              <span className="club-week-text">
                <span className="club-week-name">{comments.count} comment{comments.count === 1 ? "" : "s"} this week</span>
                {comments.latest && (
                  <span className="club-week-meta">{comments.latest.user} on {comments.latest.movie}: “{comments.latest.body}”</span>
                )}
              </span>
            </button>
          )}
        </div>
      )}
    </section>
  );
}

function Shelf({ s }) {
  return (
    <section className="shelf">
      <SectionTitle action={<Link className="shelf-all" to={`/browse?shelf=${s.key}&when=2weeks`}>See all {s.total} →</Link>}>
        {s.title}
      </SectionTitle>
      <p className="shelf-blurb">{s.blurb}</p>
      <div className="shelf-row">
        {s.items.map(c => <PosterCard key={c.movie.id} card={c} />)}
      </div>
    </section>
  );
}

function DoubleFeatures({ items }) {
  return (
    <section className="shelf">
      <SectionTitle>Double features</SectionTitle>
      <p className="shelf-blurb">Two films, one theatre, one evening — with time for a drink in between.</p>
      <div className="doubles">
        {items.slice(0, 6).map((d, i) => (
          <div key={i} className="double">
            {[d.first, d.second].map((c, j) => (
              <Link key={j} to={`/films/${c.movie.id}`} className="double-film">
                {c.movie.poster_url && <img src={c.movie.poster_url} alt="" loading="lazy" />}
                <span className="double-time">{timeLabel(c.next.start_time)}</span>
                <span className="double-title">{c.movie.title}</span>
              </Link>
            ))}
            <div className="double-meta">{d.theatre} · {dayLabel(d.first.next.start_time)} · {d.gap_minutes}-min break</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function Spotlights({ items }) {
  return (
    <section className="shelf">
      <SectionTitle>Spotlights</SectionTitle>
      <p className="shelf-blurb">Directors and stars with several films playing this month.</p>
      <div className="spotlights">
        {items.map(sp => (
          <Link key={sp.name} className="spotlight" to={`/browse?q=${encodeURIComponent(sp.name)}&when=month`}>
            <div className="spotlight-head">
              <span className="spotlight-name">{sp.name}</span>
              <span className="spotlight-count">{sp.count} films · {sp.role}</span>
            </div>
            <div className="spotlight-posters">
              {sp.films.slice(0, 4).map(f => f.movie.poster_url
                ? <img key={f.movie.id} src={f.movie.poster_url} alt={f.movie.title} loading="lazy" />
                : <span key={f.movie.id} className="spotlight-ph">{f.movie.title}</span>)}
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}

// Visitors (and members without a club) get this instead of the club strip.
function JoinClub({ user }) {
  return (
    <section className="join-club">
      <div>
        <span className="deco join-club-title">{user ? "Find your club" : "Better with a club"}</span>
        <p>
          Clubs see who's going to what, plan screenings together, vote in polls and talk films — on the site and in Discord.
          {user ? " Join one to see it here." : " Sign in to join one; browsing what's playing is open to everyone."}
        </p>
      </div>
      <Link className="btn btn-primary" to={user ? "/groups" : "/signin?next=%2Fgroups"}>{user ? "Browse clubs" : "Sign in"}</Link>
    </section>
  );
}

// Personal plans from before you joined (as a guest or without a club): asked
// once per club whether to share them — each one ticked moves into the club.
function BringPlans({ apiBase, groupId, user, clubName, onShared }) {
  const key = `cinemaclub_plans_asked_${groupId}_${user.id}`;
  const [items, setItems] = useState([]);
  const [picked, setPicked] = useState(new Set());
  const [busy, setBusy] = useState(false);
  const [asked, setAsked] = useState(() => { try { return !!localStorage.getItem(key); } catch { return false; } });
  useEffect(() => {
    if (asked) return;
    fetch(`${apiBase}/api/groups/${groupId}/personal-plans`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : { items: [] }))
      .then(d => { setItems(d.items); setPicked(new Set(d.items.map(i => i.showtime_id))); })
      .catch(() => {});
  }, [apiBase, groupId, asked]);
  if (asked || !items.length) return null;
  const done = () => { try { localStorage.setItem(key, "1"); } catch { /* private mode */ } setAsked(true); };
  async function share() {
    setBusy(true);
    const r = await fetch(`${apiBase}/api/groups/${groupId}/personal-plans`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ showtime_ids: [...picked] }),
    }).catch(() => null);
    setBusy(false);
    if (r?.ok) { done(); onShared?.(); }
  }
  const toggle = id => setPicked(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <section className="join-club bring-plans" aria-label="Share your plans">
      <div>
        <span className="deco join-club-title">Share your plans with {clubName || "the club"}?</span>
        <p>Only you can see these right now. Shared ones show who's going in the club. (Club members can already see your watchlist.)</p>
        <ul className="bring-plans-list">
          {items.map(i => (
            <li key={i.showtime_id}>
              <label>
                <input type="checkbox" checked={picked.has(i.showtime_id)} onChange={() => toggle(i.showtime_id)} />
                <span><strong>{i.title}</strong> · {dayLabel(i.start_time)} {timeLabel(i.start_time)} · {i.theatre}</span>
              </label>
            </li>
          ))}
        </ul>
      </div>
      <div className="bring-plans-actions">
        <button className="btn btn-primary" onClick={share} disabled={busy || !picked.size}>
          Share {picked.size || ""} with the club
        </button>
        <button className="btn btn-ghost" onClick={done}>Keep them private</button>
      </div>
    </section>
  );
}

// The home page: the club's week, then ways into what's playing.
export default function DiscoverPage({ user, apiBase, groupId }) {
  const navigate = useNavigate();
  const shell = useShell();
  const [data, setData] = useState(null);
  const [error, setError] = useState(false);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey(k => k + 1), []);
  const { openShowtime, sheet } = useShowtimeSheet({ user, apiBase, groupId, onChange: refresh });

  const load = useCallback(() => {
    fetch(`${apiBase}/api/discover?${groupParam(groupId)}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(d => { setData(d); setError(false); })
      .catch(() => setError(true));
  }, [apiBase, groupId]);
  useEffect(() => { setData(null); load(); }, [load]);

  async function answerAttendance(showtimeId, status) {
    const r = await fetch(`${apiBase}/api/attendance`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ showtime_id: showtimeId, status }),
    }).catch(() => null);
    if (r?.ok) refresh();
    return !!r?.ok;
  }

  const byKey = Object.fromEntries((data?.shelves || []).map(s => [s.key, s]));
  const sections = [];
  for (const key of LAYOUT) {
    if (key === "@doubles" && data?.double_features.length) sections.push(<DoubleFeatures key={key} items={data.double_features} />);
    else if (key === "@spotlights" && data?.spotlights.length) sections.push(<Spotlights key={key} items={data.spotlights} />);
    else if (byKey[key]) sections.push(<Shelf key={key} s={byKey[key]} />);
  }
  const more = (data?.shelves || []).filter(s => !LAYOUT.includes(s.key));

  return (
    <div className="page discover">
      <PageHeader title="Discover" subtitle={`What's playing across ${groupId ? "the club's theatres" : "every DC-area theatre we track"} in the next two weeks.`} />
      <SearchBox onSearch={q => navigate(`/browse?q=${encodeURIComponent(q)}&when=month`)} />

      {groupId && shell.canParticipate && user && (
        <BringPlans apiBase={apiBase} groupId={groupId} user={user} clubName={shell.group?.name} onShared={refresh} />
      )}
      {groupId ? (
        <>
          <AttendancePrompt apiBase={apiBase} refreshKey={refreshKey} onAnswer={answerAttendance} onOpenShowtime={openShowtime} />
          <ClubWeek apiBase={apiBase} groupId={groupId} viewerId={user.id} refreshKey={refreshKey}
                    onOpenShowtime={openShowtime} onOpenActivity={shell.openActivity} />
        </>
      ) : <JoinClub user={user} />}

      <div className="discover-top">
        <Surprise apiBase={apiBase} groupId={groupId} />
        <section className="moods">
          <span className="deco moods-title">In the mood for…</span>
          <div className="moods-chips">
            {(data?.moods || []).map(m => (
              <Link key={m.key} className="mood-chip" to={`/browse?mood=${m.key}&when=2weeks`}>{m.label}</Link>
            ))}
          </div>
        </section>
      </div>

      {error && <p className="discover-empty">Couldn't load Discover right now.</p>}
      {!data && !error && <p className="discover-empty">Loading…</p>}

      {sections}

      {more.length > 0 && (
        <section className="shelf">
          <SectionTitle>More ways to browse</SectionTitle>
          <div className="moods-chips">
            {more.map(s => (
              <Link key={s.key} className="mood-chip" to={`/browse?shelf=${s.key}&when=2weeks`}>
                {s.title} <span className="mood-count">{s.total}</span>
              </Link>
            ))}
            <Link className="mood-chip" to="/browse?when=week">Everything this week →</Link>
          </div>
        </section>
      )}

      {sheet}
    </div>
  );
}

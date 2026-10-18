import { useState, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import PageHeader, { PageMeta, SectionTitle } from "../ui/PageHeader";
import PosterCard from "../ui/PosterCard";
import SearchBox from "../ui/SearchBox";
import Poster from "../ui/Poster";
import TheatreLink from "../ui/TheatreLink";
import Loading, { LoadError } from "../ui/Loading";
import Panel from "../ui/Panel";
import { useJson, getJson, send, attend, hideFilm } from "../api";
import AttendancePrompt from "../components/AttendancePrompt";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { useShell } from "../shell/AppShell";
import { groupParam } from "../scope";
import "./DiscoverPage.css";
import { time, dayDate } from "../dates";
import { AnnouncedCard } from "../ui/TicketChips";

const SURPRISE_WHEN = [["tonight", "Tonight"], ["weekend", "This weekend"], ["week", "This week"]];
// Home page order (R3c): planning-friendly sections near the top. "@…" are the
// non-shelf sections; shelves not listed become "more ways to browse" chips.
export const LAYOUT = ["friends", "for-you", "rare", "@announced", "@doubles", "@spotlights", "classics", "awards", "arthouse",
                "one-night", "on-film", "big-screen", "events", "opening", "last-chance"];

const timeLabel = time, dayLabel = dayDate;

function Surprise({ apiBase, groupId }) {
  const [when, setWhen] = useState("tonight");
  const [pick, setPick] = useState(null);
  const [seen, setSeen] = useState([]);
  const [state, setState] = useState("idle");   // idle | loading | empty

  async function spin(nextWhen = when, exclude = seen) {
    setState("loading");
    const qs = new URLSearchParams({ when: nextWhen, exclude: exclude.join(",") });
    const p = await getJson(`${apiBase}/api/discover/surprise?${groupParam(groupId)}${qs}`, { cache: false }).catch(() => null);
    if (p) {
      setPick(p);
      setSeen([...exclude, p.movie.id]);
      setState("idle");
    } else {
      setPick(null);
      setState("empty");
    }
  }

  return (
    <section className="surprise" id="surprise">
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
            <Poster movie={pick.movie} fill loading="eager" />
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
export function ClubWeek({ apiBase, groupId, viewerId, refreshKey, onOpenShowtime, onOpenActivity }) {
  const [week, setWeek] = useState(null);
  useEffect(() => {
    let live = true;
    getJson(`${apiBase}/api/club/week?group_id=${groupId}`)
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
        <button type="button" className="ui-section-link" onClick={onOpenActivity}>All activity →</button>
      </div>
      {empty ? (
        <p className="club-week-empty">Nothing planned yet this week. Find something below and be the first to RSVP.</p>
      ) : (
        <div className="club-week-row">
          {plans.map(p => (
            <button key={p.showtime_id} type="button" className={`club-week-item${p.you_going ? " mine" : ""}`}
                    onClick={() => onOpenShowtime(p.showtime_id)}>
              <Poster movie={p.movie} className="club-week-poster" />
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

// Discover's sections, also used on theatre pages: `scope` narrows their
// "See all" links (e.g. "&theatres=afi").
// `onHide` (For you, R13) adds "Not for me" under each film; it leaves the row at once.
export function Shelf({ s, scope = "", onHide }) {
  const [gone, setGone] = useState(() => new Set());
  const items = s.items.filter(c => !gone.has(c.movie.id));
  if (!items.length) return null;
  const hide = id => { setGone(prev => new Set(prev).add(id)); onHide(id); };
  return (
    <section className="shelf" id={`shelf-${s.key}`}>
      <SectionTitle link={{ to: `/browse?shelf=${s.key}&when=2weeks${scope}`, label: `See all ${s.total} →` }}>
        {s.title}
      </SectionTitle>
      <p className="shelf-blurb">{s.blurb}</p>
      <div className="shelf-row">
        {items.map(c => (onHide ? (
          <div key={c.movie.id} className="poster-card-wrap">
            <PosterCard card={c} />
            <button type="button" className="linkish poster-card-hide" onClick={() => hide(c.movie.id)}
                    aria-label={`Not for me: ${c.movie.title}`}>Not for me</button>
          </div>
        ) : <PosterCard key={c.movie.id} card={c} />))}
      </div>
    </section>
  );
}

// Where For you would be, until you've told us what you like (R13).
export function TasteNudge({ userId }) {
  const shell = useShell() || {};
  const key = `cinemaclub_taste_nudge_${userId}`;
  const [gone, setGone] = useState(() => { try { return !!localStorage.getItem(key); } catch { return false; } });
  if (gone) return null;
  const later = () => { try { localStorage.setItem(key, "1"); } catch { /* private mode */ } setGone(true); };
  return (
    <Panel tone="callout" title="Make Discover yours" actions={<>
      <button type="button" className="btn btn-primary" onClick={() => shell.editTaste?.()}>Pick what you like</button>
      <button type="button" className="btn btn-ghost" onClick={later}>Not now</button>
    </>}>
      <p>Tell us the genres, films, people and theatres you love (and what you're not into), and this spot fills with films for you.</p>
    </Panel>
  );
}

// `scope` ("&theatres=afi") → the See-all pages' query string.
const moreQuery = scope => (scope ? `?${scope.replace(/^&/, "")}` : "");

export function DoubleCard({ d, showDay = true }) {
  return (
    <div className="double">
      {[d.first, d.second].map((c, j) => (
        <Link key={j} to={`/films/${c.movie.id}`} className="double-film">
          <Poster movie={c.movie} className="double-poster" />
          <span className="double-time">{timeLabel(c.next.start_time)}</span>
          <span className="double-title">{c.movie.title}</span>
        </Link>
      ))}
      <div className="double-meta">
        <TheatreLink theatre={{ slug: d.theatre_slug, name: d.theatre, color: d.theatre_color }} />
        {showDay && <> · {dayLabel(d.first.next.start_time)}</>} · {d.gap_minutes}-min break
        {d.also?.length > 0 && <div className="double-also">Also {d.also.map(dayLabel).join(", ")}</div>}
      </div>
    </div>
  );
}

export function DoubleFeatures({ items, scope = "" }) {
  return (
    <section className="shelf">
      <SectionTitle link={{ to: `/discover/doubles${moreQuery(scope)}`, label: "See all →" }}>
        Double features
      </SectionTitle>
      <p className="shelf-blurb">Two films, one theatre, one evening — with time for a drink in between.</p>
      <div className="doubles">
        {items.slice(0, 6).map((d, i) => <DoubleCard key={i} d={d} />)}
      </div>
    </section>
  );
}

// Films a theatre has announced whose tickets aren't on sale yet (R8b).
export function Announced({ items }) {
  return (
    <section className="shelf">
      <SectionTitle>Announced — tickets soon</SectionTitle>
      <p className="shelf-blurb">Coming, but not on sale yet. Watchlist one and we'll tell you the moment tickets are.</p>
      <div className="shelf-row">
        {items.map(a => <AnnouncedCard key={`${a.theatre.slug}:${a.movie.id}`} a={a} />)}
      </div>
    </section>
  );
}

export function SpotlightCard({ sp, scope = "", posters = 4 }) {
  return (
    <Link className="spotlight" to={`/browse?person=${encodeURIComponent(sp.name)}&when=month${scope}`}>
      <div className="spotlight-head">
        <span className="spotlight-name">{sp.name}</span>
        <span className="spotlight-count">{sp.count} films · {sp.role}</span>
      </div>
      <div className="spotlight-posters" style={{ "--n": posters }}>
        {sp.films.slice(0, posters).map(f => <Poster key={f.movie.id} movie={f.movie} className="spotlight-poster" alt={f.movie.title} />)}
      </div>
    </Link>
  );
}

export function Spotlights({ items, scope = "" }) {
  return (
    <section className="shelf">
      <SectionTitle link={{ to: `/discover/spotlights${moreQuery(scope)}`, label: "See all →" }}>
        Spotlights
      </SectionTitle>
      <p className="shelf-blurb">Directors and stars with several films playing this month.</p>
      <div className="spotlights">
        {items.map(sp => <SpotlightCard key={`${sp.role}:${sp.name}`} sp={sp} scope={scope} />)}
      </div>
    </section>
  );
}

// What Discover covers, under the search (R12): the club's theatres (one tap
// to each), how far ahead it looks, and every theatre (the first chip goes
// there too, so phones needn't swipe for it).
const COVERAGE_SHOWN = 4;
export function Coverage({ apiBase, group }) {
  const { data: theatres } = useJson(`${apiBase}/api/theatres`);
  if (!theatres) return null;
  const picked = group?.theatres?.length ? theatres.filter(t => group.theatres.includes(t.slug)) : null;
  const rest = picked ? picked.length - COVERAGE_SHOWN : 0;
  const items = picked ? [
    { key: "n", icon: "🎭", label: `The club's ${picked.length} theatre${picked.length === 1 ? "" : "s"}`, gold: true, to: "/theatres" },
    ...picked.slice(0, COVERAGE_SHOWN).map(t => ({ key: t.slug, node: <TheatreLink theatre={t} short /> })),
    rest > 0 && { key: "rest", label: `+${rest} more`, to: "/theatres", title: picked.slice(COVERAGE_SHOWN).map(t => t.name).join(", ") },
  ] : [{ key: "n", icon: "🎭", label: `${group ? "All " : ""}${theatres.length} DC-area theatres`, gold: true, to: "/theatres" }];
  return <PageMeta className="discover-coverage" label="What Discover covers"
                   items={[...items, { key: "when", icon: "📅", label: "Next 2 weeks" },
                           { key: "all", label: "All theatres →", to: "/theatres", more: true }]} />;
}

// Visitors (and members without a club) get this instead of the club strip.
function JoinClub({ user }) {
  return (
    <Panel tone="callout" title={user ? "Find your club" : "Better with a club"}
           actions={<Link className="btn btn-primary" to={user ? "/groups" : "/signin?next=%2Fgroups"}>{user ? "Browse clubs" : "Sign in"}</Link>}>
      <p>
        Clubs see who's going to what, plan screenings together, vote in polls and talk films — on the site and in Discord.
        {user ? " Join one to see it here." : " Sign in to join one; browsing what's playing is open to everyone."}
      </p>
    </Panel>
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
    getJson(`${apiBase}/api/groups/${groupId}/personal-plans`, { cache: false })
      .then(d => { setItems(d.items); setPicked(new Set(d.items.map(i => i.showtime_id))); })
      .catch(() => {});
  }, [apiBase, groupId, asked]);
  if (asked || !items.length) return null;
  const done = () => { try { localStorage.setItem(key, "1"); } catch { /* private mode */ } setAsked(true); };
  async function share() {
    setBusy(true);
    const ok = await send(`${apiBase}/api/groups/${groupId}/personal-plans`, "POST", { showtime_ids: [...picked] })
      .then(() => true, () => false);
    setBusy(false);
    if (ok) { done(); onShared?.(); }
  }
  const toggle = id => setPicked(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  return (
    <Panel tone="callout" className="bring-plans" aria-label="Share your plans" title={`Share your plans with ${clubName || "the club"}?`}
           actions={<>
             <button className="btn btn-primary" onClick={share} disabled={busy || !picked.size}>
               Share {picked.size || ""} with the club
             </button>
             <button className="btn btn-ghost" onClick={done}>Keep them private</button>
           </>}>
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
    </Panel>
  );
}

// The home page: the club's week, then ways into what's playing.
export default function DiscoverPage({ user, apiBase, groupId }) {
  const navigate = useNavigate();
  const shell = useShell();
  const { data, error, reload } = useJson(`${apiBase}/api/discover?${groupParam(groupId)}`);
  useEffect(() => { if (shell.tasteVersion) reload(); }, [shell.tasteVersion, reload]);     // taste changed: new picks
  const hide = id => hideFilm(apiBase, id).catch(() => {});
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey(k => k + 1), []);
  const { openShowtime, sheet } = useShowtimeSheet({ user, apiBase, groupId, onChange: refresh });


  async function answerAttendance(showtimeId, status) {
    const ok = !!(await attend(apiBase, showtimeId, status).catch(() => null));
    if (ok) refresh();
    return ok;
  }

  const byKey = Object.fromEntries((data?.shelves || []).map(s => [s.key, s]));
  const sections = [];
  for (const key of LAYOUT) {
    if (key === "@announced" && data?.announced?.length) sections.push(<Announced key={key} items={data.announced} />);
    else if (key === "@doubles" && data?.double_features.length) sections.push(<DoubleFeatures key={key} items={data.double_features} />);
    else if (key === "@spotlights" && data?.spotlights.length) sections.push(<Spotlights key={key} items={data.spotlights} />);
    else if (key === "for-you" && user && data?.taste_set === false && !byKey[key]) sections.push(<TasteNudge key={key} userId={user.id} />);
    else if (byKey[key]) sections.push(<Shelf key={key} s={byKey[key]} onHide={key === "for-you" ? hide : undefined} />);
  }
  const more = (data?.shelves || []).filter(s => !LAYOUT.includes(s.key));

  return (
    <div className="page discover">
      <PageHeader title="Discover" tour="discover" />
      <div id="site-search"><SearchBox apiBase={apiBase} groupId={groupId} onSearch={q => q && navigate(`/browse?q=${encodeURIComponent(q)}&when=month`)} /></div>
      <Coverage apiBase={apiBase} group={groupId ? shell.group : null} />

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

      {error && !data && <LoadError what="Discover" onRetry={reload} />}
      {!data && !error && <Loading context="discover" />}

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

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { Link, useSearchParams } from "react-router-dom";
import PosterImage from "../ui/Poster";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import FilterSheet, { listOf } from "../ui/FilterSheet";
import Avatar from "../ui/Avatar";
import { Segmented } from "../ui/TicketRow";
import ShowtimeDrawer from "../components/ShowtimeDrawer";
import UserProfileDrawer from "../components/UserProfileDrawer";
import AttendancePrompt from "../components/AttendancePrompt";
import "./DiscoverPage.css";        // the Filters sheet looks the same as Browse's
import "./Calendar.css";
import { groupParam } from "../scope";

// The calendar (R4): Agenda (a poster grid per day), Week (columns) and Month
// (overview; tap a day for just that day). A film playing at several theatres
// on a day is one entry. View, date and filters live in the URL; the filters
// are Browse's (same names, applied by the same server code), plus who's going.

// Deep links from Discord: /calendar?showtime=<id> opens the screening,
// ?theatre=<slug> pre-filters. Captured once at module load (StrictMode
// would otherwise consume them on its first mount).
const DEEP_LINK = (() => {
  const params = new URLSearchParams(window.location.search);
  const link = { showtime: params.get("showtime"), theatre: params.get("theatre") };
  if (link.showtime || link.theatre) {
    params.delete("showtime");
    params.delete("theatre");
    if (link.theatre) params.set("theatres", link.theatre);
    const rest = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (rest ? `?${rest}` : ""));
  }
  return link;
})();

const VIEWS = [{ status: "agenda", label: "Agenda" }, { status: "week", label: "Week" }, { status: "month", label: "Month" }];
const MULTI = new Set(["theatres", "regions", "genres", "format", "members"]);
const FILTER_KEYS = ["theatres", "regions", "genres", "decade", "format", "time", "rarity", "club", "runtime", "mood", "shelf", "q", "members"];
// Quick pills: the club's own two, then smart ones after Discover's main
// sections (shelf pills replace each other). Phones show the first few smart
// pills and a "+N more" chip.
const CLUB_PILLS = [["club", "going", "Friends going"], ["club", "mine", "My plans"]];
const SMART_PILLS = [["rarity", "rare", "Rare"], ["shelf", "one-night", "One night only"], ["format", "film", "On film"],
                     ["shelf", "classics", "Classics"], ["shelf", "arthouse", "Arthouse"], ["shelf", "awards", "Award winners"],
                     ["shelf", "events", "Special events"], ["time", "late", "Late night"]];
const PHONE_PILLS = 3;
const AGENDA_SPAN = 14;
const WEEK_TOP = 8;               // films shown per day in Week before "+N more"

const pad = n => String(n).padStart(2, "0");
const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const parseYmd = s => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || ""); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const time = iso => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
const dayTitle = (d, today) => {
  const label = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  const diff = Math.round((startOfDay(d) - today) / 864e5);
  return diff === 0 ? `Today · ${label}` : diff === 1 ? `Tomorrow · ${label}` : label;
};
const short = d => d.toLocaleDateString("en-US", { month: "short", day: "numeric" });

// The days a view covers: [start, end) plus the grid for Month.
function viewRange(view, anchor, span) {
  if (view === "month") {
    const first = new Date(anchor.getFullYear(), anchor.getMonth(), 1);
    const start = addDays(first, -first.getDay());
    const last = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 0);
    return { start, end: addDays(last, 7 - last.getDay()) };
  }
  return { start: anchor, end: addDays(anchor, view === "week" ? 7 : span) };
}

function passes(s, members) {
  if (!members.length) return true;
  return [...(s.attendees || []), ...(s.maybes || [])].some(a => members.includes(String(a.id)));
}

// {day: [entry]}: one entry per film per day, most interesting first
// (you're going, then friends, rare, recommended), then soonest.
function groupByDay(showtimes, userId) {
  const days = new Map();
  for (const s of showtimes) {
    const day = ymd(new Date(s.start_time));
    if (!days.has(day)) days.set(day, new Map());
    const films = days.get(day);
    if (!films.has(s.movie.id)) films.set(s.movie.id, { movie: s.movie, shows: [], going: new Map(), rare: null, recommended: false });
    const e = films.get(s.movie.id);
    e.shows.push(s);
    for (const a of s.attendees || []) e.going.set(a.id, a);
    if (s.rare && (!e.rare || s.rare.length > e.rare.length)) e.rare = s.rare;
    if (s.recommended) e.recommended = true;
  }
  const out = {};
  for (const [day, films] of days) {
    out[day] = [...films.values()].map(e => {
      const going = [...e.going.values()];
      const youGoing = e.shows.some(s => s.user_rsvp === "going" || s.user_rsvp === "maybe");
      const theatres = new Map();
      for (const s of e.shows) {
        if (!theatres.has(s.theatre.id)) theatres.set(s.theatre.id, { theatre: s.theatre, shows: [] });
        theatres.get(s.theatre.id).shows.push(s);
      }
      return { ...e, going, youGoing, byTheatre: [...theatres.values()],
               score: (youGoing ? 100 : 0) + 10 * going.filter(a => a.id !== userId).length + (e.rare ? 5 : 0) + (e.recommended ? 2 : 0) };
    }).sort((a, b) => b.score - a.score || new Date(a.shows[0].start_time) - new Date(b.shows[0].start_time));
  }
  return out;
}

function Poster({ movie, size = "sm" }) {
  return <PosterImage movie={movie} className={`cal-poster ${size}`} />;
}

// Times grouped by theatre; each opens that theatre's screenings of the film that day.
function TimeChips({ entry, onOpen, compact = false }) {
  return (
    <div className={`cal-times${compact ? " compact" : ""}`}>
      {entry.byTheatre.map(({ theatre, shows }) => (
        <div key={theatre.id} className="cal-times-theatre">
          <span className="cal-theatre" style={{ "--tcolor": theatre.color }}>{theatre.short_name || theatre.name}</span>
          {shows.map(s => (
            <button key={s.id} type="button" onClick={() => onOpen(shows, s)}
                    className={`cal-time${s.user_rsvp === "going" ? " going" : s.user_rsvp === "maybe" ? " maybe" : ""}${s.is_sold_out ? " sold-out" : ""}`}
                    title={[s.format_label, s.event_label, s.is_sold_out && "Sold out"].filter(Boolean).join(" · ") || undefined}>
              {time(s.start_time)}{s.format_label && !compact ? <span className="cal-time-fmt">{s.format_label}</span> : null}
            </button>
          ))}
        </div>
      ))}
    </div>
  );
}

// Agenda: a poster tile per film, with the essentials summarized: first time
// (+ how many more), theatres, who's going, rare. Tap for the screening.
function AgendaTile({ entry, onOpen }) {
  const m = entry.movie;
  const first = entry.byTheatre[0];
  const times = entry.shows.length;
  const theatres = entry.byTheatre.map(t => t.theatre.short_name || t.theatre.name);
  return (
    <article className={`cal-tile${entry.youGoing ? " mine" : ""}`}>
      <button type="button" className="cal-tile-poster" onClick={() => onOpen(first.shows, first.shows[0])} aria-label={`${m.title} — showtimes`}>
        <PosterImage movie={m} fill />
        {entry.rare && <span className="cal-pill rare" title={entry.rare.join(" · ")}>Rare</span>}
        {entry.going.length > 0 && <span className="cal-pill going" title={entry.going.map(u => u.name).join(", ")}>🎟️ {entry.going.length}</span>}
        {entry.youGoing && <span className="cal-pill you">You</span>}
      </button>
      <Link to={`/films/${m.id}`} className="cal-tile-title">{m.title}</Link>
      <div className="cal-tile-when">
        <button type="button" className="cal-tile-time" onClick={() => onOpen(first.shows, first.shows[0])}>{time(entry.shows[0].start_time)}</button>
        {times > 1 && <span className="cal-tile-more">+{times - 1}</span>}
      </div>
      <div className="cal-tile-where" title={theatres.join(", ")}>
        {theatres.slice(0, 2).join(", ")}{theatres.length > 2 ? ` +${theatres.length - 2}` : ""}
      </div>
    </article>
  );
}

function WeekCard({ entry, onOpen }) {
  const m = entry.movie;
  return (
    <div className={`cal-card${entry.youGoing ? " mine" : ""}`}>
      <button type="button" className="cal-card-head" onClick={() => onOpen(entry.byTheatre[0].shows, entry.byTheatre[0].shows[0])}>
        <Poster movie={m} />
        <span className="cal-card-title">
          {entry.rare && <span className="cal-rare-dot" title={`Rare · ${entry.rare.join(" · ")}`} />}
          {m.title}
        </span>
      </button>
      <TimeChips entry={entry} onOpen={onOpen} compact />
      {entry.going.length > 0 && (
        <span className="cal-card-going">
          {entry.going.slice(0, 5).map(u => <span key={u.id} className="cal-dot" style={{ background: u.avatar_color }} title={u.name} />)}
          {entry.going.length} going
        </span>
      )}
    </div>
  );
}

export default function Calendar({ user, apiBase, groupId }) {
  const [params, setParams] = useSearchParams();
  const today = startOfDay(new Date());
  // The URL's view, else the last one you used, else Week on desktop / Agenda on phones.
  const [fallbackView] = useState(() => {
    let v = null;
    try { v = localStorage.getItem("cinemaclub_cal_view"); } catch { /* private mode */ }
    return VIEWS.some(x => x.status === v) ? v : window.innerWidth >= 768 ? "week" : "agenda";
  });
  const view = VIEWS.some(x => x.status === params.get("view")) ? params.get("view") : fallbackView;
  const anchor = parseYmd(params.get("date")) || today;
  const dayOnly = view === "agenda" && params.get("only") === "1";     // a day picked in Month
  const [span, setSpan] = useState(AGENDA_SPAN);
  const [data, setData] = useState({ showtimes: [], total: 0, facets: null, regions: {} });
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [theatreNames, setTheatreNames] = useState({});
  const [members, setMembers] = useState([]);
  const [selected, setSelected] = useState(null);
  const [profileUserId, setProfileUserId] = useState(null);
  const [attendanceKey, setAttendanceKey] = useState(0);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [expanded, setExpanded] = useState(new Set());   // Week days showing every film
  const [allPills, setAllPills] = useState(false);       // phones: every smart pill
  const deepLink = useRef(DEEP_LINK);

  const { start, end } = viewRange(view, anchor, dayOnly ? 1 : span);
  const startKey = ymd(start), lastKey = ymd(addDays(end, -1));

  const query = useMemo(() => Object.fromEntries(FILTER_KEYS.filter(k => params.get(k)).map(k => [k, params.get(k)])), [params]);
  const serverQs = new URLSearchParams(Object.entries(query).filter(([k]) => k !== "members")).toString();
  const members_ = listOf(query.members);
  const nFilters = FILTER_KEYS.reduce((n, k) => n + (MULTI.has(k) ? listOf(query[k]).length : query[k] ? 1 : 0), 0);

  function update(changes, { replace = true } = {}) {
    const next = new URLSearchParams(params);
    for (const [k, v] of Object.entries(changes)) (v == null || v === "" ? next.delete(k) : next.set(k, v));
    setParams(next, { replace });
  }
  function toggle(key, value) {
    if (MULTI.has(key)) {
      const cur = listOf(query[key]);
      const nextList = cur.includes(value) ? cur.filter(v => v !== value) : [...cur, value];
      update({ [key]: nextList.join(",") || null });
    } else update({ [key]: query[key] === value ? null : value });
  }
  const clearFilters = () => update(Object.fromEntries(FILTER_KEYS.map(k => [k, null])));
  function setView(v) {
    try { localStorage.setItem("cinemaclub_cal_view", v); } catch { /* private mode */ }
    update({ view: v, only: null });
  }
  function goTo(date) {
    setSpan(AGENDA_SPAN);
    update({ date: ymd(date) === ymd(today) ? null : ymd(date), only: null });
  }
  function step(dir) {
    if (view === "month") goTo(new Date(anchor.getFullYear(), anchor.getMonth() + dir, 1));
    else goTo(addDays(anchor, (dayOnly ? 1 : 7) * dir));
  }

  // Theatre names and the group's members (for filters).
  useEffect(() => {
    let live = true;
    fetch(`${apiBase}/api/theatres`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(ts => { if (live) setTheatreNames(Object.fromEntries(ts.map(t => [t.slug, t.short_name || t.name]))); })
      .catch(() => {});
    if (!groupId) { setMembers([]); return () => { live = false; }; }      // public mode: no members
    fetch(`${apiBase}/api/groups/by-id/${groupId}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(g => (g?.slug ? fetch(`${apiBase}/api/groups/${g.slug}/members`, { credentials: "include" }) : null))
      .then(r => (r?.ok ? r.json() : []))
      .then(ms => { if (live) setMembers(ms.filter(m => m.status === "active" && m.user).map(m => m.user)); })
      .catch(() => {});
    return () => { live = false; };
  }, [apiBase, groupId]);

  const fetchShowtimes = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/api/discover/calendar?${groupParam(groupId)}from=${startKey}&to=${lastKey}${serverQs ? `&${serverQs}` : ""}`,
                            { credentials: "include" });
      if (!r.ok) throw new Error();
      setData(await r.json());
      setFailed(false);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }, [apiBase, groupId, startKey, lastKey, serverQs]);
  useEffect(() => { fetchShowtimes(); }, [fetchShowtimes]);

  // Deep link: open one screening.
  const openShowtime = useCallback(id => {
    fetch(`${apiBase}/api/showtimes/${id}?${groupParam(groupId)}`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(s => { if (s) setSelected([s]); })
      .catch(() => {});
  }, [apiBase, groupId]);
  useEffect(() => {
    const id = deepLink.current.showtime;
    if (!id) return;
    deepLink.current.showtime = null;
    openShowtime(id);
  }, [openShowtime]);

  const visible = useMemo(() => data.showtimes.filter(s => passes(s, members_)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [data, query.members]);
  const days = useMemo(() => groupByDay(visible, user?.id), [visible, user?.id]);
  const dayList = [];
  for (let d = start; d < end; d = addDays(d, 1)) dayList.push(d);
  const filmCount = new Set(visible.map(s => s.movie.id)).size;

  const open = (shows, s) => setSelected([s, ...shows.filter(x => x.id !== s.id)].sort((a, b) => new Date(a.start_time) - new Date(b.start_time)));
  const patch = updated => {
    setData(prev => ({ ...prev, showtimes: prev.showtimes.map(s => (s.id === updated.id ? { ...s, ...updated } : s)) }));
    setSelected(prev => (prev ? prev.map(s => (s.id === updated.id ? { ...s, ...updated } : s)) : prev));
  };
  async function handleRsvp(id, status) {
    const r = await fetch(`${apiBase}/api/rsvp`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ showtime_id: id, status, group_id: groupId }),
    });
    if (r.ok) patch(await r.json());
  }
  async function handleAttendance(id, status) {
    const r = await fetch(`${apiBase}/api/attendance`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ showtime_id: id, status }),
    });
    if (!r.ok) return false;
    patch({ id, user_attendance: status });
    setAttendanceKey(k => k + 1);
    return true;
  }

  const rangeLabel = view === "month"
    ? anchor.toLocaleDateString("en-US", { month: "long", year: "numeric" })
    : view === "week" ? `${short(start)} – ${short(addDays(end, -1))}`
    : dayOnly ? dayTitle(start, today) : `From ${start.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}`;
  const atToday = !dayOnly && (ymd(anchor) === ymd(today) || (view === "month" && anchor.getMonth() === today.getMonth() && anchor.getFullYear() === today.getFullYear()));
  const browseLink = `/browse?${new URLSearchParams({ from: startKey, to: lastKey, ...Object.fromEntries(Object.entries(query).filter(([k]) => k !== "members")) })}`;
  const title = data.title ? `Calendar · ${data.title}` : "Calendar";

  return (
    <div className={`page calendar view-${view}`}>
      <PageHeader title={title} subtitle={loading ? "Loading…" : `${filmCount} film${filmCount === 1 ? "" : "s"} · ${rangeLabel}`} />

      <div className="cal-bar">
        <Segmented label="View" options={VIEWS} value={view} onChange={v => v && setView(v)} />
        <div className="cal-nav">
          <button type="button" className="btn btn-sm" onClick={() => step(-1)} aria-label="Earlier">‹</button>
          <button type="button" className="btn btn-sm" onClick={() => goTo(today)} disabled={atToday}>Today</button>
          <button type="button" className="btn btn-sm" onClick={() => step(1)} aria-label="Later">›</button>
          <span className="cal-range">{rangeLabel}</span>
        </div>
        <button type="button" className="btn btn-sm cal-filters-btn" onClick={() => setFiltersOpen(true)}>
          Filters{nFilters ? ` (${nFilters})` : ""}
        </button>
      </div>

      <div className={`cal-quick${allPills ? " open" : ""}`} role="group" aria-label="Quick filters">
        {(() => {
          const pill = ([k, v, label], i, extra = false) => {
            const on = MULTI.has(k) ? listOf(query[k]).includes(v) : query[k] === v;
            return (
              <button key={`${k}:${v}`} type="button" className={`chip${on ? " gold" : ""}${extra && !on ? " extra" : ""}`}
                      aria-pressed={on} onClick={() => toggle(k, v)}>{label}</button>
            );
          };
          return (
            <>
              {/* Club mode: both club pills; otherwise just your own plans (R5b). */}
              {(groupId || user) && (
                <div className="cal-quick-group">{(groupId ? CLUB_PILLS : CLUB_PILLS.filter(([, v]) => v === "mine")).map((p, i) => pill(p, i))}</div>
              )}
              {(groupId || user) && <span className="cal-quick-sep" aria-hidden="true" />}
              <div className="cal-quick-group">
                {SMART_PILLS.map((p, i) => pill(p, i, i >= PHONE_PILLS))}
                <button type="button" className="chip cal-quick-more" aria-expanded={allPills} onClick={() => setAllPills(o => !o)}>
                  {allPills ? "Fewer" : `+${SMART_PILLS.length - PHONE_PILLS} more`}
                </button>
                {nFilters > 0 && <button type="button" className="chip cal-quick-clear" onClick={clearFilters}>Clear all</button>}
              </div>
            </>
          );
        })()}
      </div>

      {groupId && <AttendancePrompt apiBase={apiBase} refreshKey={attendanceKey} onAnswer={handleAttendance} onOpenShowtime={openShowtime} />}

      {failed ? (
        <p className="cal-empty">Couldn't load the calendar — <button type="button" className="share-link" onClick={fetchShowtimes}>try again</button>.</p>
      ) : view === "month" ? (
        <div className="cal-month">
          {["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"].map(d => <div key={d} className="cal-month-dow">{d}</div>)}
          {dayList.map(d => {
            const key = ymd(d);
            const entries = days[key] || [];
            const outside = d.getMonth() !== anchor.getMonth();
            return (
              <button key={key} type="button" disabled={!entries.length}
                      className={`cal-cell${outside ? " outside" : ""}${d < today ? " past" : ""}${key === ymd(today) ? " today" : ""}${entries.some(e => e.youGoing) ? " mine" : ""}`}
                      onClick={() => { setSpan(AGENDA_SPAN); update({ view: "agenda", date: key, only: "1" }, { replace: false }); }}
                      aria-label={`${d.toDateString()}: ${entries.length} films`}>
                <span className="cal-cell-num">{d.getDate()}</span>
                {entries.length > 0 && <span className="cal-cell-count">{entries.length} film{entries.length === 1 ? "" : "s"}</span>}
                <span className="cal-cell-posters">
                  {entries.slice(0, 3).map(e => <Poster key={e.movie.id} movie={e.movie} />)}
                </span>
                {entries.some(e => e.going.length) && <span className="cal-cell-club">🎟️</span>}
              </button>
            );
          })}
        </div>
      ) : view === "week" ? (
        <div className="cal-week">
          {dayList.map(d => {
            const key = ymd(d);
            const entries = days[key] || [];
            const all = expanded.has(key);
            return (
              <section key={key} className={`cal-col${key === ymd(today) ? " today" : ""}`} aria-label={dayTitle(d, today)}>
                <h2 className="cal-col-head">
                  <span className="deco">{d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</span>
                  <span className="cal-col-sub">
                    {[key === ymd(today) ? "Today" : key === ymd(addDays(today, 1)) ? "Tomorrow" : null,
                      !loading && `${entries.length} film${entries.length === 1 ? "" : "s"}`].filter(Boolean).join(" · ")}
                  </span>
                </h2>
                {!loading && !entries.length && <p className="cal-col-empty">Nothing matches.</p>}
                {(all ? entries : entries.slice(0, WEEK_TOP)).map(e => <WeekCard key={e.movie.id} entry={e} onOpen={open} />)}
                {entries.length > WEEK_TOP && (
                  <button type="button" className="cal-more" onClick={() => setExpanded(prev => {
                    const next = new Set(prev); all ? next.delete(key) : next.add(key); return next;
                  })}>
                    {all ? "Show fewer" : `+${entries.length - WEEK_TOP} more`}
                  </button>
                )}
              </section>
            );
          })}
        </div>
      ) : (
        <div className="cal-agenda">
          {dayOnly && (
            <div className="cal-only">
              Showing {dayTitle(start, today)} only ·{" "}
              <button type="button" className="share-link" onClick={() => update({ only: null })}>show the days after</button>
            </div>
          )}
          {dayList.map(d => {
            const key = ymd(d);
            const entries = days[key] || [];
            if (!entries.length) return null;
            return (
              <section key={key} className="cal-agenda-day">
                <div className="cal-agenda-head">
                  <SectionTitle action={<span className="cal-count">{entries.length} film{entries.length === 1 ? "" : "s"}</span>}>
                    {dayTitle(d, today)}
                  </SectionTitle>
                </div>
                <div className="cal-tiles">
                  {entries.map(e => <AgendaTile key={e.movie.id} entry={e} onOpen={open} />)}
                </div>
              </section>
            );
          })}
          {!loading && !visible.length && (
            <div className="cal-empty">
              <p>Nothing matches{dayOnly ? " that day" : " in these two weeks"}.</p>
              {nFilters > 0 && <button type="button" className="btn btn-sm" onClick={clearFilters}>Clear filters</button>}
            </div>
          )}
          {!loading && !dayOnly && (
            <div className="cal-load-more">
              <button type="button" className="btn" onClick={() => setSpan(s => s + AGENDA_SPAN)}>Show the next two weeks</button>
            </div>
          )}
        </div>
      )}

      {filtersOpen && (
        <FilterSheet query={query} multi={MULTI} meta={data} theatreNames={theatreNames} total={filmCount} club={!!groupId}
                     onToggle={toggle} onClear={clearFilters} onClose={() => setFiltersOpen(false)}
                     note={<>Sort, search and more in <Link to={browseLink} onClick={() => setFiltersOpen(false)}>Browse →</Link></>}>
          {members.length > 0 && (
            <fieldset><legend>Who's going</legend>
              <div className="filter-chips">
                {members.map(m => {
                  const on = members_.includes(String(m.id));
                  return (
                    <button key={m.id} type="button" className={`chip filter-choice${on ? " gold" : ""}`} aria-pressed={on} onClick={() => toggle("members", String(m.id))}>
                      <Avatar user={m} size={18} /> {m.id === user?.id ? "You" : m.name}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          )}
        </FilterSheet>
      )}

      {selected && (
        <ShowtimeDrawer showtimes={selected} user={user} groupId={groupId} apiBase={apiBase}
                        onClose={() => setSelected(null)} onRsvp={handleRsvp} onAttendance={handleAttendance}
                        onViewProfile={setProfileUserId} />
      )}
      {profileUserId && (
        <UserProfileDrawer userId={profileUserId} viewerId={user?.id} apiBase={apiBase}
                           onClose={() => setProfileUserId(null)}
                           onAttendanceChange={() => setAttendanceKey(k => k + 1)}
                           onOpenShowtime={id => { setProfileUserId(null); openShowtime(id); }} />
      )}
    </div>
  );
}

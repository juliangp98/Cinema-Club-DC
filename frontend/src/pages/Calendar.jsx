import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import ShowtimeDrawer from "../components/ShowtimeDrawer";
import ProfileMenu from "../components/ProfileMenu";
import GroupSwitcher from "../components/GroupSwitcher";
import UserProfileDrawer from "../components/UserProfileDrawer";

const DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];

// Strip diacritics for search matching (e.g. SIRÂT → SIRAT)
function normalize(str) {
  return str.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
}

// Shorthand theatre names for compact display
const THEATRE_SHORT = { suns: "SUNS", afi: "AFI", estreet: "E ST" };

// Time-of-day buckets
const TIME_BUCKETS = [
  { key: "morning",   label: "Morning",   icon: "\u2600\uFE0F", test: h => h < 12 },
  { key: "afternoon", label: "Afternoon", icon: "\u26C5", test: h => h >= 12 && h < 17 },
  { key: "evening",   label: "Evening",   icon: "\uD83C\uDF19", test: h => h >= 17 },
];

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

function startOfMonth(year, month) {
  return new Date(year, month, 1);
}

function buildCalendarDays(year, month) {
  const first = startOfMonth(year, month);
  const startDay = first.getDay(); // 0 = Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const daysInPrev = new Date(year, month, 0).getDate();
  const days = [];

  // Previous month tail
  for (let i = startDay - 1; i >= 0; i--) {
    days.push({ date: new Date(year, month - 1, daysInPrev - i), outside: true });
  }
  // Current month
  for (let d = 1; d <= daysInMonth; d++) {
    days.push({ date: new Date(year, month, d), outside: false });
  }
  // Next month head (fill to complete rows)
  let next = 1;
  while (days.length % 7 !== 0) {
    days.push({ date: new Date(year, month + 1, next++), outside: true });
  }
  return days;
}

function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() &&
         a.getMonth() === b.getMonth() &&
         a.getDate() === b.getDate();
}

export default function Calendar({ user, setUser, apiBase, groupId, setGroupId }) {
  const today = new Date();
  const [year, setYear]       = useState(today.getFullYear());
  const [month, setMonth]     = useState(today.getMonth());
  const [showtimes, setShowtimes] = useState([]);
  const [selected, setSelected]   = useState(null); // array of showtimes (grouped)
  const [allTheatres, setAllTheatres] = useState([]);   // all theatres from API
  const [groupTheatres, setGroupTheatres] = useState([]); // group's selected theatre slugs
  const [activeTheatres, setActiveTheatres] = useState(new Set());
  const [loading, setLoading]     = useState(false);
  const [showProfile, setShowProfile] = useState(false);
  const [profileUserId, setProfileUserId] = useState(null);

  // Filter bar state
  const [searchText, setSearchText]       = useState("");
  const [selectedMovies, setSelectedMovies] = useState(new Set());
  const [selectedMembers, setSelectedMembers] = useState(new Set());
  const [timeOfDay, setTimeOfDay]         = useState(new Set());
  const [showTheatreDD, setShowTheatreDD] = useState(false);
  const [showMovieDD, setShowMovieDD]     = useState(false);
  const [showMemberDD, setShowMemberDD]   = useState(false);
  const [groupMembers, setGroupMembers]   = useState([]);
  const theatreDDRef = useRef(null);
  const movieDDRef   = useRef(null);
  const memberDDRef  = useRef(null);

  const calDays = buildCalendarDays(year, month);

  // Unique movies in current showtimes (for movie search dropdown)
  const availableMovies = useMemo(() => {
    const map = new Map();
    for (const s of showtimes) {
      if (!map.has(s.movie.id)) map.set(s.movie.id, s.movie);
    }
    return Array.from(map.values()).sort((a, b) => a.title.localeCompare(b.title));
  }, [showtimes]);

  // Filtered movie list for search
  const filteredMovies = useMemo(() => {
    if (!searchText.trim()) return availableMovies;
    const q = normalize(searchText);
    return availableMovies.filter(m => normalize(m.title).includes(q));
  }, [availableMovies, searchText]);

  // Close dropdowns on outside click
  useEffect(() => {
    function handleClick(e) {
      if (theatreDDRef.current && !theatreDDRef.current.contains(e.target)) setShowTheatreDD(false);
      if (movieDDRef.current && !movieDDRef.current.contains(e.target)) setShowMovieDD(false);
      if (memberDDRef.current && !memberDDRef.current.contains(e.target)) setShowMemberDD(false);
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  // Fetch all theatres + active group's theatre config + group members
  useEffect(() => {
    async function loadTheatreData() {
      try {
        const [theatresRes, groupRes] = await Promise.all([
          fetch(`${apiBase}/api/theatres`, { credentials: "include" }),
          groupId ? fetch(`${apiBase}/api/groups/by-id/${groupId}`, { credentials: "include" }) : null,
        ]);
        if (theatresRes.ok) {
          const theatres = await theatresRes.json();
          setAllTheatres(theatres);
          // Get group's theatres (or default to all)
          let gTheatres = theatres.map(t => t.slug);
          if (groupRes && groupRes.ok) {
            const gData = await groupRes.json();
            if (gData.theatres && gData.theatres.length > 0) {
              gTheatres = gData.theatres;
            }
            // Fetch group members
            if (gData.slug) {
              try {
                const membersRes = await fetch(`${apiBase}/api/groups/${gData.slug}/members`, { credentials: "include" });
                if (membersRes.ok) {
                  const membersData = await membersRes.json();
                  setGroupMembers(
                    membersData
                      .filter(m => m.status === "active" && m.user)
                      .map(m => m.user)
                  );
                }
              } catch { /* ignore */ }
            }
          }
          setGroupTheatres(gTheatres);
          setActiveTheatres(new Set(gTheatres));
        }
      } catch { /* ignore */ }
    }
    loadTheatreData();
    setSelectedMembers(new Set());
  }, [apiBase, groupId]);

  const fetchShowtimes = useCallback(async () => {
    setLoading(true);
    const start = new Date(year, month, 1).toISOString();
    const end   = new Date(year, month + 1, 0, 23, 59).toISOString();
    const params = new URLSearchParams({ start, end });
    if (groupId) params.set("group_id", groupId);
    try {
      const r = await fetch(
        `${apiBase}/api/showtimes?${params}`,
        { credentials: "include" }
      );
      const data = await r.json();
      setShowtimes(Array.isArray(data) ? data : []);
    } catch {
      setShowtimes([]);
    } finally {
      setLoading(false);
    }
  }, [apiBase, year, month, groupId]);

  useEffect(() => { fetchShowtimes(); }, [fetchShowtimes]);

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    if (month === 11) { setYear(y => y + 1); setMonth(0); }
    else setMonth(m => m + 1);
  }
  function goToday() {
    setYear(today.getFullYear());
    setMonth(today.getMonth());
    setSelected(null);
    // scroll to today's cell within the calendar grid (not the whole page)
    setTimeout(() => {
      const el = document.querySelector(".cal-day.today");
      const container = document.querySelector(".calendar-grid");
      if (el && container) {
        const elRect = el.getBoundingClientRect();
        const containerRect = container.getBoundingClientRect();
        const offset = elRect.top - containerRect.top + container.scrollTop - container.clientHeight / 2 + elRect.height / 2;
        container.scrollTo({ top: Math.max(0, offset), behavior: "smooth" });
      }
    }, 100);
  }

  function toggleTheatre(slug) {
    setActiveTheatres(prev => {
      const next = new Set(prev);
      if (next.has(slug)) { if (next.size > 1) next.delete(slug); }
      else next.add(slug);
      return next;
    });
  }

  function toggleMovie(movieId) {
    setSelectedMovies(prev => {
      const next = new Set(prev);
      if (next.has(movieId)) next.delete(movieId);
      else next.add(movieId);
      return next;
    });
  }

  function toggleTime(key) {
    setTimeOfDay(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleMember(userId) {
    setSelectedMembers(prev => {
      const next = new Set(prev);
      if (next.has(userId)) next.delete(userId);
      else next.add(userId);
      return next;
    });
  }

  function clearAllFilters() {
    setSelectedMovies(new Set());
    setSelectedMembers(new Set());
    setTimeOfDay(new Set());
    setSearchText("");
  }

  const hasActiveFilters = selectedMovies.size > 0 || timeOfDay.size > 0 || selectedMembers.size > 0;

  function getGroupedShowtimes(date) {
    const dayShowtimes = showtimes.filter(s => {
      if (!activeTheatres.has(s.theatre.slug)) return false;
      // Movie filter
      if (selectedMovies.size > 0 && !selectedMovies.has(s.movie.id)) return false;
      // Time-of-day filter
      if (timeOfDay.size > 0) {
        const hour = new Date(s.start_time).getHours();
        const match = TIME_BUCKETS.some(b => timeOfDay.has(b.key) && b.test(hour));
        if (!match) return false;
      }
      return isSameDay(new Date(s.start_time), date);
    }).sort((a, b) => new Date(a.start_time) - new Date(b.start_time));

    // Group by movie + theatre
    const groups = new Map();
    for (const s of dayShowtimes) {
      const key = `${s.movie.id}_${s.theatre.id}`;
      if (!groups.has(key)) {
        groups.set(key, {
          key,
          movie: s.movie,
          theatre: s.theatre,
          showtimes: [],
          recommended: false,
          allSoldOut: true,
        });
      }
      const g = groups.get(key);
      g.showtimes.push(s);
      if (s.recommended) g.recommended = true;
      if (!s.is_sold_out) g.allSoldOut = false;
    }

    // Deduplicate attendees across showtimes
    return Array.from(groups.values()).map(g => {
      const seen = new Set();
      const uniqueAttendees = [];
      for (const s of g.showtimes) {
        for (const a of (s.attendees || [])) {
          if (!seen.has(a.id)) {
            seen.add(a.id);
            uniqueAttendees.push(a);
          }
        }
      }
      return { ...g, uniqueAttendees };
    }).filter(g => {
      // Member filter: only show if at least one selected member is attending
      if (selectedMembers.size === 0) return true;
      return g.uniqueAttendees.some(a => selectedMembers.has(a.id));
    });
  }

  async function handleRsvp(showtimeId, status) {
    const r = await fetch(`${apiBase}/api/rsvp`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ showtime_id: showtimeId, status, group_id: groupId }),
    });
    if (r.ok) {
      const updated = await r.json();
      setShowtimes(prev => prev.map(s => s.id === updated.id ? updated : s));
      // Update the selected array in place
      setSelected(prev =>
        prev ? prev.map(s => s.id === updated.id ? updated : s) : prev
      );
    }
  }

  async function logout() {
    await fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" });
    setUser(null);
  }

  function handleProfileUpdate(updatedUser) {
    setUser(updatedUser);
  }

  return (
    <div className="app-shell">
      {/* Header */}
      <header className="header">
        <span className="header-logo" onClick={goToday} style={{ cursor: "pointer" }}>CINEMA CLUB DC</span>
        <div className="header-sep" />

        <div className="nav-week">
          <button className="nav-btn" onClick={prevMonth}>&lsaquo;</button>
          <button className="nav-today" onClick={goToday}>Today</button>
          <button className="nav-btn" onClick={nextMonth}>&rsaquo;</button>
          <span className="nav-range">
            {MONTHS[month]} {year}
          </span>
        </div>

        <div className="header-spacer" />

        {/* Group Switcher */}
        <GroupSwitcher
          apiBase={apiBase}
          activeGroupId={groupId}
          setGroupId={setGroupId}
        />

        <div className="header-sep" />

        {/* User avatar */}
        <div style={{ position: "relative" }}>
          <div
            className="user-avatar"
            style={{ background: user.avatar_color, color: "#0d0c09" }}
            title={`${user.name} — ${user.email}`}
            onClick={() => setShowProfile(!showProfile)}
          >
            {user.name.slice(0, 2).toUpperCase()}
          </div>
          {showProfile && (
            <ProfileMenu
              user={user}
              apiBase={apiBase}
              onUpdate={handleProfileUpdate}
              onLogout={logout}
              onClose={() => setShowProfile(false)}
            />
          )}
        </div>
      </header>

      {/* Filter bar */}
      <div className="filter-bar">
        {/* Nav controls (shown on mobile only, hidden on desktop — desktop uses header's nav) */}
        <div className="nav-week filter-nav-week">
          <button className="nav-btn" onClick={prevMonth}>&lsaquo;</button>
          <button className="nav-today" onClick={goToday}>Today</button>
          <button className="nav-btn" onClick={nextMonth}>&rsaquo;</button>
          <span className="nav-range">
            {MONTHS[month]} {year}
          </span>
        </div>

        {/* Theatre dropdown */}
        <div className="filter-dd" ref={theatreDDRef}>
          <button
            className="filter-dd-btn"
            onClick={() => { setShowTheatreDD(v => !v); setShowMovieDD(false); setShowMemberDD(false); }}
          >
            <span className="filter-dd-dots">
              {allTheatres
                .filter(t => groupTheatres.includes(t.slug) && activeTheatres.has(t.slug))
                .map(t => (
                  <span key={t.slug} className="filter-dot" data-theatre={t.slug} />
                ))}
            </span>
            Theatres
            <span className="filter-dd-arrow">{showTheatreDD ? "\u25B4" : "\u25BE"}</span>
          </button>
          {showTheatreDD && (
            <div className="filter-dd-menu">
              {(() => {
                const visible = allTheatres.filter(t => groupTheatres.includes(t.slug));
                const allSelected = visible.every(t => activeTheatres.has(t.slug));
                return (
                  <>
                    {visible.length > 1 && (
                      <button
                        className="filter-select-all"
                        onClick={() => {
                          setActiveTheatres(allSelected
                            ? new Set()
                            : new Set(visible.map(t => t.slug))
                          );
                        }}
                      >
                        {allSelected ? "Deselect All" : "Select All"}
                      </button>
                    )}
                    {visible.map(t => (
                      <label key={t.slug} className="filter-dd-item" data-theatre={t.slug}>
                        <input
                          type="checkbox"
                          checked={activeTheatres.has(t.slug)}
                          onChange={() => toggleTheatre(t.slug)}
                        />
                        <span className="filter-dot" data-theatre={t.slug} />
                        {THEATRE_SHORT[t.slug] || t.name}
                      </label>
                    ))}
                  </>
                );
              })()}
            </div>
          )}
        </div>

        {/* Members dropdown */}
        <div className="filter-dd" ref={memberDDRef}>
          <button
            className="filter-dd-btn"
            onClick={() => { setShowMemberDD(v => !v); setShowTheatreDD(false); setShowMovieDD(false); }}
          >
            {selectedMembers.size > 0 && (
              <span className="filter-dd-dots">
                {groupMembers
                  .filter(m => selectedMembers.has(m.id))
                  .slice(0, 3)
                  .map(m => (
                    <span key={m.id} className="filter-dot" style={{ background: m.avatar_color }} />
                  ))}
              </span>
            )}
            Members
            {selectedMembers.size > 0 && <span className="filter-badge">{selectedMembers.size}</span>}
            <span className="filter-dd-arrow">{showMemberDD ? "\u25B4" : "\u25BE"}</span>
          </button>
          {showMemberDD && (
            <div className="filter-dd-menu filter-member-menu">
              {groupMembers.length === 0 && (
                <div className="filter-dd-empty">No members</div>
              )}
              {groupMembers.length > 1 && (
                <button
                  className="filter-select-all"
                  onClick={() => {
                    const allSelected = groupMembers.every(m => selectedMembers.has(m.id));
                    setSelectedMembers(allSelected
                      ? new Set()
                      : new Set(groupMembers.map(m => m.id))
                    );
                  }}
                >
                  {groupMembers.every(m => selectedMembers.has(m.id)) ? "Deselect All" : "Select All"}
                </button>
              )}
              {groupMembers.map(m => (
                <label key={m.id} className="filter-dd-item filter-member-item">
                  <input
                    type="checkbox"
                    checked={selectedMembers.has(m.id)}
                    onChange={() => toggleMember(m.id)}
                  />
                  <span className="filter-member-dot" style={{ background: m.avatar_color }} />
                  {m.name}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Movie search */}
        <div className="filter-dd filter-search-wrap" ref={movieDDRef}>
          <div className="filter-search-box">
            <span className="filter-search-icon">&#128269;</span>
            <input
              className="filter-search-input"
              type="text"
              placeholder="Search movies..."
              value={searchText}
              onChange={e => { setSearchText(e.target.value); setShowMovieDD(true); setShowMemberDD(false); setShowTheatreDD(false); }}
              onFocus={() => { setShowMovieDD(true); setShowMemberDD(false); setShowTheatreDD(false); }}
            />
            {selectedMovies.size > 0 && (
              <span className="filter-badge">{selectedMovies.size}</span>
            )}
          </div>
          {showMovieDD && (
            <div className="filter-dd-menu filter-movie-menu">
              {filteredMovies.length > 0 && (
                <button
                  className="filter-select-all"
                  onClick={() => {
                    const allSelected = filteredMovies.every(m => selectedMovies.has(m.id));
                    setSelectedMovies(prev => {
                      const next = new Set(prev);
                      filteredMovies.forEach(m => allSelected ? next.delete(m.id) : next.add(m.id));
                      return next;
                    });
                  }}
                >
                  {filteredMovies.every(m => selectedMovies.has(m.id)) ? "Deselect All" : "Select All"}
                </button>
              )}
              {filteredMovies.length === 0 && (
                <div className="filter-dd-empty">No matches</div>
              )}
              {filteredMovies.map(m => (
                <label key={m.id} className="filter-dd-item">
                  <input
                    type="checkbox"
                    checked={selectedMovies.has(m.id)}
                    onChange={() => toggleMovie(m.id)}
                  />
                  {m.title}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* Time-of-day pills */}
        <div className="filter-time-pills">
          {TIME_BUCKETS.map(b => (
            <button
              key={b.key}
              className={`filter-time-pill${timeOfDay.has(b.key) ? " active" : ""}`}
              onClick={() => toggleTime(b.key)}
              title={b.label}
            >
              <span className="filter-time-icon">{b.icon}</span>
              <span className="filter-time-label">{b.label}</span>
            </button>
          ))}
        </div>

        {/* Clear filters */}
        {hasActiveFilters && (
          <button className="filter-clear" onClick={clearAllFilters} title="Clear all filters">
            &#x2715;
          </button>
        )}
      </div>

      {/* Day-of-week headers */}
      <div className="day-headers">
        {DAYS.map(d => (
          <div key={d} className="day-header">{d}</div>
        ))}
      </div>

      {/* Calendar body */}
      <div className="calendar-body">
        <div className="calendar-grid">
          {calDays.map(({ date, outside }, i) => {
            const grouped = getGroupedShowtimes(date);
            const isToday = isSameDay(date, today);
            return (
              <div
                key={i}
                className={[
                  "cal-day",
                  outside ? "outside-month" : "",
                  isToday ? "today" : ""
                ].join(" ")}
              >
                <span className="cal-day-number">
                  <span className="cal-day-weekday">{DAYS[date.getDay()]} </span>
                  {date.getDate()}
                </span>
                {grouped.map(group => (
                  <div
                    key={group.key}
                    className={`cal-event${group.allSoldOut ? " cal-event-sold-out" : ""}${group.recommended ? " recommended" : ""}`}
                    data-theatre={group.theatre.slug}
                    onClick={() => setSelected(group.showtimes)}
                  >
                    <span className="cal-event-time">
                      {group.showtimes.map(s => formatTime(s.start_time)).join(", ")}
                    </span>
                    <div>
                      <div className="cal-event-title">
                        {group.recommended && <span className="rec-star" title="Recommended for you">&#9733; </span>}
                        {group.movie.title}
                      </div>
                      {group.uniqueAttendees.length > 0 && (
                        <div className="event-dots">
                          {group.uniqueAttendees.map(a => (
                            <div
                              key={a.id}
                              className="event-dot"
                              style={{ background: a.avatar_color }}
                              title={a.name}
                            />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </div>

      {/* Detail drawer */}
      {selected && (
        <ShowtimeDrawer
          showtimes={selected}
          user={user}
          groupId={groupId}
          apiBase={apiBase}
          onClose={() => setSelected(null)}
          onRsvp={handleRsvp}
          onViewProfile={setProfileUserId}
        />
      )}

      {/* User profile drawer */}
      {profileUserId && (
        <UserProfileDrawer
          userId={profileUserId}
          apiBase={apiBase}
          onClose={() => setProfileUserId(null)}
        />
      )}
    </div>
  );
}

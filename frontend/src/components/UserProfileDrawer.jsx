import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { accountLabel } from "../accountLabel";
import Sheet from "../ui/Sheet";
import Avatar from "../ui/Avatar";

function formatDate(iso) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

function formatWhen(iso) {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
  return `${day} · ${d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}`;
}

// Outside the calendar, opening a screening means going there (its deep link).
function openOnCalendar(showtimeId) {
  window.location.assign(`/calendar?showtime=${showtimeId}`);
}

function useList(url) {
  const [data, setData] = useState(null);
  useEffect(() => {
    setData(null);
    fetch(url, { credentials: "include" })
      .then(r => (r.ok ? r.json() : { error: true }))
      .then(setData)
      .catch(() => setData({ error: true }));
  }, [url]);
  return [data, setData];
}

const STATUS_LABEL = { going: "Going", maybe: "Maybe", went: "Saw it" };

// One screening in a list: title, when + where, and an optional status chip.
// Clickable rows open the screening's drawer.
function ScreeningRow({ item, status, onOpen }) {
  const body = (
    <>
      <span className="list-row-text">
        <span className="list-row-title">{item.title}</span>
        <span className="list-row-meta">
          {formatWhen(item.start_time)} · {item.theatre}{item.format_label ? ` · ${item.format_label}` : ""}
        </span>
      </span>
      {status && <span className={`list-chip ${status}`}>{STATUS_LABEL[status] || status}</span>}
    </>
  );
  return (
    <li>
      <button type="button" className="list-row" onClick={() => onOpen(item.showtime_id)}>{body}</button>
    </li>
  );
}

// A watchlisted film: opens its film page (every showing, details).
function FilmRow({ movie, next }) {
  const navigate = useNavigate();
  const text = (
    <span className="list-row-text">
      <span className="list-row-title">
        {movie.title}{movie.release_year ? ` (${movie.release_year})` : ""}
      </span>
      <span className="list-row-meta">
        {next ? `Next: ${formatWhen(next.start_time)} · ${next.theatre}` : "No showings scheduled"}
      </span>
    </span>
  );
  return (
    <li>
      <button type="button" className={`list-row${next ? "" : " muted"}`} onClick={() => navigate(`/films/${movie.id}`)}>
        {text}
      </button>
    </li>
  );
}

function ListState({ data, empty }) {
  if (!data) return <div className="list-empty">Loading…</div>;
  if (data.error) return <div className="list-empty">Couldn't load this right now.</div>;
  return <div className="list-empty">{empty}</div>;
}

export function WatchlistTab({ userId, apiBase, onOpen }) {
  const [data] = useList(`${apiBase}/api/users/${userId}/watchlist`);
  if (!data || data.error || !data.items.length) {
    return <ListState data={data} empty="No films on the watchlist yet." />;
  }
  return (
    <ul className="list-rows">
      {data.items.map(i => <FilmRow key={i.movie.id} movie={i.movie} next={i.next} />)}
    </ul>
  );
}

export function GoingTab({ userId, apiBase, onOpen }) {
  const [data] = useList(`${apiBase}/api/users/${userId}/rsvps`);
  if (!data || data.error || !data.items.length) {
    return <ListState data={data} empty="No upcoming RSVPs." />;
  }
  return (
    <ul className="list-rows">
      {data.items.map(i => <ScreeningRow key={i.showtime_id} item={i} status={i.status} onOpen={onOpen} />)}
    </ul>
  );
}

// Watch history: screenings this member saw (confirmed "went", or RSVP'd going
// and never said otherwise). On your own profile every entry is editable, and
// ones you marked "didn't go" stay listed so you can correct them.
export function HistoryTab({ userId, apiBase, onOpen, onChange }) {
  const [data, setData] = useList(`${apiBase}/api/users/${userId}/history`);

  async function setStatus(item, status) {
    const r = await fetch(`${apiBase}/api/attendance`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ showtime_id: item.showtime_id, status }),
    });
    if (!r.ok) return;
    onChange?.();
    setData(d => ({
      ...d,
      // Clearing a "didn't go" puts it back to an unconfirmed RSVP.
      items: d.items.map(i => (i.showtime_id === item.showtime_id ? { ...i, status: status || "going" } : i)),
    }));
  }

  if (!data || data.error || !data.items.length) {
    return <ListState data={data} empty="Nothing logged yet." />;
  }
  const seen = data.items.filter(i => i.status !== "missed").length;
  return (
    <>
      <div className="list-count">{seen} screening{seen === 1 ? "" : "s"} seen</div>
      <ul className="history-list">
        {data.items.map(i => (
          <li key={i.showtime_id} className={`history-item${i.status === "missed" ? " missed" : ""}`}>
            <button type="button" className="history-text" onClick={() => onOpen(i.showtime_id)}>
              <span className="history-title">{i.title}</span>
              <span className="history-meta">
                {formatDate(i.start_time)} · {i.theatre}{i.format_label ? ` · ${i.format_label}` : ""}
              </span>
            </button>
            {data.own ? (
              <div className="history-actions">
                {[["went", "Went"], ["missed", "Didn't go"]].map(([status, label]) => (
                  <button
                    key={status}
                    className={`rsvp-btn att-opt-${status}${i.status === status ? " selected" : ""}`}
                    onClick={() => setStatus(i, i.status === status ? null : status)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : (
              <span className="history-mark" title={i.status === "went" ? "Confirmed" : "RSVP'd going"}>
                {i.status === "went" ? "✓" : "🎟"}
              </span>
            )}
          </li>
        ))}
      </ul>
    </>
  );
}

// Where you and this member line up — for planning outings together.
function CompareTab({ userId, apiBase, onOpen }) {
  const [data] = useList(`${apiBase}/api/users/${userId}/compare`);
  if (!data || data.error) return <ListState data={data} />;
  const name = data.name;
  const sections = [
    ["You both want to see", data.both_want.map(i => (
      <FilmRow key={`w${i.movie.id}`} movie={i.movie} next={i.next} />))],
    ["You're both going", data.both_going.map(i => (
      <ScreeningRow key={`b${i.showtime_id}`} item={i} status={i.status} onOpen={onOpen} />))],
    [`${name}'s going to something on your watchlist`, data.they_go_you_want.map(i => (
      <ScreeningRow key={`t${i.showtime_id}`} item={i} status={i.status} onOpen={onOpen} />))],
    [`You're going to something on ${name}'s watchlist`, data.you_go_they_want.map(i => (
      <ScreeningRow key={`y${i.showtime_id}`} item={i} status={i.status} onOpen={onOpen} />))],
    ["Seen together", data.seen_together.map(i => (
      <ScreeningRow key={`s${i.showtime_id}`} item={i} onOpen={onOpen} />))],
  ].filter(([, rows]) => rows.length);
  if (!sections.length) {
    return <div className="list-empty">Nothing lines up yet — add films to your watchlist or RSVP to a screening.</div>;
  }
  return sections.map(([title, rows]) => (
    <div key={title} className="compare-section">
      <div className="compare-section-title">{title} <span className="compare-count">{rows.length}</span></div>
      <ul className="list-rows">{rows}</ul>
    </div>
  ));
}

export default function UserProfileDrawer({ userId, viewerId, apiBase, onClose, onAttendanceChange, onOpenShowtime }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [kernels, setKernels] = useState(null);
  const own = viewerId != null && viewerId === userId;
  const tabs = own ? ["Watchlist", "Going", "History"] : ["Compare", "Watchlist", "Going", "History"];
  const [tab, setTab] = useState(tabs[0]);
  const onOpen = onOpenShowtime || openOnCalendar;

  useEffect(() => {
    setTab(own ? "Watchlist" : "Compare");
  }, [userId, own]);

  useEffect(() => {
    if (!userId) return;
    setLoading(true);
    setError("");
    setUser(null);
    setKernels(null);
    Promise.all([
      fetch(`${apiBase}/api/users/${userId}/profile`, { credentials: "include" })
        .then(async (r) => {
          if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            throw new Error(d.error || "Could not load profile");
          }
          return r.json();
        }),
      fetch(`${apiBase}/api/users/${userId}/kernels`, { credentials: "include" })
        .then(r => r.ok ? r.json() : null)
        .catch(() => null),
    ])
      .then(([userData, kernelData]) => {
        setUser(userData);
        if (kernelData) setKernels(kernelData.kernels);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [userId, apiBase]);

  const genres = user && user.favorite_genres
    ? user.favorite_genres.split(",").filter(Boolean)
    : [];

  return (
    <Sheet onClose={onClose} label={user ? user.name : "Profile"} className="drawer">

        {loading && (
          <div className="drawer-content" style={{ textAlign: "center", paddingTop: "3rem" }}>
            <span style={{ color: "var(--muted)" }}>Loading profile…</span>
          </div>
        )}

        {error && (
          <div className="drawer-content" style={{ textAlign: "center", paddingTop: "3rem" }}>
            <span style={{ color: "var(--red)" }}>{error}</span>
          </div>
        )}

        {!loading && !error && user && (
          <div className="drawer-content">
            <div className="user-profile-header">
              <Avatar user={user} size={72} />
              <div className="user-profile-name">{user.name}</div>
              <div className="user-profile-email">{accountLabel(user)}</div>
              {kernels !== null && (
                <div className="profile-kernels-pill">🍿 {kernels} kernel{kernels !== 1 ? "s" : ""}</div>
              )}
            </div>

            <div className="user-profile-section">
              <div className="drawer-section-label">Favorite Genres</div>
              {genres.length === 0 ? (
                <div style={{ color: "var(--muted)", fontSize: "0.92rem" }}>
                  No genres selected yet.
                </div>
              ) : (
                <div className="genre-chips readonly">
                  {genres.map((g) => (
                    <span key={g} className="genre-chip active">{g}</span>
                  ))}
                </div>
              )}
            </div>

            <div className="user-profile-section">
              <div className="drawer-section-label">Bio</div>
              <div className="user-profile-bio">
                {user.bio || "No bio yet."}
              </div>
            </div>

            {user.letterboxd_username && (
              <div className="user-profile-section">
                <a
                  className="user-profile-letterboxd"
                  href={`https://letterboxd.com/${user.letterboxd_username}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  ▤ {user.letterboxd_username} on Letterboxd
                </a>
              </div>
            )}

            <div className="profile-tabs" role="tablist">
              {tabs.map(t => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  aria-selected={tab === t}
                  className={`profile-tab${tab === t ? " active" : ""}`}
                  onClick={() => setTab(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            <div className="profile-tab-panel" role="tabpanel">
              {tab === "Compare" && <CompareTab userId={userId} apiBase={apiBase} onOpen={onOpen} />}
              {tab === "Watchlist" && <WatchlistTab userId={userId} apiBase={apiBase} onOpen={onOpen} />}
              {tab === "Going" && <GoingTab userId={userId} apiBase={apiBase} onOpen={onOpen} />}
              {tab === "History" && (
                <HistoryTab userId={userId} apiBase={apiBase} onOpen={onOpen} onChange={onAttendanceChange} />
              )}
            </div>
          </div>
        )}
    </Sheet>
  );
}

import { useState, useEffect } from "react";
import { accountLabel } from "../accountLabel";

function formatHistoryDate(iso) {
  return new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

// Watch history: screenings this member saw (confirmed "went", or RSVP'd going
// and never said otherwise). On your own profile every entry is editable, and
// ones you marked "didn't go" stay listed so you can correct them.
function WatchHistory({ userId, apiBase, onChange }) {
  const [data, setData] = useState(null);   // { own, items }

  useEffect(() => {
    fetch(`${apiBase}/api/users/${userId}/history`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null));
  }, [userId, apiBase]);

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

  if (!data) return null;
  const seen = data.items.filter(i => i.status !== "missed").length;
  return (
    <div className="user-profile-section">
      <div className="drawer-section-label">Watch history ({seen})</div>
      {data.items.length === 0 ? (
        <div className="history-empty">Nothing logged yet.</div>
      ) : (
        <ul className="history-list">
          {data.items.map(i => (
            <li key={i.showtime_id} className={`history-item${i.status === "missed" ? " missed" : ""}`}>
              <div className="history-text">
                <span className="history-title">{i.title}</span>
                <span className="history-meta">
                  {formatHistoryDate(i.start_time)} · {i.theatre}{i.format_label ? ` · ${i.format_label}` : ""}
                </span>
              </div>
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
      )}
    </div>
  );
}

export default function UserProfileDrawer({ userId, apiBase, onClose, onAttendanceChange }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [kernels, setKernels] = useState(null);

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

  useEffect(() => {
    function onKey(e) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const genres = user && user.favorite_genres
    ? user.favorite_genres.split(",").filter(Boolean)
    : [];

  return (
    <div className="user-profile-overlay" onClick={onClose}>
      <div className="drawer" onClick={(e) => e.stopPropagation()}>
        <button className="drawer-close" onClick={onClose}>&times;</button>

        {loading && (
          <div className="drawer-content" style={{ textAlign: "center", paddingTop: "3rem" }}>
            <span style={{ color: "#b5a77a" }}>Loading profile...</span>
          </div>
        )}

        {error && (
          <div className="drawer-content" style={{ textAlign: "center", paddingTop: "3rem" }}>
            <span style={{ color: "#c0392b" }}>{error}</span>
          </div>
        )}

        {!loading && !error && user && (
          <div className="drawer-content">
            <div className="user-profile-header">
              <div
                className="user-profile-avatar"
                style={{ background: user.avatar_color, color: "#0d0c09" }}
              >
                {user.name.slice(0, 2).toUpperCase()}
              </div>
              <div className="user-profile-name">{user.name}</div>
              <div className="user-profile-email">{accountLabel(user)}</div>
              {kernels !== null && (
                <div className="profile-kernels-pill">🍿 {kernels} kernel{kernels !== 1 ? "s" : ""}</div>
              )}
            </div>

            <div className="user-profile-section">
              <div className="drawer-section-label">Favorite Genres</div>
              {genres.length === 0 ? (
                <div style={{ color: "#7a7560", fontSize: "0.92rem" }}>
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

            <WatchHistory userId={userId} apiBase={apiBase} onChange={onAttendanceChange} />
          </div>
        )}
      </div>
    </div>
  );
}

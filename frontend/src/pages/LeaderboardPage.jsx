import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ProfileMenu from "../components/ProfileMenu";
import UserProfileDrawer from "../components/UserProfileDrawer";

const MEDALS = ["🥇", "🥈", "🥉"];

export default function LeaderboardPage({ user, setUser, apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showProfile, setShowProfile] = useState(false);
  const [profileUserId, setProfileUserId] = useState(null);

  useEffect(() => {
    if (!activeGroupId) { setLoading(false); return; }
    fetch(`${apiBase}/api/groups/${activeGroupId}/leaderboard`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(data => { setRows(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, [activeGroupId, apiBase]);

  function logout() {
    fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" })
      .then(() => window.location.reload());
  }

  if (loading) return null;

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <header className="group-discovery-header">
          <button className="group-back-btn" onClick={() => navigate("/")}>
            &larr; Calendar
          </button>
          <h1 className="group-discovery-title">Leaderboard</h1>
          <div style={{ marginLeft: "auto", position: "relative" }}>
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
                onUpdate={u => setUser(u)}
                onLogout={logout}
                onClose={() => setShowProfile(false)}
              />
            )}
          </div>
        </header>

        {rows.length === 0 ? (
          <div className="leaderboard-empty">
            No standings yet — score a poll or RSVP to a screening to get on the board. 🍿
          </div>
        ) : (
          <div className="leaderboard-list">
            {rows.map((row, i) => (
              <div
                key={row.user.id}
                className={`leaderboard-row${row.user.id === user.id ? " me" : ""}`}
                onClick={() => setProfileUserId(row.user.id)}
              >
                <span className="leaderboard-rank">{MEDALS[i] || `${i + 1}.`}</span>
                <span
                  className="leaderboard-avatar"
                  style={{ background: row.user.avatar_color, color: "#0d0c09" }}
                >
                  {row.user.name.slice(0, 2).toUpperCase()}
                </span>
                <span className="leaderboard-name">{row.user.name}</span>
                <span className="leaderboard-stats">
                  <span className="leaderboard-kernels">🍿 {row.kernels}</span>
                  <span className="leaderboard-detail">
                    {row.correct} correct · {row.attendance} attended
                  </span>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>

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

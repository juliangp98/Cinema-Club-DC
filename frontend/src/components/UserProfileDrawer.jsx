import { useState, useEffect } from "react";

export default function UserProfileDrawer({ userId, apiBase, onClose }) {
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
              <div className="user-profile-email">{user.email}</div>
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
          </div>
        )}
      </div>
    </div>
  );
}

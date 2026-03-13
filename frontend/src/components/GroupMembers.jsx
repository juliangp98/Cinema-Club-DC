import { useState, useEffect } from "react";

export default function GroupMembers({ group, apiBase, onClose, onViewProfile, embedded }) {
  const [members, setMembers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selectedUserId, setSelectedUserId] = useState(null);
  const [kernels, setKernels] = useState(null);

  useEffect(() => {
    fetchMembers();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group.slug]);

  async function fetchMembers() {
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/api/groups/${group.slug}/members`, {
        credentials: "include",
      });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setError(d.error || "Could not load members");
        setMembers([]);
      } else {
        const data = await r.json();
        setMembers(Array.isArray(data) ? data : []);
        if (data.length > 0) {
          setSelectedUserId(data[0].user?.id || null);
        }
      }
    } catch {
      setError("Could not connect");
      setMembers([]);
    } finally {
      setLoading(false);
    }
  }

  const active = members.filter(m => m.status === "active");
  const pending = members.filter(m => m.status === "pending");

  const selectedMembership = members.find(m => m.user && m.user.id === selectedUserId) || null;
  const selectedUser = selectedMembership ? selectedMembership.user : null;

  const favoriteGenres = selectedUser && selectedUser.favorite_genres
    ? selectedUser.favorite_genres.split(",").filter(Boolean)
    : [];

  // Fetch kernels for selected user
  useEffect(() => {
    if (!selectedUserId) { setKernels(null); return; }
    fetch(`${apiBase}/api/users/${selectedUserId}/kernels`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setKernels(d.kernels); else setKernels(null); })
      .catch(() => setKernels(null));
  }, [selectedUserId, apiBase]);

  const content = (
    <>
      {error && <div className="group-members-error">{error}</div>}
      {loading && !error && (
        <div className="group-members-loading">Loading members...</div>
      )}

      {!loading && !error && (
        <div className={`group-members-body${embedded ? " embedded" : ""}`}>
          <div className="group-members-list">
            {active.length === 0 && pending.length === 0 && (
              <div className="group-empty">No members yet.</div>
            )}

            {active.length > 0 && (
              <>
                <div className="group-members-section-label">
                  Members ({active.length})
                </div>
                {active.map(m => (
                  <button
                    key={m.id}
                    className={`group-member-row clickable${selectedUserId === m.user.id ? " selected" : ""}`}
                    onClick={() => setSelectedUserId(m.user.id)}
                  >
                    <div
                      className="group-member-avatar"
                      style={{ background: m.user.avatar_color, color: "#0d0c09" }}
                    >
                      {m.user.name.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="group-member-main">
                      <span className="group-member-name">{m.user.name}</span>
                      <span className="group-member-email">{m.user.email}</span>
                    </div>
                    {m.role === "admin" && (
                      <span className="group-role-badge">admin</span>
                    )}
                  </button>
                ))}
              </>
            )}

            {pending.length > 0 && (
              <>
                <div className="group-members-section-label">
                  Pending ({pending.length})
                </div>
                {pending.map(m => (
                  <div key={m.id} className="group-member-row pending">
                    <div
                      className="group-member-avatar"
                      style={{ background: m.user.avatar_color, color: "#0d0c09" }}
                    >
                      {m.user.name.slice(0, 2).toUpperCase()}
                    </div>
                    <div className="group-member-main">
                      <span className="group-member-name">{m.user.name}</span>
                      <span className="group-member-email">{m.user.email}</span>
                    </div>
                    <span className="group-pending-badge">pending</span>
                  </div>
                ))}
              </>
            )}
          </div>

          <div className="group-member-profile">
            {selectedUser ? (
              <>
                <div className="profile-header">
                  <div
                    className="profile-avatar-large"
                    style={{ background: selectedUser.avatar_color, color: "#0d0c09" }}
                  >
                    {selectedUser.name.slice(0, 2).toUpperCase()}
                  </div>
                  <div className="profile-header-text">
                    <div className="profile-name">{selectedUser.name}</div>
                    <div className="profile-email">{selectedUser.email}</div>
                    {kernels !== null && (
                      <div className="profile-kernels-pill">🍿 {kernels} kernel{kernels !== 1 ? "s" : ""}</div>
                    )}
                  </div>
                </div>

                <div className="profile-section">
                  <div className="profile-section-label">Favorite Genres</div>
                  {favoriteGenres.length === 0 ? (
                    <div className="profile-empty">No genres selected yet.</div>
                  ) : (
                    <div className="genre-chips readonly">
                      {favoriteGenres.map(g => (
                        <span key={g} className="genre-chip active">
                          {g}
                        </span>
                      ))}
                    </div>
                  )}
                </div>

                <div className="profile-section">
                  <div className="profile-section-label">Bio</div>
                  <div className="profile-bio">
                    {selectedUser.bio ? selectedUser.bio : "No bio yet."}
                  </div>
                </div>

                {onViewProfile && (
                  <button
                    className="group-action-btn"
                    style={{ marginTop: "0.5rem" }}
                    onClick={() => onViewProfile(selectedUser.id)}
                  >
                    View Full Profile
                  </button>
                )}
              </>
            ) : (
              <div className="profile-empty">
                Select a member to view their profile.
              </div>
            )}
          </div>
        </div>
      )}
    </>
  );

  if (embedded) return content;

  return (
    <div className="group-members-overlay">
      <div className="group-members-panel">
        <div className="group-members-header">
          <h3 className="group-members-title">Members · {group.name}</h3>
          <button className="group-members-close" onClick={onClose}>&times;</button>
        </div>
        {content}
      </div>
    </div>
  );
}


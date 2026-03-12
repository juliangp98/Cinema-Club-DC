import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import GroupAdmin from "../components/GroupAdmin";
import GroupMembers from "../components/GroupMembers";
import UserProfileDrawer from "../components/UserProfileDrawer";
import ProfileMenu from "../components/ProfileMenu";

export default function GroupDiscovery({ user, setUser, apiBase, activeGroupId, setGroupId }) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [myGroups, setMyGroups] = useState([]);

  // Public groups with pagination
  const [publicGroups, setPublicGroups] = useState([]);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [loadingPublic, setLoadingPublic] = useState(false);

  // All theatres (fetched from API)
  const [allTheatres, setAllTheatres] = useState([]);

  // Create group form
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newPublic, setNewPublic] = useState(true);
  const [newTheatres, setNewTheatres] = useState(new Set());
  const [creating, setCreating] = useState(false);

  // Admin panel
  const [adminGroup, setAdminGroup] = useState(null);

  // Members overlay
  const [membersGroup, setMembersGroup] = useState(null);

  // Profile drawer
  const [profileUserId, setProfileUserId] = useState(null);

  // User profile menu
  const [showProfile, setShowProfile] = useState(false);

  useEffect(() => {
    fetchMyGroups();
    fetchPublicGroups(1, "");
    fetchTheatres();
  }, []);

  async function fetchTheatres() {
    try {
      const r = await fetch(`${apiBase}/api/theatres`, { credentials: "include" });
      if (r.ok) {
        const data = await r.json();
        setAllTheatres(data);
        setNewTheatres(new Set(data.map(t => t.slug)));
      }
    } catch { /* ignore */ }
  }

  async function fetchMyGroups() {
    try {
      const r = await fetch(`${apiBase}/api/groups`, { credentials: "include" });
      if (r.ok) setMyGroups(await r.json());
    } catch { /* ignore */ }
  }

  async function fetchPublicGroups(pageNum = 1, searchQuery = "") {
    setLoadingPublic(true);
    try {
      const params = new URLSearchParams({ page: pageNum, per_page: 10 });
      if (searchQuery) params.set("q", searchQuery);
      const r = await fetch(
        `${apiBase}/api/groups/discover?${params}`,
        { credentials: "include" }
      );
      if (r.ok) {
        const data = await r.json();
        setPublicGroups(data.groups || []);
        setPage(data.page || 1);
        setTotalPages(data.pages || 1);
      }
    } catch { /* ignore */ }
    finally { setLoadingPublic(false); }
  }

  function handleSearch(e) {
    e.preventDefault();
    setPage(1);
    fetchPublicGroups(1, query);
  }

  function handleClearSearch() {
    setQuery("");
    setPage(1);
    fetchPublicGroups(1, "");
  }

  async function handleJoin(slug) {
    try {
      const r = await fetch(`${apiBase}/api/groups/${slug}/join`, {
        method: "POST",
        credentials: "include",
      });
      if (r.ok) {
        fetchPublicGroups(page, query);
        fetchMyGroups();
      }
    } catch { /* ignore */ }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const r = await fetch(`${apiBase}/api/groups`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ name: newName.trim(), description: newDesc, is_public: newPublic, theatres: [...newTheatres] }),
      });
      if (r.ok) {
        const group = await r.json();
        setGroupId(group.id);
        setNewName("");
        setNewDesc("");
        setShowCreate(false);
        fetchMyGroups();
        fetchPublicGroups(page, query);
      }
    } catch { /* ignore */ }
    finally { setCreating(false); }
  }

  async function logout() {
    await fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" });
    setUser(null);
  }

  function handleProfileUpdate(updatedUser) {
    setUser(updatedUser);
  }

  function handleAdminGroupUpdated(updated) {
    setMyGroups(prev => prev.map(g => (g.id === updated.id ? { ...g, ...updated } : g)));
    setAdminGroup(prev => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
  }

  function handleGroupDeleted(groupId) {
    setAdminGroup(null);
    fetchMyGroups();
    fetchPublicGroups(page, query);
    if (activeGroupId === groupId) {
      // Reset to first remaining group or null
      const remaining = myGroups.filter(g => g.id !== groupId);
      setGroupId(remaining.length > 0 ? remaining[0].id : null);
    }
  }

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <header className="group-discovery-header">
          <button className="group-back-btn" onClick={() => navigate("/")}>
            &larr; Calendar
          </button>
          <h1 className="group-discovery-title">Groups</h1>
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
                onUpdate={handleProfileUpdate}
                onLogout={logout}
                onClose={() => setShowProfile(false)}
              />
            )}
          </div>
        </header>

        {/* My Groups */}
        <section className="group-section">
          <h2 className="group-section-title">My Groups</h2>
          {myGroups.length === 0 ? (
            <p className="group-empty">Welcome to Cinema Club DC! Find a group below to get started.</p>
          ) : (
            <div className="group-cards">
              {myGroups.map(g => (
                <div
                  key={g.id}
                  className={`group-card${g.id === activeGroupId ? " active" : ""}`}
                >
                  <div className="group-card-info">
                    <span className="group-card-name">{g.name}</span>
                    <span className="group-card-meta">
                      {g.member_count} member{g.member_count !== 1 ? "s" : ""}
                      {g.role === "admin" && " \u00B7 admin"}
                    </span>
                  </div>
                  <div className="group-card-actions">
                    {g.id !== activeGroupId && (
                      <button
                        className="group-action-btn"
                        onClick={() => setGroupId(g.id)}
                      >
                        Switch
                      </button>
                    )}
                    {g.id === activeGroupId && (
                      <span className="group-active-badge">Active</span>
                    )}
                    <button
                      className="group-card-members-btn"
                      onClick={() => setMembersGroup(g)}
                    >
                      Members
                    </button>
                    {g.role === "admin" && (
                      <button
                        className="group-action-btn admin"
                        onClick={() => setAdminGroup(adminGroup?.slug === g.slug ? null : g)}
                      >
                        Manage
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* Admin panel */}
        {adminGroup && (
          <GroupAdmin
            group={adminGroup}
            apiBase={apiBase}
            onClose={() => setAdminGroup(null)}
            onGroupUpdated={handleAdminGroupUpdated}
            onGroupDeleted={handleGroupDeleted}
            onViewProfile={setProfileUserId}
          />
        )}

        {/* Browse / Search public groups */}
        <section className="group-section">
          <h2 className="group-section-title">Browse Groups</h2>
          <form className="group-search-form" onSubmit={handleSearch}>
            <input
              className="group-search-input"
              placeholder="Search by name..."
              value={query}
              onChange={e => setQuery(e.target.value)}
            />
            <button className="group-search-btn" type="submit" disabled={loadingPublic}>
              Search
            </button>
            {query && (
              <button className="group-search-btn clear" type="button" onClick={handleClearSearch}>
                Clear
              </button>
            )}
          </form>

          {loadingPublic && publicGroups.length === 0 ? (
            <p className="group-empty" style={{ opacity: 0.5 }}>Loading...</p>
          ) : publicGroups.length === 0 ? (
            <p className="group-empty">No groups found{query ? ` for "${query}"` : ""}.</p>
          ) : (
            <div className="group-cards" style={{ marginTop: "0.75rem" }}>
              {publicGroups.map(g => (
                <div key={g.id} className="group-card">
                  <div className="group-card-info">
                    <span className="group-card-name">{g.name}</span>
                    <span className="group-card-meta">
                      {g.member_count} member{g.member_count !== 1 ? "s" : ""}
                      {g.description && ` \u00B7 ${g.description}`}
                    </span>
                  </div>
                  <div className="group-card-actions">
                    {g.membership_status === "active" ? (
                      <span className="group-active-badge">Member</span>
                    ) : g.membership_status === "pending" ? (
                      <span className="group-pending-badge">Pending</span>
                    ) : (
                      <button
                        className="group-action-btn join"
                        onClick={() => handleJoin(g.slug)}
                      >
                        Request to Join
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="group-pagination">
              <button
                className="group-action-btn"
                disabled={page <= 1}
                onClick={() => { const p = page - 1; setPage(p); fetchPublicGroups(p, query); }}
              >
                &lsaquo; Previous
              </button>
              <span className="group-pagination-info">
                Page {page} of {totalPages}
              </span>
              <button
                className="group-action-btn"
                disabled={page >= totalPages}
                onClick={() => { const p = page + 1; setPage(p); fetchPublicGroups(p, query); }}
              >
                Next &rsaquo;
              </button>
            </div>
          )}
        </section>

        {/* Create group */}
        <section className="group-section">
          {!showCreate ? (
            <button className="group-create-toggle" onClick={() => setShowCreate(true)}>
              + Create a New Group
            </button>
          ) : (
            <form className="group-create-form" onSubmit={handleCreate}>
              <h2 className="group-section-title">Create Group</h2>
              <input
                className="group-create-input"
                placeholder="Group name"
                value={newName}
                onChange={e => setNewName(e.target.value)}
                required
              />
              <input
                className="group-create-input"
                placeholder="Description (optional)"
                value={newDesc}
                onChange={e => setNewDesc(e.target.value)}
              />
              <label className="group-create-checkbox">
                <input
                  type="checkbox"
                  checked={newPublic}
                  onChange={e => setNewPublic(e.target.checked)}
                />
                Public (searchable by anyone)
              </label>
              {allTheatres.length > 0 && (
                <div style={{ marginTop: "0.5rem" }}>
                  <label className="group-create-checkbox" style={{ marginBottom: "0.3rem" }}>
                    Theatres
                  </label>
                  <div className="theatre-filters" style={{ justifyContent: "flex-start" }}>
                    {allTheatres.map(t => (
                      <button
                        key={t.slug}
                        type="button"
                        className={`theatre-pill${newTheatres.has(t.slug) ? " active" : ""}`}
                        data-theatre={t.slug}
                        onClick={() => setNewTheatres(prev => {
                          const next = new Set(prev);
                          if (next.has(t.slug)) { if (next.size > 1) next.delete(t.slug); }
                          else next.add(t.slug);
                          return next;
                        })}
                      >
                        {t.name}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="group-create-actions">
                <button className="group-action-btn" type="submit" disabled={creating}>
                  {creating ? "Creating..." : "Create"}
                </button>
                <button className="group-action-btn cancel" type="button" onClick={() => setShowCreate(false)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </section>
      </div>

      {/* Members overlay */}
      {membersGroup && (
        <GroupMembers
          group={membersGroup}
          apiBase={apiBase}
          onClose={() => setMembersGroup(null)}
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

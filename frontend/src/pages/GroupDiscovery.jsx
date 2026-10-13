import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getJson, send } from "../api";
import { ClubBadge } from "../ui/Avatar";
import UserProfileDrawer from "../components/UserProfileDrawer";
import PageHeader from "../ui/PageHeader";

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


  // Profile drawer
  const [profileUserId, setProfileUserId] = useState(null);

  // User profile menu

  useEffect(() => {
    fetchMyGroups();
    fetchPublicGroups(1, "");
    fetchTheatres();
  }, []);

  async function fetchTheatres() {
    try {
      const data = await getJson(`${apiBase}/api/theatres`);
      setAllTheatres(data);
      setNewTheatres(new Set(data.map(t => t.slug)));
    } catch { /* ignore */ }
  }

  async function fetchMyGroups() {
    try {
      setMyGroups(await getJson(`${apiBase}/api/groups`));
    } catch { /* ignore */ }
  }

  async function fetchPublicGroups(pageNum = 1, searchQuery = "") {
    setLoadingPublic(true);
    try {
      const params = new URLSearchParams({ page: pageNum, per_page: 10 });
      if (searchQuery) params.set("q", searchQuery);
      const data = await getJson(`${apiBase}/api/groups/discover?${params}`);
      setPublicGroups(data.groups || []);
      setPage(data.page || 1);
      setTotalPages(data.pages || 1);
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
      await send(`${apiBase}/api/groups/${slug}/join`);
      fetchPublicGroups(page, query);
      fetchMyGroups();
    } catch { /* ignore */ }
  }

  async function handleCreate(e) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    try {
      const group = await send(`${apiBase}/api/groups`, "POST",
        { name: newName.trim(), description: newDesc, is_public: newPublic, theatres: [...newTheatres] });
      setGroupId(group.id);
      setNewName("");
      setNewDesc("");
      setShowCreate(false);
      fetchMyGroups();
      fetchPublicGroups(page, query);
    } catch { /* ignore */ }
    finally { setCreating(false); }
  }

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <PageHeader title="Groups" />

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
                  <ClubBadge group={g} size={40} />
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
                        className="btn btn-sm"
                        onClick={() => setGroupId(g.id)}
                      >
                        Switch
                      </button>
                    )}
                    {g.id === activeGroupId && (
                      <span className="group-active-badge">Active</span>
                    )}
                    <button
                      className="btn btn-sm"
                      onClick={() => { setGroupId(g.id); navigate("/club"); }}
                    >
                      Club page
                    </button>
                    {g.role === "admin" && (
                      <button
                        className="btn btn-sm"
                        onClick={() => { setGroupId(g.id); navigate("/club?tab=settings"); }}
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
            <button className="btn btn-primary" type="submit" disabled={loadingPublic}>
              Search
            </button>
            {query && (
              <button className="btn btn-ghost" type="button" onClick={handleClearSearch}>
                Clear
              </button>
            )}
          </form>

          {loadingPublic && publicGroups.length === 0 ? (
            <p className="group-empty loading">Loading…</p>
          ) : publicGroups.length === 0 ? (
            <p className="group-empty">No groups found{query ? ` for "${query}"` : ""}.</p>
          ) : (
            <div className="group-cards spaced">
              {publicGroups.map(g => (
                <div key={g.id} className="group-card">
                  <ClubBadge group={g} size={40} />
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
                        className="btn btn-sm btn-primary"
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
                className="btn btn-sm"
                disabled={page <= 1}
                onClick={() => { const p = page - 1; setPage(p); fetchPublicGroups(p, query); }}
              >
                &lsaquo; Previous
              </button>
              <span className="group-pagination-info">
                Page {page} of {totalPages}
              </span>
              <button
                className="btn btn-sm"
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
                <div className="group-create-theatres">
                  <label className="group-create-checkbox">
                    Theatres
                  </label>
                  <div className="theatre-filters">
                    {allTheatres.map(t => (
                      <button
                        key={t.slug}
                        type="button"
                        className={`theatre-pill${newTheatres.has(t.slug) ? " active" : ""}`}
                        data-theatre={t.slug}
                        style={{ "--tcolor": t.color }}
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
                <button className="btn btn-sm btn-primary" type="submit" disabled={creating}>
                  {creating ? "Creating..." : "Create"}
                </button>
                <button className="btn btn-sm btn-ghost" type="button" onClick={() => setShowCreate(false)}>
                  Cancel
                </button>
              </div>
            </form>
          )}
        </section>
      </div>

      {/* User profile drawer */}
      {profileUserId && (
        <UserProfileDrawer
          userId={profileUserId}
          viewerId={user.id}
          apiBase={apiBase}
          onClose={() => setProfileUserId(null)}
        />
      )}
    </div>
  );
}

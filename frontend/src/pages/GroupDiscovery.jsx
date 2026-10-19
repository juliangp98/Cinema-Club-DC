import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getJson, send } from "../api";
import ToggleChip from "../ui/ToggleChip";
import { ClubBadge } from "../ui/Avatar";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import Panel from "../ui/Panel";
import SearchField from "../ui/SearchField";
import { SwitchRow } from "../ui/Settings";

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

  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

  // Clubs (R15 style, 7f): your clubs and the ones to find side by side as
  // cards, with Start a club beside them on wide screens.
  return (
    <div className="page clubs-page">
      <PageHeader title="Clubs" meta={[myGroups.length > 0 && { icon: "🍿", label: `You're in ${plural(myGroups.length, "club")}` }]} />
      <div className="ui-split" style={{ "--split-side": "340px" }}>
        <div className="clubs-main">
          {myGroups.length > 0 && (
            <section className="clubs-section">
              <SectionTitle>Your clubs</SectionTitle>
              <div className="clubs-grid">
                {myGroups.map(g => (
                  <Panel key={g.id} as="article" className={`club-find-card${g.id === activeGroupId ? " active" : ""}`}
                         title={<><ClubBadge group={g} size={36} /> {g.name}</>}
                         hint={`${plural(g.member_count, "member")}${g.role === "admin" ? " · you're an admin" : ""}`}
                         aside={g.id === activeGroupId && <span className="ui-badge gold">Viewing</span>}
                         actions={<>
                           {g.id !== activeGroupId && <button className="btn btn-sm" onClick={() => setGroupId(g.id)}>Switch to it</button>}
                           <button className="btn btn-sm" onClick={() => { setGroupId(g.id); navigate("/club"); }}>Club page</button>
                           {g.role === "admin" && (
                             <button className="btn btn-sm btn-ghost" onClick={() => { setGroupId(g.id); navigate("/club?tab=settings"); }}>Settings</button>
                           )}
                         </>} />
                ))}
              </div>
            </section>
          )}

          <section className="clubs-section">
            <SectionTitle>Find a club</SectionTitle>
            <SearchField className="group-search" label="Search clubs" placeholder="Search clubs by name — Enter to search"
                         value={query} onChange={setQuery} onSubmit={handleSearch} onClear={handleClearSearch} />
            {loadingPublic && publicGroups.length === 0 ? (
              <p className="pv-empty">Loading…</p>
            ) : publicGroups.length === 0 ? (
              <p className="pv-empty">No clubs found{query ? ` for “${query}”` : ""}.</p>
            ) : (
              <div className="clubs-grid">
                {publicGroups.map(g => (
                  <Panel key={g.id} as="article" className="club-find-card"
                         title={<><ClubBadge group={g} size={36} /> {g.name}</>} hint={plural(g.member_count, "member")}
                         actions={g.membership_status === "active" ? <span className="ui-badge go">Member</span>
                           : g.membership_status === "pending" ? <span className="ui-badge gold">Asked to join</span>
                           : <button className="btn btn-sm btn-primary" onClick={() => handleJoin(g.slug)}>Ask to join</button>}>
                    {g.description && <p className="club-find-desc">{g.description}</p>}
                  </Panel>
                ))}
              </div>
            )}
            {totalPages > 1 && (
              <div className="clubs-pages">
                <button className="btn btn-sm" disabled={page <= 1}
                        onClick={() => { const p = page - 1; setPage(p); fetchPublicGroups(p, query); }}>‹ Previous</button>
                <span className="ui-hint">Page {page} of {totalPages}</span>
                <button className="btn btn-sm" disabled={page >= totalPages}
                        onClick={() => { const p = page + 1; setPage(p); fetchPublicGroups(p, query); }}>Next ›</button>
              </div>
            )}
          </section>
        </div>

        <aside className="ui-split-side sticky" aria-label="Start a club">
          {myGroups.length === 0 && (
            <Panel tone="callout" title="Welcome!">
              <p>A club follows a few theatres and plans outings together: who's going, polls, games. Find one to ask to join, or start your own.</p>
            </Panel>
          )}
          <Panel tone="gold" title="Start a club" hint="You'll be its admin">
            {!showCreate ? (
              <>
                <p className="ui-hint">Pick its theatres and invite people from Club settings once it's made.</p>
                <button className="btn btn-sm btn-primary clubs-start" onClick={() => setShowCreate(true)}>＋ Start a club</button>
              </>
            ) : (
              <form className="clubs-create" onSubmit={handleCreate}>
                <input className="share-input" placeholder="Club name" aria-label="Club name" value={newName}
                       onChange={e => setNewName(e.target.value)} required />
                <input className="share-input" placeholder="Description (optional)" aria-label="Description" value={newDesc}
                       onChange={e => setNewDesc(e.target.value)} />
                <SwitchRow label="Anyone can find it" hint="Off: only people you invite." checked={newPublic} onChange={setNewPublic} />
                {allTheatres.length > 0 && (
                  <fieldset className="clubs-theatres"><legend className="profile-section-label">Theatres</legend>
                    <div className="filter-chips">
                      {allTheatres.map(t => (
                        <ToggleChip key={t.slug} on={newTheatres.has(t.slug)} color={t.color}
                                    onClick={() => setNewTheatres(prev => {
                                      const next = new Set(prev);
                                      if (next.has(t.slug)) { if (next.size > 1) next.delete(t.slug); } else next.add(t.slug);
                                      return next;
                                    })}>
                          {t.short_name || t.name}
                        </ToggleChip>
                      ))}
                    </div>
                  </fieldset>
                )}
                <div className="clubs-create-actions">
                  <button className="btn btn-sm btn-ghost" type="button" onClick={() => setShowCreate(false)}>Cancel</button>
                  <button className="btn btn-sm btn-primary" type="submit" disabled={creating}>{creating ? "Starting…" : "Start it"}</button>
                </div>
              </form>
            )}
          </Panel>
        </aside>
      </div>
    </div>
  );
}

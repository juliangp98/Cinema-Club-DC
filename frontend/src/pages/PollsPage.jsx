import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import ProfileMenu from "../components/ProfileMenu";

const SCORING_LABELS = {
  none: "No scoring",
  single: "1 🍿 per correct",
  ranked: "Ranked 🍿",
  confidence: "Confidence × 🍿",
};

const TYPE_LABELS = { standard: "Poll", prediction: "Prediction" };
const STATUS_LABELS = { open: "Open", closed: "Closed", scored: "Scored" };

export default function PollsPage({ user, setUser, apiBase, activeGroupId }) {
  const navigate = useNavigate();
  const [polls, setPolls] = useState([]);
  const [group, setGroup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showProfile, setShowProfile] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [isAdmin, setIsAdmin] = useState(false);

  // Create form state
  const [newTitle, setNewTitle] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [newType, setNewType] = useState("standard");
  const [newScoring, setNewScoring] = useState("none");
  const [categories, setCategories] = useState([{ title: "", options: ["", ""] }]);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    if (!activeGroupId) { setLoading(false); return; }
    Promise.all([
      fetch(`${apiBase}/api/groups`, { credentials: "include" }).then(r => r.ok ? r.json() : []),
      fetch(`${apiBase}/api/groups/${activeGroupId}/polls`, { credentials: "include" }).then(r => r.ok ? r.json() : []),
    ]).then(([groups, pollsData]) => {
      const g = groups.find(g => g.id === activeGroupId);
      setGroup(g || null);
      setIsAdmin(g?.role === "admin");
      setPolls(pollsData);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [activeGroupId, apiBase]);

  async function handleCreatePoll(e) {
    e.preventDefault();
    if (!newTitle.trim()) return;
    setCreating(true);

    const body = {
      title: newTitle.trim(),
      description: newDesc,
      poll_type: newType,
      scoring_mode: newScoring,
      categories: categories
        .filter(c => c.title.trim())
        .map(c => ({
          title: c.title.trim(),
          options: c.options.filter(o => o.trim()).map(o => ({ text: o.trim() })),
        })),
    };

    try {
      const r = await fetch(`${apiBase}/api/groups/${activeGroupId}/polls`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(body),
      });
      if (r.ok) {
        const poll = await r.json();
        setPolls(prev => [poll, ...prev]);
        setShowCreate(false);
        setNewTitle("");
        setNewDesc("");
        setCategories([{ title: "", options: ["", ""] }]);
      }
    } catch { /* ignore */ }
    finally { setCreating(false); }
  }

  async function handleCreateOscars(scoringMode) {
    setCreating(true);
    try {
      const r = await fetch(`${apiBase}/api/groups/${activeGroupId}/polls/oscars`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ scoring_mode: scoringMode }),
      });
      if (r.ok) {
        const poll = await r.json();
        setPolls(prev => [poll, ...prev]);
      }
    } catch { /* ignore */ }
    finally { setCreating(false); }
  }

  function addCategory() {
    setCategories(prev => [...prev, { title: "", options: ["", ""] }]);
  }

  function updateCategoryTitle(idx, val) {
    setCategories(prev => prev.map((c, i) => i === idx ? { ...c, title: val } : c));
  }

  function addOption(catIdx) {
    setCategories(prev => prev.map((c, i) => i === catIdx ? { ...c, options: [...c.options, ""] } : c));
  }

  function updateOption(catIdx, optIdx, val) {
    setCategories(prev => prev.map((c, i) =>
      i === catIdx ? { ...c, options: c.options.map((o, j) => j === optIdx ? val : o) } : c
    ));
  }

  function removeOption(catIdx, optIdx) {
    setCategories(prev => prev.map((c, i) =>
      i === catIdx ? { ...c, options: c.options.filter((_, j) => j !== optIdx) } : c
    ));
  }

  function removeCategory(idx) {
    setCategories(prev => prev.filter((_, i) => i !== idx));
  }

  function logout() {
    fetch(`${apiBase}/api/auth/logout`, { method: "POST", credentials: "include" })
      .then(() => window.location.reload());
  }

  if (loading) return null;
  if (!group) { navigate("/"); return null; }

  const openPolls = polls.filter(p => p.status === "open");
  const closedPolls = polls.filter(p => p.status !== "open");

  return (
    <div className="group-discovery-page">
      <div className="group-discovery-container">
        <header className="group-discovery-header">
          <button className="group-back-btn" onClick={() => navigate("/")}>
            &larr; Calendar
          </button>
          <h1 className="group-discovery-title">Polls</h1>
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

        {/* Admin actions */}
        {isAdmin && (
          <div className="poll-admin-bar">
            <button className="poll-create-btn" onClick={() => setShowCreate(!showCreate)}>
              + Create Poll
            </button>
            <button
              className="poll-create-btn oscars"
              onClick={() => handleCreateOscars("confidence")}
              disabled={creating}
            >
              🏆 Oscars Template
            </button>
          </div>
        )}

        {/* Create form */}
        {showCreate && (
          <form className="poll-create-form" onSubmit={handleCreatePoll}>
            <h3 className="poll-form-title">New Poll</h3>
            <input
              className="poll-input"
              placeholder="Poll title"
              value={newTitle}
              onChange={e => setNewTitle(e.target.value)}
              required
            />
            <input
              className="poll-input"
              placeholder="Description (optional)"
              value={newDesc}
              onChange={e => setNewDesc(e.target.value)}
            />

            <div className="poll-form-row">
              <label className="poll-form-label">Type</label>
              <div className="poll-radio-group">
                {Object.entries(TYPE_LABELS).map(([val, label]) => (
                  <label
                    key={val}
                    className={`poll-radio type-${val}${newType === val ? " active" : ""}`}
                  >
                    <input
                      type="radio"
                      name="pollType"
                      value={val}
                      checked={newType === val}
                      onChange={() => setNewType(val)}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>

            <div className="poll-form-row">
              <label className="poll-form-label">Scoring</label>
              <div className="poll-radio-group">
                {Object.entries(SCORING_LABELS).map(([val, label]) => (
                  <label
                    key={val}
                    className={`poll-radio scoring-${val}${newScoring === val ? " active" : ""}`}
                  >
                    <input
                      type="radio"
                      name="scoring"
                      value={val}
                      checked={newScoring === val}
                      onChange={() => setNewScoring(val)}
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>

            <div className="poll-categories-editor">
              <label className="poll-form-label">
                {newType === "prediction" ? "Categories" : "Options"}
              </label>
              {categories.map((cat, ci) => (
                <div key={ci} className="poll-category-block">
                  {newType === "prediction" && (
                    <div className="poll-category-header">
                      <input
                        className="poll-input small"
                        placeholder={`Category ${ci + 1} title`}
                        value={cat.title}
                        onChange={e => updateCategoryTitle(ci, e.target.value)}
                      />
                      {categories.length > 1 && (
                        <button type="button" className="poll-remove-btn" onClick={() => removeCategory(ci)}>✕</button>
                      )}
                    </div>
                  )}
                  {!newType || newType === "standard" ? (
                    // Standard: just show title as the single category
                    <input
                      className="poll-input small"
                      placeholder="Question"
                      value={cat.title}
                      onChange={e => updateCategoryTitle(ci, e.target.value)}
                      style={{ display: categories.length === 1 ? "block" : undefined }}
                    />
                  ) : null}
                  <div className="poll-options-list">
                    {cat.options.map((opt, oi) => (
                      <div key={oi} className="poll-option-row">
                        <input
                          className="poll-input tiny"
                          placeholder={`Option ${oi + 1}`}
                          value={opt}
                          onChange={e => updateOption(ci, oi, e.target.value)}
                        />
                        {cat.options.length > 2 && (
                          <button type="button" className="poll-remove-btn" onClick={() => removeOption(ci, oi)}>✕</button>
                        )}
                      </div>
                    ))}
                    <button type="button" className="poll-add-option" onClick={() => addOption(ci)}>+ Add option</button>
                  </div>
                </div>
              ))}
              {newType === "prediction" && (
                <button type="button" className="poll-add-option" onClick={addCategory}>+ Add category</button>
              )}
            </div>

            <div className="poll-form-actions">
              <button className="poll-submit-btn" type="submit" disabled={creating}>
                {creating ? "Creating..." : "Create Poll"}
              </button>
              <button type="button" className="poll-cancel-btn" onClick={() => setShowCreate(false)}>
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Open polls */}
        <section className="poll-section">
          <h2 className="group-section-title">
            {openPolls.length > 0 ? `Open (${openPolls.length})` : "No Open Polls"}
          </h2>
          <div className="poll-cards">
            {openPolls.map(p => (
              <button key={p.id} className="poll-card" onClick={() => navigate(`/polls/${p.id}`)}>
                <div className="poll-card-header">
                  <span className="poll-card-title">{p.title}</span>
                  <span className={`poll-status-badge ${p.status}`}>{STATUS_LABELS[p.status]}</span>
                </div>
                <div className="poll-card-meta">
                  <span className={`poll-type-badge ${p.poll_type}`}>{TYPE_LABELS[p.poll_type]}</span>
                  <span className="poll-scoring-badge">{SCORING_LABELS[p.scoring_mode]}</span>
                  <span>{p.category_count} {p.category_count === 1 ? "category" : "categories"}</span>
                </div>
              </button>
            ))}
          </div>
        </section>

        {/* Past polls */}
        {closedPolls.length > 0 && (
          <section className="poll-section">
            <h2 className="group-section-title">Past ({closedPolls.length})</h2>
            <div className="poll-cards">
              {closedPolls.map(p => (
                <button key={p.id} className="poll-card past" onClick={() => navigate(`/polls/${p.id}`)}>
                  <div className="poll-card-header">
                    <span className="poll-card-title">{p.title}</span>
                    <span className={`poll-status-badge ${p.status}`}>{STATUS_LABELS[p.status]}</span>
                  </div>
                  <div className="poll-card-meta">
                    <span className={`poll-type-badge ${p.poll_type}`}>{TYPE_LABELS[p.poll_type]}</span>
                    <span className="poll-scoring-badge">{SCORING_LABELS[p.scoring_mode]}</span>
                    {p.status === "scored" && <span>🍿 Scored</span>}
                  </div>
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

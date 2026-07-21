import { useState, useEffect } from "react";

export default function GroupAdmin({ group, apiBase, onClose, onGroupUpdated, onGroupDeleted, onViewProfile }) {
  const [members, setMembers] = useState([]);
  const [name, setName] = useState(group.name || "");
  const [description, setDescription] = useState(group.description || "");
  const [selectedTheatres, setSelectedTheatres] = useState(new Set(group.theatres || []));
  const [allTheatres, setAllTheatres] = useState([]);
  const [savingMeta, setSavingMeta] = useState(false);
  const [metaError, setMetaError] = useState("");
  const [metaSaved, setMetaSaved] = useState(false);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteUrl, setInviteUrl] = useState("");
  const [inviteMsg, setInviteMsg] = useState("");
  const [inviting, setInviting] = useState(false);
  const [inviteError, setInviteError] = useState("");

  useEffect(() => {
    setName(group.name || "");
    setDescription(group.description || "");
    setSelectedTheatres(new Set(group.theatres || []));
    fetchMembers();
    fetchTheatres();
  }, [group.slug, group.name, group.description]);

  async function fetchTheatres() {
    try {
      const r = await fetch(`${apiBase}/api/theatres`, { credentials: "include" });
      if (r.ok) setAllTheatres(await r.json());
    } catch { /* ignore */ }
  }

  async function fetchMembers() {
    try {
      const r = await fetch(`${apiBase}/api/groups/${group.slug}/members`, { credentials: "include" });
      if (r.ok) setMembers(await r.json());
    } catch { /* ignore */ }
  }

  async function handleSaveMeta(e) {
    e.preventDefault();
    setSavingMeta(true);
    setMetaError("");
    setMetaSaved(false);
    try {
      const r = await fetch(`${apiBase}/api/groups/${group.slug}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: name.trim(),
          description,
          theatres: [...selectedTheatres],
        }),
      });
      const d = await r.json();
      if (r.ok) {
        setName(d.name || "");
        setDescription(d.description || "");
        setMetaSaved(true);
        if (onGroupUpdated) onGroupUpdated(d);
        setTimeout(() => setMetaSaved(false), 2000);
      } else {
        setMetaError(d.error || "Could not update group");
      }
    } catch {
      setMetaError("Could not connect");
    } finally {
      setSavingMeta(false);
    }
  }

  async function approve(uid) {
    try {
      await fetch(`${apiBase}/api/groups/${group.slug}/members/${uid}/approve`, {
        method: "POST", credentials: "include",
      });
      fetchMembers();
    } catch { /* ignore */ }
  }

  async function deny(uid) {
    try {
      await fetch(`${apiBase}/api/groups/${group.slug}/members/${uid}/deny`, {
        method: "POST", credentials: "include",
      });
      fetchMembers();
    } catch { /* ignore */ }
  }

  async function removeMember(uid) {
    try {
      await fetch(`${apiBase}/api/groups/${group.slug}/members/${uid}`, {
        method: "DELETE", credentials: "include",
      });
      fetchMembers();
    } catch { /* ignore */ }
  }

  async function handleDeleteGroup() {
    if (!window.confirm(
      `Are you sure you want to delete "${group.name}"? This will remove all members, RSVPs, messages, and reactions for this group. This cannot be undone.`
    )) return;

    try {
      const r = await fetch(`${apiBase}/api/groups/${group.slug}`, {
        method: "DELETE",
        credentials: "include",
      });
      if (r.ok) {
        if (onGroupDeleted) onGroupDeleted(group.id);
      }
    } catch { /* ignore */ }
  }

  async function handleInvite(e) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setInviting(true);
    setInviteError("");
    setInviteUrl("");
    setInviteMsg("");
    try {
      const r = await fetch(`${apiBase}/api/admin/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ email: inviteEmail.trim(), group_id: group.id }),
      });
      const d = await r.json();
      if (r.ok) {
        setInviteMsg(d.message || "Done!");
        if (d.invite_url) setInviteUrl(d.invite_url);
        setInviteEmail("");
        fetchMembers();
      } else {
        setInviteError(d.error || "Invite failed");
      }
    } catch {
      setInviteError("Could not connect");
    } finally {
      setInviting(false);
    }
  }

  const pending = members.filter(m => m.status === "pending");
  const active = members.filter(m => m.status === "active");

  return (
    <div className="group-admin">
      <div className="group-admin-header">
        <h3 className="group-admin-title">Manage: {group.name}</h3>
        <button className="group-admin-close" onClick={onClose}>&times;</button>
      </div>

      {/* Group meta */}
      <div className="group-admin-section">
        <span className="group-admin-label">Group Details</span>
        <form className="group-meta-form" onSubmit={handleSaveMeta}>
          <input
            className="group-create-input"
            placeholder="Group name"
            value={name}
            onChange={e => { setName(e.target.value); setMetaSaved(false); }}
            maxLength={100}
            required
          />
          <textarea
            className="group-create-input"
            placeholder="Description (optional)"
            value={description}
            onChange={e => { setDescription(e.target.value); setMetaSaved(false); }}
            rows={2}
            maxLength={500}
          />
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
                    className={`theatre-pill${selectedTheatres.has(t.slug) ? " active" : ""}`}
                    data-theatre={t.slug}
                    style={{ "--tcolor": t.color }}
                    onClick={() => {
                      setSelectedTheatres(prev => {
                        const next = new Set(prev);
                        if (next.has(t.slug)) { if (next.size > 1) next.delete(t.slug); }
                        else next.add(t.slug);
                        return next;
                      });
                      setMetaSaved(false);
                    }}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <div className="group-create-actions">
            <button className="group-action-btn" type="submit" disabled={savingMeta}>
              {savingMeta ? "Saving..." : "Save"}
            </button>
            {metaSaved && <span className="group-meta-saved">Saved!</span>}
          </div>
          {metaError && <div className="group-invite-error">{metaError}</div>}
        </form>
      </div>

      {/* Invite */}
      <div className="group-admin-section">
        <span className="group-admin-label">Invite by Email</span>
        <form className="group-invite-form" onSubmit={handleInvite}>
          <input
            className="group-invite-input"
            type="email"
            placeholder="friend@example.com"
            value={inviteEmail}
            onChange={e => setInviteEmail(e.target.value)}
          />
          <button className="group-action-btn" type="submit" disabled={inviting}>
            Invite
          </button>
        </form>
        {inviteError && <div className="group-invite-error">{inviteError}</div>}
        {inviteMsg && (
          <div className="group-invite-success">{inviteMsg}</div>
        )}
        {inviteUrl && (
          <div className="group-invite-url">
            Share this link: <code>{inviteUrl}</code>
          </div>
        )}
      </div>

      {/* Pending */}
      {pending.length > 0 && (
        <div className="group-admin-section">
          <span className="group-admin-label">Pending Requests ({pending.length})</span>
          {pending.map(m => (
            <div key={m.id} className="group-member-row pending">
              <div
                className="group-member-avatar"
                style={{ background: m.user.avatar_color, color: "#0d0c09", cursor: "pointer" }}
                onClick={() => onViewProfile?.(m.user.id)}
              >
                {m.user.name.slice(0, 2).toUpperCase()}
              </div>
              <span
                className="group-member-name"
                style={{ cursor: "pointer" }}
                onClick={() => onViewProfile?.(m.user.id)}
              >{m.user.name}</span>
              <span className="group-member-email">{m.user.email}</span>
              <div className="group-member-actions">
                <button className="group-action-btn approve" onClick={() => approve(m.user.id)}>
                  Approve
                </button>
                <button className="group-action-btn deny" onClick={() => deny(m.user.id)}>
                  Deny
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Active members */}
      <div className="group-admin-section">
        <span className="group-admin-label">Members ({active.length})</span>
        {active.map(m => (
          <div key={m.id} className="group-member-row">
            <div
              className="group-member-avatar"
              style={{ background: m.user.avatar_color, color: "#0d0c09", cursor: "pointer" }}
              onClick={() => onViewProfile?.(m.user.id)}
            >
              {m.user.name.slice(0, 2).toUpperCase()}
            </div>
            <span
              className="group-member-name"
              style={{ cursor: "pointer" }}
              onClick={() => onViewProfile?.(m.user.id)}
            >{m.user.name}</span>
            {m.role === "admin" && <span className="group-role-badge">admin</span>}
            {m.role !== "admin" && (
              <button
                className="group-action-btn remove"
                onClick={() => removeMember(m.user.id)}
              >
                Remove
              </button>
            )}
          </div>
        ))}
      </div>

      {/* Danger Zone */}
      <div className="danger-zone">
        <div className="danger-zone-label">Danger Zone</div>
        <button className="danger-zone-btn" onClick={handleDeleteGroup}>
          Delete Group
        </button>
      </div>
    </div>
  );
}

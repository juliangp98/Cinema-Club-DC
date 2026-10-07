import { useState, useEffect } from "react";
import { SectionTitle } from "../ui/PageHeader";
import Avatar, { ClubBadge, initialsOf } from "../ui/Avatar";
import PicturePicker, { sendPicture, sendJson } from "../ui/PicturePicker";
import { ROLES } from "../roles";

// A club's settings, for its admins (R6b): picture and short name, details and
// theatres, invites, join requests, members' roles, and deleting the club.
export default function ClubSettings({ group, apiBase, viewerId, onChanged, onDeleted, onViewProfile }) {
  const base = `${apiBase}/api/groups/${group.slug}`;
  const [name, setName] = useState(group.name || "");
  const [description, setDescription] = useState(group.description || "");
  const [shortName, setShortName] = useState(group.short_name || "");
  const [theatres, setTheatres] = useState(new Set(group.theatres || []));
  const [allTheatres, setAllTheatres] = useState([]);
  const [members, setMembers] = useState([]);
  const [saved, setSaved] = useState("");
  const [error, setError] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [invite, setInvite] = useState(null);

  useEffect(() => {
    setName(group.name || "");
    setDescription(group.description || "");
    setShortName(group.short_name || "");
    setTheatres(new Set(group.theatres || []));
  }, [group]);
  useEffect(() => {
    fetch(`${apiBase}/api/theatres`, { credentials: "include" }).then(r => (r.ok ? r.json() : [])).then(setAllTheatres).catch(() => {});
  }, [apiBase]);
  const loadMembers = () => fetch(`${base}/members`, { credentials: "include" })
    .then(r => (r.ok ? r.json() : [])).then(setMembers).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { loadMembers(); }, [base]);

  const run = async (fn, okText) => {
    setError("");
    setSaved("");
    try {
      await fn();
      if (okText) { setSaved(okText); setTimeout(() => setSaved(""), 2500); }
    } catch (e) {
      setError(e.message);
    }
  };
  const update = async payload => onChanged?.(await sendJson(base, "PUT", payload));
  const memberAction = async (path, method = "POST", payload) => {
    const r = await fetch(`${base}/members/${path}`, {
      method, credentials: "include",
      headers: payload ? { "Content-Type": "application/json" } : undefined,
      body: payload ? JSON.stringify(payload) : undefined,
    }).catch(() => null);
    if (!r?.ok) throw new Error((await r?.json().catch(() => ({})))?.error || "Couldn't do that — try again.");
    loadMembers();
  };

  async function sendInvite(e) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    await run(async () => {
      const d = await sendJson(`${apiBase}/api/admin/invite`, "POST", { email: inviteEmail.trim(), group_id: group.id });
      setInvite(d);
      setInviteEmail("");
      loadMembers();
    });
  }

  async function deleteClub() {
    if (!window.confirm(`Delete "${group.name}"? Its members, RSVPs, comments, reactions and polls are removed for good.`)) return;
    await run(async () => {
      const r = await fetch(base, { method: "DELETE", credentials: "include" }).catch(() => null);
      if (!r?.ok) throw new Error("Couldn't delete the club — try again.");
      onDeleted?.();
    });
  }

  const pending = members.filter(m => m.status === "pending");
  const active = members.filter(m => m.status === "active");

  return (
    <div className="club-settings">
      {(saved || error) && <p className={error ? "share-error" : "club-saved"} role="status">{error || saved}</p>}

      <SectionTitle>Picture</SectionTitle>
      <PicturePicker
        preview={<ClubBadge group={group} size={72} />}
        onUpload={file => sendPicture(`${base}/picture`, file).then(onChanged)}
        onEmoji={emoji => update({ emoji })}
        onClear={(group.photo_url || group.emoji) ? () => update({ emoji: "", photo: null }) : null}
        clearLabel="Remove picture"
      />
      <form className="club-form" onSubmit={e => { e.preventDefault(); run(() => update({ short_name: shortName }), "Saved"); }}>
        <label className="pv-label" htmlFor="club-short">Short name</label>
        <div className="club-inline">
          <input id="club-short" className="share-input" value={shortName} maxLength={12} onChange={e => setShortName(e.target.value)}
                 placeholder={initialsOf(group.name)} />
          <button className="btn btn-sm" disabled={shortName === (group.short_name || "")}>Save</button>
        </div>
        <p className="pv-hint">Shown in the top bar when there isn't room for the full name. Blank: {initialsOf(group.name)}.</p>
      </form>

      <SectionTitle>Details</SectionTitle>
      <form className="club-form" onSubmit={e => {
        e.preventDefault();
        run(() => update({ name: name.trim(), description, theatres: [...theatres] }), "Saved");
      }}>
        <label className="pv-label" htmlFor="club-name">Name</label>
        <input id="club-name" className="share-input" value={name} maxLength={100} required onChange={e => setName(e.target.value)} />
        <label className="pv-label" htmlFor="club-desc">Description</label>
        <textarea id="club-desc" className="share-input" rows={2} maxLength={500} value={description}
                  onChange={e => setDescription(e.target.value)} />
        {allTheatres.length > 0 && (
          <>
            <span className="pv-label">Theatres</span>
            <div className="club-chips">
              {allTheatres.map(t => (
                <button key={t.slug} type="button" className={`chip${theatres.has(t.slug) ? " gold" : ""}`} aria-pressed={theatres.has(t.slug)}
                        onClick={() => setTheatres(prev => {
                          const next = new Set(prev);
                          if (next.has(t.slug)) { if (next.size > 1) next.delete(t.slug); } else next.add(t.slug);
                          return next;
                        })}>
                  {t.short_name || t.name}
                </button>
              ))}
            </div>
          </>
        )}
        <div className="club-form-foot"><button className="btn btn-primary btn-sm">Save details</button></div>
      </form>

      <SectionTitle>Invite by email</SectionTitle>
      <form className="club-inline" onSubmit={sendInvite}>
        <input className="share-input" type="email" placeholder="friend@example.com" value={inviteEmail}
               onChange={e => setInviteEmail(e.target.value)} aria-label="Email to invite" />
        <button className="btn btn-sm">Invite</button>
      </form>
      {invite && (
        <p className="pv-hint">{invite.message}{invite.invite_url && <> · Link: <code className="club-code">{invite.invite_url}</code></>}</p>
      )}

      {pending.length > 0 && (
        <>
          <SectionTitle>Join requests ({pending.length})</SectionTitle>
          <ul className="club-rows">
            {pending.map(m => (
              <li key={m.id} className="club-row">
                <Avatar user={m.user} size={34} onClick={() => onViewProfile(m.user.id)} />
                <span className="club-row-name">{m.user.name}</span>
                <span className="club-row-actions">
                  <button className="btn btn-sm btn-primary" onClick={() => run(() => memberAction(`${m.user.id}/approve`))}>Approve</button>
                  <button className="btn btn-sm" onClick={() => run(() => memberAction(`${m.user.id}/deny`))}>Deny</button>
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <SectionTitle>Members and roles ({active.length})</SectionTitle>
      <p className="pv-hint">{ROLES.map(r => `${r.label}: ${r.hint}`).join(" · ")}</p>
      <ul className="club-rows">
        {active.map(m => (
          <li key={m.id} className="club-row">
            <Avatar user={m.user} size={34} onClick={() => onViewProfile(m.user.id)} />
            <span className="club-row-name">{m.user.name}{m.user.id === viewerId && <span className="club-you"> (you)</span>}</span>
            <span className="club-row-actions">
              <select className="share-input club-role-select" value={m.role || "member"} aria-label={`${m.user.name}'s role`}
                      onChange={e => run(() => memberAction(`${m.user.id}/role`, "PUT", { role: e.target.value }), "Role updated")}>
                {ROLES.map(r => <option key={r.value} value={r.value}>{r.label}</option>)}
              </select>
              {m.role !== "admin" && (
                <button className="btn btn-sm btn-ghost" onClick={() => {
                  if (window.confirm(`Remove ${m.user.name} from the club?`)) run(() => memberAction(`${m.user.id}`, "DELETE"));
                }}>Remove</button>
              )}
            </span>
          </li>
        ))}
      </ul>

      <div className="club-danger">
        <div>
          <strong>Delete this club</strong>
          <p className="pv-hint">Removes its members, RSVPs, comments, reactions and polls. This can't be undone.</p>
        </div>
        <button className="btn btn-sm btn-danger" onClick={deleteClub}>Delete club</button>
      </div>
    </div>
  );
}

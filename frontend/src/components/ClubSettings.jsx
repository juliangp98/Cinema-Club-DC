import { useState, useEffect } from "react";
import { SectionTitle } from "../ui/PageHeader";
import Avatar, { ClubBadge, initialsOf } from "../ui/Avatar";
import PicturePicker, { sendPicture } from "../ui/PicturePicker";
import { getJson, send } from "../api";
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
    getJson(`${apiBase}/api/theatres`).then(setAllTheatres).catch(() => {});
  }, [apiBase]);
  const loadMembers = () => getJson(`${base}/members`, { cache: false }).then(setMembers).catch(() => {});
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
  const update = async payload => onChanged?.(await send(base, "PUT", payload));
  const memberAction = async (path, method = "POST", payload) => {
    await send(`${base}/members/${path}`, method, payload);
    loadMembers();
  };

  async function sendInvite(e) {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    await run(async () => {
      const d = await send(`${apiBase}/api/admin/invite`, "POST", { email: inviteEmail.trim(), group_id: group.id });
      setInvite(d);
      setInviteEmail("");
      loadMembers();
    });
  }

  async function deleteClub() {
    if (!window.confirm(`Delete "${group.name}"? Its members, RSVPs, comments, reactions and polls are removed for good.`)) return;
    await run(async () => {
      await send(base, "DELETE");
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
        <p className="ui-hint">Shown in the top bar when there isn't room for the full name. Blank: {initialsOf(group.name)}.</p>
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

      <SectionTitle>Movie trivia</SectionTitle>
      <p className="ui-hint">Questions made from the films on your calendar and classic movie quotes. Each part is off
        until you turn it on, and nobody is ever sent anything.</p>
      <div className="club-form club-trivia">
        <label className="notify-row">
          <input type="checkbox" checked={!!group.trivia?.enabled}
                 onChange={e => run(() => update({ trivia_enabled: e.target.checked }), "Saved")} />
          <span><span className="notify-name">Question of the day</span>
            <span className="ui-hint">One question a day, the same for everyone, on the club feed (and /trivia in
              Discord). A right answer is worth 2 kernels.</span></span>
        </label>
        {group.trivia?.enabled && group.discord && (
          <label className="notify-row club-trivia-sub">
            <input type="checkbox" checked={!!group.trivia?.discord}
                   onChange={e => run(() => update({ trivia_discord: e.target.checked }), "Saved")} />
            <span><span className="notify-name">Also post it in Discord (#movies)</span>
              <span className="ui-hint">Around 11 AM, with A–D buttons; answers stay private.</span></span>
          </label>
        )}
        <label className="notify-row">
          <input type="checkbox" checked={!!group.trivia?.anytime}
                 onChange={e => run(() => update({ trivia_anytime: e.target.checked }), "Saved")} />
          <span><span className="notify-name">Play anytime</span>
            <span className="ui-hint">Members can ask for extra questions whenever they like (on the feed, or /trivia
              in Discord). +1 kernel for a right one, up to 5 a day — after that they're just for fun.</span></span>
        </label>
      </div>

      <SectionTitle>Repertory bingo</SectionTitle>
      <div className="club-form club-trivia">
        <label className="notify-row">
          <input type="checkbox" checked={!!group.bingo?.enabled}
                 onChange={e => run(() => update({ bingo_enabled: e.target.checked }), "Saved")} />
          <span><span className="notify-name">A bingo card every month</span>
            <span className="ui-hint">One 3×3 card for the whole club (the middle's free) that fills in by itself from
              check-ins: on film, before 1960, a late show, a theatre you'd never been to… Only squares this month's
              calendar can fill. First line +5 kernels, the full card +15. Nobody is sent anything.</span></span>
        </label>
      </div>

      <SectionTitle>Screening notes</SectionTitle>
      <div className="club-form club-trivia">
        <label className="notify-row">
          <input type="checkbox" checked={!!group.notes?.enabled}
                 onChange={e => run(() => update({ notes_enabled: e.target.checked }), "Saved")} />
          <span><span className="notify-name">Quick notes about each screening</span>
            <span className="ui-hint">Members who checked in can tag the night: gorgeous print, sound trouble, packed
              house, great Q&amp;A… Shown on the screening, in the feed and on theatre pages (to members only). Nobody is
              sent anything.</span></span>
        </label>
      </div>

      <SectionTitle>Invite by email</SectionTitle>
      <form className="club-inline" onSubmit={sendInvite}>
        <input className="share-input" type="email" placeholder="friend@example.com" value={inviteEmail}
               onChange={e => setInviteEmail(e.target.value)} aria-label="Email to invite" />
        <button className="btn btn-sm">Invite</button>
      </form>
      {invite && (
        <p className="ui-hint">{invite.message}{invite.invite_url && <> · Link: <code className="club-code">{invite.invite_url}</code></>}</p>
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
      <p className="ui-hint">{ROLES.map(r => `${r.label}: ${r.hint}`).join(" · ")}</p>
      <ul className="club-rows">
        {active.map(m => (
          <li key={m.id} className="club-row">
            <Avatar user={m.user} size={34} onClick={() => onViewProfile(m.user.id)} />
            <span className="club-row-name">{m.user.name}{m.user.id === viewerId && <span className="club-you"> (you)</span>}
              {m.user.letterboxd_connected && (
                <small className="club-row-sub">📓 Letterboxd @{m.user.letterboxd_username} ·{" "}
                  <button type="button" className="linkish" onClick={() => {
                    if (window.confirm(`Clear ${m.user.name}'s Letterboxd link? (For when someone connected a diary that isn't theirs.)`))
                      run(() => memberAction(`${m.user.id}/letterboxd`, "DELETE"), "Cleared");
                  }}>Clear</button></small>
              )}
            </span>
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
          <p className="ui-hint">Removes its members, RSVPs, comments, reactions and polls. This can't be undone.</p>
        </div>
        <button className="btn btn-sm btn-danger" onClick={deleteClub}>Delete club</button>
      </div>
    </div>
  );
}

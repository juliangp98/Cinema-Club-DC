import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { PageMeta, SectionTitle } from "../ui/PageHeader";
import useHashScroll from "../useHashScroll";
import Avatar, { ClubBadge, initialsOf } from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import PicturePicker, { sendPicture } from "../ui/PicturePicker";
import { getJson, send } from "../api";
import ToggleChip from "../ui/ToggleChip";
import { NEVER_ALWAYS, POST_MODES, Segmented } from "../ui/TicketRow";
import GamePostsWaiting from "./GamePostsWaiting";
import { ROLES } from "../roles";

// A club's settings (R6b; grouped in R15): the club itself, its theatres,
// members and roles, its games, what the games post in Discord, the site's
// look, and deleting it. Organizers get Theatres, join requests, Games and
// Discord; the rest is admins' (the server checks the same split).
const SECTIONS = [
  { id: "settings-club", label: "Club", admin: true },
  { id: "settings-theatres", label: "Theatres" },
  { id: "settings-members", label: "Members & roles" },
  { id: "settings-games", label: "Games" },
  { id: "settings-discord", label: "Discord" },
  { id: "settings-look", label: "Look", admin: true },
  { id: "settings-danger", label: "Danger zone", admin: true },
];

export default function ClubSettings({ group, apiBase, viewerId, isAdmin = true, onChanged, onDeleted }) {
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
  useHashScroll(members.length > 0);                // the jump chips: ?tab=settings#settings-games

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
  const shown = SECTIONS.filter(sec => isAdmin || !sec.admin);
  const toggle = (on, field) => ({ checked: !!on, onChange: e => run(() => update({ [field]: e.target.checked }), "Saved") });

  return (
    <div className="club-settings">
      <PageMeta label="Settings sections" items={shown.map(sec => ({ key: sec.id, label: sec.label, to: `?tab=settings#${sec.id}` }))} />
      {!isAdmin && <p className="ui-hint">As an organizer you run the club's theatres, join requests and games. Its name,
        picture, roles and the rest are for admins.</p>}
      {(saved || error) && <p className={error ? "share-error" : "club-saved"} role="status">{error || saved}</p>}

      {isAdmin && (
        <section id="settings-club" className="club-settings-section">
          <SectionTitle>Club</SectionTitle>
          <PicturePicker
            preview={<ClubBadge group={group} size={72} />}
            onUpload={file => sendPicture(`${base}/picture`, file).then(onChanged)}
            onEmoji={emoji => update({ emoji })}
            onClear={(group.photo_url || group.emoji) ? () => update({ emoji: "", photo: null }) : null}
            clearLabel="Remove picture"
          />
          <form className="club-form" onSubmit={e => { e.preventDefault(); run(() => update({ name: name.trim(), description }), "Saved"); }}>
            <label className="pv-label" htmlFor="club-name">Name</label>
            <input id="club-name" className="share-input" value={name} maxLength={100} required onChange={e => setName(e.target.value)} />
            <label className="pv-label" htmlFor="club-desc">Description</label>
            <textarea id="club-desc" className="share-input" rows={2} maxLength={500} value={description}
                      onChange={e => setDescription(e.target.value)} />
            <div className="club-form-foot"><button className="btn btn-primary btn-sm">Save details</button></div>
          </form>
          <form className="club-form" onSubmit={e => { e.preventDefault(); run(() => update({ short_name: shortName }), "Saved"); }}>
            <label className="pv-label" htmlFor="club-short">Short name</label>
            <div className="club-inline">
              <input id="club-short" className="share-input" value={shortName} maxLength={12} onChange={e => setShortName(e.target.value)}
                     placeholder={initialsOf(group.name)} />
              <button className="btn btn-sm" disabled={shortName === (group.short_name || "")}>Save</button>
            </div>
            <p className="ui-hint">Shown in the top bar when there isn't room for the full name. Blank: {initialsOf(group.name)}.</p>
          </form>
        </section>
      )}

      <section id="settings-theatres" className="club-settings-section">
        <SectionTitle>Theatres</SectionTitle>
        <p className="ui-hint">The theatres the club follows: its calendar, Discover, digest and games use these.</p>
        {allTheatres.length > 0 && (
          <form className="club-form" onSubmit={e => { e.preventDefault(); run(() => update({ theatres: [...theatres] }), "Saved"); }}>
            <div className="club-chips">
              {allTheatres.map(t => (
                <ToggleChip key={t.slug} on={theatres.has(t.slug)} color={t.color}
                        onClick={() => setTheatres(prev => {
                          const next = new Set(prev);
                          if (next.has(t.slug)) { if (next.size > 1) next.delete(t.slug); } else next.add(t.slug);
                          return next;
                        })}>
                  {t.short_name || t.name}
                </ToggleChip>
              ))}
            </div>
            <div className="club-form-foot"><button className="btn btn-primary btn-sm">Save theatres</button></div>
          </form>
        )}
      </section>

      <section id="settings-members" className="club-settings-section">
        <SectionTitle>Members &amp; roles</SectionTitle>
        {isAdmin && (
          <>
            <span className="pv-label">Invite by email</span>
            <form className="club-inline" onSubmit={sendInvite}>
              <input className="share-input" type="email" placeholder="friend@example.com" value={inviteEmail}
                     onChange={e => setInviteEmail(e.target.value)} aria-label="Email to invite" />
              <button className="btn btn-sm">Invite</button>
            </form>
            {invite && (
              <p className="ui-hint">{invite.message}{invite.invite_url && <> · Link: <code className="club-code">{invite.invite_url}</code></>}</p>
            )}
          </>
        )}
        <h3 className="club-settings-sub">Join requests ({pending.length})</h3>
        {pending.length === 0 ? <p className="ui-hint">No one is waiting to join.</p> : (
          <ul className="club-rows">
            {pending.map(m => (
              <li key={m.id} className="club-row">
                <Avatar user={m.user} size={34} />{/* not a member yet: no page to open */}
                <span className="club-row-name">{m.user.name}</span>
                <span className="club-row-actions">
                  <button className="btn btn-sm btn-primary" onClick={() => run(() => memberAction(`${m.user.id}/approve`))}>Approve</button>
                  <button className="btn btn-sm" onClick={() => run(() => memberAction(`${m.user.id}/deny`))}>Deny</button>
                </span>
              </li>
            ))}
          </ul>
        )}
        {isAdmin && (
          <>
            <h3 className="club-settings-sub">Roles ({active.length})</h3>
            <p className="ui-hint">{ROLES.map(r => `${r.label}: ${r.hint}`).join(" · ")}</p>
            <ul className="club-rows">
              {active.map(m => (
                <li key={m.id} className="club-row">
                  <Avatar user={m.user} size={34} link />
                  <span className="club-row-name"><PersonLink user={m.user} />{m.user.id === viewerId && <span className="club-you"> (you)</span>}
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
          </>
        )}
      </section>

      <section id="settings-games" className="club-settings-section">
        <SectionTitle>Games</SectionTitle>
        <GamePostsWaiting apiBase={apiBase} slug={group.slug} />
        <p className="ui-hint">Each game is off until you turn it on; members choose their own reminders in Notification settings.</p>
        <div className="club-form club-trivia">
          <label className="notify-row">
            <input type="checkbox" {...toggle(group.trivia?.enabled, "trivia_enabled")} />
            <span><span className="notify-name">Trivia: question of the day</span>
              <span className="ui-hint">One question a day, the same for everyone, made from the films on your calendar
                and classic quotes (and /trivia in Discord). A right answer is worth 2 kernels.</span></span>
          </label>
          <label className="notify-row">
            <input type="checkbox" {...toggle(group.trivia?.anytime, "trivia_anytime")} />
            <span><span className="notify-name">Trivia: play anytime</span>
              <span className="ui-hint">Members can ask for extra questions whenever they like (on the feed, or /trivia
                in Discord). +1 kernel for a right one, up to 5 a day — after that they're just for fun.</span></span>
          </label>
          <label className="notify-row">
            <input type="checkbox" {...toggle(group.bingo?.enabled, "bingo_enabled")} />
            <span><span className="notify-name">Repertory bingo</span>
              <span className="ui-hint">One 3×3 card a month for the whole club (the middle's free) that fills in by itself
                from check-ins: on film, before 1960, a late show, a theatre you'd never been to… First line +5 kernels,
                the full card +15.</span></span>
          </label>
          {group.bingo?.enabled && (
            <label className="notify-row club-trivia-sub">
              <input type="checkbox" {...toggle(group.bingo?.home, "bingo_home")} />
              <span><span className="notify-name">🏠 Count Letterboxd diaries</span>
                <span className="ui-hint">Films members log in their Letterboxd diary that month fill the film squares —
                  era, genre, length, their watchlist — for those who've connected Letterboxd. A line that needs one is
                  worth +3, the full card +10.</span></span>
            </label>
          )}
          <label className="notify-row">
            <input type="checkbox" {...toggle(group.notes?.enabled, "notes_enabled")} />
            <span><span className="notify-name">Screening notes</span>
              <span className="ui-hint">Members who checked in can tag the night: gorgeous print, sound trouble, packed
                house, great Q&amp;A… Shown on the screening, in the feed and on theatre pages (to members only). Nobody is
                sent anything.</span></span>
          </label>
        </div>
      </section>

      <section id="settings-discord" className="club-settings-section">
        <SectionTitle>Discord</SectionTitle>
        {!group.discord ? <p className="ui-hint">This club isn't the one connected to the Discord server, so its games don't post there.</p>
          : !group.trivia?.enabled && !group.bingo?.enabled ? <p className="ui-hint">Turn on trivia or bingo (Games) to choose what they post in #movies.</p>
          : (
            <div className="club-form club-trivia">
              <p className="ui-hint">What the games post in #movies. Posts never ping anyone. Ask first: an organizer or admin checks
                it (here, or by DM) before it goes up.</p>
              {group.trivia?.enabled && (
                <PostChoice label="The question of the day" options={POST_MODES} value={group.trivia?.post}
                            hint="Around 11 AM, with A–D buttons; answers stay private. Unchecked by 10 PM: it isn't posted."
                            onChange={v => run(() => update({ trivia_post: v }), "Saved")} />
              )}
              {group.bingo?.enabled && (<>
                <PostChoice label="Each month's bingo card" options={POST_MODES} value={group.bingo?.card_post}
                            hint="On the 1st, with its squares; Ask first can reshuffle it before it goes up."
                            onChange={v => run(() => update({ bingo_card_post: v }), "Saved")} />
                <PostChoice label="Bingo wins" options={NEVER_ALWAYS} value={group.bingo?.wins_post}
                            hint="“Ana got bingo! 🎉” — naming only members whose Sharing to Discord says Always for My game wins; others are “Someone”."
                            onChange={v => run(() => update({ bingo_wins_post: v }), "Saved")} />
              </>)}
            </div>
          )}
      </section>

      {isAdmin && (
        <section id="settings-look" className="club-settings-section">
          <SectionTitle>The site's look</SectionTitle>
          <p className="ui-hint">Every button, chip, badge and panel the site is built from, on one page.{" "}
            <Link to="/styleguide">Open the style guide →</Link></p>
        </section>
      )}

      {isAdmin && (
        <section id="settings-danger" className="club-settings-section">
          <SectionTitle>Danger zone</SectionTitle>
          <div className="club-danger">
            <div>
              <strong>Delete this club</strong>
              <p className="ui-hint">Removes its members, RSVPs, comments, reactions and polls. This can't be undone.</p>
            </div>
            <button className="btn btn-sm btn-danger" onClick={deleteClub}>Delete club</button>
          </div>
        </section>
      )}
    </div>
  );
}

// One of a game's Discord posts (R14): Never / Ask first / Always (wins: Never / Always).
function PostChoice({ label, hint, options, value, onChange }) {
  return (
    <div className="notify-row club-trivia-sub club-post-choice">
      <span><span className="notify-name">{label}</span><span className="ui-hint"> {hint}</span></span>
      <Segmented label={label} options={options} value={value || "never"} onChange={v => v && onChange(v)} />
    </div>
  );
}

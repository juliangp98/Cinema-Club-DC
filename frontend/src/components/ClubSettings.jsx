import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import Avatar, { ClubBadge, initialsOf } from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import PicturePicker, { sendPicture } from "../ui/PicturePicker";
import { getJson, send } from "../api";
import Panel from "../ui/Panel";
import TheatrePicker from "../ui/TheatrePicker";
import { useShell } from "../shell/AppShell";
import { DEFAULT_CITY } from "../places";
import { NEVER_ALWAYS, POST_MODES, Segmented } from "../ui/TicketRow";
import { SaveStatus, SettingRow, SettingsGroup, SettingsSection, Switch, SwitchRow, useSaveStatus } from "../ui/Settings";
import ClubDiscord from "./ClubDiscord";
import GamePostsWaiting from "./GamePostsWaiting";
import { QUIZ_GAMES } from "./QuizGames";
import { ROLES } from "../roles";
import SectionMenu from "../ui/SectionMenu";

// A club's settings (R6b; by category in 7g, on the settings standard —
// ui/Settings): the club itself, its members, its theatres (and which of them
// announce new showtimes in Discord), its games (each one card: its switch,
// its options, what it posts in Discord) and the admin things. Organizers get
// Members (join requests), Theatres and Games; the rest is admins' (the
// server checks the same split). Everything saves as you change it.
// Where trivia's films come from (R15, film_pool.SOURCES).
const TRIVIA_SOURCES = [{ status: "local", label: "Our showings" }, { status: "tmdb", label: "Well-known films" },
                        { status: "both", label: "Both" }];

const SECTIONS = [
  { id: "settings-club", label: "Club", admin: true },
  { id: "settings-members", label: "Members" },
  { id: "settings-theatres", label: "Theatres" },
  { id: "settings-discord", label: "Discord" },
  { id: "settings-games", label: "Games" },
  { id: "settings-admin", label: "Admin", admin: true },
];

export default function ClubSettings({ group, apiBase, viewerId, isAdmin = true, onChanged, onDeleted }) {
  const base = `${apiBase}/api/groups/${group.slug}`;
  const shell = useShell();
  const [name, setName] = useState(group.name || "");
  const [description, setDescription] = useState(group.description || "");
  const [shortName, setShortName] = useState(group.short_name || "");
  const [theatres, setTheatres] = useState(new Set(group.theatres || []));
  const [allTheatres, setAllTheatres] = useState([]);
  const [members, setMembers] = useState([]);
  const [status, save] = useSaveStatus();
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

  const run = (fn, okText = "Saved") => save(fn, okText);
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
  const set = (field, label) => v => run(() => update({ [field]: v }), label);
  const followed = allTheatres.filter(t => theatres.has(t.slug));
  const announced = new Set(group.announce_theatres || []);
  const toggleTheatre = slug => {
    const next = new Set(theatres);
    if (next.has(slug)) { if (next.size === 1) return; next.delete(slug); } else next.add(slug);
    setTheatres(next);
    run(() => update({ theatres: [...next] }));
  };
  const announce = (slug, on) => run(() => update({ announce_theatres: on ? [...announced, slug] : [...announced].filter(x => x !== slug) }));
  const discord = !!group.discord;
  const cities = shell?.cities || [];
  const multiCity = !!shell?.multiCity;
  const homeCity = group.city || shell?.city || DEFAULT_CITY;
  const postRow =(label, hint, field, value, options = POST_MODES) => discord && (
    <SettingRow stack label={label} hint={hint}>
      <Segmented label={label} options={options} value={value || "never"} onChange={v => v && run(() => update({ [field]: v }))} />
    </SettingRow>
  );

  return (
    <div className="club-settings ui-split side-top" style={{ "--split-side": "200px" }}>
      <div className="club-settings-main">
        {!isAdmin && <p className="ui-hint">As an organizer you run the club's join requests, theatres and games. Its name,
          picture, roles and the rest are for admins.</p>}
        <SaveStatus status={status} />

        {isAdmin && (
          <SettingsSection id="settings-club" title="Club" intro="How the club appears: its picture, name and a line about it.">
            <SettingRow stack label="Picture" hint="A photo or an emoji.">
              <PicturePicker preview={<ClubBadge group={group} size={64} />}
                             onUpload={file => run(async () => onChanged?.(await sendPicture(`${base}/picture`, file)))}
                             onEmoji={emoji => run(() => update({ emoji }))}
                             onClear={(group.photo_url || group.emoji) ? () => run(() => update({ emoji: "", photo: null })) : null}
                             clearLabel="Remove picture" />
            </SettingRow>
            <SettingRow label="Name" hint="Saved when you leave the box.">
              <input id="club-name" className="share-input settings-name" value={name} maxLength={100} aria-label="Club name"
                     onChange={e => setName(e.target.value)} onKeyDown={e => e.key === "Enter" && e.currentTarget.blur()}
                     onBlur={() => name.trim() && name.trim() !== group.name && run(() => update({ name: name.trim() }))} />
            </SettingRow>
            <SettingRow label="Short name" hint={`In the top bar when there isn't room for the full name. Blank: ${initialsOf(group.name)}.`}>
              <input id="club-short" className="share-input settings-short" value={shortName} maxLength={12} aria-label="Short name"
                     placeholder={initialsOf(group.name)} onChange={e => setShortName(e.target.value)}
                     onKeyDown={e => e.key === "Enter" && e.currentTarget.blur()}
                     onBlur={() => shortName !== (group.short_name || "") && run(() => update({ short_name: shortName }))} />
            </SettingRow>
            <SwitchRow label="Listed on the Clubs page" checked={!!group.is_public} onChange={set("is_public")}
                       hint={group.is_public ? "Anyone signed in can find the club and ask to join; an admin approves each request."
                         : "Invite-only: hidden from the Clubs page, and nobody can ask to join — members come in by your invite (Members)."} />
            <div className="ui-setting stack">
              <div className="ui-setting-text">
                <label className="ui-setting-label" htmlFor="club-desc">Description</label>
                <span className="ui-hint">On the Clubs page and the Club page. Saved when you leave the box.</span>
              </div>
              <textarea id="club-desc" className="share-input" rows={2} maxLength={500} value={description}
                        onChange={e => setDescription(e.target.value)}
                        onBlur={() => description !== (group.description || "") && run(() => update({ description }))} />
            </div>
          </SettingsSection>
        )}

        <SettingsSection id="settings-members" title="Members" intro="Who's in, who's asking to join, and what each member can do.">
          {isAdmin && (
            <SettingRow label="Invite by email" hint={invite ? <>{invite.message}{invite.invite_url && <> · Link: <code className="club-code">{invite.invite_url}</code></>}</>
              : "They get a link that signs them in and joins the club."}>
              <form className="settings-inline" onSubmit={sendInvite}>
                <input className="share-input" type="email" placeholder="friend@example.com" value={inviteEmail}
                       onChange={e => setInviteEmail(e.target.value)} aria-label="Email to invite" />
                <button className="btn btn-sm">Invite</button>
              </form>
            </SettingRow>
          )}
          <SettingsGroup title={`Join requests (${pending.length})`}>
            {pending.length === 0 ? <p className="ui-hint">No one is waiting to join.</p> : (
              <ul className="club-rows">
                {pending.map(m => (
                  <li key={m.id} className="club-row">
                    <Avatar user={m.user} size={34} />{/* not a member yet: no page to open */}
                    <span className="club-row-name">{m.user.name}</span>
                    <span className="club-row-actions">
                      <button className="btn btn-sm btn-primary" onClick={() => run(() => memberAction(`${m.user.id}/approve`), "Approved")}>Approve</button>
                      <button className="btn btn-sm" onClick={() => run(() => memberAction(`${m.user.id}/deny`), "Denied")}>Deny</button>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </SettingsGroup>
          {isAdmin && (
            <SettingsGroup title={`Roles (${active.length})`}>
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
                          if (window.confirm(`Remove ${m.user.name} from the club?`)) run(() => memberAction(`${m.user.id}`, "DELETE"), "Removed");
                        }}>Remove</button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </SettingsGroup>
          )}
        </SettingsSection>

        <SettingsSection id="settings-theatres" title="Theatres" intro="The theatres the club follows: its calendar, Discover, digest and games use these.">
          <div id="club-settings-digest">
            <SwitchRow label="Monday digest" checked={!!group.digest?.enabled} onChange={set("digest_enabled")}
                       hint={`Mondays at 10 AM, the week's picks from these theatres: a card in the Feed and a note in members' bells${
                         discord ? ", and a post in the club's Discord channel" : ""}. Members choose where else they hear about it.`} />
          </div>
          {multiCity && isAdmin && (
            <SettingRow stack label="Home city" id="club-settings-city"
                        hint="Its clock (the digest, trivia, the week) and the theatres it shows first. Theatres it follows elsewhere stay.">
              <Segmented label="Home city" value={homeCity} onChange={v => v && run(() => update({ city: v }))}
                         options={cities.map(c => ({ status: c.slug, label: c.short }))} />
            </SettingRow>
          )}
          {allTheatres.length > 0 && (
            <TheatrePicker theatres={allTheatres} home={homeCity} cities={cities} label="Followed theatres"
                           isOn={slug => theatres.has(slug)} onToggle={toggleTheatre} />
          )}
          {discord && followed.length > 0 && (
            <SettingsGroup title="New showtimes in Discord">
              <p className="ui-hint">A theatre that's on posts its new showtimes in the club's Discord channel as they're booked{group.digest?.enabled
                ? "; the rest are in the Monday digest" : ""}. The same setting as /announcements in Discord.</p>
              {followed.map(t => <SwitchRow key={t.slug} label={t.name} checked={announced.has(t.slug)} onChange={v => announce(t.slug, v)} />)}
            </SettingsGroup>
          )}
        </SettingsSection>

        <SettingsSection id="settings-discord" title="Discord"
                         intro="The club's Discord server: the bot posts there (what you choose here), and members use its commands — anyone who does joins the club.">
          <ClubDiscord group={group} apiBase={apiBase} isAdmin={isAdmin} run={run} onConnected={() => onChanged?.()} />
        </SettingsSection>

        <SettingsSection id="settings-games" title="Games"
                         intro="Each game is off until you turn it on; members choose their own reminders in their Settings → Notifications.">
          <GamePostsWaiting apiBase={apiBase} slug={group.slug} />
          {discord ? <p className="ui-hint">What a game posts in the club's Discord channel is on its card. Posts never ping anyone; Ask
            first: an organizer or admin checks it (here, or by DM) before it goes up.</p>
            : <p className="ui-hint">No Discord server is connected (Discord, above), so the games don't post there.</p>}
          <div className="game-settings">
            <Panel as="div" className="game-setting" title="🧠 Trivia: question of the day"
                   aside={<Switch label="Trivia: question of the day" checked={!!group.trivia?.enabled} onChange={set("trivia_enabled")} />}>
              <p className="ui-hint">One question a day, the same for everyone, about films and classic quotes. A right answer is worth
                1, 2 or 3 kernels — easy, medium or hard.</p>
              <SwitchRow label="Play anytime" checked={!!group.trivia?.anytime} onChange={set("trivia_anytime")}
                         hint="Extra questions whenever members like (on Play, or /play in Discord): +1 kernel (+2 if hard), up to 5 a day." />
              {(group.trivia?.enabled || group.trivia?.anytime) && (
                <SettingRow stack label="Trivia's films" hint="Our showings: films that have played at the club's theatres. Well-known films: TMDB's 5,000 most-voted.">
                  <Segmented label="Trivia's films" options={TRIVIA_SOURCES} value={group.trivia?.source || "both"}
                             onChange={v => v && run(() => update({ trivia_source: v }))} />
                </SettingRow>
              )}
              {group.trivia?.enabled && postRow("Post it in Discord", "Around 11 AM, with A–D buttons; answers stay private. Unchecked by 10 PM: it isn't posted.",
                                                "trivia_post", group.trivia?.post)}
            </Panel>

            <Panel as="div" className="game-setting" title="🎱 Repertory bingo"
                   aside={<Switch label="Repertory bingo" checked={!!group.bingo?.enabled} onChange={set("bingo_enabled")} />}>
              <p className="ui-hint">One 3×3 card a month for the whole club (the middle's free) that fills in by itself from check-ins.
                First line +5 kernels, the full card +15.</p>
              {group.bingo?.enabled && (<>
                <SwitchRow label="🏠 Count Letterboxd diaries" checked={!!group.bingo?.home} onChange={set("bingo_home")}
                           hint="Films members log that month fill the film squares, for those who've connected Letterboxd. A line that needs one is +3, the card +10." />
                {postRow("Post each month's card", "On the 1st, with its squares; Ask first can reshuffle it before it goes up.",
                         "bingo_card_post", group.bingo?.card_post)}
                {postRow("Post wins", "“Ana got bingo! 🎉” — naming only members whose sharing settings say Always for game wins.",
                         "bingo_wins_post", group.bingo?.wins_post, NEVER_ALWAYS)}
              </>)}
            </Panel>

            <Panel as="div" className="game-setting" title="🎮 Quiz games">
              <p className="ui-hint">Each its own switch; up to 5 kernels a day from each.</p>
              {QUIZ_GAMES.map(q => (
                <SwitchRow key={q.key} label={q.label} hint={q.hint} checked={!!group.quizzes?.[q.key]}
                           onChange={v => run(() => update({ quizzes: { [q.key]: v } }))} />
              ))}
            </Panel>

            <Panel as="div" className="game-setting" title="📝 Screening notes"
                   aside={<Switch label="Screening notes" checked={!!group.notes?.enabled} onChange={set("notes_enabled")} />}>
              <p className="ui-hint">Members who checked in can tag the night: gorgeous print, sound trouble, packed house, great Q&amp;A…
                Shown on the screening, in the feed and on theatre pages (to members only). Nobody is sent anything.</p>
            </Panel>
          </div>
        </SettingsSection>

        {isAdmin && (
          <SettingsSection id="settings-admin" title="Admin">
            <SettingRow label="The site's look" hint="Every button, chip, badge, panel and setting the site is built from, on one page.">
              <Link className="btn btn-sm" to="/styleguide">Open the style guide</Link>
            </SettingRow>
            <SettingRow label="Delete this club" hint="Removes its members, RSVPs, comments, reactions and polls. This can't be undone.">
              <button className="btn btn-sm btn-danger" onClick={deleteClub}>Delete club</button>
            </SettingRow>
          </SettingsSection>
        )}
      </div>
      <div className="ui-split-side sticky">
        <SectionMenu label="Settings sections" items={shown.map(sec => ({ id: sec.id, label: sec.label }))} />
      </div>
    </div>
  );
}

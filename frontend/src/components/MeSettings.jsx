import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { accountLabel } from "../accountLabel";
import { getJson, send } from "../api";
import Avatar from "../ui/Avatar";
import PicturePicker, { sendPicture } from "../ui/PicturePicker";
import Prompt from "../ui/Prompt";
import SectionMenu from "../ui/SectionMenu";
import { SaveStatus, SettingRow, SettingsGroup, SettingsSection, SwitchRow, useSaveStatus } from "../ui/Settings";
import { ALWAYS_NEVER, ASK_ALWAYS_NEVER, Segmented } from "../ui/TicketRow";
import { getSharePrefs, setSharePrefs } from "../ui/DiscordShare";
import { useShell } from "../shell/AppShell";
import CalendarLinks from "./CalendarLinks";
import NotifySettings from "./NotifySettings";
import TasteEditor from "./TasteEditor";

// Your settings (7g): Me → Settings, one page by category — what used to be
// the Edit profile and Your taste sheets, the bell's Notification settings
// and Me's calendar links. Built from the settings standard (ui/Settings),
// with a section menu beside it on wide screens. Everything saves as you
// change it (the name and bio when you leave the box), and says so in one
// place. Deep links: /me?tab=settings#settings-<section>.
export const SETTINGS_SECTIONS = [
  { id: "settings-profile", label: "Profile" },
  { id: "settings-taste", label: "Your taste" },
  { id: "settings-notify", label: "Notifications" },
  { id: "settings-connections", label: "Connections" },
  { id: "settings-privacy", label: "Privacy and sharing" },
  { id: "settings-account", label: "Account" },
];

const AVATAR_COLORS = ["#e8a838", "#c45c3a", "#4a7c6f", "#7b5ea7", "#3a6bb5", "#b5503a"];

const SHARE_KINDS = [
  ["rsvp", "My RSVPs", "Never still leaves a Share button on each screening."],
  ["poll", "Polls I create", "Announcements and results (organizers and admins)."],
  ["comment", "My comments", "Only where a screening has a Discord thread. Ask = remember my last choice."],
  ["watchlist", "My watchlist", "Whether the weekly digest names (and pings) you when a film you want is playing."],
  ["games", "My game wins", "Whether a bingo win posted in #movies names you (if the club posts wins).", ALWAYS_NEVER],
];
// Why sharing isn't on offer: only members who've linked Discord and are in
// the club's server ever appear there.
const UNAVAILABLE = {
  not_linked: "Link your Discord (Connections, above) to share to the club's server. Until then, nothing you do here appears there.",
  not_in_server: "Your Discord is linked, but you're not in the club's server, so nothing you do here appears there. Join it to share.",
};

function ProfileSection({ user, apiBase, onUpdate, save }) {
  const [name, setName] = useState(user.name || "");
  const [bio, setBio] = useState(user.bio || "");
  const color = user.avatar_color || AVATAR_COLORS[0];
  const putProfile = fields => save(async () => onUpdate((await send(`${apiBase}/api/auth/profile`, "PUT", fields)).user));
  const picture = body => save(async () => onUpdate((await send(`${apiBase}/api/me/picture`, "PUT", body)).user));
  return (
    <SettingsSection id="settings-profile" title="Profile" intro="How you appear to your clubs: your name, picture and a line about you.">
      <SettingRow stack label="Picture" hint={user.is_guest ? "Keep your profile (Account, below) to upload a photo." : "A photo, an emoji, or your initials."}>
        <PicturePicker
          preview={<Avatar user={{ ...user, name }} size={56} />}
          canUpload={!user.is_guest}
          onUpload={file => save(async () => onUpdate((await sendPicture(`${apiBase}/api/me/picture`, file)).user))}
          onEmoji={emoji => picture({ kind: "emoji", emoji })}
          onClear={user.avatar_kind !== "initials" ? () => picture({ kind: "initials" }) : null}
          extra={user.discord_avatar_url && user.avatar_kind !== "discord" && (
            <button type="button" className="btn btn-sm" onClick={() => picture({ kind: "discord" })}>Use my Discord picture</button>
          )} />
      </SettingRow>
      <SettingRow label="Name" hint="Saved when you leave the box.">
        <input className="share-input settings-name" value={name} maxLength={100} aria-label="Name"
               onChange={e => setName(e.target.value)}
               onBlur={() => name.trim() && name.trim() !== user.name && putProfile({ name: name.trim() })}
               onKeyDown={e => e.key === "Enter" && e.currentTarget.blur()} />
      </SettingRow>
      <SettingRow label="Initials color" hint="Behind your initials when you don't use a picture.">
        <div className="color-swatches" role="group" aria-label="Initials color">
          {AVATAR_COLORS.map(c => (
            <button key={c} type="button" className={`color-swatch${color === c ? " active" : ""}`} style={{ background: c }}
                    aria-label={`Color ${c}`} aria-pressed={color === c} onClick={() => putProfile({ avatar_color: c })} />
          ))}
        </div>
      </SettingRow>
      <div className="ui-setting stack">
        <div className="ui-setting-text">
          <label className="ui-setting-label" htmlFor="settings-bio">Bio</label>
          <span className="ui-hint">On your page for your clubs. Saved when you leave the box.</span>
        </div>
        <textarea id="settings-bio" className="profile-textarea" value={bio} maxLength={500} rows={3}
                  placeholder="Tell the club about yourself…" onChange={e => setBio(e.target.value)}
                  onBlur={() => bio !== (user.bio || "") && putProfile({ bio })} />
      </div>
    </SettingsSection>
  );
}

function DiscordRow({ user, apiBase }) {
  const [oauth, setOauth] = useState(false);
  const [code, setCode] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getJson(`${apiBase}/api/auth/providers`).then(d => setOauth(!!d?.discord)).catch(() => {});
  }, [apiBase]);
  async function linkCode() {
    setBusy(true);
    try { setCode((await send(`${apiBase}/api/me/discord-link-code`)).code); } catch { /* the button stays */ }
    setBusy(false);
  }
  return (
    <SettingRow label="Discord" id="profile-discord"
                hint={user.discord_linked ? `Linked${user.discord_username ? ` as @${user.discord_username}` : ""} — your site and Discord activity are one.`
                  : code ? <>In Discord, run <code>/link {code}</code> — the code expires in 10 minutes.</>
                  : "Link it to RSVP, vote and get DMs in the club's server."}>
      {!user.discord_linked && !code && (oauth
        ? <a className="btn btn-sm" href={`${apiBase}/api/auth/discord/start?mode=connect`}>🔗 Connect Discord</a>
        : <button type="button" className="btn btn-sm" disabled={busy} onClick={linkCode}>{busy ? "…" : "🔗 Link Discord"}</button>)}
    </SettingRow>
  );
}

// Letterboxd (Connections): one row per thing connected. The diary (R10f):
// connect it by username (we check the diary exists); then what a diary entry
// for a screening you were going to does. (Showing ratings and quiz clues are
// in Privacy and sharing.)
function DiaryRows({ lb, call, busy }) {
  const [name, setName] = useState(lb.username || "");
  if (!lb.connected) {
    return (
      <SettingRow label="Diary" id="profile-letterboxd"
                  hint="Connect your diary and screenings you log there can count as check-ins here — you choose how. We only read your public diary feed.">
        <form className="settings-inline" onSubmit={e => { e.preventDefault(); call("POST", { username: name }); }}>
          <input className="share-input" value={name} onChange={e => setName(e.target.value)} maxLength={60}
                 placeholder="Your Letterboxd username" aria-label="Letterboxd username" />
          <button className="btn btn-sm" disabled={busy || !name.trim()}>{busy ? "Checking…" : "Connect"}</button>
        </form>
      </SettingRow>
    );
  }
  const read = lb.synced_at && new Date(lb.synced_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  return (
    <>
      <SettingRow label="Diary" id="profile-letterboxd"
                  hint={<>📓 Connected to <a href={`https://letterboxd.com/${lb.username}/`} target="_blank" rel="noreferrer">@{lb.username}</a>
                    {read && ` · read ${read}`}</>}>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => call("POST", null, "/sync")}>Read it now</button>
        <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => call("DELETE")}>Disconnect</button>
      </SettingRow>
      <SettingRow label="Check me in from my diary"
                  hint={'When your diary has a film you said you were going to (that day or the next). Ask = your "Did you make it?" prompt says so.'}>
        <Segmented label="Check me in from my diary" options={ASK_ALWAYS_NEVER} value={lb.checkin} onChange={v => v && call("PUT", { checkin: v })} />
      </SettingRow>
    </>
  );
}

// The watchlist: Letterboxd's export (the zip, or its watchlist.csv),
// imported again whenever you like. Its films join your watchlist as they
// turn up in our listings; the first import asks whether they alert you.
const WATCH_ALERTS = [{ status: "yes", label: "Alert me" }, { status: "no", label: "Just For you" }];

function WatchlistRows({ lb, apiBase, save, onChange }) {
  const file = useRef(null);
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState(false);
  const w = lb.watchlist || {};

  async function upload(f) {
    if (!f) return;
    const body = new FormData();
    body.append("file", f);
    setBusy(true);
    const d = await save(() => send(`${apiBase}/api/me/letterboxd/watchlist`, "POST", body), "Imported");
    setBusy(false);
    if (file.current) file.current.value = "";
    if (!d) return;
    onChange(d);
    setAsk(!!d.ask_alerts);
  }
  async function setAlerts(on) {
    const d = await save(() => send(`${apiBase}/api/me/letterboxd`, "PUT", { watch_alerts: on }));
    if (d) { onChange(d); setAsk(false); }
  }
  async function turnOff() {
    if (!window.confirm("Turn off your Letterboxd watchlist? The films it brought in leave your watchlist (films you added here stay).")) return;
    const d = await save(() => send(`${apiBase}/api/me/letterboxd/watchlist`, "DELETE"), "Turned off");
    if (d) onChange(d);
  }

  const picker = (
    <>
      <input ref={file} type="file" accept=".zip,.csv,application/zip,text/csv" hidden
             aria-label="Letterboxd export file" onChange={e => upload(e.target.files?.[0])} />
      <button type="button" className="btn btn-sm" disabled={busy} onClick={() => file.current?.click()}>
        {busy ? "Importing…" : w.on ? "Import again" : "Choose the file"}
      </button>
    </>
  );
  if (!w.on) {
    return (
      <SettingRow label="Watchlist" id="profile-letterboxd-watchlist"
                  hint="Bring in your Letterboxd watchlist: on Letterboxd, Settings → Import & Export → Export your data, then choose the zip (or the watchlist.csv inside). Its films join your watchlist here as theatres book them.">
        {picker}
      </SettingRow>
    );
  }
  const when = w.imported_at && new Date(w.imported_at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  return (
    <>
      <SettingRow label="Watchlist" id="profile-letterboxd-watchlist"
                  hint={`📓 ${w.films} film${w.films === 1 ? "" : "s"} · ${w.matched} in our listings${when ? ` · imported ${when}` : ""}. Import again whenever your list changes — films you've taken off Letterboxd leave.`}>
        {picker}
        <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={turnOff}>Turn off</button>
      </SettingRow>
      {ask ? (
        <Prompt question="Alert you about these like your watchlist?"
                hint="When a theatre books or announces one, or tickets go on sale. Or just use them for For you and the digest's counts."
                onClose={() => setAsk(false)}
                actions={<>
                  <button type="button" className="btn btn-sm btn-primary" onClick={() => setAlerts(true)}>Alert me</button>
                  <button type="button" className="btn btn-sm" onClick={() => setAlerts(false)}>Just For you</button>
                </>} />
      ) : (
        <SettingRow label="Alerts for these films"
                    hint="Alert me: like the rest of your watchlist (where alerts reach you is under Notifications). Just For you: they shape your picks, nothing more.">
          <Segmented label="Alerts for Letterboxd watchlist films" options={WATCH_ALERTS}
                     value={w.alerts === true ? "yes" : w.alerts === false ? "no" : null}
                     onChange={v => v && setAlerts(v === "yes")} />
        </SettingRow>
      )}
    </>
  );
}

function LetterboxdRows({ lb, call, busy, apiBase, save, onChange }) {
  return (
    <SettingsGroup title="Letterboxd">
      <DiaryRows lb={lb} call={call} busy={busy} />
      <WatchlistRows lb={lb} apiBase={apiBase} save={save} onChange={onChange} />
    </SettingsGroup>
  );
}

function SharingRows({ user, apiBase, onUpdate, save }) {
  const [state, setState] = useState(null);
  useEffect(() => {
    getSharePrefs(apiBase).then(setState).catch(() => setState(null));
  }, [apiBase, user?.discord_linked]);
  if (state && !state.available && UNAVAILABLE[state.reason]) return <p className="ui-hint">{UNAVAILABLE[state.reason]}</p>;
  if (!state?.available) return null;
  const choose = (kind, value) => value && save(async () => {
    const next = await setSharePrefs(apiBase, { [kind]: value });
    setState(next);
    onUpdate?.({ ...user, share_prefs: next.prefs });
  });
  return (
    <>
      <p className="ui-hint">Nothing you do here posts to #movies unless you choose to. Shared posts never ping anyone.</p>
      {SHARE_KINDS.map(([kind, label, hint, options = ASK_ALWAYS_NEVER]) => (
        <SettingRow key={kind} label={label} hint={hint}>
          <Segmented label={label} options={options} value={state.prefs[kind]} onChange={v => choose(kind, v)} />
        </SettingRow>
      ))}
    </>
  );
}

export default function MeSettings({ user, apiBase }) {
  const shell = useShell() || {};
  const onUpdate = u => shell.setUser?.(u);
  const [status, save] = useSaveStatus();
  const [taste, setTaste] = useState(null);
  const [lb, setLb] = useState(null);
  const [lbBusy, setLbBusy] = useState(false);
  useEffect(() => {
    getJson(`${apiBase}/api/me/taste`, { cache: false }).then(setTaste).catch(() => {});
    if (!user.is_guest) getJson(`${apiBase}/api/me/letterboxd`).then(setLb).catch(() => setLb(null));
  }, [apiBase, user.is_guest]);

  async function lbCall(method, body, path = "") {
    setLbBusy(true);
    const d = await save(() => send(`${apiBase}/api/me/letterboxd${path}`, method, body),
                         method === "DELETE" ? "Disconnected" : path === "/sync" ? "Read" : "Saved");
    setLbBusy(false);
    if (!d) return;
    setLb(d);
    onUpdate({ ...user, letterboxd_username: d.username, letterboxd_connected: d.connected });
  }
  const setPublic = v => save(async () => setTaste(await send(`${apiBase}/api/me/taste`, "PUT", { public: v })));
  const noLb = !lb?.connected;

  return (
    <div className="me-settings ui-split side-top" style={{ "--split-side": "200px" }}>
      <div className="me-settings-main">
        <SaveStatus status={status} />
        <ProfileSection user={user} apiBase={apiBase} onUpdate={onUpdate} save={save} />

        <SettingsSection id="settings-taste" title="Your taste"
                         intro="What For you goes on — on Discover, theatre pages and /foryou in Discord. Saved as you go.">
          <TasteEditor apiBase={apiBase} onChange={t => { setTaste(t); shell.tasteChanged?.(); }} />
        </SettingsSection>

        <SettingsSection id="settings-notify" title="Notifications"
                         intro="Nothing is emailed, sent by Discord DM or pushed until you turn it on here. Every alert also lands in the 🔔 bell.">
          <NotifySettings apiBase={apiBase} save={save} key={`${user.discord_linked}-${!!user.email}`} />
        </SettingsSection>

        <SettingsSection id="settings-connections" title="Connections"
                         intro="Discord, Letterboxd and your calendar app — linked to your account here.">
          <DiscordRow user={user} apiBase={apiBase} />
          {lb && <LetterboxdRows lb={lb} call={lbCall} busy={lbBusy} apiBase={apiBase} save={save} onChange={setLb} />}
          {!user.is_guest && (
            <div id="me-calendar">
              <SettingsGroup title="Calendar subscriptions">
                <p className="ui-hint">Subscribe once and your plans stay in sync with Google, Apple or Outlook Calendar.</p>
                <CalendarLinks apiBase={apiBase} />
              </SettingsGroup>
            </div>
          )}
        </SettingsSection>

        <SettingsSection id="settings-privacy" title="Privacy and sharing"
                         intro="What your clubs see beyond your plans and check-ins, and what goes to the club's Discord.">
          {taste && <SwitchRow label="Show my taste on my profile" checked={taste.public} onChange={setPublic}
                               hint="People in your clubs see it on your page and in Discord. Off: only you see it." />}
          {lb && (
            <>
              <SwitchRow label="Show my star ratings with my check-ins" checked={!!lb.ratings} disabled={noLb}
                         hint={noLb ? "Connect Letterboxd (Connections) first." : "In the club feed, with a link to your review."}
                         onChange={v => lbCall("PUT", { ratings: v })} />
              <SwitchRow label="Let a line from my reviews be a quiz clue" checked={lb.clues !== false} disabled={noLb}
                         hint={noLb ? "Connect Letterboxd (Connections) first."
                           : "Guess from the reviews may use a sentence of yours — never with your name, and never one that gives the film away."}
                         onChange={v => lbCall("PUT", { clues: v })} />
            </>
          )}
          <div id="profile-sharing">
            <SettingsGroup title="Sharing to Discord">
              <SharingRows user={user} apiBase={apiBase} onUpdate={onUpdate} save={save} />
            </SettingsGroup>
          </div>
        </SettingsSection>

        <SettingsSection id="settings-account" title="Account">
          <SettingRow label="Signed in" hint={accountLabel(user)}>
            {user.is_guest && <Link className="btn btn-sm btn-primary" to="/signin?next=%2Fme">Keep your profile</Link>}
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => shell.logout?.()}>Sign out</button>
          </SettingRow>
          {!user.is_guest && (
            <SettingRow label="The welcome tour" hint="A quick trip through each main page. Every page also has its own — tap ? at the top.">
              <button type="button" className="btn btn-sm" onClick={() => shell.startTour?.()}>Take the tour</button>
            </SettingRow>
          )}
          <SettingRow label="Help" hint="How everything works, and answers to common questions.">
            <Link className="btn btn-sm" to="/help">Open Help</Link>
          </SettingRow>
        </SettingsSection>
      </div>
      <div className="ui-split-side sticky">
        <SectionMenu label="Settings sections" items={SETTINGS_SECTIONS} />
      </div>
    </div>
  );
}

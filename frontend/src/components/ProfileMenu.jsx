import { useState, useEffect } from "react";
import { accountLabel } from "../accountLabel";
import { ALWAYS_NEVER, ASK_ALWAYS_NEVER, Segmented } from "../ui/TicketRow";
import { getSharePrefs, setSharePrefs } from "../ui/DiscordShare";
import Avatar from "../ui/Avatar";
import PicturePicker, { sendPicture } from "../ui/PicturePicker";
import { getJson, send } from "../api";
import { SheetTitle } from "../ui/Sheet";
import NotifySettings from "./NotifySettings";
import TasteChips from "../ui/TasteChips";
import { useShell } from "../shell/AppShell";

const AVATAR_COLORS = ['#e8a838', '#c45c3a', '#4a7c6f', '#7b5ea7', '#3a6bb5', '#b5503a'];

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
  not_linked: "Link your Discord (above) to share to the club's server. Until then, nothing you do here appears there.",
  not_in_server: "Your Discord is linked, but you're not in the club's server, so nothing you do here appears there. Join it to share.",
};

// What goes to the club's Discord from the site: per kind, ask / always / never.
// Saved as soon as you pick.
function SharingPrefs({ user, apiBase, onUpdate }) {
  const [state, setState] = useState(null);
  useEffect(() => {
    getSharePrefs(apiBase).then(setState).catch(() => setState(null));
  }, [apiBase, user?.discord_linked]);
  if (state && !state.available && UNAVAILABLE[state.reason]) {
    return (
      <div className="profile-sharing">
        <div className="profile-section-label">Sharing to Discord</div>
        <p className="profile-sharing-hint">{UNAVAILABLE[state.reason]}</p>
      </div>
    );
  }
  if (!state?.available) return null;
  async function choose(kind, value) {
    if (!value) return;                     // picking the current choice again keeps it
    const next = await setSharePrefs(apiBase, { [kind]: value }).catch(() => null);
    if (next) {
      setState(next);
      onUpdate?.({ ...user, share_prefs: next.prefs });
    }
  }
  return (
    <div className="profile-sharing">
      <div className="profile-section-label">Sharing to Discord</div>
      <p className="profile-sharing-hint">Nothing you do here posts to #movies unless you choose to. Shared posts never ping anyone.</p>
      {SHARE_KINDS.map(([kind, label, hint, options = ASK_ALWAYS_NEVER]) => (
        <div key={kind} className="profile-sharing-row">
          <div>
            <div className="profile-sharing-kind">{label}</div>
            <div className="profile-sharing-hint">{hint}</div>
          </div>
          <Segmented label={label} options={options} value={state.prefs[kind]} onChange={v => choose(kind, v)} />
        </div>
      ))}
    </div>
  );
}

// Your Letterboxd diary (R10f): connect it by username (we check the diary
// exists); then choose what a diary entry for a screening you were going to
// does, and whether your ratings show with your check-ins. Off until you
// connect; disconnecting forgets what was read.
function LetterboxdSection({ user, apiBase, onUpdate }) {
  const [s, setS] = useState(null);
  const [name, setName] = useState(user.letterboxd_username || "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  useEffect(() => {
    getJson(`${apiBase}/api/me/letterboxd`).then(setS).catch(() => setS(null));
  }, [apiBase]);
  if (!s || user.is_guest) return null;

  async function call(method, body, path = "") {
    setBusy(true);
    setMsg(null);
    let d;
    try {
      d = await send(`${apiBase}/api/me/letterboxd${path}`, method, body);
    } catch (e) {
      setMsg(e.message);
      return null;
    } finally { setBusy(false); }
    setS(d);
    onUpdate?.({ ...user, letterboxd_username: d.username, letterboxd_connected: d.connected });
    return d;
  }

  if (!s.connected) {
    return (
      <div className="profile-sharing">
        <div className="profile-section-label">Letterboxd</div>
        <p className="profile-sharing-hint">Connect your diary and screenings you log there can count as check-ins here
          — you choose how. We only read your public diary feed.</p>
        <form className="profile-lb-connect" onSubmit={e => { e.preventDefault(); call("POST", { username: name }); }}>
          <input className="profile-input" value={name} onChange={e => setName(e.target.value)} maxLength={60}
                 placeholder="Your Letterboxd username" aria-label="Letterboxd username" />
          <button className="btn btn-sm" disabled={busy || !name.trim()}>{busy ? "Checking…" : "Connect"}</button>
        </form>
        {msg && <p className="profile-sharing-hint" role="status">{msg}</p>}
      </div>
    );
  }
  return (
    <div className="profile-sharing">
      <div className="profile-section-label">Letterboxd</div>
      <p className="profile-sharing-hint">
        📓 Connected to <a href={`https://letterboxd.com/${s.username}/`} target="_blank" rel="noreferrer">@{s.username}</a>
        {s.synced_at && ` · read ${new Date(s.synced_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`}
        {" · "}<button type="button" className="linkish" disabled={busy} onClick={() => call("POST", null, "/sync")}>Read it now</button>
      </p>
      <div className="profile-sharing-row">
        <div>
          <div className="profile-sharing-kind">Check me in from my diary</div>
          <div className="profile-sharing-hint">When your diary has a film you said you were going to (that day or the next).
            Ask = your "Did you make it?" prompt says so.</div>
        </div>
        <Segmented label="Check me in from my diary" options={ASK_ALWAYS_NEVER} value={s.checkin}
                   onChange={v => v && call("PUT", { checkin: v })} />
      </div>
      <label className="notify-row">
        <input type="checkbox" checked={s.ratings} onChange={e => call("PUT", { ratings: e.target.checked })} />
        <span><span className="notify-name">Show my star ratings with my check-ins</span>
          <span className="ui-hint">In the club feed, with a link to your review.</span></span>
      </label>
      {msg && <p className="profile-sharing-hint" role="status">{msg}</p>}
      <button type="button" className="linkish" disabled={busy} onClick={() => call("DELETE")}>Disconnect Letterboxd</button>
    </div>
  );
}

// The profile editor (name, color, bio, your taste, Letterboxd, Discord and
// what to share there). Shown in a Sheet from the account menu or the Me page.
export default function ProfileEditor({ user, apiBase, onUpdate }) {
  const [name, setName] = useState(user.name || "");
  const [bio, setBio] = useState(user.bio || "");
  const [avatarColor, setAvatarColor] = useState(user.avatar_color || AVATAR_COLORS[0]);
  const shell = useShell() || {};
  const [taste, setTaste] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [kernels, setKernels] = useState(null);
  const [linkCode, setLinkCode] = useState(null);
  const [linkLoading, setLinkLoading] = useState(false);
  const [discordOAuth, setDiscordOAuth] = useState(false);

  // "Connect Discord" uses Discord sign-in when the site has it configured;
  // otherwise fall back to the /link code.
  useEffect(() => {
    getJson(`${apiBase}/api/auth/providers`)
      .then(d => setDiscordOAuth(!!d?.discord))
      .catch(() => {});
  }, [apiBase]);

  // Fetch kernel count
  useEffect(() => {
    if (!user?.id) return;
    getJson(`${apiBase}/api/users/${user.id}/kernels`)
      .then(d => { if (d) setKernels(d.kernels); })
      .catch(() => {});
  }, [user?.id, apiBase]);

  // Your taste (R13) is edited in its own sheet; this shows where it stands.
  useEffect(() => {
    getJson(`${apiBase}/api/me/taste`, { cache: false }).then(setTaste).catch(() => {});
  }, [apiBase, shell.tasteVersion]);

  async function handleSave() {
    setSaving(true);
    try {
      const d = await send(`${apiBase}/api/auth/profile`, "PUT", {
        name: name.trim(),
        bio,
        avatar_color: avatarColor,
      });
      onUpdate(d.user);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="profile-menu">
      <SheetTitle>Edit profile</SheetTitle>
      <div className="profile-menu-header">
        <Avatar user={{ ...user, name, avatar_color: avatarColor }} size={56} />
        <div className="profile-header-info">
          <div className="profile-email">{accountLabel(user)}</div>
          {kernels !== null && (
            <div className="profile-kernels-pill">🍿 {kernels} kernel{kernels !== 1 ? "s" : ""}</div>
          )}
        </div>
      </div>

      <label className="profile-field-label">Name</label>
      <input
        className="profile-input"
        value={name}
        onChange={e => { setName(e.target.value); setSaved(false); }}
        maxLength={100}
      />

      <label className="profile-field-label">Picture</label>
      <PicturePicker
        preview={<Avatar user={{ ...user, name, avatar_color: avatarColor }} size={64} />}
        canUpload={!user.is_guest}
        uploadNote={user.is_guest ? "Keep your profile (add an email or Discord) to upload a photo." : undefined}
        onUpload={file => sendPicture(`${apiBase}/api/me/picture`, file).then(d => onUpdate(d.user))}
        onEmoji={emoji => send(`${apiBase}/api/me/picture`, "PUT", { kind: "emoji", emoji }).then(d => onUpdate(d.user))}
        onClear={user.avatar_kind !== "initials"
          ? () => send(`${apiBase}/api/me/picture`, "PUT", { kind: "initials" }).then(d => onUpdate(d.user)) : null}
        extra={user.discord_avatar_url && user.avatar_kind !== "discord" && (
          <button type="button" className="btn btn-sm" onClick={() => send(`${apiBase}/api/me/picture`, "PUT", { kind: "discord" })
            .then(d => onUpdate(d.user)).catch(() => {})}>Use my Discord picture</button>
        )}
      />

      <label className="profile-field-label">Initials color</label>
      <div className="color-swatches">
        {AVATAR_COLORS.map(c => (
          <button
            key={c}
            className={`color-swatch${avatarColor === c ? " active" : ""}`}
            style={{ background: c }}
            onClick={() => { setAvatarColor(c); setSaved(false); }}
          />
        ))}
      </div>

      <label className="profile-field-label">Your taste</label>
      <div className="profile-taste">
        <TasteChips taste={taste?.summary} empty={<p className="ui-hint">Not set yet — tell us what you like and Discover picks films for you.</p>} />
        <button type="button" className="btn btn-sm" onClick={() => shell.editTaste?.()}>
          {taste?.set ? "Edit your taste" : "Pick what you like"}</button>
        {taste && <span className="ui-hint">{taste.public ? "Shown on your profile" : "Only you see it"}</span>}
      </div>

      <label className="profile-field-label">Bio</label>
      <textarea
        className="profile-textarea"
        value={bio}
        onChange={e => { setBio(e.target.value); setSaved(false); }}
        maxLength={500}
        rows={3}
        placeholder="Tell the group about yourself..."
      />

      <div className="profile-actions">
        <button className="btn btn-primary btn-block" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : saved ? "Saved!" : "Save"}
        </button>
      </div>

      <hr className="profile-divider" />

      <div className="profile-discord">
        {user.discord_linked && !linkCode ? (
          <div className="profile-discord-linked">
            ✅ Discord linked{user.discord_username ? ` · @${user.discord_username}` : ""}
          </div>
        ) : discordOAuth ? (
          <a className="btn btn-block" href={`${apiBase}/api/auth/discord/start?mode=connect`}>
            🔗 Connect Discord
          </a>
        ) : linkCode ? (
          <div className="profile-discord-code">
            In Discord, run <code>/link {linkCode}</code>
            <div className="profile-discord-hint">Code expires in 10 minutes.</div>
          </div>
        ) : (
          <button
            className="btn btn-block"
            disabled={linkLoading}
            onClick={async () => {
              setLinkLoading(true);
              try {
                setLinkCode((await send(`${apiBase}/api/me/discord-link-code`)).code);
              } catch { /* ignore */ }
              setLinkLoading(false);
            }}
          >
            {linkLoading ? "..." : "🔗 Link Discord"}
          </button>
        )}
      </div>

      <SharingPrefs user={user} apiBase={apiBase} onUpdate={onUpdate} />

      <hr className="profile-divider" />
      <LetterboxdSection user={user} apiBase={apiBase} onUpdate={onUpdate} />

      <hr className="profile-divider" />
      <div className="profile-section-label profile-notify-title">Notifications</div>
      <NotifySettings apiBase={apiBase} key={`${user.discord_linked}-${!!user.email}`} />
    </div>
  );
}

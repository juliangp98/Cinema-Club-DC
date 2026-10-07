import { useState, useEffect } from "react";
import { accountLabel } from "../accountLabel";
import { Segmented } from "../ui/TicketRow";
import { getSharePrefs, setSharePrefs } from "../ui/DiscordShare";

const AVATAR_COLORS = ['#e8a838', '#c45c3a', '#4a7c6f', '#7b5ea7', '#3a6bb5', '#b5503a'];

const GENRE_LIST = [
  'action', 'comedy', 'drama', 'horror', 'sci-fi', 'thriller',
  'documentary', 'animation', 'romance', 'classic', 'foreign',
  'indie', 'experimental', 'mystery', 'fantasy', 'musical', 'war',
  'western', 'noir', 'biographical'
];

const SHARE_CHOICES = [
  { status: "ask", label: "Ask me" },
  { status: "always", label: "Always" },
  { status: "never", label: "Never" },
];
const SHARE_KINDS = [
  ["rsvp", "My RSVPs", "Never still leaves a Share button on each screening."],
  ["poll", "Polls I create", "Announcements and results (group admins)."],
  ["comment", "My comments", "Only where a screening has a Discord thread. Ask = remember my last choice."],
];

// What goes to the club's Discord from the site: per kind, ask / always / never.
// Saved as soon as you pick.
function SharingPrefs({ user, apiBase, onUpdate }) {
  const [state, setState] = useState(null);
  useEffect(() => {
    getSharePrefs(apiBase).then(setState).catch(() => setState(null));
  }, [apiBase]);
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
      {SHARE_KINDS.map(([kind, label, hint]) => (
        <div key={kind} className="profile-sharing-row">
          <div>
            <div className="profile-sharing-kind">{label}</div>
            <div className="profile-sharing-hint">{hint}</div>
          </div>
          <Segmented label={label} options={SHARE_CHOICES} value={state.prefs[kind]} onChange={v => choose(kind, v)} />
        </div>
      ))}
    </div>
  );
}

// The profile editor (name, color, genres, bio, Letterboxd, Discord and what
// to share there). Shown in a Sheet from the account menu or the Me page.
export default function ProfileEditor({ user, apiBase, onUpdate }) {
  const [name, setName] = useState(user.name || "");
  const [bio, setBio] = useState(user.bio || "");
  const [avatarColor, setAvatarColor] = useState(user.avatar_color || AVATAR_COLORS[0]);
  const [genres, setGenres] = useState(() => {
    return user.favorite_genres ? user.favorite_genres.split(",").filter(Boolean) : [];
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [kernels, setKernels] = useState(null);
  const [linkCode, setLinkCode] = useState(null);
  const [linkLoading, setLinkLoading] = useState(false);
  const [discordOAuth, setDiscordOAuth] = useState(false);
  const [letterboxd, setLetterboxd] = useState(user.letterboxd_username || "");

  // "Connect Discord" uses Discord sign-in when the site has it configured;
  // otherwise fall back to the /link code.
  useEffect(() => {
    fetch(`${apiBase}/api/auth/providers`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : {}))
      .then(d => setDiscordOAuth(!!d.discord))
      .catch(() => {});
  }, [apiBase]);

  // Fetch kernel count
  useEffect(() => {
    if (!user?.id) return;
    fetch(`${apiBase}/api/users/${user.id}/kernels`, { credentials: "include" })
      .then(r => r.ok ? r.json() : null)
      .then(d => { if (d) setKernels(d.kernels); })
      .catch(() => {});
  }, [user?.id, apiBase]);

  function toggleGenre(g) {
    setGenres(prev => prev.includes(g) ? prev.filter(x => x !== g) : [...prev, g]);
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    try {
      const r = await fetch(`${apiBase}/api/auth/profile`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({
          name: name.trim(),
          bio,
          avatar_color: avatarColor,
          favorite_genres: genres.join(","),
          letterboxd_username: letterboxd.trim(),
        }),
      });
      if (r.ok) {
        const d = await r.json();
        onUpdate(d.user);
        setSaved(true);
        setTimeout(() => setSaved(false), 2000);
      }
    } catch {
      // ignore
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="profile-menu">
      <h2 className="ui-section-title" style={{ marginBottom: "1rem" }}>
        <span className="deco" style={{ fontSize: "1.3rem", color: "var(--amber)" }}>Edit profile</span>
      </h2>
      <div className="profile-menu-header">
        <div
          className="profile-avatar-large"
          style={{ background: avatarColor, color: "var(--ink)" }}
        >
          {(name || "?").slice(0, 2).toUpperCase()}
        </div>
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

      <label className="profile-field-label">Avatar Color</label>
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

      <label className="profile-field-label">Favorite Genres</label>
      <div className="genre-chips">
        {GENRE_LIST.map(g => (
          <button
            key={g}
            className={`genre-chip${genres.includes(g) ? " active" : ""}`}
            onClick={() => toggleGenre(g)}
          >
            {g}
          </button>
        ))}
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

      <input
        className="profile-input"
        value={letterboxd}
        onChange={e => { setLetterboxd(e.target.value); setSaved(false); }}
        maxLength={60}
        placeholder="Letterboxd username (optional)"
      />

      <div className="profile-actions">
        <button className="profile-save-btn" onClick={handleSave} disabled={saving}>
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
          <a className="profile-discord-btn" href={`${apiBase}/api/auth/discord/start?mode=connect`}>
            🔗 Connect Discord
          </a>
        ) : linkCode ? (
          <div className="profile-discord-code">
            In Discord, run <code>/link {linkCode}</code>
            <div className="profile-discord-hint">Code expires in 10 minutes.</div>
          </div>
        ) : (
          <button
            className="profile-discord-btn"
            disabled={linkLoading}
            onClick={async () => {
              setLinkLoading(true);
              try {
                const r = await fetch(`${apiBase}/api/me/discord-link-code`, {
                  method: "POST", credentials: "include",
                });
                if (r.ok) setLinkCode((await r.json()).code);
              } catch { /* ignore */ }
              setLinkLoading(false);
            }}
          >
            {linkLoading ? "..." : "🔗 Link Discord"}
          </button>
        )}
      </div>

      <SharingPrefs user={user} apiBase={apiBase} onUpdate={onUpdate} />
    </div>
  );
}

import { useState, useEffect, useRef } from "react";

const AVATAR_COLORS = ['#e8a838', '#c45c3a', '#4a7c6f', '#7b5ea7', '#3a6bb5', '#b5503a'];

const GENRE_LIST = [
  'action', 'comedy', 'drama', 'horror', 'sci-fi', 'thriller',
  'documentary', 'animation', 'romance', 'classic', 'foreign',
  'indie', 'experimental', 'mystery', 'fantasy', 'musical', 'war',
  'western', 'noir', 'biographical'
];

export default function ProfileMenu({ user, apiBase, onUpdate, onLogout, onClose }) {
  const ref = useRef(null);
  const [name, setName] = useState(user.name || "");
  const [bio, setBio] = useState(user.bio || "");
  const [avatarColor, setAvatarColor] = useState(user.avatar_color || AVATAR_COLORS[0]);
  const [genres, setGenres] = useState(() => {
    return user.favorite_genres ? user.favorite_genres.split(",").filter(Boolean) : [];
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [kernels, setKernels] = useState(null);

  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    function onClick(e) {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    }
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, [onClose]);

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
    <div className="profile-menu" ref={ref}>
      <div className="profile-menu-header">
        <div
          className="profile-avatar-large"
          style={{ background: avatarColor, color: "#0d0c09" }}
        >
          {(name || "?").slice(0, 2).toUpperCase()}
        </div>
        <div className="profile-header-info">
          <div className="profile-email">{user.email}</div>
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

      <div className="profile-actions">
        <button className="profile-save-btn" onClick={handleSave} disabled={saving}>
          {saving ? "Saving..." : saved ? "Saved!" : "Save"}
        </button>
      </div>

      <hr className="profile-divider" />

      <button className="profile-logout-btn" onClick={onLogout}>
        Log Out
      </button>
    </div>
  );
}

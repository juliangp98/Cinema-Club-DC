import { useState, useEffect } from "react";

// Initials readable on any avatar color (R9e, WCAG AA 4.5:1): dark ink on
// light colors, ivory on dark ones; a mid-tone color that suits neither is
// deepened a little until ivory reads. Returns { background, color }.
const lum = n => {
  const lin = c => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  return 0.2126 * lin(n >> 16) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
};
const INK = 0.0049, IVORY = 0.835;                         // --ink #22090f, --cream #f5ecd7
export function initialsStyle(bg) {
  const m = /^#?([0-9a-f]{6})$/i.exec(bg || "");
  if (!m) return { background: bg, color: "var(--ink)" };
  let n = parseInt(m[1], 16);
  if ((lum(n) + 0.05) / (INK + 0.05) >= 4.5) return { background: `#${m[1]}`, color: "var(--ink)" };
  for (let i = 0; i < 20 && (IVORY + 0.05) / (lum(n) + 0.05) < 4.5; i += 1) {
    n = [16, 8, 0].reduce((acc, sh) => acc | (Math.round(((n >> sh) & 255) * 0.9) << sh), 0);
  }
  return { background: `#${n.toString(16).padStart(6, "0")}`, color: "var(--cream)" };
}

// A member's picture (R6b): their photo (an upload or their Discord picture),
// an emoji, or their initials on their chosen color.
export default function Avatar({ user, size = 32, onClick, title }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [user?.avatar_url]);
  const label = title || user?.name || "";
  const photo = user?.avatar_url && !broken;
  const emoji = !photo && user?.avatar_emoji;
  const colors = photo || emoji ? { background: "var(--bg3)" } : initialsStyle(user?.avatar_color || "#dcb15c");
  const style = { ...colors, width: size, height: size, fontSize: Math.max(10, Math.round(size * (emoji ? 0.55 : 0.36))) };
  const inner = photo
    ? <img src={user.avatar_url} alt="" onError={() => setBroken(true)} />
    : emoji || (user?.name || "?").slice(0, 2).toUpperCase();
  const cls = `ui-avatar${photo ? " photo" : emoji ? " emoji" : ""}`;
  return onClick ? (
    <button type="button" className={cls} style={style} onClick={onClick} title={label} aria-label={label}>{inner}</button>
  ) : (
    <span className={cls} style={style} title={label}>{inner}</span>
  );
}

// Just what goes inside an avatar, for places with their own avatar styling
// (feed stacks, chat): the photo, the emoji, or initials.
export function AvatarFace({ user }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [user?.avatar_url]);
  if (user?.avatar_url && !broken) return <img className="avatar-face-img" src={user.avatar_url} alt="" onError={() => setBroken(true)} />;
  if (user?.avatar_emoji) return <span className="avatar-face-emoji">{user.avatar_emoji}</span>;
  return (user?.name || "?").slice(0, 2).toUpperCase();
}

// Two letters for a name, skipping small words ("Motion Picture Hate and
// Derision Society" → "MP").
const SMALL = new Set(["a", "an", "and", "the", "of", "for", "in", "on", "at", "to", "dc"]);
export function initialsOf(name) {
  const words = (name || "").split(/\s+/).filter(Boolean);
  const big = words.filter(w => !SMALL.has(w.toLowerCase()));
  const use = (big.length ? big : words).slice(0, 2);
  return use.map(w => w[0]).join("").toUpperCase() || "?";
}

// A club's picture: its photo, or emoji, or initials. Square-ish with rounded
// corners, so it doesn't read as a person.
export function ClubBadge({ group, size = 32 }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [group?.photo_url]);
  const photo = group?.photo_url && !broken;
  const style = { width: size, height: size,
                  fontSize: Math.max(10, Math.round(size * (group?.emoji && !photo ? 0.55 : 0.38))) };
  return (
    <span className={`ui-club-badge${photo ? " photo" : ""}`} style={style} aria-hidden="true">
      {photo ? <img src={group.photo_url} alt="" onError={() => setBroken(true)} />
        : group?.emoji || initialsOf(group?.name)}
    </span>
  );
}

// What the top bar shows when there's no room for a club's full name.
export const shortNameOf = group => group?.short_name || initialsOf(group?.name);

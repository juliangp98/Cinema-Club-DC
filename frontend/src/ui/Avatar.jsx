import { useState, useEffect } from "react";

// A member's picture (R6b): their photo (an upload or their Discord picture),
// an emoji, or their initials on their chosen color.
export default function Avatar({ user, size = 32, onClick, title }) {
  const [broken, setBroken] = useState(false);
  useEffect(() => setBroken(false), [user?.avatar_url]);
  const label = title || user?.name || "";
  const photo = user?.avatar_url && !broken;
  const emoji = !photo && user?.avatar_emoji;
  const style = { background: photo ? "var(--bg3)" : emoji ? "var(--bg3)" : user?.avatar_color || "var(--amber)",
                  width: size, height: size, fontSize: Math.max(10, Math.round(size * (emoji ? 0.55 : 0.36))) };
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

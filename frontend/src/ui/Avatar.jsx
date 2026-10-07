// A member's initials on their chosen color.
export default function Avatar({ user, size = 32, onClick, title }) {
  const style = { background: user?.avatar_color || "var(--amber)", width: size, height: size,
                  fontSize: Math.max(10, Math.round(size * 0.36)) };
  const label = title || user?.name || "";
  const initials = (user?.name || "?").slice(0, 2).toUpperCase();
  return onClick ? (
    <button type="button" className="ui-avatar" style={style} onClick={onClick} title={label} aria-label={label}>
      {initials}
    </button>
  ) : (
    <span className="ui-avatar" style={style} title={label}>{initials}</span>
  );
}

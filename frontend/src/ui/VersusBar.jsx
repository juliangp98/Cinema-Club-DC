// Two (or more) numbers as bars side by side, scaled to the largest: their
// kernels next to yours when you size up a challenge. rows: [{label, value,
// tone?}] ("you" draws in green); a value below zero draws an empty bar.
export default function VersusBar({ rows, unit = "🍿", label }) {
  const most = Math.max(1, ...rows.map(r => r.value));
  return (
    <div className="ui-versus" role="img" aria-label={label}>
      {rows.map(r => (
        <div key={r.label} className="ui-versus-row">
          <span className="ui-versus-label">{r.label}</span>
          <span className={`ui-versus-bar${r.tone ? ` ${r.tone}` : ""}`}>
            <span style={{ width: `${(Math.max(0, r.value) / most) * 100}%` }} />
          </span>
          <strong>{r.value} {unit}</strong>
        </div>
      ))}
    </div>
  );
}

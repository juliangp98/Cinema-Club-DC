// Numbers people can scan, instead of a run-on line joined with dots.
//
// Facts: label/value pairs as small chips: [Record 3–1] [Won 75%]. A
// member's record, a poll score, your kernels by part. items: [{label, value,
// tone?}] (falsy items skipped); tone "good", "bad" or "gold" colors the value.
export default function Facts({ items, label, className = "" }) {
  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <dl className={`ui-facts${className ? ` ${className}` : ""}`} aria-label={label}>
      {shown.map(f => (
        <div key={f.label} className={`ui-fact${f.tone ? ` ${f.tone}` : ""}`}>
          <dt>{f.label}</dt>
          <dd>{f.value}</dd>
        </div>
      ))}
    </dl>
  );
}

// MetaRow: a card's details in one row, each with its icon, spaced apart
// (no dots between): who started it, how long it is, what's at stake, when
// it closes. items: [{icon, text, strong?}] (falsy items skipped); `strong`
// marks the one that matters most (usually the deadline). Plain spans, so
// it also fits inside a card that's a button.
export function MetaRow({ items, label }) {
  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <span className="ui-meta" aria-label={label}>
      {shown.map((m, i) => (
        <span key={i} className="ui-meta-item">
          {m.icon && <span aria-hidden="true">{m.icon}</span>}
          {m.strong ? <strong>{m.text}</strong> : m.text}
        </span>
      ))}
    </span>
  );
}

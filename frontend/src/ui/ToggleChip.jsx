// A chip you switch on and off (R13) — filters, the Feed's kinds, Your
// taste, picking a club's theatres. Gold when on; `color` adds a theatre's
// dot; `count` a small tally.
export default function ToggleChip({ on, onClick, count, color, title, disabled, children }) {
  return (
    <button type="button" className={`chip chip-toggle${on ? " gold" : ""}`} aria-pressed={!!on} onClick={onClick}
            disabled={disabled} title={title} style={color ? { "--tcolor": color } : undefined}>
      {color && <span className="theatre-link-dot" aria-hidden="true" />}
      {children}
      {count != null && <span className="mood-count">{count}</span>}
    </button>
  );
}

// A chip for something you picked, with a × to take it off (R13).
export function RemovableChip({ children, onRemove, label }) {
  return (
    <span className="chip chip-removable">
      {children}
      <button type="button" className="chip-remove" onClick={onRemove} aria-label={`Remove ${label}`}>×</button>
    </span>
  );
}

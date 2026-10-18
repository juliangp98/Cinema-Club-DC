// The site's one search bar (7f): Discover's — a pill with a magnifier, what
// you typed, × to clear it, and optionally a round action at the end (✨ to
// ask the AI). Enter submits. Used by the film search (SearchBox), Help, Your
// taste's pickers and Find a club; `inputProps` passes anything else the
// input needs (a combobox's aria, key handling).
export default function SearchField({ value, onChange, onSubmit, onClear, label, placeholder, action, inputProps = {},
                                      className = "" }) {
  return (
    <form className={`ui-search${className ? ` ${className}` : ""}`} role="search"
          onSubmit={e => { e.preventDefault(); onSubmit?.(e); }}>
      <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" />
      </svg>
      <input type="search" value={value} placeholder={placeholder} aria-label={label} autoComplete="off"
             onChange={e => onChange(e.target.value)} {...inputProps} />
      {value && (
        <button type="button" className="ui-search-clear" aria-label="Clear" onClick={() => (onClear ? onClear() : onChange(""))}>
          &times;
        </button>
      )}
      {action}
    </form>
  );
}

// The round button at the end of a search bar (✨).
export function SearchAction({ busy, className = "", children, ...props }) {
  return <button type="button" className={`ui-search-action${busy ? " busy" : ""}${className ? ` ${className}` : ""}`} {...props}>{children}</button>;
}

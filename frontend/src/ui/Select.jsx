// The site's one dropdown: a native <select> (so phones get their own picker)
// in the kit's field look, with its chevron drawn inside the padding rather
// than the browser's at the very edge. `options` are {value, label}; `size`
// "sm" is the chip-sized pill for rows and filter bars (a member's role, a
// poll's answer, Any theatre). Stretched by its parent, it fills the width.
export default function Select({ value, onChange, options, label, size, className = "", ...props }) {
  return (
    <span className={`ui-select${size === "sm" ? " sm" : ""}${className ? ` ${className}` : ""}`}>
      <select value={value} aria-label={label} onChange={e => onChange(e.target.value)} {...props}>
        {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"
           strokeLinejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6" /></svg>
    </span>
  );
}

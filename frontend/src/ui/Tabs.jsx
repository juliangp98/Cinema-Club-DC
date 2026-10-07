// A row of tabs (the profile-tabs look). tabs: [{ key, label }]; arrow keys move between them.
export default function Tabs({ tabs, value, onChange, label }) {
  function onKey(e) {
    const i = tabs.findIndex(t => t.key === value);
    const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = tabs[(i + step + tabs.length) % tabs.length];
    onChange(next.key);
    e.currentTarget.parentElement.querySelector(`[data-tab="${next.key}"]`)?.focus();
  }
  return (
    <div className="profile-tabs" role="tablist" aria-label={label}>
      {tabs.map(t => (
        <button key={t.key} type="button" role="tab" data-tab={t.key} aria-selected={value === t.key}
                tabIndex={value === t.key ? 0 : -1} className={`profile-tab${value === t.key ? " active" : ""}`}
                onClick={() => onChange(t.key)} onKeyDown={onKey}>
          {t.label}
        </button>
      ))}
    </div>
  );
}

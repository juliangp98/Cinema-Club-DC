import { useCallback, useRef, useState } from "react";
import { SectionTitle } from "./PageHeader";

// The settings standard (7g): every setting on the site — yours (Me →
// Settings), a club's (Club → Settings), and the questions asked in place —
// is built from these, so they look and behave the same everywhere:
//   SettingsSection  a titled section, with one line on what it covers
//   SettingsGroup    a small heading inside a section ("Your films")
//   SettingRow       a label and hint on the left, its control on the right
//                    (stacked on phones; `stack`: always, for wide controls)
//   Switch           on / off (a toggle, not a checkbox)
//   SwitchRow        a SettingRow with a Switch
// Settings save as you change them; useSaveStatus + SaveStatus say so in
// one place ("Saved" / the error).

export function SettingsSection({ id, title, intro, children, className = "" }) {
  return (
    <section id={id} className={`ui-settings-section${className ? ` ${className}` : ""}`} aria-labelledby={id && `${id}-title`}>
      <SectionTitle><span id={id && `${id}-title`}>{title}</span></SectionTitle>
      {intro && <p className="ui-hint ui-settings-intro">{intro}</p>}
      {children}
    </section>
  );
}

export function SettingsGroup({ title, children }) {
  return (
    <div className="ui-settings-group" role="group" aria-label={title}>
      <h3 className="ui-settings-group-title">{title}</h3>
      {children}
    </div>
  );
}

export function SettingRow({ label, hint, children, id, disabled, stack }) {
  return (
    <div className={`ui-setting${disabled ? " off" : ""}${stack ? " stack" : ""}`}>
      <div className="ui-setting-text">
        <span className="ui-setting-label" id={id}>{label}</span>
        {hint && <span className="ui-hint">{hint}</span>}
      </div>
      {children && <div className="ui-setting-control">{children}</div>}
    </div>
  );
}

export function Switch({ checked, onChange, label, labelledBy, disabled }) {
  return (
    <button type="button" role="switch" aria-checked={!!checked} aria-label={labelledBy ? undefined : label}
            aria-labelledby={labelledBy} disabled={disabled} className={`ui-switch${checked ? " on" : ""}`}
            onClick={() => onChange(!checked)}>
      <span className="ui-switch-knob" aria-hidden="true" />
    </button>
  );
}

let rowIds = 0;
export function SwitchRow({ label, hint, checked, onChange, disabled }) {
  const id = useRef(`setting-${(rowIds += 1)}`).current;
  return (
    <SettingRow label={label} hint={hint} id={id} disabled={disabled}>
      <Switch checked={checked} onChange={onChange} labelledBy={id} disabled={disabled} />
    </SettingRow>
  );
}

// One "Saved" for a settings page: `save(promise-making fn)` runs it and
// shows "Saved" for a moment, or the error.
export function useSaveStatus() {
  const [status, setStatus] = useState(null);
  const timer = useRef(null);
  const save = useCallback(async (fn, done = "Saved") => {
    clearTimeout(timer.current);
    try {
      const out = await fn();
      setStatus({ ok: true, text: done });
      timer.current = setTimeout(() => setStatus(null), 2200);
      return out;
    } catch (e) {
      setStatus({ ok: false, text: e?.data?.error || e?.message || "Couldn't save that — try again." });
      return undefined;
    }
  }, []);
  return [status, save];
}

export function SaveStatus({ status }) {
  return (
    <p className={`ui-save-status${status ? (status.ok ? " ok" : " err") : ""}`} role="status" aria-live="polite">
      {status ? (status.ok ? `✓ ${status.text}` : status.text) : ""}
    </p>
  );
}

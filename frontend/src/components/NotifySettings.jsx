import { useEffect, useState } from "react";

// Your one notification setting (R8): where alerts reach you, and which you
// get. The same setting as /notifications in Discord. Saved as you change it.
const CHANNELS = [
  ["discord", "Discord DMs", "Link Discord (in Edit profile) to get alerts as DMs."],
  ["email", "Email", "Add an email address to your account to get alerts by email."],
];

export default function NotifySettings({ apiBase }) {
  const [s, setS] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    fetch(`${apiBase}/api/me/notifications`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setS).catch(() => setFailed(true));
  }, [apiBase]);

  async function save(change) {
    const r = await fetch(`${apiBase}/api/me/notifications`, {
      method: "PUT", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change),
    }).catch(() => null);
    if (r?.ok) setS(await r.json());
  }

  if (failed) return <p className="notify-hint">Couldn't load your notification settings — try again in a bit.</p>;
  if (!s) return null;
  return (
    <div className="notify-settings">
      <div className="profile-section-label">Where alerts reach you</div>
      <label className="notify-row">
        <input type="checkbox" checked disabled />
        <span><span className="notify-name">Site bell</span><span className="notify-hint">Always — every alert is kept here.</span></span>
      </label>
      {CHANNELS.map(([key, name, missing]) => (
        <label key={key} className={`notify-row${s.available[key] ? "" : " off"}`}>
          <input type="checkbox" checked={s.channels[key]} disabled={!s.available[key]}
                 onChange={e => save({ channels: { [key]: e.target.checked } })} />
          <span><span className="notify-name">{name}</span>{!s.available[key] && <span className="notify-hint">{missing}</span>}</span>
        </label>
      ))}
      <div className="profile-section-label">Which alerts</div>
      {s.types_info.map(t => (
        <label key={t.key} className="notify-row">
          <input type="checkbox" checked={s.types[t.key]} onChange={e => save({ types: { [t.key]: e.target.checked } })} />
          <span><span className="notify-name">{t.label}</span><span className="notify-hint">{t.hint}</span></span>
        </label>
      ))}
    </div>
  );
}

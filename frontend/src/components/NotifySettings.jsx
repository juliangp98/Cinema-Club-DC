import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJson, send } from "../api";
import { SettingRow, SettingsGroup, SwitchRow } from "../ui/Settings";

// Push on this device (R8d): needs the browser's permission and, on iPhone,
// the site added to the Home Screen.
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
const isIos = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
const standalone = () => window.matchMedia?.("(display-mode: standalone)").matches || navigator.standalone;
const keyBytes = b64 => Uint8Array.from(atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/")), c => c.charCodeAt(0));

export function PushDevice({ apiBase, onSettings }) {
  const [key, setKey] = useState(null);
  const [sub, setSub] = useState(undefined);       // this device's subscription (null: none)
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => {
    getJson(`${apiBase}/api/push/key`).then(d => setKey(d?.key || "")).catch(() => setKey(""));
    if (pushSupported()) navigator.serviceWorker.ready.then(reg => reg.pushManager.getSubscription()).then(setSub).catch(() => setSub(null));
  }, [apiBase]);
  if (!key) return null;                             // push isn't set up on the server
  const post = (path, body) => send(`${apiBase}/api/push/${path}`, "POST", body);

  async function turnOn() {
    setBusy(true); setMsg("");
    try {
      if (await Notification.requestPermission() !== "granted") {
        setMsg("Notifications are blocked for this site — allow them in your browser's site settings, then try again.");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key) });
      const d = await post("subscribe", s.toJSON());
      setSub(s);
      onSettings(d);
    } catch {
      setMsg("Couldn't turn on push here — try again in a bit.");
    } finally { setBusy(false); }
  }
  async function turnOff() {
    setBusy(true);
    try {
      const d = await post("unsubscribe", { endpoint: sub.endpoint }).catch(() => null);
      await sub.unsubscribe().catch(() => {});
      setSub(null);
      if (d) onSettings(d);
    } finally { setBusy(false); }
  }
  async function test() {
    const ok = await post("test", {}).then(() => true, () => false);
    setMsg(ok ? "Sent — it should pop up in a moment." : "Couldn't send a test just now.");
  }

  let body;
  if (!pushSupported()) {
    body = isIos() && !standalone()
      ? "On iPhone: tap Share → Add to Home Screen, open Cinema Club from there, and turn push on in this menu."
      : "This browser can't get push notifications.";
  } else if (sub === undefined) {
    body = null;
  } else if (sub) {
    body = <>On for this device. <button type="button" className="linkish" disabled={busy} onClick={test}>Send a test</button> ·{" "}
      <button type="button" className="linkish" disabled={busy} onClick={turnOff}>Turn off here</button></>;
  } else {
    body = <button type="button" className="btn btn-sm" disabled={busy} onClick={turnOn}>Turn on push on this device</button>;
  }
  return (
    <div className="notify-push">
      {body && <div className="ui-hint">{body}</div>}
      {msg && <div className="ui-hint" role="status">{msg}</div>}
    </div>
  );
}

// Your one notification setting (R8): where alerts reach you, and which you
// get, grouped (7g: Your films / Going out / Games / Running a club — the
// backend's notify.TYPE_GROUPS), and your saved searches. The same setting
// as /notifications in Discord. Saved as you change it (`save`: the page's
// useSaveStatus, so it says "Saved" in one place).
const CHANNELS = [
  ["discord", "Discord DMs", "Link Discord (Settings → Connections) to get alerts as DMs."],
  ["email", "Email", "Add an email address to your account to get alerts by email."],
  ["push", "Push notifications", "Pop-ups on your phone or computer, even with the site closed."],
];

export default function NotifySettings({ apiBase, save = fn => fn() }) {
  const [s, setS] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    getJson(`${apiBase}/api/me/notifications`).then(setS).catch(() => setFailed(true));
  }, [apiBase]);

  const put = change => save(async () => setS(await send(`${apiBase}/api/me/notifications`, "PUT", change)));
  const removeSearch = id => save(async () => {
    await send(`${apiBase}/api/searches/${id}`, "DELETE");
    setS(cur => ({ ...cur, searches: cur.searches.filter(x => x.id !== id) }));
  }, "Removed");

  if (failed) return <p className="ui-hint">Couldn't load your notification settings — try again in a bit.</p>;
  if (!s) return null;
  const groups = [];
  for (const t of s.types_info) {
    if (!groups.length || groups.at(-1).key !== t.group) groups.push({ key: t.group, label: t.group_label, types: [] });
    groups.at(-1).types.push(t);
  }
  return (
    <div className="notify-settings">
      <SettingsGroup title="Where alerts reach you">
        <SwitchRow label="Site bell" hint="Always on — every alert is kept here." checked disabled onChange={() => {}} />
        {CHANNELS.filter(([key]) => key !== "push" || s.push_ready).map(([key, name, missing]) => (
          <div key={key}>
            <SwitchRow label={name} hint={s.available[key] ? null : missing} checked={s.channels[key]} disabled={!s.available[key]}
                       onChange={v => put({ channels: { [key]: v } })} />
            {key === "push" && <PushDevice apiBase={apiBase} onSettings={setS} />}
          </div>
        ))}
      </SettingsGroup>
      <div id="notify-which">
        {groups.map(g => (
          <SettingsGroup key={g.key} title={g.label}>
            {g.types.map(t => <SwitchRow key={t.key} label={t.label} hint={t.hint} checked={s.types[t.key]}
                                         disabled={!!t.needs && !s.types[t.needs]}
                                         onChange={v => put({ types: { [t.key]: v } })} />)}
          </SettingsGroup>
        ))}
      </div>
      <div id="notify-searches">
        <SettingsGroup title="Saved searches">
          {s.searches?.length ? s.searches.map(x => (
            <SettingRow key={x.id} label={<Link to={x.path}>{x.label}</Link>} hint="A theatre books a film that fits it">
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => removeSearch(x.id)}>Remove</button>
            </SettingRow>
          )) : <p className="ui-hint">None yet. On Browse, pick some filters and tap 🔔 Alert me.</p>}
        </SettingsGroup>
      </div>
    </div>
  );
}

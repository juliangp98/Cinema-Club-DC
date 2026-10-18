import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJson, send } from "../api";

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
// get. The same setting as /notifications in Discord. Saved as you change it.
const CHANNELS = [
  ["discord", "Discord DMs", "Link Discord (in Edit profile) to get alerts as DMs."],
  ["email", "Email", "Add an email address to your account to get alerts by email."],
  ["push", "Push notifications", "Pop-ups on your phone or computer, even with the site closed."],
];

export default function NotifySettings({ apiBase }) {
  const [s, setS] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    getJson(`${apiBase}/api/me/notifications`).then(setS).catch(() => setFailed(true));
  }, [apiBase]);

  async function save(change) {
    const d = await send(`${apiBase}/api/me/notifications`, "PUT", change).catch(() => null);
    if (d) setS(d);
  }
  async function removeSearch(id) {
    const ok = await send(`${apiBase}/api/searches/${id}`, "DELETE").then(() => true, () => false);
    if (ok) setS(cur => ({ ...cur, searches: cur.searches.filter(x => x.id !== id) }));
  }

  if (failed) return <p className="ui-hint">Couldn't load your notification settings — try again in a bit.</p>;
  if (!s) return null;
  return (
    <div className="notify-settings">
      <div className="profile-section-label">Where alerts reach you</div>
      <p className="ui-hint">Nothing is sent anywhere until you turn it on here.</p>
      <label className="notify-row">
        <input type="checkbox" checked disabled />
        <span><span className="notify-name">Site bell</span><span className="ui-hint">Always — every alert is kept here.</span></span>
      </label>
      {CHANNELS.filter(([key]) => key !== "push" || s.push_ready).map(([key, name, missing]) => (
        <div key={key}>
          <label className={`notify-row${s.available[key] ? "" : " off"}`}>
            <input type="checkbox" checked={s.channels[key]} disabled={!s.available[key]}
                   onChange={e => save({ channels: { [key]: e.target.checked } })} />
            <span><span className="notify-name">{name}</span>{!s.available[key] && <span className="ui-hint">{missing}</span>}</span>
          </label>
          {key === "push" && <PushDevice apiBase={apiBase} onSettings={setS} />}
        </div>
      ))}
      <div className="profile-section-label" id="notify-which">Which alerts</div>
      {s.types_info.map(t => (
        <label key={t.key} className="notify-row">
          <input type="checkbox" checked={s.types[t.key]} onChange={e => save({ types: { [t.key]: e.target.checked } })} />
          <span><span className="notify-name">{t.label}</span><span className="ui-hint">{t.hint}</span></span>
        </label>
      ))}
      <div className="profile-section-label" id="notify-searches">Saved searches</div>
      {s.searches?.length ? s.searches.map(x => (
        <div key={x.id} className="notify-row notify-search">
          <Link to={x.path} className="notify-name">{x.label}</Link>
          <button type="button" className="linkish" onClick={() => removeSearch(x.id)}>Remove</button>
        </div>
      )) : <p className="ui-hint">None yet. On Browse, pick some filters and tap 🔔 Alert me.</p>}
    </div>
  );
}

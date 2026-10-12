import { useEffect, useState } from "react";
import { PushDevice } from "../components/NotifySettings";

// Notifications are opt-in: these ask once, at the first moment they matter.
// Nothing leaves the site unless the person picks something here (or in the
// bell's Notification settings, which can change it all later).

const put = (apiBase, path, body) => fetch(`${apiBase}${path}`, {
  method: "PUT", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
});

// After a first watchlist add: how (if at all) to hear when a theatre books
// one. `digest`: also offer the Monday digest mention in the club's Discord.
export function WatchAlertPrompt({ apiBase, movieId, digest, onDone }) {
  const [s, setS] = useState(null);
  const [pick, setPick] = useState({ discord: false, email: false, mention: false });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    fetch(`${apiBase}/api/me/notifications`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : null)).then(setS).catch(() => setS(null));
  }, [apiBase]);
  if (!s) return null;
  const ways = [["discord", "Discord DM"], ["email", "Email"]].filter(([k]) => s.available[k]);

  async function save() {
    setBusy(true);
    const channels = Object.fromEntries(ways.filter(([k]) => pick[k]).map(([k]) => [k, true]));
    if (Object.keys(channels).length) await put(apiBase, "/api/me/notifications", { channels }).catch(() => {});
    if (digest) await put(apiBase, `/api/watchlist/${movieId}/discord`, { share: pick.mention, remember: true }).catch(() => {});
    setBusy(false);
    onDone?.();
  }
  return (
    <div className="share-prompt alert-ask" role="group" aria-label="Watchlist alerts">
      <p className="alert-ask-q">Want to hear when a theatre books (or announces) films on your watchlist?</p>
      <p className="notify-hint">They'll always show in the 🔔 here. Pick any way you'd also like to be told — nothing is sent otherwise.</p>
      <div className="alert-ask-ways">
        {ways.map(([k, label]) => (
          <label key={k} className="notify-row">
            <input type="checkbox" checked={pick[k]} onChange={e => setPick(p => ({ ...p, [k]: e.target.checked }))} />
            <span className="notify-name">{label}</span>
          </label>
        ))}
        {digest && (
          <label className="notify-row">
            <input type="checkbox" checked={pick.mention} onChange={e => setPick(p => ({ ...p, mention: e.target.checked }))} />
            <span className="notify-name">Mention me in the Monday digest on Discord</span>
          </label>
        )}
        {s.push_ready && <div><span className="notify-name">Push on this device</span><PushDevice apiBase={apiBase} onSettings={setS} /></div>}
      </div>
      <div className="alert-ask-actions">
        <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={save}>Save</button>
        <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onDone?.()}>Not now</button>
        <span className="notify-hint">Change it any time: 🔔 → Notification settings.</span>
      </div>
    </div>
  );
}

// After a first "Going" (Discord members): "Did you make it?" DMs.
export function AttendanceAsk({ apiBase }) {
  const [done, setDone] = useState(false);
  if (done) return null;
  const answer = async yes => {
    setDone(true);
    if (yes) await put(apiBase, "/api/me/notifications", { types: { attendance: true } }).catch(() => {});
  };
  return (
    <div className="share-prompt alert-ask" role="group" aria-label="Did you make it? DMs">
      <span>Want a Discord DM after screenings you're going to, to log whether you made it?</span>
      <button type="button" className="btn btn-sm btn-primary" onClick={() => answer(true)}>Yes, DM me</button>
      <button type="button" className="btn btn-sm" onClick={() => answer(false)}>No thanks</button>
    </div>
  );
}

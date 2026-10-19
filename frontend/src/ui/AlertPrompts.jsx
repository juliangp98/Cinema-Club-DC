import { useEffect, useState } from "react";
import { PushDevice } from "../components/NotifySettings";
import { getJson, send } from "../api";
import { Link } from "react-router-dom";
import Prompt from "./Prompt";
import { SettingRow, SwitchRow } from "./Settings";

// Notifications are opt-in: these ask once, at the first moment they matter.
// Nothing leaves the site unless the person picks something here (or in the
// Settings → Notifications, which can change it all later).

const put = (apiBase, path, body) => send(`${apiBase}${path}`, "PUT", body);

// What to ask after a watchlist add, from the server's answer.
export const watchPromptOf = d => (d.alert_prompt ? { alerts: true, digest: !!d.discord_prompt }
  : d.discord_prompt ? { digest: true } : null);

// After a first watchlist add (or saved search): how (if at all) to hear when
// a theatre books one. `digest`: also offer the Monday digest mention in the
// club's Discord. `question`: what's being asked about.
export function WatchAlertPrompt({ apiBase, movieId, digest, onDone,
  question = "Want to hear when a theatre books (or announces) films on your watchlist?" }) {
  const [s, setS] = useState(null);
  const [pick, setPick] = useState({ discord: false, email: false, mention: false });
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    getJson(`${apiBase}/api/me/notifications`, { cache: false }).then(setS).catch(() => setS(null));
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
    <Prompt question={question} label="How to get alerts" onClose={() => onDone?.()}
            hint="They'll always show in the 🔔 here. Pick any way you'd also like to be told — nothing is sent otherwise."
            actions={<>
              <button type="button" className="btn btn-sm btn-primary" disabled={busy} onClick={save}>Save</button>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => onDone?.()}>Not now</button>
            </>}>
      <div className="ui-prompt-choices">
        {ways.map(([k, label]) => (
          <SwitchRow key={k} label={label} checked={pick[k]} onChange={v => setPick(p => ({ ...p, [k]: v }))} />
        ))}
        {digest && <SwitchRow label="Mention me in the Monday digest on Discord" checked={pick.mention}
                              onChange={v => setPick(p => ({ ...p, mention: v }))} />}
        {s.push_ready && <SettingRow label="Push on this device"><PushDevice apiBase={apiBase} onSettings={setS} /></SettingRow>}
        <p className="ui-hint">Change it any time in <Link to="/me?tab=settings#settings-notify">Settings → Notifications</Link>.</p>
      </div>
    </Prompt>
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
    <Prompt question="A Discord DM after screenings you're going to?" label="Did you make it? DMs"
            hint="To log whether you made it — one tap. Nothing is sent unless you say yes." onClose={() => setDone(true)}
            actions={<>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => answer(true)}>Yes, DM me</button>
              <button type="button" className="btn btn-sm" onClick={() => answer(false)}>No thanks</button>
            </>} />
  );
}

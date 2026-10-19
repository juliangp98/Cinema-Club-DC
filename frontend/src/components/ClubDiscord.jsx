import { useEffect, useState } from "react";
import { getJson, send } from "../api";
import { SettingRow, SettingsGroup } from "../ui/Settings";

// Club settings → Discord: the club's Discord server. Admins connect one in
// two steps — add the bot (Discord's invite), then run /setup with a one-time
// code in the channel it should use (we check back every few seconds until it
// connects) — or disconnect it. Organizers see where things stand.
const WATCH_EVERY = 5000;

export default function ClubDiscord({ group, apiBase, isAdmin, run, onConnected }) {
  const base = `${apiBase}/api/groups/${group.slug}/discord`;
  const [info, setInfo] = useState(null);
  const [code, setCode] = useState(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    getJson(base, { cache: false }).then(setInfo).catch(() => setInfo(null));
  }, [base]);

  // A code is out: watch for /setup to connect the server.
  const waiting = !!code && !info?.server;
  useEffect(() => {
    if (!waiting) return undefined;
    const t = setInterval(async () => {
      const next = await getJson(base, { cache: false }).catch(() => null);
      if (next?.server) {
        setInfo(next);
        setCode(null);
        onConnected?.();
      }
    }, WATCH_EVERY);
    return () => clearInterval(t);
  }, [waiting, base]);   // eslint-disable-line react-hooks/exhaustive-deps

  if (!info) return null;
  const command = code && `/setup code:${code.code}`;
  const makeCode = () => run(async () => setCode(await send(`${base}/code`, "POST")), "Code ready");
  const copy = async () => {
    try { await navigator.clipboard.writeText(command); setCopied(true); setTimeout(() => setCopied(false), 2000); }
    catch { window.prompt("Copy this:", command); }
  };
  const disconnect = () => {
    if (!window.confirm(`Disconnect ${info.server.name || "the server"}? The bot stops posting there and members' commands there no longer use this club. Your Discord settings here are kept.`)) return;
    run(async () => { setInfo(await send(base, "DELETE")); onConnected?.(); }, "Disconnected");
  };

  if (info.server) {
    const s = info.server;
    return (
      <>
        <SettingRow label={s.name || "Your server"} id="club-settings-discord-server"
                    hint={`Posts in #${s.channel || "its channel"} · ${s.linked} member${s.linked === 1 ? "" : "s"} here ${s.linked === 1 ? "is" : "are"} in the server. Move it: run /setup in another channel (server admins).`}>
          {isAdmin && !info.home && <button type="button" className="btn btn-sm btn-ghost" onClick={disconnect}>Disconnect</button>}
        </SettingRow>
        {s.missing?.length > 0 && (
          <p className="ui-hint club-discord-missing" role="note">
            ⚠️ The bot can't do everything in #{s.channel || "its channel"}. Give it: {s.missing.join(", ")} (the channel's permissions, or
            Server Settings → Integrations).
          </p>
        )}
        {info.home && <p className="ui-hint">This is the site's own server — the bot's home, set in its settings.</p>}
      </>
    );
  }
  if (info.connected) {                 // the home club, before the bot has registered its server
    return <p className="ui-hint" id="club-settings-discord-server">Connected to the site's own server — the bot registers it when it starts.</p>;
  }
  if (!isAdmin) {
    return <p className="ui-hint" id="club-settings-discord-server">No Discord server is connected. A club admin can connect one here.</p>;
  }
  return (
    <SettingsGroup title="Connect your server">
      <SettingRow label="1. Add the bot" id="club-settings-discord-server"
                  hint="Opens Discord: pick your club's server (you need Manage Server there).">
        {info.invite_url
          ? <a className="btn btn-sm btn-discord" href={info.invite_url} target="_blank" rel="noopener noreferrer">Add to Discord ↗</a>
          : <span className="ui-hint">The bot isn't running yet — try again in a bit.</span>}
      </SettingRow>
      <SettingRow stack label="2. Connect it"
                  hint={code ? `In the channel the bot should post in, run this. It works once, for ${code.minutes} minutes; this page updates when it's done.`
                    : "Make a code, then run /setup with it in the channel the bot should post in."}>
        {code ? (
          <div className="settings-inline">
            <input className="share-input club-discord-code" readOnly value={command} aria-label="Setup command"
                   onFocus={e => e.target.select()} />
            <button type="button" className="btn btn-sm" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
            <button type="button" className="btn btn-sm btn-ghost" onClick={makeCode}>New code</button>
          </div>
        ) : <button type="button" className="btn btn-sm" onClick={makeCode}>Make a code</button>}
      </SettingRow>
    </SettingsGroup>
  );
}

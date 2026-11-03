import { useRef, useState } from "react";
import { send, useJson } from "../api";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import StatTiles from "../ui/StatTiles";
import Panel from "../ui/Panel";
import { signed } from "./Challenges";

// Challenge scouting (scout.py), at the top of Play's Challenges: your record
// and the club's best (who wins most, the hottest streak, the biggest pot, the
// fiercest rivalry…), then who you should challenge and why — kernels, win
// rates, how you've done against them, a suggested game and stake — with a
// roast of their movie habits next to yours, and the habits themselves.

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The stats; `children(scout)` renders below them (the picks), so both share one request.
export function ChallengeStats({ apiBase, groupId, children }) {
  const { data } = useJson(`${apiBase}/api/challenges/scout?group_id=${groupId}`, { refreshOn: "kernels" });
  if (!data) return null;
  const { stats } = data;
  const you = stats.you;
  return (
    <section className="ch-arena" aria-label="Challenge stats">
      {you && you.played > 0 ? (
        <StatTiles label="Your challenges" items={[
          { label: "Your record", value: `${you.won}–${you.lost}`, sub: `${you.win_rate}% won${you.streak > 1 ? ` · ${you.streak} in a row 🔥` : ""}` },
          { label: "Kernels from challenges", value: `${signed(you.kernels)} 🍿`, sub: you.biggest_win ? `biggest win +${you.biggest_win} 🍿` : "no big wins yet" },
          you.nemesis && { label: "Your nemesis", value: you.nemesis.user.name, sub: `beat you ${plural(you.nemesis.lost, "time")}` },
          you.victim && { label: "Your favorite victim", value: you.victim.user.name, sub: `you beat them ${plural(you.victim.won, "time")}` },
          you.best_game && { label: "Your best game", value: `${you.best_game.emoji} ${you.best_game.label}`, sub: `${you.best_game.win_rate}% won` },
          you.titles > 0 && { label: "Tournament titles", value: `🏆 ${you.titles}` },
        ]} />
      ) : <p className="ui-hint">You haven't played a challenge yet — your record, your nemesis and your best game show up here.</p>}
      {stats.club.length > 0 && (
        <ul className="ch-trophies" aria-label="The club's challenge stats">
          {stats.club.map(row => (
            <li key={row.key} className="ch-trophy">
              <span className="ch-trophy-icon" aria-hidden="true">{row.icon}</span>
              <span className="ch-trophy-label">{row.label}</span>
              {row.user && <strong>{row.user.name}{row.other && ` vs ${row.other.name}`}</strong>}
              <span className="ch-trophy-value">{row.value}</span>
            </li>
          ))}
          <li className="ch-trophy muted">
            <span className="ch-trophy-icon" aria-hidden="true">🍿</span>
            <span className="ch-trophy-label">Decided so far</span>
            <strong>{plural(stats.decided, "challenge")}</strong>
            <span className="ch-trophy-value">{stats.kernels_moved} 🍿 changed hands</span>
          </li>
        </ul>
      )}
      {children?.(data)}
    </section>
  );
}

// Their movie habits next to yours (only what they show the club).
function Habits({ rows }) {
  return (
    <table className="ch-habits">
      <thead><tr><th scope="col">Habit</th><th scope="col">You</th><th scope="col">Them</th></tr></thead>
      <tbody>
        {rows.map(r => (
          <tr key={r.label}><th scope="row"><span aria-hidden="true">{r.icon}</span> {r.label}</th><td>{r.you ?? "—"}</td><td>{r.them ?? "—"}</td></tr>
        ))}
      </tbody>
    </table>
  );
}

function PickCard({ apiBase, groupId, p, spotlight, onChallenge }) {
  const [roast, setRoast] = useState(null);
  const [roasting, setRoasting] = useState(false);
  const [habits, setHabits] = useState(false);
  const [error, setError] = useState("");
  const k = p.kernels;
  const most = Math.max(k.them, k.you, 1);
  const bar = n => `${(Math.max(0, n) / most) * 100}%`;                // below zero: an empty bar

  async function fire(again) {
    setRoasting(true);
    setError("");
    try {
      setRoast(await send(`${apiBase}/api/challenges/scout/${p.user.id}/roast`, "POST", { group_id: groupId, again }));
    } catch (e) { setError(e.data?.error || "The roast fizzled — try again."); }
    finally { setRoasting(false); }
  }

  return (
    <article className={`ch-pick${spotlight ? " spotlight" : ""}`} aria-label={`Challenge ${p.user.name}?`}>
      <div className="ch-pick-head">
        <Avatar user={p.user} size={40} link />
        <div className="ch-pick-who">
          <PersonLink user={p.user} className="ch-pick-name" />
          <span className="ui-badge gold">{p.tag.emoji} {p.tag.label}</span>
        </div>
      </div>
      <div className="ch-pick-kernels" aria-label={`${p.user.name} has ${k.them} kernels; you have ${k.you}`}>
        <span>{p.user.name}</span><span className="ch-bar"><span style={{ width: bar(k.them) }} /></span><strong>{k.them} 🍿</strong>
        <span>You</span><span className="ch-bar you"><span style={{ width: bar(k.you) }} /></span><strong>{k.you} 🍿</strong>
      </div>
      <p className="ch-pick-record">
        {p.record.played ? `${p.record.won}–${p.record.lost} in challenges · ${p.record.win_rate}% won` : "Hasn't played a challenge yet"}
        {p.versus.played > 0 ? ` · you're ${p.versus.won}–${p.versus.lost} against them` : ""}
        {p.best_game && ` · best at ${p.best_game.label}`}
      </p>
      <ul className="ch-pick-why">{p.why.map(w => <li key={w}>{w}</li>)}</ul>
      {p.suggest.kind && <p className="ch-pick-try">Try: {p.suggest.emoji} {p.suggest.label}{p.suggest.stake ? ` for ${p.suggest.stake} 🍿` : ""}</p>}
      {roast && (
        <blockquote className="ch-roast" aria-live="polite">
          <p>🔥 {roast.roast}</p>
          <footer>{roast.by === "ai" ? "Written by the AI from their habits" : "From their habits"}</footer>
        </blockquote>
      )}
      {error && <p className="share-error">{error}</p>}
      {habits && <Habits rows={p.habits} />}
      <div className="ch-pick-actions">
        <button type="button" className="btn btn-sm btn-primary" onClick={() => onChallenge(p)}>⚔️ Challenge</button>
        {p.roastable ? (
          <button type="button" className="btn btn-sm" disabled={roasting || (roast && !roast.more)} onClick={() => fire(!!roast)}>
            {roasting ? "🔥 Heating up…" : roast ? (roast.more ? "🔥 Another" : "🔥 That's all today") : "🔥 Roast"}
          </button>
        ) : <span className="ui-hint">🛡️ Roasts off</span>}
        {p.habits.length > 0 && (
          <button type="button" className="btn btn-sm btn-ghost" aria-pressed={habits} onClick={() => setHabits(h => !h)}>📊 Habits</button>
        )}
      </div>
    </article>
  );
}

// "Who should you challenge?" — the best picks first, side by side; 🎲 picks one for you.
export function ScoutPicks({ apiBase, groupId, picks, onChallenge }) {
  const [spot, setSpot] = useState(null);
  const row = useRef(null);
  if (!picks.length) return null;
  function luck() {
    const p = picks[Math.floor(Math.random() * picks.length)];
    setSpot(p.user.id);
    row.current?.querySelector(`[data-pick="${p.user.id}"]`)?.scrollIntoView?.({ behavior: "smooth", block: "nearest", inline: "center" });
  }
  return (
    <Panel as="div" tone="gold" className="ch-scout" title="🔍 Who should you challenge?"
           hint="By your record, theirs and the kernels — with a roast, if they're up for one"
           aside={<button type="button" className="btn btn-sm" onClick={luck}>🎲 Pick for me</button>}>
      <div className="ch-picks" ref={row}>
        {picks.map(p => (
          <div key={p.user.id} data-pick={p.user.id}>
            <PickCard apiBase={apiBase} groupId={groupId} p={p} spotlight={spot === p.user.id} onChallenge={onChallenge} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

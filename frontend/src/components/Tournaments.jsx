import { useState } from "react";
import { Link } from "react-router-dom";
import { changed, send } from "../api";
import Avatar from "../ui/Avatar";
import Sheet, { SheetTitle } from "../ui/Sheet";
import { Segmented } from "../ui/TicketRow";
import { untilText } from "./PollList";
import { MetaRow } from "../ui/Facts";
import { AnnounceChoice, GameSet, PeoplePick, REVEALS, SEEN, STAKES, useAnnounce, useGameSet } from "./Challenges";

// Tournaments (tournaments.py): a bracket of 1-v-1 challenges for three or
// more — double elimination (a losers' bracket, one grand final) or a round
// robin and a final. The card (Play, the Feed), the "new tournament" sheet
// and the bracket live here; each has its own page (pages/TournamentPage.jsx)
// and each match is played on its challenge page.

export const TOURNAMENT_STATUS = { open: "Taking entries", running: "Under way", done: "Decided", cancelled: "Called off" };
export const MEDALS = { 1: "🥇", 2: "🥈", 3: "🥉" };
const FORMATS = [{ status: "double", label: "Double elimination" }, { status: "round_robin", label: "Round robin + final" }];
const PAYOUTS = [{ status: "all", label: "Winner takes all" }, { status: "top3", label: "60 / 30 / 10" }];
const SEEDINGS = [{ status: "random", label: "Random" }, { status: "record", label: "By challenge record" }];
const entrants = t => t.players.filter(p => p.status === "accepted");
// The prizes from a pot, as tournaments.py splits it (what rounding leaves goes to the champion).
export function prizes(pot, payout) {
  const shares = (payout === "top3" ? [60, 30, 10] : [100]).map(p => Math.floor((pot * p) / 100));
  shares[0] += pot - shares.reduce((a, b) => a + b, 0);
  return shares;
}

function nextStep(t) {
  const y = t.you;
  if (y.can_accept) return { label: "Join or decline", gold: true };
  if (y.match) return { label: "▶ Play your match", gold: true, to: `/challenges/${y.match}` };
  if (y.can_join) return { label: "🪑 Take a seat" };
  if (y.can_back) return { label: "🍿 Back a player" };
  return { label: t.status === "done" ? "See how it ended" : "See the bracket" };
}

// A tournament in a list (Play) or the Feed.
export function TournamentCard({ t, onOpen }) {
  const step = nextStep(t);
  const people = t.players.filter(p => !["declined", "expired"].includes(p.status));
  return (
    <article className={`ch-card tour-card status-${t.status === "running" ? "open" : t.status}`}>
      <button type="button" className="ch-card-main" onClick={onOpen}>
        <span className={`ui-badge ${{ open: "go", running: "go", done: "gold" }[t.status] || ""}`}>{TOURNAMENT_STATUS[t.status]}</span>
        <span className="ch-card-title">🏆 {t.format_label}: {t.games_line}</span>
        <MetaRow label="About it" items={[
          { icon: "👤", text: t.created_by.name },
          { icon: "👥", text: `${entrants(t).length} in` },
          { icon: "🍿", text: t.stake ? `${t.stake} each, pot ${t.pot}, ${t.payout_label.toLowerCase()}` : "For bragging rights" },
          t.status === "open" && { icon: "⏰", text: `entries close ${untilText(t.closes_at)}`, strong: true },
          t.backing.count > 0 && { icon: "🤝", text: `${t.backing.total} 🍿 backing` },
        ]} />
        <span className="ch-people">
          {people.map(p => (
            <span key={p.user.id} className={`ch-person${p.place === 1 ? " winner" : ""}${t.status === "running" && !p.alive ? " out" : ""}`}>
              <Avatar user={p.user} size={22} />
              <span>{MEDALS[p.place] || (p.seed ? `#${p.seed} ` : "")}{p.user.name}</span>
            </span>
          ))}
        </span>
      </button>
      {step.to ? <Link className="btn btn-sm btn-primary" to={step.to}>{step.label}</Link>
        : <button type="button" className={`btn btn-sm${step.gold ? " btn-primary" : ""}`} onClick={onOpen}>{step.label}</button>}
    </article>
  );
}

// "🏆 Start a tournament": the format, the games every match plays, who's
// invited and open seats, the entry and the prizes, seeds, when entries close
// and how long each match stays open, scores, who sees it, Discord.
export function NewTournament({ apiBase, groupId, settings, options, viewerId, onClose, onMade }) {
  const set = useGameSet();
  const announce = useAnnounce();
  const [format, setFormat] = useState("double");
  const [players, setPlayers] = useState([]);
  const [seats, setSeats] = useState(0);
  const [stake, setStake] = useState(Math.min(3, settings.max_stake, settings.available));
  const [payout, setPayout] = useState("all");
  const [seeding, setSeeding] = useState("random");
  const [deadline, setDeadline] = useState("tonight");
  const [matchTime, setMatchTime] = useState("day");
  const [reveal, setReveal] = useState("sealed");
  const [seen, setSeen] = useState("club");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lo, hi] = options.players[format];
  const total = 1 + players.length + seats;
  const pot = stake * total;
  const toggle = id => setPlayers(ps => (ps.includes(id) ? ps.filter(x => x !== id) : total < hi ? [...ps, id] : ps));

  async function create() {
    setBusy(true);
    setError("");
    try {
      const made = await send(`${apiBase}/api/tournaments`, "POST", {
        group_id: groupId, format, rounds: set.rounds, players, seats, stake, payout, seeding, deadline,
        match_time: matchTime, reveal, visibility: seen, ...(announce.canAnnounce && seen === "club" ? { announce: announce.post } : {}),
      });
      changed("kernels");
      onMade(made);
    } catch (e) { setError(e.data?.error || "Couldn't set that up. Try again."); }
    finally { setBusy(false); }
  }

  return (
    <Sheet label="New tournament" onClose={onClose} className="share-sheet ch-sheet">
      <div className="share-sheet-body">
        <SheetTitle>🏆 New tournament</SheetTitle>
        <span className="share-label">Format</span>
        <Segmented label="Format" options={FORMATS} value={format} onChange={v => v && setFormat(v)} />
        <p className="ui-hint">{format === "double"
          ? `${lo}–${hi} players. Lose once and you drop to the losers' bracket; lose twice and you're out. One grand final.`
          : `${lo}–${hi} players. Everyone plays everyone once; the top two meet in a final.`}</p>
        <GameSet set={set} settings={settings} note="Every match plays these; random ones are drawn fresh for each match." />

        <span className="share-label">Who's invited</span>
        <PeoplePick apiBase={apiBase} viewerId={viewerId} picked={players} onToggle={toggle} />
        <label className="share-label" htmlFor="tour-seats">Open seats (anyone in the club can take one)</label>
        <input id="tour-seats" type="number" className="share-input ch-number" min={0} max={Math.min(options.max_seats, hi - 1 - players.length)}
               value={seats} onChange={e => setSeats(Math.max(0, Math.min(options.max_seats, hi - 1 - players.length, Number(e.target.value) || 0)))} />
        <p className="ui-hint">{total} of {lo}–{hi} players with you{total < lo ? `. It needs ${lo - total} more` : ""}.</p>

        <span className="share-label">Entry (each player, into the prize pot)</span>
        <Segmented label="Entry" options={STAKES.filter(n => n <= settings.max_stake).map(n => ({ status: String(n), label: n ? `${n} 🍿` : "None" }))}
                   value={String(stake)} onChange={v => v != null && setStake(Number(v))} />
        {stake > 0 && <>
          <span className="share-label">Prizes</span>
          <Segmented label="Prizes" options={PAYOUTS} value={payout} onChange={v => v && setPayout(v)} />
        </>}
        <p className="ui-hint">
          {stake > settings.available ? `You have ${settings.available} 🍿 to put in.`
            : !stake ? "Just for bragging rights."
            : payout === "all" ? `Pot: ${pot} 🍿 with ${total} in, all to the winner.`
            : `Pot: ${pot} 🍿 with ${total} in: ${prizes(pot, payout).map((n, i) => `${MEDALS[i + 1]} ${n}`).join(", ")}.`}
        </p>
        <span className="share-label">Seeds</span>
        <Segmented label="Seeds" options={SEEDINGS} value={seeding} onChange={v => v && setSeeding(v)} />
        <span className="share-label">Entries close</span>
        <Segmented label="Entries close" options={Object.entries(settings.deadlines).map(([status, label]) => ({ status, label }))}
                   value={deadline} onChange={v => v && setDeadline(v)} />
        <p className="ui-hint">It starts sooner if everyone answers and the seats fill, or when you start it.</p>
        <span className="share-label">Each match stays open</span>
        <Segmented label="Each match stays open" options={Object.entries(options.match_times).map(([status, label]) => ({ status, label }))}
                   value={matchTime} onChange={v => v && setMatchTime(v)} />
        <span className="share-label">Scores</span>
        <Segmented label="Scores" options={REVEALS} value={reveal} onChange={v => v && setReveal(v)} />
        <span className="share-label">Who sees it</span>
        <Segmented label="Who sees it" options={SEEN} value={seen} onChange={v => v && setSeen(v)} />
        <p className="ui-hint">{seen === "club" ? `On Play and the Feed${settings.backing ? "; members can back someone to win it all" : ""}.` : "Only the players."}</p>
        {seen === "club" && <AnnounceChoice announce={announce} />}
        {error && <p className="share-error">{error}</p>}
        <div className="share-sheet-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || total < lo || stake > settings.available} onClick={create}>
            {busy ? "Setting up…" : "🏆 Send the invites"}
          </button>
        </div>
      </div>
    </Sheet>
  );
}

// One match: its two sides (a bye, or "TBD" until known), the scores once
// shown, the winner in gold — and a link to play or watch it.
function Match({ m, viewerId }) {
  const side = s => {
    if (!s) return <span className="tour-side tbd">TBD</span>;
    if (s.bye) return <span className="tour-side bye">bye</span>;
    const id = String(s.user.id);
    return (
      <span className={`tour-side${m.winner_id === s.user.id ? " won" : m.winner_id ? " lost" : ""}`}>
        <span className="tour-seed">{s.seed}</span>
        <span className="tour-name">{s.user.name}</span>
        {m.scores[id] != null && <strong className="tour-score">{m.scores[id]}</strong>}
        {m.status === "open" && m.played[id] === "finished" && m.scores[id] == null && <span title="Played" aria-label="played">✅</span>}
      </span>
    );
  };
  const mine = m.status === "open" && [m.a, m.b].some(s => s?.user?.id === viewerId) && m.played[String(viewerId)] === "accepted";
  return (
    <div className={`tour-match status-${m.status}${mine ? " mine" : ""}`}>
      <span className="tour-match-head">
        <span>{m.label}</span>
        {m.challenge_id ? <Link to={`/challenges/${m.challenge_id}`}>{mine ? "▶ Play" : m.status === "open" ? "Watch" : "Results"}</Link>
          : <span className="ui-hint">{m.status === "bye" ? "through" : "waiting"}</span>}
      </span>
      {side(m.a)}
      {side(m.b)}
      {m.status === "open" && m.closes_at && <span className="tour-match-foot">closes {untilText(m.closes_at)}</span>}
    </div>
  );
}

function Rounds({ title, matches, viewerId }) {
  const rounds = [...new Set(matches.map(m => m.round))];
  return (
    <section className="tour-section" aria-label={title}>
      <h3 className="pv-past-title">{title}</h3>
      <div className="tour-rounds">
        {rounds.map(r => (
          <div key={r} className="tour-round">
            {matches.filter(m => m.round === r).map(m => <Match key={m.key} m={m} viewerId={viewerId} />)}
          </div>
        ))}
      </div>
    </section>
  );
}

// The bracket: winners' and losers' brackets and the grand final — or the
// round robin's standings, its matches and the final.
export function Bracket({ t, viewerId }) {
  const b = t.bracket;
  if (t.status === "cancelled" && !t.started_at) return null;     // called off before it started: no bracket to show
  if (t.status === "open") {
    return <p className="ui-hint">The bracket is drawn when entries close: {t.min_players}–{t.max_players} players, seeded {t.seeding === "record" ? "by challenge record" : "at random"}.</p>;
  }
  if (t.format === "round_robin") {
    return (
      <>
        {t.standings && (
          <section className="tour-section" aria-label="Standings">
            <h3 className="pv-past-title">Standings</h3>
            <table className="ch-table">
              <thead><tr><th scope="col">#</th><th scope="col">Player</th><th scope="col">Won</th><th scope="col">Lost</th><th scope="col">🍿 scored</th></tr></thead>
              <tbody>
                {t.standings.map((r, i) => (
                  <tr key={r.user_id} className={i < 2 ? "right" : ""}>
                    <td>{i + 1}</td><th scope="row">{r.user?.name}</th><td>{r.won}</td><td>{r.lost}</td><td>{r.score}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="ui-hint">The top two meet in the final.</p>
          </section>
        )}
        <Rounds title="Final" matches={b.final} viewerId={viewerId} />
        <Rounds title="Round robin" matches={b.league} viewerId={viewerId} />
      </>
    );
  }
  return (
    <>
      <Rounds title="Grand final" matches={b.final} viewerId={viewerId} />
      <Rounds title="Winners' bracket" matches={b.winners} viewerId={viewerId} />
      {b.losers.length > 0 && <Rounds title="Losers' bracket" matches={b.losers} viewerId={viewerId} />}
    </>
  );
}

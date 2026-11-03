import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { changed, getJson, send } from "../api";
import PageHeader from "../ui/PageHeader";
import Panel from "../ui/Panel";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import Loading, { LoadError } from "../ui/Loading";
import { dayDateAt } from "../dates";
import { ROUNDS } from "../components/QuizGames";
import { untilText } from "../components/PollList";
import { Backing, CHALLENGE_STATUS, STATUS_ICONS, STATUS_WORDS, lengthLine, netClass, signed, stakesLine } from "../components/Challenges";
import "./Challenges.css";

const secondsLeft = iso => Math.max(0, Math.ceil((new Date(iso) - Date.now()) / 1000));

// The 30 seconds a challenge question gets. When it runs out, the page asks
// again: the server counts it as a miss and moves on.
function Clock({ endsAt, onUp }) {
  const [left, setLeft] = useState(() => secondsLeft(endsAt));
  useEffect(() => {
    setLeft(secondsLeft(endsAt));
    const t = setInterval(() => {
      const s = secondsLeft(endsAt);
      setLeft(s);
      if (s <= 0) { clearInterval(t); onUp(); }
    }, 250);
    return () => clearInterval(t);
  }, [endsAt]);
  return (
    <div className={`ch-clock${left <= 5 ? " low" : ""}`} role="timer" aria-label={`${left} seconds left`}>
      <span className="ch-clock-bar"><span style={{ width: `${Math.min(100, (left / 30) * 100)}%` }} /></span>
      <strong>⏱️ {left}s</strong>
    </div>
  );
}

// Your turn: one question at a time, shown the way the solo games show it.
function Ballot({ apiBase, q, busy, onAnswer, onTimeUp }) {
  const Round = ROUNDS[q.kind];
  return (
    <Panel tone="gold" className="ch-ballot" title={`${q.emoji} ${q.label}`}
           hint={`${q.rounds > 1 ? `Game ${q.round + 1} of ${q.rounds} · ` : ""}Question ${q.q + 1}${q.kind === "higher_lower" ? "" : ` of ${q.of}`} · ${q.score} 🍿 scored`}>
      {q.ends_at && <Clock endsAt={q.ends_at} onUp={onTimeUp} />}
      <Round r={q} busy={busy} apiBase={apiBase} onAnswer={onAnswer} />
    </Panel>
  );
}

// Each game, question by question, everyone side by side.
function Results({ c }) {
  const players = c.players.filter(p => ["finished", "forfeit"].includes(p.status));
  const name = id => players.find(p => p.user.id === id)?.user.name;
  return c.results.map(game => (
    <Panel key={game.round} as="div" className="ch-results" title={`${c.gauntlet ? `Game ${game.round + 1}: ` : ""}${game.emoji} ${game.label}`}
           hint={game.winners.length ? `Won by ${game.winners.map(name).join(" and ")}` : "Nobody scored"}>
      <div className="ch-table-wrap">
        <table className="ch-table">
          <thead><tr><th scope="col">Question</th>{players.map(p => <th key={p.user.id} scope="col">{p.user.name}</th>)}</tr></thead>
          <tbody>
            {game.questions.map(row => (
              <tr key={row.q}>
                <th scope="row">{row.summary}</th>
                {players.map(p => {
                  const a = row.answers[String(p.user.id)];
                  return <td key={p.user.id} className={a?.right ? "right" : a ? "wrong" : ""}>
                    {!a ? "—" : a.timeout ? "⏱️" : a.right ? `✓ +${a.points}` : "✗"}
                  </td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  ));
}

// A challenge (/challenges/<id>): who's in and what's on the line, your turn
// (with a 30-second clock), backing a player, and — once it's decided — the
// results, game by game, with a rematch.
export default function ChallengePage({ apiBase }) {
  const { challengeId } = useParams();
  const navigate = useNavigate();
  const base = `${apiBase}/api/challenges/${challengeId}`;
  const [c, setC] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [q, setQ] = useState(null);                  // the question you're on
  const [last, setLast] = useState(null);            // your final answer, once you've played
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => getJson(base, { cache: false }).then(d => { setC(d); setLoadError(null); }).catch(setLoadError);
  useEffect(() => { setC(null); setQ(null); setLast(null); load(); }, [challengeId]);
  useEffect(() => {                                  // others accepting, playing, backing
    if (!c || c.status !== "open" || q) return undefined;
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [c?.status, q, challengeId]);

  async function act(action, body = {}) {
    setBusy(true);
    setError("");
    try {
      const d = await send(`${base}/${action}`, "POST", body);
      changed("kernels");
      if (action === "rematch") navigate(`/challenges/${d.id}`);
      else setC(d);
    } catch (e) { setError(e.data?.error || "That didn't work — try again."); }
    finally { setBusy(false); }
  }

  async function play() {
    setError("");
    try {
      const d = await getJson(`${base}/play`, { cache: false });
      setC(prev => ({ ...prev, ...d.challenge }));
      setQ(d.question);
      if (!d.question) changed("kernels");
    } catch (e) { setError(e.data?.error || "Couldn't open your turn — try again."); }
  }

  async function answer(choice) {
    setBusy(true);
    setError("");
    try {
      const d = await send(`${base}/play`, "POST", { choice });
      setC(prev => ({ ...prev, ...d.challenge }));
      setQ(d.question);
      if (!d.question) { setLast(d.answered); changed("kernels"); }
    } catch (e) { setError(e.data?.error || "Couldn't save that — try again."); play(); }
    finally { setBusy(false); }
  }

  if (loadError) return <div className="page"><LoadError what="this challenge" onRetry={load} /></div>;
  if (!c) return <div className="page"><Loading context="games" /></div>;
  const y = c.you;
  const title = c.gauntlet ? "🧩 Gauntlet" : `${c.emoji} ${c.label}`;
  const backable = c.players.filter(p => ["accepted", "invited"].includes(p.status));
  const tour = c.tournament;
  return (
    <div className="page challenge-page">
      <PageHeader title={tour ? `${tour.match}: ${title}` : title} tour="challenge"
                  back={tour ? { to: `/tournaments/${tour.id}`, label: "The bracket" } : { to: "/play#challenges", label: "Play" }}
                  meta={[{ label: CHALLENGE_STATUS[c.status], gold: c.status === "open" }, { label: lengthLine(c) },
                         { label: tour ? tour.title : stakesLine(c) }, { label: c.reveal === "live" ? "Scores live" : "Scores sealed" },
                         { label: c.visibility === "club" ? "The club sees it" : "Just the players" }]} />
      {tour && <p className="pv-desc">A match in the <Link to={`/tournaments/${tour.id}`}>{tour.title.replace("🏆 ", "")}</Link> tournament — one winner goes on; a tie goes to the faster player, then the higher seed.</p>}
      {c.gauntlet && <p className="pv-desc">{c.rounds.map(r => `${r.emoji} ${r.label}`).join(" → ")} · most games won takes it</p>}
      {c.status === "open" && (
        <p className="pv-closes">⏰ Closes {dayDateAt(c.closes_at)} — {untilText(c.closes_at)} · started by {c.created_by.name}</p>
      )}
      <p className="ui-hint ch-kernels-note">The kernels you score decide the winner{tour ? "." : `; the pot${c.backing.allowed ? " and backing" : ""} is what changes hands.`}</p>

      {q ? (
        <Ballot apiBase={apiBase} q={q} busy={busy} onAnswer={answer} onTimeUp={play} />
      ) : (
        <section className="pv-manage ch-actions" aria-label="What you can do">
          <div className="pv-manage-row">
            {y.can_accept && <>
              <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act("respond", { accept: true })}>
                ✓ Accept{c.stake ? ` (${c.stake} 🍿)` : ""}
              </button>
              <button className="btn btn-sm" disabled={busy} onClick={() => act("respond", { accept: false })}>Decline</button>
            </>}
            {y.can_join && <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act("join")}>🪑 Take a seat{c.stake ? ` (${c.stake} 🍿)` : ""}</button>}
            {y.can_play && <button className="btn btn-sm btn-primary" disabled={busy} onClick={play}>▶ Play now</button>}
            {y.can_rematch && !c.rematch && <>
              <button className="btn btn-sm" disabled={busy} onClick={() => act("rematch", { double: false })}>🔁 Rematch</button>
              <button className="btn btn-sm" disabled={busy} onClick={() => act("rematch", { double: true })}>🔁 Double or nothing</button>
            </>}
            {c.rematch && <Link className="btn btn-sm" to={`/challenges/${c.rematch}`}>See the rematch →</Link>}
            {y.can_end && <button className="btn btn-sm btn-ghost" disabled={busy} onClick={() => act("end")}>End it now</button>}
            {y.can_cancel && <button className="btn btn-sm btn-ghost pv-danger" disabled={busy}
                                     onClick={() => window.confirm("Call it off? Nobody's stake changes hands.") && act("cancel")}>Call it off</button>}
          </div>
          {y.can_play && <p className="ui-hint">30 seconds a question — once you start, the clock runs.</p>}
          {last && <p className="quiz-result" role="status">✅ You've played{c.status === "open" ? " — the results come once everyone has." : "!"}</p>}
          {y.status === "finished" && !last && c.status === "open" && <p className="ui-hint">You've played. Waiting on the others.</p>}
        </section>
      )}
      {error && <p className="share-error" role="alert">{error}</p>}

      <Panel as="div" className="ch-players" title="Players" kicker>
        <ul className="ch-player-list">
          {c.players.map(p => (
            <li key={p.user.id} className={p.winner ? "winner" : ""}>
              <Avatar user={p.user} size={28} link />
              <PersonLink user={p.user} className="ch-player-name" />
              <span className="ch-player-status">{STATUS_ICONS[p.status]} {STATUS_WORDS[p.status]}{p.seat ? " · took a seat" : ""}</span>
              {p.score != null && <strong className="ch-player-score">
                {p.winner && "🏆 "}{c.gauntlet && p.rounds_won != null ? `${p.rounds_won} game${p.rounds_won === 1 ? "" : "s"} · ` : ""}{p.score} 🍿 scored
              </strong>}
              {p.net != null && c.stake > 0 && <span className={netClass(p.net)}>{signed(p.net)} 🍿</span>}
              {p.backers > 0 && <span className="ui-hint">{p.backers} backing</span>}
            </li>
          ))}
        </ul>
        {c.seats_left > 0 && c.status === "open" && <p className="ui-hint">🪑 {c.seats_left} open seat{c.seats_left === 1 ? "" : "s"} — anyone in the club can take one.</p>}
      </Panel>

      {c.backing.allowed && !tour && (
        <Panel as="div" className="ch-backing" title="🍿 Backing" kicker
               hint={`${c.backing.total} 🍿 from ${c.backing.count} member${c.backing.count === 1 ? "" : "s"}${c.backing.open ? " · open until the first player finishes" : " · closed"}`}>
          <Backing backing={c.backing} players={backable} available={c.available} busy={busy}
                   onBack={y.can_back ? (who, amount) => act("back", { user_id: who, amount }) : null} />
        </Panel>
      )}

      {c.status === "done" && c.results && <Results c={c} />}
      {c.status === "cancelled" && <p className="pv-empty">Called off — nothing changed hands.</p>}
    </div>
  );
}

import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { changed, getJson, send } from "../api";
import PageHeader from "../ui/PageHeader";
import Panel from "../ui/Panel";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import Loading, { LoadError } from "../ui/Loading";
import { dayDateAt } from "../dates";
import { untilText } from "../components/PollList";
import { Backing, STATUS_ICONS, STATUS_WORDS, netClass, signed } from "../components/Challenges";
import { Bracket, MEDALS, TOURNAMENT_STATUS } from "../components/Tournaments";
import "./Challenges.css";

// A tournament (/tournaments/<id>): who's in and the prizes, joining or
// starting it, your match (played on its challenge page), backing someone to
// win it all, and the bracket — winners' and losers' brackets and the grand
// final, or the round robin's standings and its final.
export default function TournamentPage({ apiBase, user }) {
  const { tournamentId } = useParams();
  const base = `${apiBase}/api/tournaments/${tournamentId}`;
  const [t, setT] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = () => getJson(base, { cache: false }).then(d => { setT(d); setLoadError(null); }).catch(setLoadError);
  useEffect(() => { setT(null); load(); }, [tournamentId]);
  useEffect(() => {                                  // entries, matches being played, backing
    if (!t || !["open", "running"].includes(t.status)) return undefined;
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [t?.status, tournamentId]);

  async function act(action, body = {}) {
    setBusy(true);
    setError("");
    try {
      setT(await send(`${base}/${action}`, "POST", body));
      changed("kernels");
    } catch (e) { setError(e.data?.error || "That didn't work. Try again."); }
    finally { setBusy(false); }
  }

  if (loadError) return <div className="page"><LoadError what="this tournament" onRetry={load} /></div>;
  if (!t) return <div className="page"><Loading context="games" /></div>;
  const y = t.you;
  const people = t.players.filter(p => !["declined", "expired"].includes(p.status));
  const ranked = [...people].sort((a, b) => (a.place || 9) - (b.place || 9) || (a.seed || 99) - (b.seed || 99));
  const inIt = y.status === "accepted" && ["open", "running"].includes(t.status);
  const anything = y.can_accept || y.can_join || y.match || y.can_start || y.can_cancel || inIt;
  return (
    <div className="page tournament-page">
      <PageHeader title={t.title} back={{ to: "/play/challenges", label: "Play" }} tour="tournament"
                  meta={[{ label: TOURNAMENT_STATUS[t.status], gold: ["open", "running"].includes(t.status) }, { label: t.games_line },
                         { label: t.stake ? `${t.stake} 🍿 entry, pot ${t.pot} 🍿` : "For bragging rights" },
                         t.stake ? { label: t.payout_label } : null, { label: `Each match: ${t.match_time_label.toLowerCase()}` },
                         { label: t.visibility === "club" ? "The club sees it" : "Just the players" }].filter(Boolean)} />
      {t.status === "open" && (
        <p className="pv-closes">⏰ Entries close {dayDateAt(t.closes_at)} ({untilText(t.closes_at)}). Started by {t.created_by.name}.</p>
      )}
      {t.stake > 0 && t.status !== "cancelled" && (
        <p className="ui-hint ch-kernels-note">
          Prizes: {t.prizes.map((n, i) => `${MEDALS[i + 1]} ${n} 🍿`).join(", ")}{t.status === "open" ? " (as it stands: more players, a bigger pot)" : ""}.
          Each match is a 1-v-1 challenge; a tie goes to the faster player, then the higher seed.
        </p>
      )}

      {anything && <section className="pv-manage ch-actions" aria-label="What you can do">
        <div className="pv-manage-row">
          {y.can_accept && <>
            <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act("respond", { accept: true })}>✓ I'm in{t.stake ? ` (${t.stake} 🍿)` : ""}</button>
            <button className="btn btn-sm" disabled={busy} onClick={() => act("respond", { accept: false })}>Decline</button>
          </>}
          {y.can_join && <button className="btn btn-sm btn-primary" disabled={busy} onClick={() => act("join")}>🪑 Take a seat{t.stake ? ` (${t.stake} 🍿)` : ""}</button>}
          {y.match && <Link className="btn btn-sm btn-primary" to={`/challenges/${y.match}`}>▶ Play your match</Link>}
          {y.can_start && <button className="btn btn-sm" disabled={busy} onClick={() => act("start")}>🏁 Start it now</button>}
          {y.can_cancel && <button className="btn btn-sm btn-ghost pv-danger" disabled={busy}
                                   onClick={() => window.confirm("Call it off? Nobody's entry changes hands.") && act("cancel")}>Call it off</button>}
        </div>
        {y.status === "accepted" && t.status === "open" && <p className="ui-hint">You're in. Your first match opens once it starts.</p>}
        {t.status === "running" && y.status === "accepted" && !y.match && <p className="ui-hint">Nothing for you to play right now. Your next match opens as soon as your opponent is known.</p>}
      </section>}
      {error && <p className="share-error" role="alert">{error}</p>}
      {t.status === "cancelled" && <p className="pv-empty">Called off. Nothing changed hands.</p>}

      <Panel as="div" className="ch-players" title="Players" kicker>
        <ul className="ch-player-list">
          {ranked.map(p => (
            <li key={p.user.id} className={p.place === 1 ? "winner" : ""}>
              <Avatar user={p.user} size={28} link />
              <PersonLink user={p.user} className="ch-player-name" />
              <span className="ch-player-status">
                {p.seed ? `seed ${p.seed}` : `${STATUS_ICONS[p.status]} ${STATUS_WORDS[p.status]}`}{p.seat ? ", took a seat" : ""}
                {t.status === "running" && !p.alive ? ", out" : ""}
              </span>
              {p.place && <strong className="ch-player-score">{MEDALS[p.place]} {["", "Champion", "Second", "Third"][p.place]}</strong>}
              {p.net != null && t.stake > 0 && <span className={netClass(p.net)}>{signed(p.net)} 🍿</span>}
              {p.backers > 0 && <span className="ui-hint">{p.backers} backing</span>}
            </li>
          ))}
        </ul>
        {t.seats_left > 0 && t.status === "open" && <p className="ui-hint">🪑 {t.seats_left} open seat{t.seats_left === 1 ? "" : "s"}. Anyone in the club can take one.</p>}
      </Panel>

      {t.backing.allowed && (t.backing.open || t.backing.count > 0) && (
        <Panel as="div" className="ch-backing" title="🍿 Back someone to win it all" kicker
               hint={`${t.backing.total} 🍿 from ${t.backing.count} member${t.backing.count === 1 ? "" : "s"}${t.backing.open ? ", open until the first match is decided" : ", closed"}`}>
          <Backing backing={t.backing} players={people.filter(p => p.status === "accepted")} available={t.available} busy={busy}
                   onBack={y.can_back ? (who, amount) => act("back", { user_id: who, amount }) : null} />
        </Panel>
      )}

      <div className="tour-bracket">
        <Bracket t={t} viewerId={user?.id} />
      </div>
    </div>
  );
}

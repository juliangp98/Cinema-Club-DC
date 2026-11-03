import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { changed, send, useJson } from "../api";
import Avatar from "../ui/Avatar";
import Sheet, { SheetTitle } from "../ui/Sheet";
import ToggleChip from "../ui/ToggleChip";
import Loading, { LoadError } from "../ui/Loading";
import { Segmented } from "../ui/TicketRow";
import { useShell } from "../shell/AppShell";
import { untilText } from "./PollList";
import "../pages/Challenges.css";

// Challenges (challenges.py): members play the same set of games against each
// other, kernels on the line, others back a player. Play's Challenges section
// and the "new challenge" sheet live here; each challenge has its own page
// (pages/ChallengePage.jsx); the Feed shows club-visible ones as cards.

export const STATUS_ICONS = { invited: "✉️", accepted: "🎮", finished: "✅", forfeit: "💤", declined: "✖️", expired: "⌛" };
export const STATUS_WORDS = { invited: "invited", accepted: "in", finished: "played", forfeit: "didn't play",
                              declined: "declined", expired: "never answered" };
export const CHALLENGE_STATUS = { open: "Open", done: "Decided", cancelled: "Called off" };
export const signed = n => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
export const stakesLine = c => (c.stake ? `${c.stake} 🍿 each · pot ${c.pot} 🍿` : "For bragging rights");
export const lengthLine = c => (c.gauntlet ? `${c.rounds.length} games` : c.questions ? `${c.questions} questions` : "one run");

// The one thing to do with it now.
function nextStep(c) {
  const y = c.you;
  if (y.can_accept) return { label: "Accept or decline", gold: true };
  if (y.can_play) return { label: "▶ Play", gold: true };
  if (y.can_join) return { label: "🪑 Take a seat" };
  if (y.can_back) return { label: "🍿 Back a player" };
  return { label: c.status === "done" ? "See results" : "Watch" };
}

// A challenge in a list (Play) or the Feed: its games, who's in, what's on the line.
export function ChallengeCard({ c, onOpen }) {
  const step = nextStep(c);
  const shown = c.players.filter(p => !["declined", "expired"].includes(p.status));
  return (
    <article className={`ch-card status-${c.status}`}>
      <button type="button" className="ch-card-main" onClick={onOpen}>
        <span className={`ui-badge ${{ open: "go", done: "gold" }[c.status] || ""}`}>{CHALLENGE_STATUS[c.status]}</span>
        <span className="ch-card-title">{c.gauntlet ? c.games_line : `${c.emoji} ${c.label}`}</span>
        <span className="ch-card-meta">
          {c.created_by.name} · {lengthLine(c)} · {stakesLine(c)}
          {c.status === "open" && <> · <strong className="pv-card-closes">closes {untilText(c.closes_at)}</strong></>}
          {c.backing.count > 0 && ` · ${c.backing.total} 🍿 backing`}
        </span>
        <span className="ch-people">
          {shown.map(p => (
            <span key={p.user.id} className={`ch-person${p.winner ? " winner" : ""}`} title={`${p.user.name}: ${STATUS_WORDS[p.status]}`}>
              <Avatar user={p.user} size={22} />
              <span>{p.winner && "🏆 "}{p.user.name}</span>
              <span aria-hidden="true">{STATUS_ICONS[p.status]}</span>
              {p.score != null && <strong>{c.gauntlet && p.rounds_won != null ? `${p.rounds_won}g` : p.score}</strong>}
            </span>
          ))}
        </span>
      </button>
      <button type="button" className={`btn btn-sm${step.gold ? " btn-primary" : ""}`} onClick={onOpen}>{step.label}</button>
    </article>
  );
}

const STAKES = [0, 1, 2, 3, 5, 10, 15, 20, 25, 50];
const REVEALS = [{ status: "sealed", label: "Sealed till the end" }, { status: "live", label: "Live" }];
const SEEN = [{ status: "club", label: "The club" }, { status: "players", label: "Just the players" }];
const MODES = [{ status: "one", label: "One game" }, { status: "gauntlet", label: "🧩 Gauntlet" }];
const RANDOM = { kind: "random", emoji: "🎲", label: "Random" };

// The game picker: each of the club's games, or Random.
function GamePick({ games, value, onChange, label }) {
  return (
    <select className="share-input ch-game-select" value={value} onChange={e => onChange(e.target.value)} aria-label={label}>
      {[RANDOM, ...games].map(g => <option key={g.kind} value={g.kind}>{g.emoji} {g.label}</option>)}
    </select>
  );
}

// "⚔️ Challenge someone": the games (one, or a gauntlet — each picked or
// random, 1–10 questions each), who, open seats, the stake, the deadline,
// sealed or live scores, who sees it, and — the creator's call on the spot —
// whether it's posted in the club's Discord.
export function NewChallenge({ apiBase, groupId, settings, viewerId, rematchOf, onClose, onMade }) {
  const shell = useShell();
  const slug = shell?.group?.slug;
  const { data: members } = useJson(slug ? `${apiBase}/api/groups/${slug}/members` : null);
  const others = (members || []).filter(m => m.status === "active" && m.user && m.user.id !== viewerId);
  const canAnnounce = !!(shell?.group?.discord && shell?.user?.discord_clubs?.includes(shell.group.id));
  const [mode, setMode] = useState("one");
  const [kinds, setKinds] = useState(["random", "random", "random"]);
  const [questions, setQuestions] = useState(5);
  const [opponents, setOpponents] = useState([]);
  const [seats, setSeats] = useState(0);
  const [stake, setStake] = useState(Math.min(3, settings.max_stake, settings.available));
  const [deadline, setDeadline] = useState("tonight");
  const [reveal, setReveal] = useState("sealed");
  const [seen, setSeen] = useState("club");
  const [post, setPost] = useState(() => (shell?.user?.share_prefs?.challenge === "never" ? "none" : "now"));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const count = mode === "one" ? 1 : kinds.length;
  const stakes = STAKES.filter(n => n <= settings.max_stake);
  const players = 1 + opponents.length + seats;
  const toggle = id => setOpponents(o => (o.includes(id) ? o.filter(x => x !== id) : o.length + seats < settings.max_players - 1 ? [...o, id] : o));
  const setKind = (i, k) => setKinds(ks => ks.map((x, j) => (j === i ? k : x)));
  const games = n => setKinds(ks => Array.from({ length: n }, (_, i) => ks[i] || "random"));

  async function create() {
    setBusy(true);
    setError("");
    try {
      const made = await send(`${apiBase}/api/challenges`, "POST", {
        group_id: groupId, rounds: kinds.slice(0, count).map(kind => ({ kind, questions })), opponents, seats, stake,
        deadline, reveal, visibility: seen, ...(canAnnounce && seen === "club" ? { announce: post } : {}),
      });
      changed("kernels");                      // a stake is on the line now
      onMade(made);
    } catch (e) { setError(e.data?.error || "Couldn't start that — try again."); }
    finally { setBusy(false); }
  }

  return (
    <Sheet label="New challenge" onClose={onClose} className="share-sheet ch-sheet">
      <div className="share-sheet-body">
        <SheetTitle>{rematchOf ? "Rematch" : "⚔️ New challenge"}</SheetTitle>
        <span className="share-label">Games</span>
        <Segmented label="Games" options={MODES} value={mode} onChange={v => v && setMode(v)} />
        {mode === "one" ? (
          <GamePick games={settings.games} value={kinds[0]} onChange={k => setKind(0, k)} label="Game" />
        ) : (
          <div className="ch-gauntlet">
            <label className="share-label" htmlFor="ch-count">How many games</label>
            <input id="ch-count" type="number" className="share-input ch-number" min={2} max={settings.max_rounds} value={kinds.length}
                   onChange={e => games(Math.max(2, Math.min(settings.max_rounds, Number(e.target.value) || 2)))} />
            {kinds.map((k, i) => <GamePick key={i} games={settings.games} value={k} onChange={v => setKind(i, v)} label={`Game ${i + 1}`} />)}
            <button type="button" className="share-link" onClick={() => setKinds(ks => ks.map(() => "random"))}>🎲 Make them all random</button>
            <p className="ui-hint">Each game's top scorer wins it; most games won takes the gauntlet (then kernels scored, then speed).</p>
          </div>
        )}
        <label className="share-label" htmlFor="ch-questions">Questions in {count > 1 ? "each game" : "the game"}</label>
        <input id="ch-questions" type="number" className="share-input ch-number" min={settings.questions[0]} max={settings.questions[1]}
               value={questions} onChange={e => setQuestions(Math.max(settings.questions[0], Math.min(settings.questions[1], Number(e.target.value) || 1)))} />
        <p className="ui-hint">Higher or lower is always one run: a miss ends it. 30 seconds a question.</p>

        <span className="share-label">Who</span>
        {members ? (
          <div className="ch-who">
            {others.map(m => (
              <ToggleChip key={m.user.id} on={opponents.includes(m.user.id)} onClick={() => toggle(m.user.id)}>
                <Avatar user={m.user} size={18} /> {m.user.name}
              </ToggleChip>
            ))}
          </div>
        ) : <Loading compact />}
        <label className="share-label" htmlFor="ch-seats">Open seats (anyone in the club can take one)</label>
        <input id="ch-seats" type="number" className="share-input ch-number" min={0} max={Math.min(settings.max_seats, settings.max_players - 1 - opponents.length)}
               value={seats} onChange={e => setSeats(Math.max(0, Math.min(settings.max_seats, settings.max_players - 1 - opponents.length, Number(e.target.value) || 0)))} />

        <span className="share-label">Stake (each player, into the pot)</span>
        <Segmented label="Stake" options={stakes.map(n => ({ status: String(n), label: n ? `${n} 🍿` : "None" }))}
                   value={String(stake)} onChange={v => v != null && setStake(Number(v))} />
        <p className="ui-hint">
          {stake > settings.available ? `You have ${settings.available} 🍿 to put in.` : stake ? `Pot: ${stake * players} 🍿 if everyone's in.` : "Just for bragging rights."}
        </p>
        <span className="share-label">Closes</span>
        <Segmented label="Closes" options={Object.entries(settings.deadlines).map(([status, label]) => ({ status, label }))}
                   value={deadline} onChange={v => v && setDeadline(v)} />
        <span className="share-label">Scores</span>
        <Segmented label="Scores" options={REVEALS} value={reveal} onChange={v => v && setReveal(v)} />
        <p className="ui-hint">{reveal === "live" ? "Each score shows as that player finishes." : "Nobody sees a score until everyone has played."}</p>
        <span className="share-label">Who sees it</span>
        <Segmented label="Who sees it" options={SEEN} value={seen} onChange={v => v && setSeen(v)} />
        <p className="ui-hint">{seen === "club" ? `On Play and the Feed${settings.backing ? "; members can back a player" : ""}.` : "Only the players."}</p>
        {canAnnounce && seen === "club" && (
          <>
            <span className="share-label">Discord</span>
            <Segmented label="Discord" options={[{ status: "now", label: "Post it in the channel" }, { status: "none", label: "Don't post" }]}
                       value={post} onChange={v => v && setPost(v)} />
          </>
        )}
        {error && <p className="share-error">{error}</p>}
        <div className="share-sheet-foot">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={busy || (!opponents.length && !seats) || stake > settings.available} onClick={create}>
            {busy ? "Starting…" : "⚔️ Send the challenge"}
          </button>
        </div>
      </div>
    </Sheet>
  );
}

// Play → Challenges: waiting for you, live in the club, recently decided.
export default function ChallengesSection({ apiBase, groupId, viewerId, canRun }) {
  const navigate = useNavigate();
  const { data, error, reload } = useJson(groupId ? `${apiBase}/api/challenges?group_id=${groupId}` : null, { refreshOn: "kernels" });
  const [making, setMaking] = useState(false);
  const lists = useMemo(() => {
    const all = data?.challenges || [];
    const yours = all.filter(c => c.status === "open" && (c.you.can_accept || c.you.can_play));
    return [["Waiting for you", yours], ["Live in the club", all.filter(c => c.status === "open" && !yours.includes(c))],
            ["Decided", all.filter(c => c.status !== "open")]];
  }, [data]);
  if (!data) return error ? <LoadError what="challenges" onRetry={reload} /> : <Loading context="games" compact />;
  if (!data.enabled) {
    return canRun ? (
      <p className="ui-note">⚔️ Challenges are off. <Link to="/club?tab=settings#settings-games">Turn them on in Club settings</Link></p>
    ) : <p className="ui-note">⚔️ Challenges aren't on in this club yet.</p>;
  }
  const open = c => navigate(`/challenges/${c.id}`);
  return (
    <>
      <div className="ch-head">
        <button type="button" className="btn btn-sm btn-primary" onClick={() => setMaking(true)} disabled={!data.games.length}>⚔️ Challenge someone</button>
        <span className="ui-hint">You have {data.available} 🍿 to put in{data.on_the_line ? ` · ${data.on_the_line} 🍿 on the line` : ""}.</span>
      </div>
      {lists.every(([, l]) => !l.length) && <p className="pv-empty">No challenges yet — start one.</p>}
      {lists.map(([title, list]) => list.length > 0 && (
        <div key={title}>
          <h3 className="pv-past-title">{title}</h3>
          <div className="pv-cards">{list.map(c => <ChallengeCard key={c.id} c={c} onOpen={() => open(c)} />)}</div>
        </div>
      ))}
      {making && <NewChallenge apiBase={apiBase} groupId={groupId} settings={data} viewerId={viewerId}
                               onClose={() => setMaking(false)} onMade={c => navigate(`/challenges/${c.id}`)} />}
    </>
  );
}

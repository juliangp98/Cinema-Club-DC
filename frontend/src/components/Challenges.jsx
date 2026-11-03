import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { changed, send, useJson } from "../api";
import Avatar from "../ui/Avatar";
import Sheet, { SheetTitle } from "../ui/Sheet";
import ToggleChip from "../ui/ToggleChip";
import Loading, { LoadError } from "../ui/Loading";
import { Segmented } from "../ui/TicketRow";
import Select from "../ui/Select";
import { useShell } from "../shell/AppShell";
import { untilText } from "./PollList";
import { ChallengeStats, ScoutPicks } from "./ChallengeScout";
import { NewTournament, TournamentCard } from "./Tournaments";
import "../pages/Challenges.css";

// Challenges (challenges.py): members play the same set of games against each
// other, kernels on the line, others back a player. Play's Challenges arena
// (stats, who to challenge — components/ChallengeScout.jsx — then yours, the
// club's and tournaments: components/Tournaments.jsx) and the "new
// challenge" sheet live here; each challenge has its own page
// (pages/ChallengePage.jsx); the Feed shows club-visible ones as cards.

export const STATUS_ICONS = { invited: "✉️", accepted: "🎮", finished: "✅", forfeit: "💤", declined: "✖️", expired: "⌛" };
export const STATUS_WORDS = { invited: "invited", accepted: "in", finished: "played", forfeit: "didn't play",
                              declined: "declined", expired: "never answered" };
export const CHALLENGE_STATUS = { open: "Open", done: "Decided", cancelled: "Called off" };
export const signed = n => `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n)}`;
export const stakesLine = c => (c.stake ? `${c.stake} 🍿 each · pot ${c.pot} 🍿` : "For bragging rights");
export const lengthLine = c => (c.gauntlet ? `${c.rounds.length} games` : c.questions ? `${c.questions} questions` : "one run");
export const netClass = n => `ch-net ${n > 0 ? "up" : n < 0 ? "down" : ""}`;

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
        <span className="ch-card-title">
          {c.tournament && <>🏆 {c.tournament.match} · </>}{c.gauntlet ? c.games_line : `${c.emoji} ${c.label}`}
        </span>
        <span className="ch-card-meta">
          {c.tournament ? c.tournament.title : c.created_by.name} · {lengthLine(c)}{!c.tournament && ` · ${stakesLine(c)}`}
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

export const STAKES = [0, 1, 2, 3, 5, 10, 15, 20, 25, 50];
export const REVEALS = [{ status: "sealed", label: "Sealed till the end" }, { status: "live", label: "Live" }];
export const SEEN = [{ status: "club", label: "The club" }, { status: "players", label: "Just the players" }];
const MODES = [{ status: "one", label: "One game" }, { status: "gauntlet", label: "🧩 Gauntlet" }];
const RANDOM = { kind: "random", emoji: "🎲", label: "Random" };
const BETS = [1, 2, 3, 5, 10];

// The game picker: each of the club's games, or Random.
function GamePick({ games, value, onChange, label }) {
  return <Select label={label} value={value} onChange={onChange}
                 options={[RANDOM, ...games].map(g => ({ value: g.kind, label: `${g.emoji} ${g.label}` }))} />;
}

// The games: one, or a gauntlet of several (each picked or random), and the
// questions in each. `set` is {kinds, questions}; `count` how many are in play.
export function useGameSet(first = "random") {
  const [mode, setMode] = useState("one");
  const [kinds, setKinds] = useState([first, "random", "random"]);
  const [questions, setQuestions] = useState(5);
  const count = mode === "one" ? 1 : kinds.length;
  return { mode, setMode, kinds, setKinds, questions, setQuestions, count,
           rounds: kinds.slice(0, count).map(kind => ({ kind, questions })) };
}

export function GameSet({ set, settings, note }) {
  const { mode, setMode, kinds, setKinds, questions, setQuestions, count } = set;
  const setKind = (i, k) => setKinds(ks => ks.map((x, j) => (j === i ? k : x)));
  const games = n => setKinds(ks => Array.from({ length: n }, (_, i) => ks[i] || "random"));
  return (
    <>
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
      <p className="ui-hint">Higher or lower is always one run: a miss ends it. 30 seconds a question.{note ? ` ${note}` : ""}</p>
    </>
  );
}

// Members of the club to pick from (not you), as toggle chips.
export function PeoplePick({ apiBase, viewerId, picked, onToggle }) {
  const shell = useShell();
  const slug = shell?.group?.slug;
  const { data: members } = useJson(slug ? `${apiBase}/api/groups/${slug}/members` : null);
  const others = (members || []).filter(m => m.status === "active" && m.user && m.user.id !== viewerId);
  return members ? (
    <div className="ch-who">
      {others.map(m => (
        <ToggleChip key={m.user.id} on={picked.includes(m.user.id)} onClick={() => onToggle(m.user.id)}>
          <Avatar user={m.user} size={18} /> {m.user.name}
        </ToggleChip>
      ))}
    </div>
  ) : <Loading compact />;
}

// "Post it in the channel" — the creator's call on the spot (club-visible, in a club on Discord).
export function useAnnounce() {
  const shell = useShell();
  const canAnnounce = !!(shell?.group?.discord && shell?.user?.discord_clubs?.includes(shell.group.id));
  const [post, setPost] = useState(() => (shell?.user?.share_prefs?.challenge === "never" ? "none" : "now"));
  return { canAnnounce, post, setPost };
}

export function AnnounceChoice({ announce }) {
  return announce.canAnnounce && (
    <>
      <span className="share-label">Discord</span>
      <Segmented label="Discord" options={[{ status: "now", label: "Post it in the channel" }, { status: "none", label: "Don't post" }]}
                 value={announce.post} onChange={v => v && announce.setPost(v)} />
    </>
  );
}

// Backing a player (a challenge) or an entrant to win it all (a tournament):
// who, how much, and what you've put on so far.
export function Backing({ backing, players, available, busy, onBack, openUntil }) {
  const [who, setWho] = useState(null);
  const [amount, setAmount] = useState(2);
  const bets = BETS.filter(n => n <= Math.min(backing.max, available ?? 0));
  const mine = backing.mine;
  const name = id => players.find(p => p.user.id === id)?.user.name;
  return (
    <>
      {mine && (
        <p>You backed <strong>{name(mine.backing_id)}</strong> with {mine.amount} 🍿
          {mine.net != null && <> · <span className={netClass(mine.net)}>{signed(mine.net)} 🍿</span></>}</p>
      )}
      {onBack && (bets.length ? <>
        <Segmented label="Who wins?" options={players.map(p => ({ status: String(p.user.id), label: p.user.name }))}
                   value={who} onChange={setWho} />
        <Segmented label="How much" options={bets.map(n => ({ status: String(n), label: `${n} 🍿` }))}
                   value={String(Math.min(amount, bets[bets.length - 1]))} onChange={v => v && setAmount(Number(v))} />
        <button className="btn btn-sm btn-primary" disabled={busy || !who}
                onClick={() => onBack(Number(who), Math.min(amount, bets[bets.length - 1]))}>Back them</button>
        <p className="ui-hint">If they win, everyone who backed them splits the backing pot by what they put in. If nobody backed the winner, it all comes back.{openUntil ? ` Open ${openUntil}.` : ""}</p>
      </> : <p className="ui-hint">You don't have kernels free to back anyone right now.</p>)}
    </>
  );
}

// "⚔️ Challenge someone": the games (one, or a gauntlet — each picked or
// random, 1–10 questions each), who, open seats, the stake, the deadline,
// sealed or live scores, who sees it, and — the creator's call on the spot —
// whether it's posted in the club's Discord. `preset` ({opponent, kind,
// stake}) comes from a scouting pick.
export function NewChallenge({ apiBase, groupId, settings, viewerId, rematchOf, preset, onClose, onMade }) {
  const set = useGameSet(preset?.kind || "random");
  const announce = useAnnounce();
  const [opponents, setOpponents] = useState(preset?.opponent ? [preset.opponent] : []);
  const [seats, setSeats] = useState(0);
  const [stake, setStake] = useState(Math.min(preset?.stake ?? 3, settings.max_stake, settings.available));
  const [deadline, setDeadline] = useState("tonight");
  const [reveal, setReveal] = useState("sealed");
  const [seen, setSeen] = useState("club");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const stakes = STAKES.filter(n => n <= settings.max_stake);
  const players = 1 + opponents.length + seats;
  const toggle = id => setOpponents(o => (o.includes(id) ? o.filter(x => x !== id) : o.length + seats < settings.max_players - 1 ? [...o, id] : o));

  async function create() {
    setBusy(true);
    setError("");
    try {
      const made = await send(`${apiBase}/api/challenges`, "POST", {
        group_id: groupId, rounds: set.rounds, opponents, seats, stake, deadline, reveal, visibility: seen,
        ...(announce.canAnnounce && seen === "club" ? { announce: announce.post } : {}),
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
        <GameSet set={set} settings={settings} />

        <span className="share-label">Who</span>
        <PeoplePick apiBase={apiBase} viewerId={viewerId} picked={opponents} onToggle={toggle} />
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
        {seen === "club" && <AnnounceChoice announce={announce} />}
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

// Play → Challenges, first on the page: your record and the club's, who you
// should challenge (with a roast), then what's waiting for you, what's live,
// tournaments, and what's been decided.
export default function ChallengesSection({ apiBase, groupId, viewerId, canRun }) {
  const navigate = useNavigate();
  const { data, error, reload } = useJson(groupId ? `${apiBase}/api/challenges?group_id=${groupId}` : null, { refreshOn: "kernels" });
  const cups = useJson(groupId && data?.enabled ? `${apiBase}/api/tournaments?group_id=${groupId}` : null, { refreshOn: "kernels" }).data;
  const [making, setMaking] = useState(null);           // {} or a scouting pick's preset
  const [cup, setCup] = useState(false);
  const lists = useMemo(() => {
    const all = data?.challenges || [];
    const ts = cups?.tournaments || [];
    const yours = all.filter(c => c.status === "open" && (c.you.can_accept || c.you.can_play));
    const myCups = ts.filter(t => t.you.can_accept || t.you.match);
    return [["Waiting for you", yours, myCups],
            ["Live in the club", all.filter(c => c.status === "open" && !yours.includes(c)),
             ts.filter(t => ["open", "running"].includes(t.status) && !myCups.includes(t))],
            ["Decided", all.filter(c => c.status !== "open"), ts.filter(t => ["done", "cancelled"].includes(t.status))]];
  }, [data, cups]);
  if (!data) return error ? <LoadError what="challenges" onRetry={reload} /> : <Loading context="games" compact />;
  if (!data.enabled) {
    return canRun ? (
      <p className="ui-note">⚔️ Challenges are off. <Link to="/club?tab=settings#settings-games">Turn them on in Club settings</Link></p>
    ) : <p className="ui-note">⚔️ Challenges aren't on in this club yet.</p>;
  }
  const open = c => navigate(`/challenges/${c.id}`);
  const empty = lists.every(([, l, t]) => !l.length && !t.length);
  return (
    <>
      <div className="ch-head">
        <button type="button" className="btn btn-primary" onClick={() => setMaking({})} disabled={!data.games.length}>⚔️ Challenge someone</button>
        <button type="button" className="btn" onClick={() => setCup(true)} disabled={!data.games.length || !cups}>🏆 Start a tournament</button>
        <span className="ui-hint">You have {data.available} 🍿 to put in{data.on_the_line ? ` · ${data.on_the_line} 🍿 on the line` : ""}.</span>
      </div>
      <ChallengeStats apiBase={apiBase} groupId={groupId}>
        {scout => <ScoutPicks apiBase={apiBase} groupId={groupId} picks={scout.picks}
                              onChallenge={p => setMaking({ opponent: p.user.id, kind: p.suggest.kind, stake: p.suggest.stake })} />}
      </ChallengeStats>
      {empty && <p className="pv-empty">No challenges yet — start one.</p>}
      {lists.map(([title, list, ts]) => (list.length > 0 || ts.length > 0) && (
        <div key={title}>
          <h3 className="pv-past-title">{title}</h3>
          <div className="pv-cards">
            {ts.map(t => <TournamentCard key={`t${t.id}`} t={t} onOpen={() => navigate(`/tournaments/${t.id}`)} />)}
            {list.map(c => <ChallengeCard key={c.id} c={c} onOpen={() => open(c)} />)}
          </div>
        </div>
      ))}
      {making && <NewChallenge apiBase={apiBase} groupId={groupId} settings={data} viewerId={viewerId} preset={making}
                               onClose={() => setMaking(null)} onMade={c => navigate(`/challenges/${c.id}`)} />}
      {cup && cups && <NewTournament apiBase={apiBase} groupId={groupId} settings={data} options={cups} viewerId={viewerId}
                                     onClose={() => setCup(false)} onMade={t => navigate(`/tournaments/${t.id}`)} />}
    </>
  );
}

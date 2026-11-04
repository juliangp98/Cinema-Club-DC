import { useEffect } from "react";
import { Link, Navigate, useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import PageHeader from "../ui/PageHeader";
import RouteTabs from "../ui/RouteTabs";
import PollList from "../components/PollList";
import QuizGames from "../components/QuizGames";
import ChallengesSection from "../components/Challenges";
import { GamesRunPanel, KernelStrip, LeftToday, Movers, MonthBoard, YourKernels } from "../components/PlaySide";
import { waitingItems } from "../ui/GamesSummary";
import { useJson } from "../api";
import { useShell } from "../shell/AppShell";
import { runsClub } from "../roles";
import { RecordsTab } from "../components/GameRecords";
import { BingoPage, HigherLowerPage, TriviaPage } from "../components/GamePages";

// Play: the club's games. Today (/play) is the hub: what's waiting on you,
// then a tile for each part, beside your kernels and the boards on wide
// screens. Each part has its own page (/play/challenges, /play/trivia…), so
// none crowds the others. On phones the boards are their own page
// (/play/kernels) instead of trailing below every game. Trivia, Bingo and
// Higher or lower (/play/games/higher-lower, under Games) have pages with
// depth (Phase 3): your numbers, history, the club's board, modes. Old links
// (/play#trivia, ?tab=records) land on the new pages.

const PAGES = [
  { key: "today", label: "Today", to: "/play", end: true },
  { key: "challenges", label: "Challenges", to: "/play/challenges" },
  { key: "trivia", label: "Trivia", to: "/play/trivia" },
  { key: "bingo", label: "Bingo", to: "/play/bingo" },
  { key: "polls", label: "Polls", to: "/play/polls" },
  { key: "games", label: "Games", to: "/play/games" },
  { key: "records", label: "Records", to: "/play/records" },
  { key: "kernels", label: "Kernels", to: "/play/kernels" },
];
const KEYS = new Set(PAGES.map(p => p.key));
const TOURS = { today: "play", challenges: "play-challenges", trivia: "play-trivia", bingo: "play-bingo" };
const GAME_PAGES = ["higher-lower"];          // /play/games/<game>

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The tile for each part: its live line, and whether something there is waiting on you.
function tiles(s, canRun) {
  if (!s) return [];
  const ch = s.challenges;
  const waiting = ch ? ch.invites.length + ch.your_turn.length + (ch.tournaments?.length || 0) : 0;
  const toVote = s.polls.filter(p => !p.you_voted).length;
  const t = s.trivia, b = s.bingo, left = s.kernels.today?.total || 0;
  return [
    (ch || canRun) && { key: "challenges", icon: "⚔️", label: "Challenges", hot: waiting > 0,
                        line: !ch ? "Off in this club" : waiting ? `${plural(waiting, "thing")} waiting for you` : "Challenge someone, or start a tournament" },
    (t || canRun) && { key: "trivia", icon: "🧠", label: "Trivia", hot: !!(t?.to_answer || t?.waiting),
                       line: !t ? "Off in this club" : t.to_answer ? "Today's question is waiting"
                         : t.answered ? (t.correct ? "You got today's ✓" : "Answered today") : t.anytime ? "Anytime questions are on" : "A new question tomorrow" },
    (b || canRun) && { key: "bingo", icon: "🎱", label: "Bingo",
                       line: !b ? "Off in this club" : b.full ? "Full card! 🎉" : `${b.filled} of 8${b.line ? ", a line! 🎉" : ""}` },
    { key: "polls", icon: "🗳️", label: "Polls", hot: toVote > 0,
      line: toVote ? `${toVote} to vote in` : s.polls.length ? "You've voted in every open poll" : "No open polls right now" },
    { key: "games", icon: "🎮", label: "Games", hot: left > 0, line: left ? `${left} 🍿 left to earn today` : "Every game kernel earned today" },
    { key: "records", icon: "📊", label: "Records", line: "Yours, everyone's and the club's" },
    { key: "kernels", icon: "🍿", label: "Kernels", phone: true, line: `${s.kernels.kernels} 🍿, this month's board and this week's movers` },
  ].filter(Boolean);
}

// Today: what's waiting on you (one thing to do for each), then the tiles.
function Today({ summary, canRun }) {
  const items = waitingItems(summary);
  if (!summary) return null;
  return (
    <>
      <section className="play-turn" aria-label="Your turn">
        <h2 className="ui-panel-title kicker">Your turn</h2>
        {items.length ? (
          <ul className="play-turn-list">
            {items.map(it => (
              <li key={it.key}>
                <span className="play-turn-icon" aria-hidden="true">{it.icon}</span>
                <span className="play-turn-text">{it.text}</span>
                <Link className="btn btn-sm btn-primary" to={it.to}>{it.action}</Link>
              </li>
            ))}
          </ul>
        ) : <p className="ui-hint">You're all caught up. Pick a game below, or challenge someone.</p>}
      </section>
      <ul className="play-tiles" aria-label="Play">
        {tiles(summary, canRun).map(t => (
          <li key={t.key} className={t.phone ? "phone-only" : ""}>
            <Link to={`/play/${t.key}`} className={`play-tile${t.hot ? " hot" : ""}`}>
              <span className="play-tile-icon" aria-hidden="true">{t.icon}</span>
              <span className="play-tile-name">{t.label}</span>
              <span className="play-tile-line">{t.line}</span>
            </Link>
          </li>
        ))}
      </ul>
    </>
  );
}

export default function PlayPage({ user, apiBase, groupId }) {
  const { role, group } = useShell() || {};
  const canRun = runsClub(role);
  const { section = "today", game } = useParams();
  const { hash } = useLocation();
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const board = period => (groupId ? `${apiBase}/api/groups/${groupId}/leaderboard?period=${period}` : null);
  // Your numbers and the boards follow what you earn as you play (api.changed("kernels")).
  const live = { refreshOn: "kernels" };
  const { data: k } = useJson(groupId ? `${apiBase}/api/kernels?group_id=${groupId}` : null, live);
  const { data: summary } = useJson(groupId && section === "today" ? `${apiBase}/api/play?group_id=${groupId}` : null, live);
  const wantsBoards = section === "today" || section === "kernels";
  const month = useJson(wantsBoards ? board("month") : null, live).data?.rows;
  const week = useJson(wantsBoards ? board("week") : null, live).data?.rows;

  // Links from before Play had pages: /play#trivia, /play?tab=records.
  const old = hash.slice(1) || (params.get("tab") === "records" ? "records" : "");
  useEffect(() => {
    if (section === "today" && KEYS.has(old) && old !== "today") navigate(`/play/${old}`, { replace: true });
  }, [section, old]);

  if (!KEYS.has(section)) return <Navigate to="/play" replace />;
  if (game && (section !== "games" || !GAME_PAGES.includes(game))) return <Navigate to={`/play/${section}`} replace />;
  if (!groupId) {
    return (
      <div className="page">
        <PageHeader title="Play" />
        <p className="pv-empty">Trivia, bingo and polls happen in a club. <Link to="/groups">Find or start a club</Link> to play.</p>
      </div>
    );
  }
  const rail = section === "today";
  const boards = (
    <>
      <YourKernels k={k} month={month} viewerId={user.id} />
      <LeftToday k={k} />
      <MonthBoard month={month} viewerId={user.id} />
      <Movers week={week} viewerId={user.id} />
      {canRun && <GamesRunPanel apiBase={apiBase} slug={group?.slug} />}
    </>
  );
  return (
    <div className={`page play-page play-on-${section}`}>
      <PageHeader title="Play" tour={game ? `play-${game}` : TOURS[section]} />
      <KernelStrip k={k} month={month} viewerId={user.id} />
      <RouteTabs tabs={PAGES} label="Play" />
      <div className={rail ? "play-layout ui-split" : "play-layout"}>
        <div className="play-main">
          {section === "today" && <Today summary={summary} canRun={canRun} />}
          {section === "challenges" && <ChallengesSection apiBase={apiBase} groupId={groupId} viewerId={user.id} canRun={canRun} />}
          {section === "trivia" && <TriviaPage apiBase={apiBase} groupId={groupId} role={role} viewerId={user.id} />}
          {section === "bingo" && <BingoPage apiBase={apiBase} groupId={groupId} role={role} viewerId={user.id} />}
          {section === "polls" && <>
            {canRun && <p className="play-actions"><Link to="/polls/new" className="btn btn-sm btn-primary">＋ New poll</Link></p>}
            <PollList apiBase={apiBase} groupId={groupId} canRun={canRun} />
          </>}
          {section === "games" && !game && <QuizGames apiBase={apiBase} groupId={groupId} canRun={canRun} />}
          {game === "higher-lower" && <HigherLowerPage apiBase={apiBase} groupId={groupId} viewerId={user.id} canRun={canRun} />}
          {section === "records" && group && <RecordsTab apiBase={apiBase} group={group} viewerId={user.id} />}
          {section === "kernels" && <div className="play-kernels">{boards}</div>}
        </div>
        {rail && <aside className="play-side ui-split-side sticky" aria-label="Kernels and standings">{boards}</aside>}
      </div>
    </div>
  );
}

import { Link, useSearchParams } from "react-router-dom";
import PageHeader, { SectionTitle } from "../ui/PageHeader";
import TriviaCard from "../ui/TriviaCard";
import BingoCard from "../ui/BingoCard";
import PollList from "../components/PollList";
import QuizGames from "../components/QuizGames";
import ChallengesSection from "../components/Challenges";
import { GamesRunPanel, KernelStrip, LeftToday, Movers, MonthBoard, YourKernels } from "../components/PlaySide";
import { useJson } from "../api";
import { useShell } from "../shell/AppShell";
import { runsClub } from "../roles";
import Tabs from "../ui/Tabs";
import { ClubBingo, RecordsTab } from "../components/GameRecords";
// Play (R10; laid out in R15): the club's games — challenges first (stats,
// who to challenge, tournaments), then trivia, bingo (with everyone's card,
// 7g), every poll and the quiz games — in the main column, beside your kernels,
// this month's standings and this week's movers (and, for organizers and
// admins, the games they run). Its Records tab (7g, ?tab=records): yours,
// everyone's and the club's. The feed's rail and strip (and /play in
// Discord) lead here; /polls too.
const TABS = [{ key: "games", label: "Games" }, { key: "records", label: "Records" }];

export default function PlayPage({ user, apiBase, groupId }) {
  const { role, group } = useShell() || {};
  const canRun = runsClub(role);
  const board = period => (groupId ? `${apiBase}/api/groups/${groupId}/leaderboard?period=${period}` : null);
  // Your numbers and the boards follow what you earn as you play (api.changed("kernels")).
  const live = { refreshOn: "kernels" };
  const { data: k } = useJson(groupId ? `${apiBase}/api/kernels?group_id=${groupId}` : null, live);
  const month = useJson(board("month"), live).data?.rows;
  const week = useJson(board("week"), live).data?.rows;
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") === "records" ? "records" : "games";
  const setTab = key => setParams(key === "games" ? {} : { tab: key }, { replace: true });

  if (!groupId) {
    return (
      <div className="page">
        <PageHeader title="Play" />
        <p className="pv-empty">Trivia, bingo and polls happen in a club. <Link to="/groups">Find or start a club</Link> to play.</p>
      </div>
    );
  }
  return (
    <div className="page play-page">
      <PageHeader title="Play" tour="play" />
      <KernelStrip k={k} month={month} viewerId={user.id} />
      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Play" />
      <div className="play-layout ui-split">
        <div className="play-main">
          {tab === "records" ? (group && <RecordsTab apiBase={apiBase} group={group} viewerId={user.id} />) : <>
          <section id="challenges" className="play-section play-challenges">
            <SectionTitle>⚔️ Challenges</SectionTitle>
            <ChallengesSection apiBase={apiBase} groupId={groupId} viewerId={user.id} canRun={canRun} />
          </section>
          <section id="trivia" className="play-section">
            <SectionTitle>Trivia</SectionTitle>
            <TriviaCard apiBase={apiBase} groupId={groupId} role={role} offNote />
          </section>
          <section id="bingo" className="play-section">
            <SectionTitle>Bingo</SectionTitle>
            <BingoCard apiBase={apiBase} groupId={groupId} role={role} offNote />
            <ClubBingo apiBase={apiBase} groupId={groupId} viewerId={user.id} />
          </section>
          <section id="polls" className="play-section">
            <SectionTitle link={canRun ? { to: "/polls/new", label: "＋ New poll" } : undefined}>Polls</SectionTitle>
            <PollList apiBase={apiBase} groupId={groupId} canRun={canRun} />
          </section>
          <section id="games" className="play-section">
            <SectionTitle>More games</SectionTitle>
            <QuizGames apiBase={apiBase} groupId={groupId} canRun={canRun} />
          </section>
          </>}
        </div>
        <aside className="play-side ui-split-side sticky" aria-label="Kernels and standings">
          <YourKernels k={k} month={month} viewerId={user.id} />
          <LeftToday k={k} />
          <MonthBoard month={month} viewerId={user.id} />
          <Movers week={week} viewerId={user.id} />
          {canRun && <GamesRunPanel apiBase={apiBase} slug={group?.slug} />}
        </aside>
      </div>
    </div>
  );
}

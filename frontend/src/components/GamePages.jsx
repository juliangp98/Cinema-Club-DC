import { useState } from "react";
import { Link } from "react-router-dom";
import { useJson } from "../api";
import { dayDate, monthYear } from "../dates";
import Facts, { MetaRow } from "../ui/Facts";
import Loading, { LoadError } from "../ui/Loading";
import MiniBingo from "../ui/MiniBingo";
import PersonLink from "../ui/PersonLink";
import Select from "../ui/Select";
import StatTiles from "../ui/StatTiles";
import TriviaCard from "../ui/TriviaCard";
import BingoCard from "../ui/BingoCard";
import { Segmented } from "../ui/TicketRow";
import { PERIODS } from "./ClubBoard";
import { ClubBingo } from "./GameRecords";
import { Game } from "./QuizGames";

// Play's game pages (Phase 3): Trivia, Higher or lower and Bingo each play in
// place on top, then your numbers for a period, your history and the club's
// board (game_pages.py). They reload after every answer (changed("games")).

const LEVELS = ["easy", "medium", "hard"];
const cap = s => s[0].toUpperCase() + s.slice(1);
const day = iso => dayDate(`${iso}T12:00:00`);
const during = period => PERIODS.find(p => p.status === period)?.label.toLowerCase();   // "this month"

function usePage(apiBase, groupId, game, period) {
  return useJson(`${apiBase}/api/play/${game}?group_id=${groupId}&period=${period}`, { keep: true, refreshOn: "games" });
}

// A section of a game page: its title, and (for the numbers) the period.
function Section({ id, title, period, onPeriod, children }) {
  return (
    <section className="game-section" aria-labelledby={id}>
      <div className="game-section-head">
        <h2 className="ui-settings-group-title" id={id}>{title}</h2>
        {onPeriod && <Segmented label={`${title}: period`} options={PERIODS} value={period} onChange={v => v && onPeriod(v)} />}
      </div>
      {children}
    </section>
  );
}

// The club's board for a game: place, member (you in gold), its numbers.
function Board({ label, rows, cols, viewerId, empty }) {
  if (!rows.length) return <p className="ui-hint">{empty}</p>;
  return (
    <div className="ui-table-wrap">
      <table className="ui-table game-board" aria-label={label}>
        <thead>
          <tr><th scope="col">#</th><th scope="col">Member</th>{cols.map(c => <th key={c.label} scope="col">{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.user.id} className={r.user.id === viewerId ? "me" : ""}>
              <td>{i + 1}</td>
              <td>{r.user.id === viewerId ? "You" : <PersonLink user={r.user} />}</td>
              {cols.map(c => <td key={c.label}>{c.show(r)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Numbers({ data, error, reload, what, children }) {
  if (error && !data) return <LoadError what={what} onRetry={reload} />;
  if (!data) return <Loading context="games" compact />;
  return children;
}

// ─── Trivia ───────────────────────────────────────────────────────────────────

export function TriviaPage({ apiBase, groupId, role, viewerId }) {
  const [period, setPeriod] = useState("month");
  const { data, error, reload } = usePage(apiBase, groupId, "trivia", period);
  const you = data?.you;
  return (
    <div className="game-page">
      <TriviaCard apiBase={apiBase} groupId={groupId} role={role} offNote />
      {(data?.enabled ?? true) && (
        <Numbers data={data} error={error} reload={reload} what="your trivia">
          {data && (<>
            <Section id="trivia-you" title="Your trivia" period={period} onPeriod={setPeriod}>
              <StatTiles size="sm" label="Your trivia" items={[
                { label: "Right", value: you.correct, sub: `of ${you.answered} answered` },
                { label: "Accuracy", value: you.accuracy != null ? `${you.accuracy}%` : "—" },
                { label: "Streak", value: you.streak, sub: "daily questions in a row" },
                { label: "Best streak", value: you.best_streak },
                { label: "Kernels", value: `${you.kernels} 🍿` },
              ]} />
              <Facts label="By difficulty" items={LEVELS.map(lv => you.levels[lv].answered > 0 && {
                label: cap(lv), value: `${you.levels[lv].correct} of ${you.levels[lv].answered}`,
              })} />
            </Section>
            <Section id="trivia-history" title="Your latest answers">
              {data.history.length ? (
                <ul className="game-history">
                  {data.history.map(h => (
                    <li key={h.id}>
                      <span className="game-history-what">{h.correct ? "✅" : "❌"} {h.prompt}</span>
                      <span className="game-history-answer">
                        {h.correct ? <>You said <strong>{h.answer}</strong>.</>
                          : <>You said {h.yours}; it was <strong>{h.answer}</strong>.</>}
                      </span>
                      <MetaRow label="About it" items={[
                        { icon: "📅", text: day(h.day) },
                        { icon: h.daily ? "🧠" : "🎲", text: h.daily ? "Question of the day" : "Anytime" },
                        { text: cap(h.difficulty) },
                      ]} />
                    </li>
                  ))}
                </ul>
              ) : <p className="ui-hint">Nothing answered yet. Today's question is above.</p>}
            </Section>
            <Section id="trivia-club" title={`The club, ${during(period)}`}>
              <Board label="The club's trivia" rows={data.board} viewerId={viewerId} empty="Nobody's answered yet this period."
                     cols={[{ label: "Right", show: r => r.correct }, { label: "Accuracy", show: r => `${r.accuracy}%` },
                            { label: "Best streak", show: r => r.streak }]} />
            </Section>
          </>)}
        </Numbers>
      )}
    </div>
  );
}

// ─── Higher or lower ──────────────────────────────────────────────────────────

export function HigherLowerPage({ apiBase, groupId, viewerId, canRun }) {
  const [period, setPeriod] = useState("month");
  const [decade, setDecade] = useState("");                 // "": classic, any year
  const { data, error, reload } = usePage(apiBase, groupId, "higher-lower", period);
  const { data: games } = useJson(`${apiBase}/api/quizzes?group_id=${groupId}`);
  const g = games?.games.find(x => x.kind === "higher_lower");
  if (data && !data.enabled) {
    return canRun ? (
      <p className="ui-note">↕️ Higher or lower is off for the club. <Link to="/club?tab=settings#settings-games">Turn it on in Club settings</Link></p>
    ) : <p className="ui-note">↕️ Higher or lower isn't on in this club yet.</p>;
  }
  const you = data?.you;
  return (
    <div className="game-page">
      <p className="game-back"><Link to="/play/games">‹ All the games</Link></p>
      {data?.modes.length > 1 && (
        <div className="game-modes">
          <Select label="Which films" value={decade} onChange={setDecade}
                  options={data.modes.map(m => ({ value: m.value ? String(m.value) : "", label: m.value ? `The ${m.label}` : "Classic: any year" }))} />
          <span className="ui-hint">A new run uses it; one you're in the middle of keeps its own.</span>
        </div>
      )}
      {g && <Game g={g} apiBase={apiBase} groupId={groupId} decade={decade ? Number(decade) : null} />}
      <Numbers data={data} error={error} reload={reload} what="your runs">
        {data && (<>
          <Section id="hl-you" title="Your runs" period={period} onPeriod={setPeriod}>
            <StatTiles size="sm" label="Your runs" items={[
              { label: "Runs", value: you.runs },
              { label: "Best streak", value: you.best },
              { label: "Average", value: you.average ?? "—" },
              { label: "Right calls", value: you.right },
              { label: "Kernels", value: `${you.kernels} 🍿`, sub: `${data.left_today} left today` },
            ]} />
            <Facts label="Best by decade" items={you.by_mode.map(m => ({ label: m.label, value: m.best }))} />
          </Section>
          <Section id="hl-history" title="Your latest runs">
            {data.history.length ? (
              <ul className="game-history">
                {data.history.map(h => (
                  <li key={h.id}>
                    <span className="game-history-what"><strong>{h.score}</strong> in a row</span>
                    <MetaRow label="About it" items={[
                      { icon: "📅", text: day(h.day) }, { icon: "🎞️", text: h.mode },
                      h.earned > 0 && { icon: "🍿", text: `+${h.earned}` },
                    ]} />
                  </li>
                ))}
              </ul>
            ) : <p className="ui-hint">No runs yet. Play one above.</p>}
          </Section>
          <Section id="hl-club" title={`The club's best, ${during(period)}`}>
            <Board label="The club's best streaks" rows={data.board} viewerId={viewerId} empty="No runs yet this period."
                   cols={[{ label: "Best streak", show: r => r.best }, { label: "Runs", show: r => r.runs }]} />
          </Section>
        </>)}
      </Numbers>
    </div>
  );
}

// ─── Bingo ────────────────────────────────────────────────────────────────────

export function BingoPage({ apiBase, groupId, role, viewerId }) {
  const [period, setPeriod] = useState("all");
  const { data, error, reload } = usePage(apiBase, groupId, "bingo", period);
  const you = data?.you;
  return (
    <div className="game-page">
      <BingoCard apiBase={apiBase} groupId={groupId} role={role} offNote />
      <ClubBingo apiBase={apiBase} groupId={groupId} viewerId={viewerId} />
      {data?.enabled && (
        <Numbers data={data} error={error} reload={reload} what="your bingo">
          <Section id="bingo-you" title="Your bingo" period={period} onPeriod={setPeriod}>
            <StatTiles size="sm" label="Your bingo" items={[
              { label: "Cards played", value: you.played },
              { label: "Lines", value: you.lines },
              { label: "Full cards", value: you.cards },
              { label: "Kernels", value: `${you.kernels} 🍿` },
            ]} />
            <Facts label="Your best" items={[
              you.best && { label: "Best month", value: `${you.best.label}, ${you.best.filled} of 8`, tone: "gold" },
              you.favorite && { label: "Most filled", value: `${you.favorite.label} (${you.favorite.count})` },
            ]} />
          </Section>
          {data.history.length > 0 && (
            <Section id="bingo-history" title="Your past cards">
              <ul className="member-bingo-past game-bingo-past" aria-label="Your past cards">
                {data.history.map(h => (
                  <li key={h.month}>
                    <MiniBingo cells={h.cells} line={h.line} full={h.full} size="md"
                               label={`${h.month_label}: ${h.full ? "full card" : h.line ? "a line" : `${h.filled} of 8`}`} />
                    <span>{monthYear(`${h.month}-15T12:00:00`)}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}
          <Section id="bingo-club" title={`The club, ${during(period)}`}>
            <Board label="The club's bingo" rows={data.board} viewerId={viewerId} empty="Nobody's filled a square yet this period."
                   cols={[{ label: "Full cards", show: r => r.cards }, { label: "Lines", show: r => r.lines },
                          { label: "Kernels", show: r => r.kernels }]} />
          </Section>
        </Numbers>
      )}
    </div>
  );
}

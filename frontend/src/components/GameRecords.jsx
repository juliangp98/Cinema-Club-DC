import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useJson } from "../api";
import BingoGrid from "../ui/BingoGrid";
import MiniBingo from "../ui/MiniBingo";
import Panel from "../ui/Panel";
import PersonLink from "../ui/PersonLink";
import Sheet, { SheetTitle } from "../ui/Sheet";
import StatTiles from "../ui/StatTiles";
import { Segmented } from "../ui/TicketRow";
import { PERIODS } from "./ClubBoard";

// Members' long-term game standing (7g): everyone's bingo card this month
// (the strip on Play), a member's card and their last six (their page), and
// game records — yours, everyone's and the club's — on Play's Records tab.
// The numbers are the leaderboard's (club_stats: trivia, bingo, quiz games,
// poll picks), so every view counts the same way. Only games the club has on.

export function gamesOn(group) {
  const q = group?.quizzes || {};
  return {
    trivia: !!(group?.trivia?.enabled || group?.trivia?.anytime),
    bingo: !!group?.bingo?.enabled,
    hl: !!q.higher_lower,
    quizzes: Object.values(q).some(Boolean),
  };
}

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const pct = (right, of) => (of ? `${Math.round((100 * right) / of)}%` : "—");

// A member's records as tiles, from their leaderboard row.
export function recordItems(row, on) {
  if (!row) return [];
  const { trivia: t, bingo: b, quizzes: q } = row.stats;
  return [
    on.trivia && { label: "Trivia", value: pct(t.correct, t.answered), sub: t.answered ? `${t.correct} of ${t.answered} · best streak ${t.streak}` : "None answered yet" },
    on.bingo && { label: "Bingo", value: plural(b.lines, "line"), sub: plural(b.cards, "full card") },
    on.hl && { label: "Higher or lower", value: q?.best_streak || 0, sub: "best streak" },
    on.quizzes && { label: "Quiz games", value: q?.right || 0, sub: `right · ${plural(q?.rounds || 0, "round")}` },
    { label: "Polls", value: row.correct, sub: "right picks" },
  ];
}

// The club's totals, from everyone's rows.
function clubItems(rows, on) {
  const sum = f => rows.reduce((n, r) => n + f(r), 0);
  const answered = sum(r => r.stats.trivia.answered), correct = sum(r => r.stats.trivia.correct);
  return [
    on.trivia && { label: "Trivia answered", value: answered, sub: answered ? `${pct(correct, answered)} right` : "None yet" },
    on.bingo && { label: "Bingo", value: plural(sum(r => r.stats.bingo.lines), "line"), sub: plural(sum(r => r.stats.bingo.cards), "full card") },
    on.quizzes && { label: "Quiz rounds", value: sum(r => r.stats.quizzes?.rounds || 0),
                    sub: on.hl ? `longest streak ${Math.max(0, ...rows.map(r => r.stats.quizzes?.best_streak || 0))}` : null },
    { label: "Poll picks", value: sum(r => r.correct), sub: "right" },
  ];
}

const COLUMNS = [
  { key: "trivia", label: "Trivia", on: o => o.trivia, sort: r => (r.stats.trivia.answered ? r.stats.trivia.correct / r.stats.trivia.answered : -1),
    show: r => pct(r.stats.trivia.correct, r.stats.trivia.answered) },
  { key: "streak", label: "Streak", on: o => o.trivia, sort: r => r.stats.trivia.streak, show: r => r.stats.trivia.streak },
  { key: "bingo", label: "Bingo", on: o => o.bingo, sort: r => r.stats.bingo.lines * 10 + r.stats.bingo.cards,
    show: r => `${r.stats.bingo.lines} · ${r.stats.bingo.cards} full` },
  { key: "hl", label: "H or L", on: o => o.hl, sort: r => r.stats.quizzes?.best_streak || 0, show: r => r.stats.quizzes?.best_streak || 0 },
  { key: "quiz", label: "Quiz right", on: o => o.quizzes, sort: r => r.stats.quizzes?.right || 0, show: r => r.stats.quizzes?.right || 0 },
  { key: "polls", label: "Polls", on: () => true, sort: r => r.correct, show: r => r.correct },
];

// Play → Records: you, everyone (a table you can sort; names go to their
// pages), and the club — this month to start, or this year / all time.
export function RecordsTab({ apiBase, group, viewerId }) {
  const [period, setPeriod] = useState("month");
  const on = gamesOn(group);
  const cols = COLUMNS.filter(c => c.on(on));
  const [sortKey, setSortKey] = useState(cols[0]?.key);
  const { data, error } = useJson(`${apiBase}/api/groups/${group.id}/leaderboard?period=${period}`, { keep: true });
  const rows = data?.rows || [];
  const sorted = useMemo(() => {
    const col = cols.find(c => c.key === sortKey) || cols[0];
    return [...rows].sort((a, b) => col.sort(b) - col.sort(a) || a.user.name.localeCompare(b.user.name));
  }, [rows, sortKey]);   // eslint-disable-line react-hooks/exhaustive-deps
  const me = rows.find(r => r.user.id === viewerId);
  return (
    <div className="records">
      <div className="records-head">
        <Segmented label="Records period" options={PERIODS} value={period} onChange={v => v && setPeriod(v)} />
      </div>
      {error && <p className="pv-empty">Couldn't load the records right now.</p>}
      {!data && !error && <p className="pv-empty">Loading…</p>}
      {data && (<>
        <section className="records-section" aria-labelledby="records-you">
          <h3 className="ui-settings-group-title" id="records-you">You</h3>
          {me ? <StatTiles label="Your records" items={recordItems(me, on)} /> : <p className="ui-hint">Nothing yet this period.</p>}
        </section>
        <section className="records-section" aria-labelledby="records-everyone">
          <h3 className="ui-settings-group-title" id="records-everyone">Everyone</h3>
          <div className="ui-table-wrap">
            <table className="ui-table" aria-labelledby="records-everyone">
              <thead>
                <tr>
                  <th scope="col">Member</th>
                  {cols.map(c => (
                    <th key={c.key} scope="col" aria-sort={sortKey === c.key ? "descending" : undefined}>
                      <button type="button" onClick={() => setSortKey(c.key)}>{c.label}{sortKey === c.key ? " ↓" : ""}</button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map(r => (
                  <tr key={r.user.id} className={r.user.id === viewerId ? "me" : ""}>
                    <td>{r.user.id === viewerId ? "You" : <PersonLink user={r.user} />}</td>
                    {cols.map(c => <td key={c.key}>{c.show(r)}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section className="records-section" aria-labelledby="records-club">
          <h3 className="ui-settings-group-title" id="records-club">The club</h3>
          <StatTiles label="The club's records" items={clubItems(rows, on)} />
        </section>
      </>)}
    </div>
  );
}

// A member's bingo: this month's card square by square, and their last six.
export function MemberBingo({ apiBase, groupId, userId, name }) {
  const { data } = useJson(`${apiBase}/api/bingo/people/${userId}?group_id=${groupId}`);
  if (!data?.enabled) return null;
  const status = data.full ? "full card 🎉" : data.line ? "a line 🎉" : `${data.filled} of 8`;
  return (
    <div className="member-bingo">
      <div className="member-bingo-card">
        <p className="ui-hint">{data.month_label} · {status}</p>
        <BingoGrid squares={data.squares} label={`${name}'s card`} compact />
      </div>
      {data.history.length > 0 && (
        <div className="member-bingo-history">
          <p className="ui-hint">Past cards</p>
          <ul className="member-bingo-past" aria-label={`${name}'s past cards`}>
            {data.history.map(h => (
              <li key={h.month}>
                <MiniBingo cells={h.cells} line={h.line} full={h.full} size="md"
                           label={`${h.month_label}: ${h.full ? "full card" : h.line ? "a line" : `${h.filled} of 8`}`} />
                {h.month_label} · {h.full ? "full" : h.line ? "line" : `${h.filled}/8`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

// A member's page → Games: their bingo and their all-time records.
export function MemberGames({ apiBase, group, userId, name }) {
  const on = gamesOn(group);
  const { data } = useJson(group ? `${apiBase}/api/groups/${group.id}/leaderboard?period=all` : null);
  const row = data?.rows.find(r => r.user.id === userId);
  if (!group || !row) return null;                        // not (yet) in your club: nothing to show
  return (
    <section className="member-games" aria-labelledby="member-games-title">
      <h2 className="ui-settings-group-title" id="member-games-title">Games</h2>
      {on.bingo && <MemberBingo apiBase={apiBase} groupId={group.id} userId={userId} name={name} />}
      {row && <StatTiles label={`${name}'s records`} items={recordItems(row, on)} />}
      <p className="ui-hint"><Link to="/play?tab=records">Everyone's records on Play →</Link></p>
    </section>
  );
}

// Everyone's card this month, in one swipeable row under yours on Play; tap
// one for theirs.
export function ClubBingo({ apiBase, groupId, viewerId }) {
  const { data } = useJson(`${apiBase}/api/bingo/club?group_id=${groupId}`);
  const [open, setOpen] = useState(null);
  if (!data?.enabled || !data.cards.length) return null;
  return (
    <Panel as="div" tone="tile" className="club-bingo" title={`The club's cards · ${data.month_label}`} kicker
           hint="A gold edge is a line. Tap one to see it.">
      <ul className="club-bingo-row" aria-label="The club's cards">
        {data.cards.map(c => {
          const mine = c.user.id === viewerId;
          return (
            <li key={c.user.id}>
              <button type="button" className={`club-bingo-who${mine ? " me" : ""}`} onClick={() => setOpen(c.user)}
                      aria-label={`${mine ? "Your" : `${c.user.name}'s`} card: ${c.full ? "full card" : c.line ? "a line" : `${c.filled} of 8`}`}>
                <MiniBingo cells={c.cells} line={c.line} full={c.full} size="md" />
                <span className="club-bingo-name">{mine ? "You" : c.user.name}</span>
                <span>{c.filled}/8</span>
              </button>
            </li>
          );
        })}
      </ul>
      {open && (
        <Sheet label={`${open.name}'s card`} onClose={() => setOpen(null)}>
          <div className="share-sheet-body">
            <SheetTitle>{open.id === viewerId ? "Your card" : `${open.name}'s card`}</SheetTitle>
            <MemberBingo apiBase={apiBase} groupId={groupId} userId={open.id} name={open.name} />
            {open.id !== viewerId && <p className="ui-hint"><Link to={`/people/${open.id}`} onClick={() => setOpen(null)}>{open.name}'s page →</Link></p>}
          </div>
        </Sheet>
      )}
    </Panel>
  );
}

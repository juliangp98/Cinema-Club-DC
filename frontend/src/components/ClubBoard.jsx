import { useState } from "react";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import { Segmented } from "../ui/TicketRow";
import { useJson } from "../api";
import { KERNEL_PARTS, medal } from "../kernels";

// The club's leaderboard (R15): this month, this year or all time — kernels
// earned in the period as a bar by where they came from, the period's
// superlatives, and each member's stats a tap away. (club_stats.py)

export const PERIODS = [
  { status: "month", label: "This month" },
  { status: "year", label: "This year" },
  { status: "all", label: "All time" },
];

export function KernelBar({ breakdown, total, most }) {
  const parts = KERNEL_PARTS.map(p => ({ ...p, n: Math.max(0, breakdown[p.key] || 0) })).filter(p => p.n);
  const sum = parts.reduce((a, p) => a + p.n, 0);
  return (
    <span className="kbar" role="img" aria-label={parts.map(p => `${p.label} ${p.n}`).join(", ") || "no kernels yet"}>
      <span className="kbar-fill" style={{ width: `${most ? Math.max(0, total) / most * 100 : 0}%` }}>
        {parts.map(p => <span key={p.key} className={`kbar-${p.key}`} style={{ flexGrow: p.n / (sum || 1) }} />)}
      </span>
    </span>
  );
}

function Stats({ s }) {
  const t = s.trivia;
  const items = [
    ["Screenings", s.screenings], ["On film", s.film_prints], ["Theatres", s.theatres], ["Late shows", s.late],
    ["Crew nights", s.crew_nights], ["Weeks in a row", s.week_streak], ["First going", s.first_going],
    ["Comments", s.comments],
    ["Trivia", t.answered ? `${t.correct}/${t.answered} · ${t.accuracy}%` : "—"], ["Trivia streak", t.streak],
    ["Bingo", s.bingo.lines || s.bingo.cards ? `${s.bingo.lines} line${s.bingo.lines === 1 ? "" : "s"} · ${s.bingo.cards} card${s.bingo.cards === 1 ? "" : "s"}` : "—"],
    ...(s.quizzes?.rounds ? [["Quiz games", s.quizzes.rounds], ["Best streak", s.quizzes.best_streak]] : []),
  ];
  return (
    <dl className="club-board-stats">
      {items.map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
    </dl>
  );
}

export default function ClubBoard({ group, apiBase, viewerId }) {
  const [period, setPeriod] = useState("month");
  const { data, error } = useJson(`${apiBase}/api/groups/${group.id}/leaderboard?period=${period}`, { keep: true });
  const rows = data?.rows || [];
  const most = Math.max(1, ...rows.map(r => r.kernels));
  const quiet = rows.every(r => !r.kernels && !r.attendance);
  return (
    <div className="club-board">
      <div className="club-board-head">
        <Segmented label="Leaderboard period" options={PERIODS} value={period} onChange={v => v && setPeriod(v)} />
        <ul className="club-board-legend" aria-label="Kernels from">
          {KERNEL_PARTS.map(p => <li key={p.key}><span className={`kbar-dot kbar-${p.key}`} aria-hidden="true" />{p.label}</li>)}
        </ul>
      </div>
      {error && <p className="pv-empty">Couldn't load the leaderboard right now.</p>}
      {!data && !error && <p className="pv-empty">Loading…</p>}
      {data && data.superlatives.length > 0 && (
        <ul className="club-superlatives" aria-label="Superlatives">
          {data.superlatives.map(s => (
            <li key={s.key} className="club-superlative" title={`Most ${s.what}`}>
              <span className="club-superlative-emoji" aria-hidden="true">{s.emoji}</span>
              <span><strong>{s.title}</strong> <PersonLink user={s.user} />
                <span className="ui-hint"> {s.key === "sharpshooter" ? `${s.value}% right` : `${s.value} ${s.what}`}</span></span>
            </li>
          ))}
        </ul>
      )}
      {data && quiet && (
        <p className="pv-empty">Nothing yet {period === "all" ? "" : `this ${period}`} — vote in a scored poll, play a game or
          check in after a screening. 🍿</p>
      )}
      {data && !quiet && (
        <ol className="club-board-rows">
          {rows.map((r, i) => (
            <li key={r.user.id} className={`club-board-row${r.user.id === viewerId ? " me" : ""}`}>
              <div className="club-board-main">
                <span className="club-rank">{medal(r.place, r.kernels)}</span>
                <Avatar user={r.user} size={34} link />
                <span className="club-board-who">
                  <PersonLink user={r.user} className="club-row-name" />
                  <KernelBar breakdown={r.breakdown} total={r.kernels} most={most} />
                </span>
                <span className="club-score"><strong>🍿 {r.kernels}</strong>
                  <small>{r.correct} correct · {r.attendance} screening{r.attendance === 1 ? "" : "s"}</small></span>
              </div>
              <details className="club-board-more">
                <summary>Stats</summary>
                <Stats s={r.stats} />
              </details>
            </li>
          ))}
        </ol>
      )}
      <p className="ui-hint">Kernels from scored polls, going out (check in after a screening, be first to go, crew nights),
        trivia and bingo (when they're on) and what members give each other — counted in the period they were earned.
        Ties: correct picks, then screenings.</p>
    </div>
  );
}

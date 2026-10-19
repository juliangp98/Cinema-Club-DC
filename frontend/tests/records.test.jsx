import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ClubBingo, MemberGames, RecordsTab } from "../src/components/GameRecords";
import { mockApi, renderPage } from "./support";

// Members' games (7g): everyone's bingo card on Play (tap one for theirs),
// Records (you, everyone, the club) and a member's Games on their page.

const stats = (t, b, q) => ({ trivia: { answered: t[0], correct: t[1], accuracy: 0, streak: t[2] }, bingo: { lines: b[0], cards: b[1] },
                              quizzes: { rounds: q[0], best_streak: q[1], right: q[2] } });
const row = (id, name, s, correct) => ({ user: { id, name }, kernels: 0, place: 1, correct, attendance: 0, breakdown: {}, stats: s });
const group = { id: 1, trivia: { enabled: true }, bingo: { enabled: true }, quizzes: { higher_lower: true, who_said: false } };
const board = { period: "month", superlatives: [], rows: [
  row(1, "Ana", stats([10, 8, 4], [1, 0], [3, 7, 0]), 5),
  row(2, "Bo", stats([10, 9, 2], [2, 1], [5, 12, 1]), 2),
] };
const card = (filled, line) => ({ filled, line, full: false, cells: [true, true, true, false, true, false, false, false, false] });

test("records: yours, everyone's sortable, the club's", async () => {
  const calls = mockApi({ "GET /api/groups/1/leaderboard": board });
  renderPage(<RecordsTab apiBase="" group={group} viewerId={1} />);
  const you = await screen.findByRole("list", { name: "Your records" });
  expect(within(you).getAllByRole("listitem").map(li => li.textContent))
    .toEqual(["Trivia80%8 of 10 · best streak 4", "Bingo1 line0 full cards", "Higher or lower7best streak", "Quiz games0right · 3 rounds", "Polls5right picks"]);
  const table = screen.getByRole("table");
  const names = () => within(table).getAllByRole("row").slice(1).map(r => r.cells[0].textContent);
  expect(names()).toEqual(["Bo", "You"]);                                          // by trivia: 90% first
  await userEvent.click(within(table).getByRole("button", { name: "Polls" }));
  expect(names()).toEqual(["You", "Bo"]);
  expect(within(screen.getByRole("list", { name: "The club's records" })).getByText("20")).toBeInTheDocument();   // trivia answered
  await userEvent.click(screen.getByRole("button", { name: "All time" }));
  expect(calls.at(-1).path).toBe("/api/groups/1/leaderboard?period=all");
});

test("everyone's card this month, and a tap opens theirs", async () => {
  mockApi({
    "GET /api/bingo/club": { enabled: true, month_label: "October", cards: [{ user: { id: 2, name: "Bo" }, ...card(5, true) },
                                                                             { user: { id: 1, name: "Ana" }, ...card(2, false) }] },
    "GET /api/bingo/people/2": { enabled: true, month_label: "October 2026", filled: 5, line: true, full: false, cells: card(5).cells,
      squares: [{ key: "film", emoji: "🎞️", label: "On film", hint: "h", done: true, by: { title: "VERTIGO", start_time: "2026-10-03T19:00:00", theatre: "AFI" } }],
      history: [{ month: "2026-09", month_label: "Sep", filled: 8, line: true, full: true, cells: Array(9).fill(true) }] },
  });
  renderPage(<ClubBingo apiBase="" groupId={1} viewerId={1} />);
  const bo = await screen.findByRole("button", { name: "Bo's card: a line" });
  expect(screen.getByRole("button", { name: "Your card: 2 of 8" })).toHaveTextContent("You");
  await userEvent.click(bo);
  expect(await screen.findByText("✓ VERTIGO")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Sep: full card" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Bo's page →" })).toHaveAttribute("href", "/people/2");
});

test("a member's games on their page — only when they're in your club", async () => {
  mockApi({ "GET /api/groups/1/leaderboard": { ...board, period: "all" },
            "GET /api/bingo/people/2": { enabled: false } });
  const { unmount } = renderPage(<MemberGames apiBase="" group={group} userId={2} name="Bo" />);
  expect(await screen.findByRole("list", { name: "Bo's records" })).toHaveTextContent("Higher or lower12best streak");
  unmount();
  renderPage(<MemberGames apiBase="" group={group} userId={9} name="Stranger" />);
  await new Promise(r => setTimeout(r, 50));
  expect(screen.queryByRole("heading", { name: "Games" })).toBeNull();
});

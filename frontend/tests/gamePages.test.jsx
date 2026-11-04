import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BingoPage, HigherLowerPage, TriviaPage } from "../src/components/GamePages";
import { mockApi, renderPage } from "./support";

// Play's game pages (Phase 3): the game on top, then your numbers for a
// period, your history and the club's board (you in gold), and the modes:
// an anytime question's level, Higher or lower's decade.

const me = { id: 1, name: "Dee" }, bo = { id: 2, name: "Bo" };
const levels = { easy: { answered: 2, correct: 2 }, medium: { answered: 1, correct: 0 }, hard: { answered: 0, correct: 0 } };
const TRIVIA = {
  enabled: true, anytime: true, period: "month",
  you: { answered: 3, correct: 2, accuracy: 67, streak: 2, best_streak: 4, kernels: 5, levels },
  history: [{ id: 9, day: "2026-11-03", prompt: "Who directed VERTIGO?", daily: true, difficulty: "medium", correct: false,
              yours: "Lang", answer: "Hitchcock" }],
  board: [{ user: bo, answered: 5, correct: 4, accuracy: 80, streak: 3 }, { user: me, answered: 3, correct: 2, accuracy: 67, streak: 4 }],
};

test("trivia: your numbers by difficulty, your answers, the club; the next question's level", async () => {
  const calls = mockApi({
    "GET /api/trivia/today": { enabled: true, daily: true, anytime: true, question: null },
    "GET /api/play/trivia": TRIVIA,
    "POST /api/trivia/another": { id: 11, prompt: "Who's in HEAT?", options: ["A", "B", "C", "D"], kernels: 2, anytime: true,
                                  difficulty: "hard", kernels_left_today: 5 },
  });
  renderPage(<TriviaPage apiBase="" groupId={1} role="member" viewerId={1} />);
  const you = await screen.findByRole("list", { name: "Your trivia" });
  expect(you).toHaveTextContent("Right2of 3 answered");
  expect(screen.getByLabelText("By difficulty")).toHaveTextContent("Easy2 of 2Medium0 of 1");     // hard: none yet
  expect(screen.getByText(/You said Lang; it was/)).toHaveTextContent("You said Lang; it was Hitchcock.");
  const rows = within(screen.getByRole("table", { name: "The club's trivia" })).getAllByRole("row");
  expect(rows[2]).toHaveClass("me");
  expect(rows[2]).toHaveTextContent("2You267%4");
  expect(screen.getByRole("heading", { name: "The club, this month" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Hard" }));
  await userEvent.click(screen.getByRole("button", { name: /Play a question/ }));
  expect(calls.find(c => c.method === "POST").body).toEqual({ group_id: 1, difficulty: "hard" });
  await userEvent.click(screen.getByRole("button", { name: "This year" }));
  expect(calls.at(-1).path).toBe("/api/play/trivia?group_id=1&period=year");
});

const game = { kind: "higher_lower", emoji: "↕️", label: "Higher or lower", blurb: "Before or after?", each: 1, cap: 5,
               earned_today: 0, best: 3, round: null };
const HL = {
  enabled: true, period: "month", left_today: 4,
  modes: [{ value: null, label: "Classic" }, { value: 1970, label: "1970s" }, { value: 1980, label: "1980s" }],
  you: { runs: 2, best: 3, average: 2, right: 4, kernels: 4, by_mode: [{ label: "Classic", best: 3 }, { label: "1970s", best: 1 }] },
  history: [{ id: 5, day: "2026-11-03", score: 3, earned: 3, mode: "Classic" }],
  board: [{ user: me, best: 3, runs: 2 }],
};

test("higher or lower: pick a decade, play it, and your runs by decade", async () => {
  const calls = mockApi({
    "GET /api/play/higher-lower": HL, "GET /api/quizzes": { games: [game] },
    "POST /api/quizzes/start": { id: 6, kind: "higher_lower", label: "Higher or lower", emoji: "↕️", done: false, score: 0, earned: 0,
                                 each: 1, left_today: 4, last: null, history: [], decade: "1970s",
                                 current: { key: "a", title: "Jaws", year: 1975 }, next: { key: "b", title: "Alien", year: null } },
  });
  renderPage(<HigherLowerPage apiBase="" groupId={1} viewerId={1} canRun={false} />);
  expect(await screen.findByLabelText("Best by decade")).toHaveTextContent("Classic31970s1");
  expect(screen.getByRole("link", { name: "‹ All the games" })).toHaveAttribute("href", "/play/games");
  await userEvent.selectOptions(screen.getByRole("combobox", { name: "Which films" }), "The 1970s");
  await userEvent.click(await screen.findByRole("button", { name: "▶ Play" }));
  expect(calls.find(c => c.method === "POST").body).toEqual({ group_id: 1, kind: "higher_lower", decade: 1970 });
  expect(await screen.findByText("Streak: 0, in the 1970s")).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "The club's best streaks" })).toHaveTextContent("1You32");
});

test("higher or lower off: a note, and the switch for those who run the club", async () => {
  mockApi({ "GET /api/play/higher-lower": { ...HL, enabled: false }, "GET /api/quizzes": { games: [] } });
  renderPage(<HigherLowerPage apiBase="" groupId={1} viewerId={1} canRun />);
  expect(await screen.findByRole("link", { name: "Turn it on in Club settings" })).toHaveAttribute("href", "/club?tab=settings#settings-games");
});

test("bingo: your numbers, your best, your past cards and the club", async () => {
  mockApi({
    "GET /api/bingo": { enabled: false }, "GET /api/bingo/club": { enabled: false },
    "GET /api/play/bingo": {
      enabled: true, period: "all",
      you: { played: 3, lines: 2, cards: 1, kernels: 25, best: { month: "2026-09", label: "September 2026", filled: 8 },
             favorite: { label: "On film", count: 3 } },
      history: [{ month: "2026-10", month_label: "October 2026", filled: 4, line: true, full: false, cells: Array(9).fill(false) }],
      board: [{ user: me, played: 3, lines: 2, cards: 1, kernels: 25 }],
    },
  });
  renderPage(<BingoPage apiBase="" groupId={1} role="member" viewerId={1} />);
  expect(await screen.findByRole("list", { name: "Your bingo" })).toHaveTextContent("Full cards1");
  expect(screen.getByLabelText("Your best")).toHaveTextContent("Best monthSeptember 2026, 8 of 8Most filledOn film (3)");
  expect(screen.getByRole("img", { name: "October 2026: a line" })).toBeInTheDocument();
  expect(screen.getByRole("table", { name: "The club's bingo" })).toHaveTextContent("1You1225");
});

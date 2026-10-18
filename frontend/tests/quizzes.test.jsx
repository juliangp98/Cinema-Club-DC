import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import QuizGames from "../src/components/QuizGames";
import ClubSettings from "../src/components/ClubSettings";
import { mockApi, renderPage } from "./support";

// Quiz games on Play (R15): each one the club has on, played in place.

const film = (key, title, year) => ({ key, title, year, poster_url: null });
const game = { kind: "higher_lower", emoji: "↕️", label: "Higher or lower", blurb: "Before or after?", each: 1, cap: 5,
               earned_today: 0, best: 0, round: null };
const round = (extra = {}) => ({ id: 4, kind: "higher_lower", label: "Higher or lower", emoji: "↕️", done: false, score: 0,
                                 earned: 0, each: 1, left_today: 5, last: null, history: [],
                                 current: film("a", "Vertigo", 1958), next: film("b", "Alien", null), ...extra });

test("higher or lower: start, call it, and the run goes on", async () => {
  const calls = mockApi({
    "GET /api/quizzes": { games: [game] },
    "POST /api/quizzes/start": round(),
    "POST /api/quizzes/answer": round({ score: 1, earned: 1, left_today: 4, last: { right: true, paid: 1 },
                                        history: [film("a", "Vertigo", 1958)], current: film("b", "Alien", 1979),
                                        next: film("c", "Heat", null) }),
  });
  renderPage(<QuizGames apiBase="" groupId={1} canRun={false} />);
  await userEvent.click(await screen.findByRole("button", { name: "▶ Play" }));
  const group = await screen.findByRole("group", { name: "Did Alien come out before or after 1958?" });
  await userEvent.click(within(group).getByRole("button", { name: "After 1958 ➡️" }));
  expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/quizzes/answer", body: { group_id: 1, round_id: 4, choice: "after" } });
  expect(await screen.findByRole("status")).toHaveTextContent("✅ Right! +1 🍿");
  expect(screen.getByRole("button", { name: "⬅️ Before 1979" })).toBeInTheDocument();          // the next call
  expect(screen.getByText(/4 left today/)).toBeInTheDocument();
});

test("none on: organizers see where to turn them on", async () => {
  mockApi({ "GET /api/quizzes": { games: [] } });
  renderPage(<QuizGames apiBase="" groupId={1} canRun />);
  expect(await screen.findByRole("link", { name: "Turn them on in Club settings" })).toHaveAttribute("href", "/club?tab=settings#settings-games");
});

test("each game is its own switch in Club settings", async () => {
  const group = { id: 1, slug: "club", name: "Club", discord: false, theatres: [], trivia: { enabled: false }, bingo: { enabled: false },
                  notes: { enabled: false }, quizzes: { higher_lower: false, who_said: true } };
  const calls = mockApi({ "GET /api/theatres": [], "GET /api/groups/club/members": [], "GET /api/groups/club/game-posts": { waiting: [], skipped: [] },
                          "PUT /api/groups/club": body => ({ ...group, ...body }) });
  renderPage(<ClubSettings group={group} apiBase="" viewerId={1} isAdmin onChanged={() => {}} />, { route: "/club?tab=settings" });
  const hl = await screen.findByRole("checkbox", { name: /Higher or lower/ });
  expect(hl).not.toBeChecked();
  expect(screen.getByRole("checkbox", { name: /Who said it/ })).toBeChecked();
  await userEvent.click(hl);
  expect(calls.find(c => c.method === "PUT").body).toEqual({ quizzes: { higher_lower: true } });
});

test("guess from the reviews: another review costs a kernel, the source is said but no one's named", async () => {
  const rev = (extra = {}) => ({ id: 9, kind: "reviews", label: "Guess from the reviews", emoji: "📝", done: false, score: 0, earned: 0,
                                 each: 3, by_step: true, left_today: 5, last: null, step: 1, steps: 3, worth: 3,
                                 clues: [{ text: "The score alone will follow you home.", from: "club" }],
                                 options: ["Vertigo (1958)", "Psycho (1960)", "The Birds (1963)", "Rear Window (1954)"], ...extra });
  const calls = mockApi({
    "GET /api/quizzes": { games: [{ ...game, kind: "reviews", label: "Guess from the reviews", emoji: "📝", each: 3, by_step: true }] },
    "POST /api/quizzes/start": rev(),
    "POST /api/quizzes/answer": body => (body.choice === "more"
      ? rev({ step: 2, worth: 2, clues: [...rev().clues, { text: "Dreamy, sad and perfectly made.", from: "tmdb" }] })
      : rev({ done: true, step: 2, worth: 2, answer: 0, film: { title: "Vertigo", year: 1958 }, last: { right: true, paid: 2 },
              clues: [...rev().clues, { text: "Dreamy, sad and perfectly made.", from: "tmdb" }] })),
  });
  renderPage(<QuizGames apiBase="" groupId={1} canRun={false} />);
  expect(await screen.findByText("3 / 2 / 1 🍿 · 5 left today")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "▶ Play" }));
  expect(await screen.findByText(/from a club member's diary/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "📝 Another review (then worth 2)" }));
  expect(await screen.findByText(/from a review on TMDB/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /Vertigo \(1958\)/ }));
  expect(calls.at(-1).body).toEqual({ group_id: 1, round_id: 9, choice: 0 });
  expect(await screen.findByRole("status")).toHaveTextContent("✅ Right! +2 🍿");
});

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PlayPage from "../src/pages/PlayPage";
import { LeftToday } from "../src/components/PlaySide";
import { mockApi, renderPage } from "./support";

// Your kernels, the month's board and the week's movers follow what you earn
// as you play — no page refresh — and Play counts what's still on the table today.

const RULES = { went: 5, planned: 2, trailblazer_max: 5, crew_min: 3, crew: 3, give: 10, take: 3, trivia: null,
                trivia_anytime: null, bingo: null, games: [{ label: "Who said it", each: 1, per_day: 5, by_step: false }] };
const me = { id: 7, name: "Dee" };
const kernels = (n, left) => ({ kernels: n, polls: 0, going_out: 0, trivia: 0, bingo: 0, games: n, members: 0,
                                allowance: { give_left: 10, take_left: 3 }, rules: RULES,
                                today: { total: left, parts: left ? [{ key: "who_said", label: "Who said it", left, to: "/play#games" }] : [] } });
const row = (n, place = 1) => ({ user: me, kernels: n, place });
const who = (extra = {}) => ({ id: 3, kind: "who_said", label: "Who said it", emoji: "🗣️", done: false, score: 0, earned: 0, each: 1,
                               left_today: 5, last: null, quote: "Here's looking at you, kid.", film: { title: "Casablanca", year: 1942 },
                               options: ["Rick", "Ilsa", "Victor", "Louis"], ...extra });

test("a game that pays updates your kernels, the month's board and the movers at once", async () => {
  let earned = 0;
  mockApi({
    "GET /api/kernels": () => kernels(earned, 5 - earned),
    "GET /api/groups/1/leaderboard": () => ({ rows: [row(earned)] }),
    "GET /api/trivia/today": { enabled: false },
    "GET /api/bingo": { enabled: false },
    "GET /api/bingo/club": { cards: [] },
    "GET /api/groups/1/polls": [],
    "GET /api/quizzes": { games: [{ kind: "who_said", emoji: "🗣️", label: "Who said it", blurb: "", each: 1, cap: 5, earned_today: 0,
                                    best: 0, round: who() }] },
    "POST /api/quizzes/answer": () => { earned = 1; return who({ done: true, answer: 0, score: 1, earned: 1, left_today: 4, last: { right: true, paid: 1 } }); },
  });
  renderPage(<PlayPage user={me} apiBase="" groupId={1} />, { route: "/play", shell: { role: "member" } });
  const side = await screen.findByRole("complementary", { name: "Kernels and standings" });
  const panel = title => within(side).getByText(title).closest(".ui-panel");
  await within(side).findByText("Your kernels");
  expect(within(panel("Your kernels")).getByText("🍿 0")).toBeInTheDocument();
  expect(within(panel("Still on the table today")).getByText("🎯 5")).toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: /Rick/ }));
  expect(await within(panel("Your kernels")).findByText("🍿 1")).toBeInTheDocument();         // your total
  expect(await within(panel("Still on the table today")).findByText("🎯 4")).toBeInTheDocument();
  expect(await within(panel("This month")).findByText("🍿 1")).toBeInTheDocument();           // this month's board
  expect(await within(panel("This week's movers")).findByText("+1")).toBeInTheDocument();      // and the movers
});

test("still on the table today: each game's kernels, then a well done", () => {
  const { unmount } = renderPage(<LeftToday k={kernels(2, 3)} />);
  expect(screen.getByText("Still on the table today")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Who said it" })).toHaveAttribute("href", "#games");
  expect(screen.getByText("+3")).toBeInTheDocument();
  unmount();
  const { unmount: again } = renderPage(<LeftToday k={kernels(5, 0)} />);
  expect(screen.getByText(/You've earned every game kernel there is today/)).toBeInTheDocument();
  again();
  const { container } = renderPage(<LeftToday k={{ ...kernels(0, 0), rules: { ...RULES, games: [] } }} />);
  expect(container).toBeEmptyDOMElement();                                                   // no daily games in this club
});

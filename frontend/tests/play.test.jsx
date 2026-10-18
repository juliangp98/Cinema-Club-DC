import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { GamesRunPanel, KernelStrip, Movers, MonthBoard, YourKernels } from "../src/components/PlaySide";
import { mockApi, renderPage } from "./support";

// Play's side (R15): your kernels, this month's standings with you in them,
// this week's movers, your numbers as a strip on phones — and the games their
// organizers run, skipped posts included.

const row = (id, kernels) => ({ user: { id, name: `M${id}` }, kernels });
const month = [row(1, 50), row(2, 40), row(3, 30), row(4, 20), row(5, 10), row(6, 5), row(7, 3)];
const k = { kernels: 42, polls: 2, going_out: 30, trivia: 4, bingo: 5, members: 1, allowance: { give_left: 8, take_left: 3 },
  rules: { went: 5, planned: 2, trailblazer_max: 5, crew_min: 3, crew: 3, give: 10, trivia: 2, trivia_anytime: null, bingo: null } };

test("your kernels: all time by source, this month's place, what's left to give", () => {
  renderPage(<YourKernels k={k} month={month} viewerId={7} />);
  expect(screen.getByText("🍿 42")).toBeInTheDocument();
  expect(screen.getByRole("img")).toHaveAttribute("aria-label", "polls 2, going out 30, trivia 4, bingo 5, from members 1");
  expect(screen.getByText("This month: 🍿 3 · #7 in the club")).toBeInTheDocument();
  expect(screen.getByText(/8 to give · 3 to take/)).toBeInTheDocument();
});

test("this month: the top five, then you if you're further down", () => {
  const { container } = renderPage(<MonthBoard month={month} viewerId={7} />);
  const items = screen.getAllByRole("listitem");
  expect(items.map(li => li.textContent)).toEqual(["1M1M1🍿 50", "2M2M2🍿 40", "3M3M3🍿 30", "4M4M4🍿 20", "5M5M5🍿 10", "7M7M7🍿 3"]);
  expect(container.querySelector(".play-board-gap")).toHaveTextContent("⋯");        // a gap before you
  expect(items.at(-1)).toHaveClass("me");
  expect(screen.getByRole("link", { name: "Full leaderboard →" })).toHaveAttribute("href", "/club?tab=leaderboard");
});

test("this week's movers: the three who earned most since Monday", () => {
  const { unmount } = renderPage(<Movers week={[row(3, 14), row(1, 9), row(2, 2), row(4, 1)]} viewerId={1} />);
  expect(screen.getAllByRole("listitem").map(li => li.textContent)).toEqual(["1M3M3+14", "2M1M1+9", "3M2M2+2"]);
  unmount();
  renderPage(<Movers week={[row(1, 0)]} viewerId={1} />);
  expect(screen.getByText(/No kernels yet this week/)).toBeInTheDocument();
});

test("phones: your numbers in one strip", () => {
  renderPage(<KernelStrip k={k} month={month} viewerId={2} />);
  const strip = screen.getByRole("navigation", { name: "Your kernels" });
  expect(within(strip).getByText("🍿 42")).toBeInTheDocument();
  expect(within(strip).getByRole("link", { name: "#2 this month" })).toHaveAttribute("href", "/club?tab=leaderboard");
});

test("running the games: what's waiting, and a skipped post posted after all", async () => {
  const skipped = { id: 9, kind: "trivia", status: "skipped", until: "10 PM" };
  const calls = mockApi({
    "GET /api/groups/club/game-posts": { waiting: [{ id: 8, kind: "bingo_card", status: "waiting", month_label: "October 2026" }],
                                         skipped: [skipped] },
    "POST /api/groups/club/game-posts/9": { ...skipped, status: "approved", until: undefined },
  });
  renderPage(<GamesRunPanel apiBase="" slug="club" />);
  expect(await screen.findByRole("link", { name: "👀 1 waiting for your OK →" })).toHaveAttribute("href", "/club?tab=settings#game-posts");
  expect(screen.getByText(/skipped — it can still go up until 10 PM/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Post it after all" }));
  expect(calls.find(c => c.method === "POST").body).toEqual({ action: "post" });
  expect(screen.queryByRole("button", { name: "Post it after all" })).toBeNull();
});

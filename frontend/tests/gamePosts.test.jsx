import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ClubSettings from "../src/components/ClubSettings";
import GamePostsWaiting from "../src/components/GamePostsWaiting";
import { mockApi, renderPage, reply } from "./support";

// The games' Discord posts (R14): Never / Ask first / Always in Club
// settings, and posts waiting for an admin's OK, shown as they'll look.

const QUESTION = { kind: "trivia", id: 3, status: "waiting", can_swap: true, answer: 1,
  question: { id: 9, prompt: "Who directed VERTIGO?", options: ["Lang", "Hitchcock", "Wilder", "Ford"] } };
const CARD = { kind: "bingo_card", id: 4, status: "waiting", month_label: "October 2026",
  squares: [{ key: "film", emoji: "🎞️", label: "On film", hint: "35mm, 16mm or 70mm" }] };

test("a waiting question: the answer shown for checking; post, swap or skip", async () => {
  const calls = mockApi({
    "GET /api/groups/club/game-posts": { waiting: [QUESTION, CARD] },
    "POST /api/groups/club/game-posts/3": body => (body.action === "another"
      ? { ...QUESTION, question: { ...QUESTION.question, prompt: "Who's in PSYCHO?" } } : { ...QUESTION, status: "approved" }),
  });
  renderPage(<GamePostsWaiting apiBase="" slug="club" />);
  const q = await screen.findByRole("region", { name: /question of the day/ });
  expect(within(q).getByText("Hitchcock").closest("li")).toHaveClass("right");
  await userEvent.click(within(q).getByRole("button", { name: "Try another" }));
  expect(calls.at(-1).body).toEqual({ action: "another" });
  expect(await within(q).findByText("Who's in PSYCHO?")).toBeInTheDocument();
  await userEvent.click(within(q).getByRole("button", { name: "Post it" }));
  expect(screen.queryByRole("region", { name: /question of the day/ })).toBeNull();   // on its way: off the list
  const card = screen.getByRole("region", { name: /bingo card/ });
  expect(within(card).getByRole("button", { name: "Reshuffle" })).toBeInTheDocument();
  expect(within(card).queryByRole("button", { name: "Try another" })).toBeNull();
});

test("a question someone answered can't be swapped; errors show", async () => {
  mockApi({ "GET /api/groups/club/game-posts": { waiting: [{ ...QUESTION, can_swap: false }] },
            "POST /api/groups/club/game-posts/3": reply(400, { error: "Too late for that one." }) });
  renderPage(<GamePostsWaiting apiBase="" slug="club" />);
  expect(await screen.findByRole("button", { name: "Try another" })).toBeDisabled();
  await userEvent.click(screen.getByRole("button", { name: "Skip" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Too late for that one.");
});

test("nothing waiting: nothing shown", async () => {
  mockApi({ "GET /api/groups/club/game-posts": { waiting: [] } });
  const { container } = renderPage(<GamePostsWaiting apiBase="" slug="club" />);
  await new Promise(r => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
});

test("Club settings: each game post is Never / Ask first / Always (wins Never / Always)", async () => {
  const group = { id: 1, slug: "club", name: "Club", discord: true, theatres: [],
    trivia: { enabled: true, anytime: false, post: "never" }, bingo: { enabled: true, card_post: "never", wins_post: "never" },
    notes: { enabled: false } };
  const calls = mockApi({ "GET /api/theatres": [], "GET /api/groups/club/members": [], "GET /api/groups/club/game-posts": { waiting: [] },
                          "PUT /api/groups/club": body => ({ ...group, ...body }) });
  renderPage(<ClubSettings group={group} apiBase="" viewerId={1} onChanged={() => {}} />);
  const triviaCard = (await screen.findByText("🧠 Trivia: question of the day")).closest(".game-setting");   // on the game's own card (7g)
  const trivia = within(triviaCard).getByRole("group", { name: "Post it in Discord" });
  expect(within(trivia).getByRole("button", { name: "Never" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(trivia).getByRole("button", { name: "Ask first" }));
  expect(calls.find(c => c.method === "PUT").body).toEqual({ trivia_post: "ask" });
  const wins = screen.getByRole("group", { name: "Post wins" });
  expect(within(wins).getAllByRole("button").map(b => b.textContent)).toEqual(["Never", "Always"]);
  expect(screen.getByRole("group", { name: "Post each month's card" })).toBeInTheDocument();
});

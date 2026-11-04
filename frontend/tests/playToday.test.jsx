import { screen, within } from "@testing-library/react";
import { Route, Routes, useLocation } from "react-router-dom";
import PlayPage from "../src/pages/PlayPage";
import { mockApi, renderPage } from "./support";

// Play is a hub: Today lists what's waiting on you (one button each), then a
// tile per part; each part is its own page. Links from before (/play#trivia,
// ?tab=records) land on the new pages.

const me = { id: 7, name: "Dee" };
const SUMMARY = {
  trivia: { to_answer: true, waiting: false, anytime: false, answered: false, correct: false },
  bingo: { month_label: "November", filled: 5, line: true, full: false, cells: [] },
  polls: [{ id: 4, title: "Election night", you_voted: false }, { id: 5, title: "Oscars", you_voted: true }],
  challenges: { invites: [{ id: 9, by: "Ana", game: "🧠 Trivia" }], your_turn: [{ id: 8, game: "🏆 Winners' round 1", against: "Bo" }],
                tournaments: [] },
  kernels: { kernels: 14, allowance: { give_left: 10, take_left: 3 }, today: { total: 6 } },
};

function Where() {
  const { pathname } = useLocation();
  return <p data-testid="where">{pathname}</p>;
}

const play = route => {
  const page = <><PlayPage user={me} apiBase="" groupId={1} /><Where /></>;
  return renderPage(<Routes><Route path="/play" element={page} /><Route path="/play/:section" element={page} /></Routes>,
                    { route, shell: { role: "member" } });
};

test("Today: what's waiting on you first, then a tile for each part", async () => {
  mockApi({ "GET /api/play": SUMMARY, "GET /api/kernels": null, "GET /api/groups/1/leaderboard": { rows: [] } });
  play("/play");
  const turn = within(await screen.findByRole("region", { name: "Your turn" }));
  expect(turn.getAllByRole("listitem").map(li => li.textContent)).toEqual([
    "⚔️Ana challenged you: 🧠 TriviaAnswer", "⚔️Your turn vs Bo: 🏆 Winners' round 1Play", "🧠Today's trivia questionAnswer",
    "🗳️Election nightVote"]);
  expect(turn.getByRole("link", { name: "Vote" })).toHaveAttribute("href", "/polls/4");
  const tiles = within(screen.getByRole("list", { name: "Play" }));
  const line = name => tiles.getByRole("link", { name: new RegExp(`^${name}`) });
  expect(line("Challenges")).toHaveTextContent("2 things waiting for you");
  expect(line("Challenges")).toHaveClass("hot");
  expect(line("Trivia")).toHaveTextContent("Today's question is waiting");
  expect(line("Bingo")).toHaveTextContent("5 of 8, a line! 🎉");
  expect(line("Polls")).toHaveTextContent("1 to vote in");
  expect(line("Games")).toHaveAttribute("href", "/play/games");
  expect(line("Games")).toHaveTextContent("6 🍿 left to earn today");
  const tabs = within(screen.getByRole("navigation", { name: "Play" }));
  expect(tabs.getAllByRole("link").map(a => a.textContent)).toEqual(
    ["Today", "Challenges", "Trivia", "Bingo", "Polls", "Games", "Records", "Kernels"]);
  expect(tabs.getByRole("link", { name: "Today" })).toHaveClass("active");
});

test("caught up: a line saying so", async () => {
  mockApi({ "GET /api/play": { ...SUMMARY, trivia: null, polls: [], challenges: null }, "GET /api/kernels": null,
            "GET /api/groups/1/leaderboard": { rows: [] } });
  play("/play");
  expect(await screen.findByText(/You're all caught up/)).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Challenges/, hidden: false, exact: false })).not.toBeNull();   // the tab
  expect(within(screen.getByRole("list", { name: "Play" })).queryByRole("link", { name: /Trivia/ })).toBeNull();   // off, and you don't run the club
});

test("old links land on the new pages", async () => {
  mockApi({ "GET /api/play": SUMMARY, "GET /api/kernels": null, "GET /api/groups/1/leaderboard": { rows: [] },
            "GET /api/trivia/today": { enabled: false } });
  const { unmount } = play("/play#trivia");
  expect(await screen.findByTestId("where")).toHaveTextContent("/play/trivia");
  unmount();
  mockApi({ "GET /api/play": SUMMARY, "GET /api/kernels": null, "GET /api/groups/1/leaderboard": { rows: [] } });
  play("/play?tab=records");
  expect(await screen.findByTestId("where")).toHaveTextContent("/play/records");
});

test("the Kernels page: the boards in their grid, the page itself left as a page", async () => {
  mockApi({ "GET /api/kernels": null, "GET /api/groups/1/leaderboard": { rows: [] } });
  const { container } = play("/play/kernels");
  expect(container.querySelector(".play-page")).toHaveClass("play-on-kernels");
  expect(container.querySelectorAll(".play-kernels")).toHaveLength(1);           // only the boards' grid, not the page
  expect(container.querySelector(".play-page")).not.toHaveClass("play-kernels");
});

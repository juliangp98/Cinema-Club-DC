import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import PollList from "../src/components/PollList";
import PersonPage from "../src/pages/PersonPage";
import Avatar from "../src/ui/Avatar";
import { mockApi, renderPage, reply } from "./support";

// Page flow (R15): polls live on Play; every member has a page, and their
// picture and name lead there.

const poll = (id, status, extra = {}) => ({ id, title: `Poll ${id}`, status, poll_type: "standard", scoring_mode: "none",
                                            category_count: 2, you_picked: 0, voters: 1, ...extra });

test("Play's polls: open ones as cards, the latest three past ones, the rest a tap away", async () => {
  mockApi({ "GET /api/groups/1/polls": [poll(1, "open", { you_picked: 1 }), poll(2, "scored"), poll(3, "closed"),
                                         poll(4, "scored"), poll(5, "closed")] });
  renderPage(<PollList apiBase="" groupId={1} canRun={false} />);
  const open = await screen.findByText("Poll 1");
  expect(open.closest(".pv-card")).toHaveTextContent("1 of 2 picked");
  expect(within(open.closest(".pv-card")).getByRole("button", { name: "Continue" })).toBeInTheDocument();
  expect(screen.getByText("Past polls")).toBeInTheDocument();
  expect(screen.queryByText("Poll 5")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Show all 4 past polls" }));
  expect(screen.getByText("Poll 5")).toBeInTheDocument();
});

test("no open polls: organizers get a way to start one", async () => {
  mockApi({ "GET /api/groups/1/polls": [] });
  renderPage(<PollList apiBase="" groupId={1} canRun />);
  expect(await screen.findByRole("link", { name: "Start one →" })).toHaveAttribute("href", "/polls/new");
});

const me = { id: 1, name: "Ana" };
const page = (route, routes = {}) => {
  mockApi(routes);
  return renderPage(
    <Routes>
      <Route path="/people/:id" element={<PersonPage user={me} apiBase="" groupId={1} />} />
      <Route path="/me" element={<p>my page</p>} />
    </Routes>, { route });
};

test("a member's page: who they are, kernels, taste, and Compare first", async () => {
  page("/people/2", {
    "GET /api/users/2/profile": { id: 2, name: "Bo", bio: "Rep cinema forever.", letterboxd_username: "bofilms",
                                  taste: { genres: ["Horror"], films: [], people: [], theatres: [], dislikes: [] },
                                  taste_match: { score: 72, shared: ["Horror"] } },
    "GET /api/users/2/kernels": { kernels: 14, breakdown: { polls: 2, going_out: 10, members: 2 } },
    "GET /api/users/2/compare": { name: "Bo", both_want: [], both_going: [], they_go_you_want: [], you_go_they_want: [],
                                  seen_together: [] },
  });
  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Bo");
  expect(screen.getByText("Rep cinema forever.")).toBeInTheDocument();
  expect(await screen.findByText(/14 kernels/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "‹ Members" })).toHaveAttribute("href", "/club?tab=members");
  expect(screen.getByRole("heading", { name: "Taste" })).toBeInTheDocument();
  expect(screen.getByRole("tab", { name: "Compare" })).toHaveAttribute("aria-selected", "true");
  expect(await screen.findByText(/Nothing lines up yet/)).toBeInTheDocument();
});

test("your own page is the Me page", async () => {
  page("/people/1");
  expect(await screen.findByText("my page")).toBeInTheDocument();
});

test("someone outside your clubs: a way back instead of an error", async () => {
  page("/people/9", { "GET /api/users/9/profile": reply(403, { error: "You do not share a group with this user" }) });
  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("Not in your clubs");
  expect(screen.getByRole("link", { name: "See your club's members →" })).toHaveAttribute("href", "/club?tab=members");
});

test("a member's picture links to their page", () => {
  renderPage(<Avatar user={{ id: 7, name: "Cy" }} link />);
  expect(screen.getByRole("link", { name: "Cy's profile" })).toHaveAttribute("href", "/people/7");
});

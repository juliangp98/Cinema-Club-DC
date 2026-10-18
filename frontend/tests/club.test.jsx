import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ClubSettings from "../src/components/ClubSettings";
import ClubBoard from "../src/components/ClubBoard";
import { ClubStats, MembersStrip } from "../src/components/ClubOverview";
import { mockApi, renderPage } from "./support";

// The Club page (R15): settings by role, the leaderboard by period, and the
// overview's people and numbers.

const group = { id: 1, slug: "club", name: "Club", discord: true, theatres: ["afi"],
  trivia: { enabled: true, anytime: false, post: "never" }, bingo: { enabled: false }, notes: { enabled: false } };
const person = (id, name, extra = {}) => ({ id: 10 + id, status: "active", role: "member", user: { id, name }, ...extra });
const settingsApi = () => mockApi({
  "GET /api/theatres": [{ slug: "afi", name: "AFI Silver", color: "#c33" }, { slug: "suns", name: "Suns", color: "#3c3" }],
  "GET /api/groups/club/members": [person(1, "Ana", { role: "admin" }), person(2, "Newt", { status: "pending" })],
  "GET /api/groups/club/game-posts": { waiting: [] },
  "PUT /api/groups/club": body => ({ ...group, ...body }),
});

test("organizers get theatres, join requests, games and Discord — not the club's details", async () => {
  const calls = settingsApi();
  renderPage(<ClubSettings group={group} apiBase="" viewerId={3} isAdmin={false} onChanged={() => {}} />, { route: "/club?tab=settings" });
  const jump = screen.getByRole("list", { name: "Settings sections" });
  expect(within(jump).getAllByRole("link").map(a => a.textContent)).toEqual(["Theatres", "Members & roles", "Games", "Discord"]);
  expect(await screen.findByText("Newt")).toBeInTheDocument();                         // join requests
  expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  expect(screen.queryByLabelText("Name")).toBeNull();                                 // admins'
  expect(screen.queryByText("Roles (1)")).toBeNull();
  expect(screen.queryByRole("button", { name: "Delete club" })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Suns" }));
  await userEvent.click(screen.getByRole("button", { name: "Save theatres" }));
  expect(calls.find(c => c.method === "PUT").body).toEqual({ theatres: ["afi", "suns"] });
});

test("admins get every section", async () => {
  settingsApi();
  renderPage(<ClubSettings group={group} apiBase="" viewerId={1} isAdmin onChanged={() => {}} />, { route: "/club?tab=settings" });
  const jump = screen.getByRole("list", { name: "Settings sections" });
  expect(within(jump).getAllByRole("link").map(a => a.textContent))
    .toEqual(["Club", "Theatres", "Members & roles", "Games", "Discord", "Look", "Danger zone"]);
  expect(within(jump).getByRole("link", { name: "Games" })).toHaveAttribute("href", "/club?tab=settings#settings-games");
  expect(await screen.findByText("Roles (1)")).toBeInTheDocument();
});

const stats = { screenings: 3, film_prints: 1, theatres: 2, late: 1, crew_nights: 0, week_streak: 2, first_going: 1,
  comments: 4, trivia: { answered: 10, correct: 9, accuracy: 90, streak: 5 }, bingo: { lines: 1, cards: 0 }, last_out: null };
const row = (id, name, kernels) => ({ user: { id, name }, kernels, correct: 1, attendance: 3, stats,
  breakdown: { polls: 1, going_out: kernels - 1, trivia: 0, bingo: 0, members: 0 } });

test("the leaderboard: a period, its superlatives, kernels as a bar, stats a tap away", async () => {
  const calls = mockApi({
    "GET /api/groups/1/leaderboard?period=month": { period: "month", rows: [row(1, "Ana", 12), row(2, "Bo", 6)],
      superlatives: [{ key: "night_owl", emoji: "🦉", title: "Night owl", what: "screenings at 9:30 PM or later", value: 2,
                       user: { id: 1, name: "Ana" } }] },
    "GET /api/groups/1/leaderboard?period=year": { period: "year", rows: [row(2, "Bo", 30), row(1, "Ana", 20)], superlatives: [] },
  });
  renderPage(<ClubBoard group={group} apiBase="" viewerId={2} />);
  expect(await screen.findByText("Night owl")).toBeInTheDocument();
  const rows = screen.getAllByRole("listitem").filter(li => li.classList.contains("club-board-row"));
  expect(rows.map(r => within(r).getAllByRole("link")[1].textContent)).toEqual(["Ana", "Bo"]);
  expect(within(rows[0]).getByRole("img")).toHaveAttribute("aria-label", "polls 1, going out 11");
  await userEvent.click(within(rows[0]).getByText("Stats"));
  expect(within(rows[0]).getByText("9/10 · 90%")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "This year" }));
  expect(await screen.findByText("Bo", { selector: ".club-board-row:first-child a.person-link" })).toBeInTheDocument();
  expect(calls.map(c => c.path)).toContain("/api/groups/1/leaderboard?period=year");
});

test("the overview's side: members (to their pages) and the month's numbers", async () => {
  const onAll = vi.fn();
  const members = Array.from({ length: 14 }, (_, i) => person(i + 1, `M${i + 1}`));
  renderPage(<>
    <MembersStrip members={members} onAll={onAll} />
    <ClubStats onBoard={() => {}} stats={{ month_label: "October", member_screenings: 7, screenings_together: 2,
      most_wanted: { movie: { id: 5, title: "VERTIGO" }, wanters: 3 },
      busiest_theatre: { theatre: { slug: "afi", name: "AFI Silver", short_name: "AFI" }, screenings: 4 },
      top: [{ user: { id: 1, name: "M1" }, kernels: 12 }] }} />
  </>);
  expect(screen.getByText("Members · 14")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "M1's profile" })).toHaveAttribute("href", "/people/1");
  await userEvent.click(screen.getByRole("button", { name: "+2" }));
  expect(onAll).toHaveBeenCalled();
  expect(screen.getByText("October in the club")).toBeInTheDocument();
  expect(screen.getByText(/7 screenings · 2 together/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "VERTIGO" })).toHaveAttribute("href", "/films/5");
});

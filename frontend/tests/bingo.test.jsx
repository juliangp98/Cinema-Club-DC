import { screen, within } from "@testing-library/react";
import BingoCard from "../src/ui/BingoCard";
import { mockApi, renderPage } from "./support";

// Repertory bingo (R10e): this month's card, filled in by check-ins.

const sq = (key, done, by) => ({ key, emoji: "🎞️", label: key, hint: `hint for ${key}`, done, by });
const CARD = {
  enabled: true, month_label: "October 2026", filled: 3, line: true, full: false, kernels: 5,
  rules: { line: 5, full: 15 }, club: [{ user: { id: 2, name: "Bo" }, filled: 4, line: true, full: false }],
  squares: [sq("film", true, { title: "VERTIGO", start_time: "2026-10-03T19:00:00", theatre: "AFI" }), sq("pre1960", true),
            sq("horror", false), sq("late", false), { key: "free", emoji: "🍿", label: "Free", hint: "On the house", done: true },
            sq("comedy", false), sq("matinee", false), sq("long", false), sq("double", false)],
};

test("the card: nine squares, what filled them, and how you're doing", async () => {
  mockApi({ "GET /api/bingo?group_id=1": CARD });
  renderPage(<BingoCard apiBase="" groupId={1} role="member" />);
  const card = await screen.findByRole("region", { name: "🎱 Repertory bingo · October 2026" });
  expect(card).toHaveClass("ui-panel", "ui-panel-gold");
  const cells = within(card).getAllByRole("listitem");
  expect(cells).toHaveLength(9);
  expect(cells[0]).toHaveClass("done");
  expect(cells[0]).toHaveTextContent("✓ VERTIGO");
  expect(cells[4]).toHaveClass("free");
  expect(within(card).getByText("🎉 Bingo! Now fill the whole card")).toBeInTheDocument();
  expect(within(card).getByText(/you've earned 5/)).toBeInTheDocument();
  expect(within(card).getByText("The club: Bo 4/8 🎉")).toHaveClass("ui-hint");
});

test("off: only admins see where to turn it on", async () => {
  mockApi({ "GET /api/bingo?group_id=1": { enabled: false } });
  renderPage(<BingoCard apiBase="" groupId={1} role="admin" />);
  expect(await screen.findByRole("link", { name: "Turn it on in Club settings" })).toBeInTheDocument();
});

test("home viewing (R15): a square a diary entry filled, and how it counts", async () => {
  const squares = CARD.squares.map((s, i) => (i === 1 ? { ...s, home: { title: "OLD DOC", watched_on: "2026-10-05", link: "" } } : s));
  mockApi({ "GET /api/bingo?group_id=1": { ...CARD, squares, rules: { line: 5, full: 15, home: true, home_line: 3, home_full: 10 } } });
  renderPage(<BingoCard apiBase="" groupId={1} role="member" />);
  const card = await screen.findByRole("region", { name: "🎱 Repertory bingo · October 2026" });
  const cell = within(card).getAllByRole("listitem")[1];
  expect(cell).toHaveClass("done", "home");
  expect(cell).toHaveTextContent("🏠 OLD DOC");
  expect(cell).toHaveAttribute("title", "OLD DOC · watched at home Oct 5");
  expect(within(card).getByText(/a line that needs one is \+3, the full card \+10/)).toBeInTheDocument();
});

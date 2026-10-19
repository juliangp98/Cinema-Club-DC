import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import BrowsePage from "../src/pages/BrowsePage";
import Calendar from "../src/pages/Calendar";
import FilterSheet from "../src/ui/FilterSheet";
import TicketRow from "../src/ui/TicketRow";
import { mockApi, renderPage } from "./support";

// Tickets (R15): All · Available · Sold out · Coming soon on Browse and the
// Calendar (and in the Filters sheet), kept in the address; announced films
// show on the day a theatre expects them. A showing gone from a theatre's
// site is "Off sale — likely sold out" (Phase 8).

const announced = { movie: { id: 9, title: "NEXT WEEK", year: 1999 }, theatre: { slug: "suns", name: "Suns Cinema", short_name: "Suns", color: "#c33" },
                    date: "2026-10-21" };
const browseReply = (films = [], soon = []) => ({ films, total: films.length, next_offset: null, facets: {}, regions: {}, announced: soon,
                                                  window: { start: "2026-10-18T00:00:00", end: "2026-10-25T00:00:00" } });

test("Browse: the ticket chips filter through the address, and announced films come first", async () => {
  const calls = mockApi({ "GET /api/theatres": [], "GET /api/discover/browse": browseReply([], [announced]) });
  renderPage(<BrowsePage apiBase="" groupId={null} user={null} />, { route: "/browse" });
  expect(await screen.findByText("Announced — tickets soon")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /NEXT WEEK/ })).toHaveAttribute("href", "/films/9");
  expect(screen.queryByText(/Nothing matches/)).toBeNull();
  const chips = screen.getByRole("group", { name: "Tickets" });
  expect(within(chips).getByRole("button", { name: "All" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(chips).getByRole("button", { name: "Sold out" }));
  expect(calls.at(-1).path).toContain("tickets=soldout");
  await userEvent.click(within(chips).getByRole("button", { name: "All" }));
  expect(calls.at(-1).path).not.toContain("tickets=");
});

test("the Calendar shows announced films on the day they're expected", async () => {
  mockApi({ "GET /api/theatres": [], "GET /api/discover/calendar": { showtimes: [], movies: {}, theatres: {}, total: 0, facets: {}, regions: {},
                                                                    announced: [announced] } });
  renderPage(<Calendar user={null} apiBase="" groupId={null} />, { route: "/calendar?view=agenda&date=2026-10-20" });
  const tile = (await screen.findByLabelText("NEXT WEEK — announced")).closest(".cal-tile");
  expect(within(tile).getByText("Tickets soon")).toBeInTheDocument();
  expect(within(tile).getByRole("link", { name: "Suns" })).toHaveAttribute("href", "/theatres/suns");
  expect(screen.queryByText(/Nothing matches/)).toBeNull();
});

test("the Filters sheet has the same choice", async () => {
  const onToggle = vi.fn();
  renderPage(<FilterSheet query={{ tickets: "available" }} multi={new Set()} meta={{}} theatreNames={{}} total={3}
                          onToggle={onToggle} onClear={() => {}} onClose={() => {}} />);
  const group = screen.getByText("Tickets").closest("fieldset");
  expect(within(group).getByRole("button", { name: "Available" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(within(group).getByRole("button", { name: "Coming soon" }));
  expect(onToggle).toHaveBeenCalledWith("tickets", "soon");
});

test("a showing gone from the theatre's site says it's off sale, and can still be RSVP'd", () => {
  const show = (extra) => ({ id: 1, start_time: "2099-10-21T19:00:00", end_time: null, purchase_link: "https://example.test/t",
                             theatre: { slug: "afi", name: "AFI Silver" }, is_sold_out: true, ...extra });
  const { unmount } = renderPage(<TicketRow showtime={show({ off_sale: true })} apiBase="" onRsvp={() => {}} />);
  expect(screen.getByText("Off sale — likely sold out")).toBeInTheDocument();
  expect(screen.getByRole("group", { name: "Your RSVP" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /Tickets/ })).toBeNull();
  unmount();
  renderPage(<TicketRow showtime={show({})} apiBase="" onRsvp={() => {}} />);
  expect(screen.getByText("Sold out")).toBeInTheDocument();
});

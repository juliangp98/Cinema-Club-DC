import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ClubSettings from "../src/components/ClubSettings";
import NotifySettings from "../src/components/NotifySettings";
import { DigestCard } from "../src/pages/Feed";
import { mockApi, renderPage } from "./support";

// The Monday digest: a club setting (Club settings → Theatres), a card in the
// Feed with your own watchlist first, and its alerts in Settings → Notifications.

const show = (id, title, extra = {}) => ({ showtime_id: id, movie_id: id, title, start_time: "2026-10-21T19:30:00",
                                           theatre: "AFI", format_label: null, ...extra });

test("the card: your watchlist, then the week's picks; titles open the showtime", async () => {
  const onOpen = vi.fn();
  const card = { key: "d2026-10-19", at: "2026-10-19T14:00:00Z", type: "digest", digest: {
    week_of: "2026-10-19", yours: [show(1, "WANTED", { count: 2 })], yours_more: 1,
    plans: [show(2, "SINNERS", { wanted: 3 })], rare: [show(3, "RARE PRINT", { format_label: "35mm", reasons: ["35mm print"] })],
    opening: [], last_chance: [], polls: [{ id: 9, title: "Fest picks" }], new_on_calendar: [{ theatre: "AFI", showtimes: 23 }] } };
  renderPage(<DigestCard card={card} onOpenShowtime={onOpen} />);
  expect(screen.getByText(/This week at the movies · Oct 19 – Oct 25/)).toBeInTheDocument();
  const yours = screen.getByText("👀 On your watchlist").closest("section");
  expect(within(yours).getByText(/2 showings/)).toBeInTheDocument();
  expect(within(yours).getByRole("link", { name: "+1 more on your watchlist" })).toBeInTheDocument();
  expect(screen.getByText(/3 members want to see it/)).toBeInTheDocument();
  expect(screen.queryByText(/Opening this week/)).toBeNull();                  // empty sections stay out
  expect(screen.getByRole("link", { name: "Fest picks" })).toHaveAttribute("href", "/polls/9");
  expect(screen.getByText(/AFI \+23/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "RARE PRINT" }));
  expect(onOpen).toHaveBeenCalledWith(3);
});

test("a quiet week says so", () => {
  const card = { key: "d", at: "2026-10-19T14:00:00Z", type: "digest", digest: {
    week_of: "2026-10-19", yours: [], yours_more: 0, plans: [], rare: [], opening: [], last_chance: [], polls: [], new_on_calendar: [] } };
  renderPage(<DigestCard card={card} onOpenShowtime={() => {}} />);
  expect(screen.getByText(/A quiet week/)).toBeInTheDocument();
});

test("organizers turn the Monday digest on at the top of Theatres", async () => {
  const group = { id: 1, slug: "club", name: "Club", discord: true, theatres: ["afi"], announce_theatres: [],
                  digest: { enabled: false }, trivia: { enabled: false }, bingo: { enabled: false }, notes: { enabled: false }, quizzes: {} };
  const calls = mockApi({ "GET /api/theatres": [{ slug: "afi", name: "AFI Silver", short_name: "AFI" }],
                          "GET /api/groups/club/members": [], "GET /api/groups/club/game-posts": { waiting: [], skipped: [] },
                          "PUT /api/groups/club": body => ({ ...group, ...body }) });
  renderPage(<ClubSettings group={group} apiBase="" viewerId={1} isAdmin={false} onChanged={() => {}} />);
  const sw = await screen.findByRole("switch", { name: "Monday digest" });
  expect(sw).not.toBeChecked();
  expect(screen.getByText(/a post in the club's Discord channel/)).toBeInTheDocument();
  await userEvent.click(sw);
  expect(calls.at(-1).body).toEqual({ digest_enabled: true });
});

test("'by email, push or DM too' waits on the digest alert itself", async () => {
  const types_info = [
    { key: "digest", label: "The Monday digest is up", hint: "h", group: "club", group_label: "Your club", needs: null },
    { key: "digest_out", label: "The Monday digest by email, push or DM too", hint: "h", group: "club", group_label: "Your club", needs: "digest" },
  ];
  const settings = { channels: { discord: false, email: true, push: false }, available: { discord: false, email: true, push: false },
                     push_ready: false, types: { digest: true, digest_out: false }, types_info, searches: [] };
  mockApi({ "GET /api/me/notifications": settings,
            "PUT /api/me/notifications": body => ({ ...settings, types: { ...settings.types, ...body.types } }) });
  renderPage(<NotifySettings apiBase="" />);
  const out = await screen.findByRole("switch", { name: "The Monday digest by email, push or DM too" });
  expect(out).toBeEnabled();
  await userEvent.click(screen.getByRole("switch", { name: "The Monday digest is up" }));
  expect(await screen.findByRole("switch", { name: "The Monday digest by email, push or DM too" })).toBeDisabled();
});

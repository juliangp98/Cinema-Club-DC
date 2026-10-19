import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import MeSettings from "../src/components/MeSettings";
import ClubSettings from "../src/components/ClubSettings";
import { SwitchRow } from "../src/ui/Settings";
import { mockApi, renderPage } from "./support";

// Settings (7g): one standard (ui/Settings — sections, rows, switches, one
// "Saved"), your Settings by category on Me, and a club's by category.

const user = { id: 1, name: "Ana", email: "ana@x.test", is_guest: false, avatar_kind: "initials", avatar_color: "#e8a838",
               discord_linked: false, bio: "" };
const notify = {
  channels: { discord: false, email: true, push: false }, available: { discord: false, email: true, push: false }, push_ready: false,
  types: { showings: true, attendance: false, trivia_daily: false },
  types_info: [
    { key: "showings", label: "A film on your watchlist is booked or announced", hint: "h", group: "films", group_label: "Your films" },
    { key: "attendance", label: '"Did you make it?" DMs', hint: "h", group: "going", group_label: "Going out" },
    { key: "trivia_daily", label: "Trivia: the question of the day is up", hint: "h", group: "games", group_label: "Games" },
  ],
  searches: [{ id: 3, label: "Horror · AFI", path: "/browse?genres=horror" }],
};
const taste = { options: { genres: [], ways: [], theatres: [] }, genres: [], avoid: [], ways: [], theatres: [], movies: [], people: [],
                hidden: [], public: false, set: false, summary: {} };

function server() {
  return mockApi({
    "GET /api/me/notifications": notify, "PUT /api/me/notifications": body => ({ ...notify, types: { ...notify.types, ...body.types } }),
    "GET /api/me/taste": taste, "PUT /api/me/taste": body => ({ ...taste, ...body }),
    "GET /api/me/letterboxd": { connected: false }, "GET /api/auth/providers": { discord: false },
    "GET /api/me/calendar": null, "GET /api/me/share-prefs": { available: false, reason: "not_linked" },
    "PUT /api/auth/profile": body => ({ user: { ...user, ...body } }),
  });
}

test("a switch row is a labelled switch", async () => {
  const onChange = vi.fn();
  renderPage(<SwitchRow label="Email" hint="Alerts by email." checked={false} onChange={onChange} />);
  const sw = screen.getByRole("switch", { name: "Email" });
  expect(sw).not.toBeChecked();
  await userEvent.click(sw);
  expect(onChange).toHaveBeenCalledWith(true);
});

test("your settings: a section menu, alerts by category, privacy in one place, saved as you go", async () => {
  const calls = server();
  const setUser = vi.fn();
  renderPage(<MeSettings user={user} apiBase="" />, { shell: { setUser } });
  const menu = screen.getByRole("navigation", { name: "Settings sections" });
  expect(within(menu).getAllByRole("link").map(a => a.textContent))
    .toEqual(["Profile", "Your taste", "Notifications", "Connections", "Privacy and sharing", "Account"]);
  expect(within(menu).getByRole("link", { name: "Notifications" })).toHaveAttribute("href", "/#settings-notify");

  for (const g of ["Where alerts reach you", "Your films", "Going out", "Games", "Saved searches"]) {
    expect(await screen.findByRole("group", { name: g })).toBeInTheDocument();
  }
  await userEvent.click(screen.getByRole("switch", { name: "Trivia: the question of the day is up" }));
  expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/me/notifications", body: { types: { trivia_daily: true } } });
  expect(await screen.findByRole("status")).toHaveTextContent("✓ Saved");

  const privacy = screen.getByRole("region", { name: "Privacy and sharing" });
  await userEvent.click(within(privacy).getByRole("switch", { name: "Show my taste on my profile" }));
  expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/me/taste", body: { public: true } });

  const name = screen.getByRole("textbox", { name: "Name" });
  await userEvent.clear(name);
  await userEvent.type(name, "Ana B.{Enter}");                                 // saved when you leave the box
  expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/auth/profile", body: { name: "Ana B." } });
  expect(setUser).toHaveBeenCalledWith(expect.objectContaining({ name: "Ana B." }));
});

test("a club's theatres: follow them, and choose which announce new showtimes in #movies", async () => {
  const group = { id: 1, slug: "club", name: "Club", discord: true, theatres: ["afi", "suns"], announce_theatres: ["suns"],
                  trivia: { enabled: false }, bingo: { enabled: false }, notes: { enabled: false }, quizzes: {} };
  const calls = mockApi({ "GET /api/theatres": [{ slug: "afi", name: "AFI Silver", short_name: "AFI" }, { slug: "suns", name: "Suns Cinema", short_name: "SUNS" }],
                          "GET /api/groups/club/members": [], "GET /api/groups/club/game-posts": { waiting: [], skipped: [] },
                          "PUT /api/groups/club": body => ({ ...group, ...body }) });
  renderPage(<ClubSettings group={group} apiBase="" viewerId={1} isAdmin={false} onChanged={() => {}} />);
  const posts = await screen.findByRole("group", { name: "New showtimes in #movies" });
  expect(within(posts).getByRole("switch", { name: "Suns Cinema" })).toBeChecked();
  await userEvent.click(within(posts).getByRole("switch", { name: "AFI Silver" }));
  expect(calls.at(-1).body).toEqual({ announce_theatres: ["suns", "afi"] });
  await userEvent.click(within(screen.getByRole("group", { name: "Followed theatres" })).getByRole("button", { name: "AFI" }));
  expect(calls.at(-1).body).toEqual({ theatres: ["suns"] });                   // saved as you pick (no Save button)
});

// The Letterboxd watchlist (Connections → Letterboxd → Watchlist): upload the
// export, answer the alerts question once, import again, or turn it off.
test("the Letterboxd watchlist: import, the alerts question, import again, turn off", async () => {
  const off = { connected: false, username: "", watchlist: { on: false, films: 0, matched: 0, alerts: null, imported_at: null } };
  const on = alerts => ({ ...off, watchlist: { on: true, films: 312, matched: 41, alerts, imported_at: "2026-10-19T14:00:00Z" } });
  const calls = mockApi({
    "GET /api/me/notifications": notify, "GET /api/me/taste": taste, "GET /api/me/letterboxd": off,
    "GET /api/auth/providers": { discord: false }, "GET /api/me/calendar": null,
    "GET /api/me/share-prefs": { available: false, reason: "not_linked" },
    "POST /api/me/letterboxd/watchlist": () => ({ ...on(null), ask_alerts: true, imported: { films: 312, matched: 41, added: 40, removed: 0 } }),
    "PUT /api/me/letterboxd": body => on(body.watch_alerts),
    "DELETE /api/me/letterboxd/watchlist": off,
  });
  renderPage(<MeSettings user={user} apiBase="" />);
  const group = await screen.findByRole("group", { name: "Letterboxd" });
  expect(within(group).getByText("Diary")).toBeInTheDocument();
  expect(within(group).getByText(/Export your data/)).toBeInTheDocument();

  const file = new File(["Date,Name,Year,Letterboxd URI\n"], "watchlist.csv", { type: "text/csv" });
  await userEvent.upload(screen.getByLabelText("Letterboxd export file"), file);
  const sent = calls.find(c => c.method === "POST" && c.path === "/api/me/letterboxd/watchlist");
  expect(sent.body).toBeInstanceOf(FormData);
  expect(sent.body.get("file").name).toBe("watchlist.csv");
  expect(await screen.findByText(/312 films · 41 in our listings/)).toBeInTheDocument();

  const ask = screen.getByRole("group", { name: "Alert you about these like your watchlist?" });
  await userEvent.click(within(ask).getByRole("button", { name: "Just For you" }));
  expect(calls.at(-1)).toEqual({ method: "PUT", path: "/api/me/letterboxd", body: { watch_alerts: false } });
  const choice = await screen.findByRole("group", { name: "Alerts for Letterboxd watchlist films" });
  expect(within(choice).getByRole("button", { name: "Just For you" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Import again" })).toBeInTheDocument();

  vi.spyOn(window, "confirm").mockReturnValue(true);
  await userEvent.click(screen.getByRole("button", { name: "Turn off" }));
  expect(calls.at(-1)).toMatchObject({ method: "DELETE", path: "/api/me/letterboxd/watchlist" });
  expect(await screen.findByRole("button", { name: "Choose the file" })).toBeInTheDocument();
  window.confirm.mockRestore();
});

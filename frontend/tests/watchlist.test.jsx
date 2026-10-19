import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import FilmPage from "../src/pages/FilmPage";
import { WatchlistTab } from "../src/components/ProfileLists";
import { mockApi, renderPage } from "./support";

// The watchlist button (Oct 2026 fix): its click handler was named like the
// shared toggleWatch() call it makes, so it called itself and never reached
// the server.

const FILM = { movie: { id: 5, title: "VERTIGO", genres: "thriller", release_year: "1958" }, showtimes: [],
               viewer_wants: false, members: [] };

test("adding to and taking off the watchlist reaches the server", async () => {
  let wants = false;
  const calls = mockApi({ "GET /api/films/5": FILM,
                          "POST /api/watchlist": () => ({ watching: (wants = !wants) }) });
  renderPage(<Routes><Route path="/films/:id" element={<FilmPage user={{ id: 1 }} apiBase="" />} /></Routes>,
             { route: "/films/5", shell: { user: { id: 1 } } });
  const button = await screen.findByRole("button", { name: /watchlist/i });
  await userEvent.click(button);
  expect(calls.filter(c => c.method === "POST")).toEqual([{ method: "POST", path: "/api/watchlist", body: { movie_id: 5 } }]);
  expect(await screen.findByRole("button", { name: /on your watchlist|watching|✓/i })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /on your watchlist|watching|✓/i }));
  expect(calls.filter(c => c.method === "POST")).toHaveLength(2);
});

test("films from a Letterboxd watchlist are marked on the list", async () => {
  mockApi({ "GET /api/users/1/watchlist": { own: true, items: [
    { movie: { id: 7, title: "STALKER", release_year: "1979" }, source: "letterboxd", next: null },
    { movie: { id: 8, title: "VERTIGO", release_year: "1958" }, source: null, next: null },
  ] } });
  renderPage(<WatchlistTab userId={1} apiBase="" onOpen={() => {}} />);
  const stalker = (await screen.findByText(/STALKER/)).closest("button");
  expect(within(stalker).getByText("📓 Letterboxd")).toBeInTheDocument();
  expect(within(screen.getByText(/VERTIGO/).closest("button")).queryByText("📓 Letterboxd")).toBeNull();
});

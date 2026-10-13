import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Shelf, TasteNudge } from "../src/pages/DiscoverPage";
import { TheatresPage } from "../src/pages/Theatres";
import { mockApi, renderPage } from "./support";

// For you (R13): the shelf with its reasons and "Not for me", the nudge where
// it would be before you've set your taste, and "N for you" on Theatres.

const card = (id, title, reasons) => ({ movie: { id, title, year: 1963 }, reasons,
  next: { showtime_id: id, start_time: "2026-10-20T19:00:00", theatre: "AFI" }, club: { going: 0, wanted: 0 } });
const SHELF = { key: "for-you", title: "For you", blurb: "From your taste", total: 2,
                items: [card(1, "THE BIRDS", ["more from Alfred Hitchcock", "Horror"]), card(2, "MARNIE", ["on 35mm"])] };

test("each pick says why; Not for me takes it out", async () => {
  const onHide = vi.fn();
  renderPage(<Shelf s={SHELF} onHide={onHide} />);
  expect(screen.getByText("more from Alfred Hitchcock · Horror")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Not for me: MARNIE" }));
  expect(onHide).toHaveBeenCalledWith(2);
  expect(screen.queryByText("MARNIE")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Not for me: THE BIRDS" }));
  expect(screen.queryByRole("region")).toBeNull();                         // an emptied shelf goes away
  expect(document.querySelector(".shelf")).toBeNull();
});

test("other shelves have no Not for me", () => {
  renderPage(<Shelf s={{ ...SHELF, key: "rare", title: "Rare gems" }} />);
  expect(screen.queryByRole("button", { name: /Not for me/ })).toBeNull();
});

test("before you've set your taste: an invitation, or not now", async () => {
  const editTaste = vi.fn();
  const { unmount } = renderPage(<TasteNudge userId={7} />, { shell: { editTaste } });
  await userEvent.click(screen.getByRole("button", { name: "Pick what you like" }));
  expect(editTaste).toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(screen.queryByText("Make Discover yours")).toBeNull();
  unmount();
  renderPage(<TasteNudge userId={7} />, { shell: { editTaste } });
  expect(screen.queryByText("Make Discover yours")).toBeNull();            // stays dismissed
});

const theatre = (slug, name) => ({ slug, name, color: "#c33", region: "DC", address: "",
  preview: { posters: [], rare: 0, formats: [], tonight: 0, film_count: 3, next: null } });

test("Theatres: how many films are for you at each", async () => {
  mockApi({ "GET /api/theatres-overview": [theatre("afi", "AFI Silver"), theatre("suns", "Suns Cinema")],
            "GET /api/for-you/theatres?group_id=1&": { afi: 2 } });
  renderPage(<TheatresPage apiBase="" />, { shell: { user: { id: 7 }, groupId: 1 } });
  const chip = await screen.findByRole("link", { name: "✨ 2 for you" });
  expect(chip).toHaveAttribute("href", "/theatres/afi#shelf-for-you");
  expect(within(screen.getByText("Suns Cinema").closest("article")).queryByText(/for you/)).toBeNull();
});

test("Theatres for visitors: no counts asked for", async () => {
  const calls = mockApi({ "GET /api/theatres-overview": [theatre("afi", "AFI Silver")] });
  renderPage(<TheatresPage apiBase="" />, { shell: { user: null } });
  await screen.findByText("AFI Silver");
  expect(calls.map(c => c.path)).toEqual(["/api/theatres-overview"]);
});

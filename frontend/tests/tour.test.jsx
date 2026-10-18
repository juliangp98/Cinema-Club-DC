import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useLocation } from "react-router-dom";
import Tour, { PageTour, holeFor } from "../src/shell/Tour";
import { PAGE_TOURS } from "../src/shell/pageTours";
import { TourButton, TourOffer } from "../src/ui/PageTourControls";
import { renderPage } from "./support";

function Where() {
  const { pathname } = useLocation();
  return <output aria-label="page">{pathname}</output>;
}
const page = () => screen.getByRole("status", { name: "page" }).textContent;

// The welcome tour (R11, short since 7f): slides with the essentials, one
// spotlight on the menu, then Your taste. Page tours (7f): each page's own
// steps, then its Help. Steps for things you can't use, or can't see, are skipped.

test("slides: the club one only for club members; skip, Escape and Back", async () => {
  const onFinish = vi.fn();
  const { unmount } = renderPage(<Tour inClub={false} onFinish={onFinish} />);
  expect(screen.getByRole("dialog", { name: "Welcome to Cinema Club DC" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  await userEvent.click(screen.getByRole("button", { name: "Next" }));
  expect(screen.getByRole("dialog", { name: "Nothing sent without a yes" })).toBeInTheDocument();   // no "Your club"
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(screen.getByRole("dialog", { name: "Make plans together" })).toBeInTheDocument();
  fireEvent.keyDown(window, { key: "Escape" });
  expect(onFinish).toHaveBeenCalledTimes(1);
  unmount();
  renderPage(<Tour inClub onFinish={onFinish} />);
  await userEvent.click(screen.getByRole("button", { name: "Skip" }));
  expect(onFinish).toHaveBeenCalledTimes(2);
});

describe("the spotlight", () => {
  // jsdom lays nothing out: pretend whatever's in the page is on screen.
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "offsetParent", "get").mockImplementation(function () { return this.parentNode; });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      { top: 10, left: 10, bottom: 40, right: 90, width: 80, height: 30, x: 10, y: 10 });
  });

  test("one step on the menu, without leaving the page", async () => {
    document.body.insertAdjacentHTML("beforeend", `<nav class="topbar-nav"><a href="/">Discover</a></nav>`);
    const onFinish = vi.fn();
    renderPage(<><Tour inClub={false} onFinish={onFinish} /><Where /></>, { route: "/help" });
    for (let i = 0; i < 2; i += 1) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Show me around" }));
    const step = screen.getByRole("dialog", { name: "Find your way around" });
    expect(step).toHaveTextContent("1 of 1");
    expect(step).toHaveTextContent("Each page has its own short tour");
    expect(page()).toBe("/help");                                              // the welcome tour stays put
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onFinish).toHaveBeenCalled();
    document.querySelector(".topbar-nav").remove();
  });

  test("then an invitation to set up Your taste — now, or later", async () => {
    document.body.insertAdjacentHTML("beforeend", `<nav class="topbar-nav"><a href="/">Discover</a></nav>`);
    const onFinish = vi.fn(), onTaste = vi.fn();
    const { unmount } = renderPage(<Tour inClub={false} onFinish={onFinish} onTaste={onTaste} />);
    for (let i = 0; i < 2; i += 1) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Show me around" }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.getByRole("dialog", { name: "Make it yours" })).toBeInTheDocument();
    expect(onFinish).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Pick what you like" }));
    expect(onFinish).toHaveBeenCalledTimes(1);
    expect(onTaste).toHaveBeenCalledTimes(1);
    unmount();
    renderPage(<Tour inClub={false} onFinish={onFinish} onTaste={onTaste} />);
    for (let i = 0; i < 2; i += 1) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Show me around" }));
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(onFinish).toHaveBeenCalledTimes(2);
    expect(onTaste).toHaveBeenCalledTimes(1);
    document.querySelector(".topbar-nav").remove();
  });

  test("nothing on screen to show: straight to the end", async () => {
    const onFinish = vi.fn();
    renderPage(<Tour inClub={false} onFinish={onFinish} />);
    for (let i = 0; i < 2; i += 1) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Show me around" }));
    expect(onFinish).toHaveBeenCalled();
  });
});

describe("a page's tour", () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "offsetParent", "get").mockImplementation(function () { return this.parentNode; });
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(
      { top: 100, left: 10, bottom: 140, right: 90, width: 80, height: 40, x: 10, y: 100 });
  });

  test("what's on the page, then its part of Help", async () => {
    document.body.insertAdjacentHTML("beforeend", `<section id="trivia">t</section><section id="polls">p</section>`);
    const onFinish = vi.fn();
    renderPage(<><PageTour tour={PAGE_TOURS.play} onFinish={onFinish} /><Where /></>, { route: "/play" });
    expect(screen.getByRole("dialog", { name: "Trivia" })).toHaveTextContent("1 of 3");   // bingo, games, kernels: not here
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Polls" })).toHaveTextContent("2 of 3");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "There's more in Help" })).toHaveTextContent("Everything about Play");
    await userEvent.click(screen.getByRole("button", { name: "Open Help" }));
    expect(onFinish).toHaveBeenCalled();
    expect(page()).toBe("/help");
    document.getElementById("trivia").remove();
    document.getElementById("polls").remove();
  });

  test("every page's tour ends at Help that exists, in 3 to 6 steps", async () => {
    const { TOPICS, SECTIONS } = await import("../src/help");
    const ids = new Set([...Object.keys(TOPICS), ...SECTIONS.map(s => s.id)]);
    for (const [key, t] of Object.entries(PAGE_TOURS)) {
      expect(ids.has(t.help), `${key} → ${t.help}`).toBe(true);
      expect(t.steps.length + 1).toBeGreaterThanOrEqual(3);
      expect(t.steps.length + 1).toBeLessThanOrEqual(6);
    }
    expect(Object.keys(PAGE_TOURS).sort()).toEqual(["browse", "calendar", "club", "discover", "feed", "film", "me", "play", "poll", "theatre"]);
  });
});

test("the ? button and the one-time offer", async () => {
  const startPageTour = vi.fn(), markPageTour = vi.fn();
  const shell = { startPageTour, markPageTour, offerPageTour: page => page === "play" };
  const { unmount } = renderPage(<><TourButton page="play" /><TourOffer page="play" /></>, { shell });
  await userEvent.click(screen.getByRole("button", { name: "Tour of Play" }));
  expect(startPageTour).toHaveBeenLastCalledWith("play");
  const offer = screen.getByRole("group", { name: "Page tour" });
  expect(offer).toHaveTextContent("A 30-second tour of Play");
  await userEvent.click(screen.getByRole("button", { name: "No thanks" }));
  expect(markPageTour).toHaveBeenCalledWith("play");
  unmount();
  renderPage(<TourOffer page="feed" />, { shell });
  expect(screen.queryByRole("group", { name: "Page tour" })).toBeNull();          // already offered
});

test("the spotlight's outline stays on screen, the same size across a bar", () => {
  const topbar = { top: 0, bottom: 58 };
  const link = holeFor({ top: 12, bottom: 43, left: 300, right: 383, width: 83, height: 31 }, 1024, 800, topbar);
  const bell = holeFor({ top: 8.5, bottom: 46.5, left: 900, right: 938, width: 38, height: 38 }, 1024, 800, topbar);
  const clubs = holeFor({ top: 13.5, bottom: 41.5, left: 800, right: 852, width: 52, height: 28 }, 1024, 800, topbar);
  expect([link.top, bell.top, clubs.top]).toEqual([6, 6, 6]);                // the 4px outline stays in the bar
  expect([link.height, bell.height, clubs.height]).toEqual([46, 46, 46]);
  expect(bell).toMatchObject({ left: 894, width: 50 });
  const tabbar = { top: 752, bottom: 812 };                                   // phones
  const tab = holeFor({ top: 756, bottom: 808, left: 0, right: 75, width: 75, height: 52 }, 375, 812, tabbar);
  expect(tab.top + tab.height).toBeLessThanOrEqual(812 - 6);
  expect(tab.left).toBeGreaterThanOrEqual(6);
  const loose = holeFor({ top: 300, bottom: 330, left: 100, right: 200, width: 100, height: 30 }, 1024, 800);
  expect(loose).toEqual({ top: 294, left: 94, width: 112, height: 42 });     // anywhere else: PAD all round
});

import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Tour from "../src/shell/Tour";
import { renderPage } from "./support";

// The welcome tour (R11): slides with the essentials, then a spotlight on
// the real navigation. Steps for things you can't use, or can't see, are skipped.

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

  test("goes through what's on screen, in order, then finishes", async () => {
    document.body.insertAdjacentHTML("beforeend", `<nav class="topbar-nav"><a href="/">Discover</a>
      <a href="/calendar">Calendar</a></nav><button class="topbar-bell">bell</button>`);
    const onFinish = vi.fn();
    renderPage(<Tour inClub={false} onFinish={onFinish} />);
    for (let i = 0; i < 2; i += 1) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Show me around" }));
    expect(screen.getByRole("dialog", { name: "Discover" })).toHaveTextContent("1 of 3");
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "Calendar" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByRole("dialog", { name: "The bell" })).toHaveTextContent("3 of 3");
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onFinish).toHaveBeenCalled();
    document.querySelector(".topbar-nav").remove();
    document.querySelector(".topbar-bell").remove();
  });

  test("nothing on screen to show: straight to the end", async () => {
    const onFinish = vi.fn();
    renderPage(<Tour inClub={false} onFinish={onFinish} />);
    for (let i = 0; i < 2; i += 1) await userEvent.click(screen.getByRole("button", { name: "Next" }));
    await userEvent.click(screen.getByRole("button", { name: "Show me around" }));
    expect(onFinish).toHaveBeenCalled();
  });
});

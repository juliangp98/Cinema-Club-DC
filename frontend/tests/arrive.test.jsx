import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useNavigate } from "react-router-dom";
import useArrival, { GLOW_MS } from "../src/arrive";

// Where you land (7f): a new page starts at the top, Back returns to where you
// were, and any link to #something lights it up when you land — waiting for
// a slow page to draw it, opening the <details> it's in — then fades.

function Shell({ children }) {
  useArrival();
  return children;
}

beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }));
afterEach(() => vi.useRealTimers());

test("lands, glows, fades — and the same link glows again", async () => {
  render(<MemoryRouter initialEntries={["/play#polls"]}><Shell>
    <section id="polls">Polls</section><Link to="/play#polls">again</Link></Shell></MemoryRouter>);
  const el = document.getElementById("polls");
  await act(async () => { vi.advanceTimersByTime(100); });
  expect(el).toHaveClass("arrive-glow");
  await act(async () => { vi.advanceTimersByTime(GLOW_MS + 10); });
  expect(el).not.toHaveClass("arrive-glow");                            // never left on: it blocks nothing
  await userEvent.click(screen.getByRole("link", { name: "again" }));
  await act(async () => { vi.advanceTimersByTime(100); });
  expect(el).toHaveClass("arrive-glow");
});

test("waits for the page to draw it, and opens a closed topic", async () => {
  function Late() {
    return <details><summary>q</summary><p id="late">a</p></details>;
  }
  const { rerender } = render(<MemoryRouter initialEntries={["/help#late"]}><Shell><div /></Shell></MemoryRouter>);
  await act(async () => { vi.advanceTimersByTime(800); });                // not drawn yet: still looking
  rerender(<MemoryRouter initialEntries={["/help#late"]}><Shell><Late /></Shell></MemoryRouter>);
  await act(async () => { vi.advanceTimersByTime(200); });
  expect(document.getElementById("late")).toHaveClass("arrive-glow");
  expect(document.querySelector("details").open).toBe(true);
});

test("a new page starts at the top; a filter or tab keeps your place; Back returns to it", async () => {
  function Nav() {
    const navigate = useNavigate();
    return <>
      <button type="button" onClick={() => navigate("/")}>Discover</button>
      <button type="button" onClick={() => navigate("/calendar?tickets=soldout", { replace: true })}>Filter</button>
      <button type="button" onClick={() => navigate(-1)}>Back</button>
    </>;
  }
  render(<MemoryRouter initialEntries={["/calendar"]}><main className="shell-main"><Shell><Nav /></Shell></main></MemoryRouter>);
  const main = document.querySelector(".shell-main");
  main.scrollTop = 900;
  main.dispatchEvent(new Event("scroll"));
  await userEvent.click(screen.getByRole("button", { name: "Filter" }));
  expect(main.scrollTop).toBe(900);                                     // same page: stays put
  main.dispatchEvent(new Event("scroll"));
  await userEvent.click(screen.getByRole("button", { name: "Discover" }));
  expect(main.scrollTop).toBe(0);                                       // a new page: the top
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  expect(main.scrollTop).toBe(900);                                     // Back: where you were
});

test("a section menu's jump lands at the section's top without the glow, and marks it selected", async () => {
  const { default: SectionMenu } = await import("../src/ui/SectionMenu");
  const tops = { one: 0, two: 900 };                                    // jsdom lays nothing out: where each section is
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function () {
    const top = tops[this.id] ?? 0;
    return { top, bottom: top + 100, height: 100, left: 0, right: 100, width: 100 };
  });
  render(<MemoryRouter initialEntries={["/help"]}><main className="shell-main"><Shell>
    <SectionMenu label="Topics" items={[{ id: "one", label: "One" }, { id: "two", label: "Two" }]} />
    <section id="one">1</section><section id="two">2</section></Shell></main></MemoryRouter>);
  const one = screen.getByRole("link", { name: "One" });
  expect(one).toHaveClass("gold");
  expect(one).toHaveAttribute("aria-current", "true");
  await userEvent.click(screen.getByRole("link", { name: "Two" }));
  await act(async () => { vi.advanceTimersByTime(300); });
  expect(screen.getByRole("link", { name: "Two" })).toHaveClass("gold");
  expect(screen.getByRole("link", { name: "One" })).not.toHaveClass("gold");
  expect(document.getElementById("two")).not.toHaveClass("arrive-glow");          // navigation, not "look here"
});

test("the glow takes the site's rounded corners on square things", async () => {
  render(<MemoryRouter initialEntries={["/play#sq"]}><Shell><section id="sq">square</section></Shell></MemoryRouter>);
  await act(async () => { vi.advanceTimersByTime(100); });
  expect(document.getElementById("sq")).toHaveClass("arrive-glow", "arrive-round");
});

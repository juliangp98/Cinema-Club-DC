import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter } from "react-router-dom";
import useArrival, { GLOW_MS } from "../src/arrive";

// The arrival glow (7f): any link to #something lights it up when you land,
// waits for a slow page to draw it, opens the <details> it's in, and fades.

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

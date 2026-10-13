import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HelpPage from "../src/pages/HelpPage";
import { renderPage } from "./support";

// The help guide (R11): one searchable page.

test("searching narrows to matching answers, opened", async () => {
  renderPage(<HelpPage />);
  expect(screen.getByRole("navigation", { name: "Help topics" })).toBeInTheDocument();
  await userEvent.type(screen.getByRole("searchbox", { name: "Search help" }), "leave club");
  expect(screen.queryByRole("navigation", { name: "Help topics" })).toBeNull();
  const q = screen.getByText("How do I leave a club?");
  expect(q.closest("details")).toHaveAttribute("open");
  expect(screen.queryByText("How do I RSVP?")).toBeNull();
});

test("nothing found says so", async () => {
  renderPage(<HelpPage />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Search help" }), "zzzqqq");
  expect(screen.getByText(/Nothing matches/)).toBeInTheDocument();
});

test("the tour is offered to signed-in members", async () => {
  const startTour = vi.fn();
  const { unmount } = renderPage(<HelpPage />, { shell: { user: { id: 1, is_guest: false }, startTour } });
  await userEvent.click(screen.getByRole("button", { name: "Take the tour" }));
  expect(startTour).toHaveBeenCalled();
  unmount();
  renderPage(<HelpPage />, { shell: { user: { id: 2, is_guest: true } } });
  expect(screen.queryByRole("button", { name: "Take the tour" })).toBeNull();
});

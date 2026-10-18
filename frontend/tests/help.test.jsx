import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import HelpPage from "../src/pages/HelpPage";
import { mockApi, renderPage } from "./support";

// The help guide (R11): one searchable page — with links to the place in the
// site, and ✨ Ask for signed-in accounts (7f).

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
  expect(screen.getByText(/Nothing has every word/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "See every topic" })).toBeInTheDocument();
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

test("answers link straight to the place, which glows when you land", () => {
  renderPage(<HelpPage />);
  const [link] = screen.getAllByRole("link", { name: "Club settings → Games" });     // in "Where are the games?"
  expect(link).toHaveAttribute("href", "/club?tab=settings#settings-games");
  expect(screen.getAllByRole("link", { name: "earns kernels" })[0]).toHaveAttribute("href", "/help#earn-kernels");   // another topic
  expect(document.getElementById("earn-kernels").tagName).toBe("DETAILS");          // each topic has its own address
});

test("no topic has every word: the closest ones", async () => {
  renderPage(<HelpPage />);
  await userEvent.type(screen.getByRole("searchbox", { name: "Search help" }), "give kernels friend");
  expect(screen.getByRole("link", { name: "Can I give kernels to people?" })).toHaveAttribute("href", "/help#give-kernels");
  expect(screen.queryByRole("button", { name: "✨ Ask" })).toBeNull();                // visitors: keyword search only
});

test("✨ Ask: an answer in the guide's words, with its links and its topics", async () => {
  const calls = mockApi({ "POST /api/help/ask": { ai: true, topics: ["give-kernels"],
    answer: "Tap 🍿 Kernels on a screening in [the feed](feed) — 10 to give a week. [Somewhere](made-up)." } });
  renderPage(<HelpPage />, { shell: { user: { id: 1, is_guest: false } } });
  await userEvent.type(screen.getByRole("searchbox", { name: "Search help" }), "how do I thank someone for planning a night");
  await userEvent.click(screen.getByRole("button", { name: "✨ Ask" }));
  expect(calls.at(-1)).toMatchObject({ method: "POST", path: "/api/help/ask", body: { q: "how do I thank someone for planning a night" } });
  const card = (await screen.findByText("✨ AI answer")).closest(".help-answer");
  expect(card).toHaveTextContent("AI can get things wrong");
  expect(screen.getByRole("link", { name: "the feed" })).toHaveAttribute("href", "/feed");
  expect(screen.queryByRole("link", { name: "Somewhere" })).toBeNull();               // an unknown place stays words
  expect(screen.getByRole("link", { name: "Can I give kernels to people?" })).toHaveAttribute("href", "/help#give-kernels");
});

test("✨ Ask when the AI can't: the closest topics, said so", async () => {
  mockApi({ "POST /api/help/ask": { ai: false, topics: ["save-search"], answer: null, note: "The AI isn't available right now — here are the closest topics." } });
  renderPage(<HelpPage />, { shell: { user: { id: 1, is_guest: false } } });
  await userEvent.type(screen.getByRole("searchbox", { name: "Search help" }), "tell me when horror films come");
  await userEvent.click(screen.getByRole("button", { name: "✨ Ask" }));
  expect(await screen.findByText("✨ Best matches")).toBeInTheDocument();
  expect(screen.getByText(/isn't available right now/)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "How do I save a search?" })).toBeInTheDocument();
});

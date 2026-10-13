import { screen, within } from "@testing-library/react";
import { GamesRail, GamesStrip } from "../src/ui/GamesSummary";
import { renderPage } from "./support";

// What there is to play (R10 Play): the feed's rail and the phone strip.

const SUMMARY = {
  trivia: { to_answer: true, waiting: false, anytime: true, answered: false, correct: false },
  bingo: { month_label: "October", filled: 3, line: true, full: false, cells: [true, false, false, false, true, false, false, false, false] },
  polls: [{ id: 4, title: "Best of fall", you_voted: false }, { id: 5, title: "Oscars", you_voted: true }],
  kernels: { kernels: 14, allowance: { give_left: 10, take_left: 3 } },
};

test("the rail: what's waiting, bingo, kernels — each a way into Play", () => {
  renderPage(<GamesRail summary={SUMMARY} />);
  const todo = screen.getByText("To do").closest(".ui-panel");
  expect(within(todo).getAllByRole("link").map(a => [a.textContent, a.getAttribute("href")])).toEqual([
    ["🧠 Today's trivia question", "/play#trivia"], ["🗳️ Vote: Best of fall", "/polls/4"]]);
  expect(screen.getByRole("link", { name: /Bingo · October/ })).toHaveAttribute("href", "/play#bingo");
  expect(screen.getByRole("link", { name: /Your kernels/ })).toHaveTextContent("10 to give · 3 to take this week");
});

test("the rail when you're caught up; nothing without a summary", () => {
  const { container, unmount } = renderPage(<GamesRail summary={null} />);
  expect(container).toBeEmptyDOMElement();
  unmount();
  renderPage(<GamesRail summary={{ ...SUMMARY, trivia: { ...SUMMARY.trivia, to_answer: false }, polls: [] }} />);
  expect(screen.getByText(/You're all caught up/)).toHaveClass("ui-hint");
  expect(screen.getByRole("link", { name: "play an anytime question" })).toBeInTheDocument();
});

test("the phone strip: gold where something's waiting", () => {
  renderPage(<GamesStrip summary={SUMMARY} />);
  const strip = screen.getByRole("navigation", { name: "Games" });
  expect(within(strip).getByRole("link", { name: "🧠 1 to answer" })).toHaveClass("gold");
  expect(within(strip).getByRole("link", { name: "🗳️ 1 to vote" })).toHaveClass("gold");
  expect(within(strip).getByRole("link", { name: "🎱 3/8 🎉" })).not.toHaveClass("gold");
  expect(within(strip).getByRole("link", { name: "🍿 14" })).toHaveAttribute("href", "/play#kernels");
});

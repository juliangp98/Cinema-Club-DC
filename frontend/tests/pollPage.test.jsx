import { screen, within } from "@testing-library/react";
import { Route, Routes } from "react-router-dom";
import PollDetailPage from "../src/pages/PollDetailPage";
import { mockApi, renderPage } from "./support";

// A live poll part way through, from a member's side: your score as facts
// (kernels, right, place, how many are answered so far), each locked
// category's answer and how your pick did, and the vote split.

const POLL = {
  id: 3, group_id: 1, title: "Election night", status: "open", poll_type: "prediction", scoring_mode: "single",
  reveal: "live", decided: 1, you_run: false,
  your_score: { kernels: 1, correct: 1, total: 1, place: 1, of: 4 },
  categories: [
    { id: 10, title: "Senate: PA", locked: true, correct_option_id: 100, your_kernels: 1,
      user_vote: { option_id: 100 }, vote_distribution: { 100: 3, 101: 1 },
      options: [{ id: 100, text: "Red" }, { id: 101, text: "Blue" }] },
    { id: 11, title: "Senate: OH", locked: false, user_vote: { option_id: 103 }, vote_distribution: { 102: 2, 103: 2 },
      options: [{ id: 102, text: "Red" }, { id: 103, text: "Blue" }] },
  ],
};

test("a live poll part way through: your score, a locked answer, the split", async () => {
  mockApi({ "GET /api/polls/3": POLL, "GET /api/groups": [{ id: 1, role: "member" }] });
  renderPage(<Routes><Route path="/polls/:pollId" element={<PollDetailPage user={{ id: 1 }} apiBase="" />} /></Routes>,
             { route: "/polls/3" });
  const score = await screen.findByRole("group", { name: "Your score" });
  expect(within(score).getByText("+1 🍿")).toBeInTheDocument();
  expect(within(score).getByLabelText("How you did")).toHaveTextContent("Right1 of 1Place1st of 4Answered so far1 of 2");
  expect(screen.getByText("🔒 answered")).toBeInTheDocument();                     // Senate: PA is decided
  expect(screen.getAllByText("3 (75%)")).toHaveLength(1);                          // the split, count and share
  expect(screen.getAllByText("2 (50%)")).toHaveLength(2);
  expect(screen.queryByText(/ · /)).toBeNull();                                   // no dot-joined lines
});

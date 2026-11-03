import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import PollEditorPage from "../src/pages/PollEditorPage";
import { mockApi, renderPage } from "./support";

// A live prediction poll in Discord, as answers come in: the poll's post keeps
// its standings, each answer goes up as a reply (app.queue_poll_call), or both.
// The editor offers the choice only for live polls; both, unless changed.

const SHELL = { role: "organizer", group: { id: 1, slug: "club", discord: false }, user: { id: 1, share_prefs: {} } };

test("a live poll's editor: in Discord, the post updates, a reply per answer, or both", async () => {
  const calls = mockApi({ "POST /api/groups/1/polls": body => ({ id: 3, ...body }) });
  renderPage(<Routes><Route path="/polls/new" element={<PollEditorPage apiBase="" activeGroupId={1} />} /></Routes>,
             { route: "/polls/new", shell: SHELL });
  await userEvent.type(screen.getByLabelText("Title"), "Election night");
  await userEvent.click(screen.getByRole("button", { name: "Prediction" }));
  expect(screen.queryByRole("group", { name: "In Discord, as answers come in" })).toBeNull();   // all at once: nothing live
  await userEvent.click(screen.getByRole("button", { name: "Live" }));
  expect(screen.getByRole("button", { name: "Both" })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "Post each answer" }));
  expect(screen.getByText(/A running feed that shows as new messages/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Category 1 title"), "Senate: PA");
  await userEvent.type(screen.getByLabelText("Category 1 option 1"), "Red");
  await userEvent.type(screen.getByLabelText("Category 1 option 2"), "Blue");
  await userEvent.click(screen.getByRole("button", { name: "Create poll" }));
  expect(calls.find(c => c.method === "POST").body).toMatchObject({ reveal: "live", live_discord: "feed", poll_type: "prediction" });
});

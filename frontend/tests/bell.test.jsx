import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ActivityPanel, clearQuestion } from "../src/shell/Activity";
import { mockApi, renderPage } from "./support";

// Clear in the bell: an "Are you sure?" first, and alerts still asking you
// something stay (tagged "Needs your answer").

const alert = (id, headline, needs = false) => ({ id, kind: needs ? "game_review" : "showings", headline, detail: "",
  link: "/", created_at: "2026-10-19T14:00:00Z", read: true, needs_answer: needs });
const activity = { tab: "mine", setTab: () => {}, close: () => {}, seeMine: () => {}, seeClub: () => {} };

test("the question says what stays", () => {
  expect(clearQuestion([alert(1, "a"), alert(2, "b")])).toBe("Clear all 2 notifications? You can't bring them back.");
  expect(clearQuestion([alert(1, "a"), alert(2, "b", true)]))
    .toBe("Clear 1 notification? One still needs your answer, so it stays until you answer.");
});

test("clear asks first, then leaves only what needs an answer", async () => {
  const items = [alert(1, "VERTIGO is playing"), alert(2, "A game post is waiting", true)];
  const calls = mockApi({ "GET /api/notifications": { items, unread: 0 },
                          "POST /api/notifications/clear": { cleared: 1, items: [items[1]], unread: 0 } });
  const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  renderPage(<ActivityPanel user={{ id: 1 }} apiBase="" groupId={null} activity={activity} />);
  expect(await screen.findByText("Needs your answer")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(calls.some(c => c.path === "/api/notifications/clear")).toBe(false);          // said no: nothing cleared
  await userEvent.click(screen.getByRole("button", { name: "Clear" }));
  expect(await screen.findByRole("status")).toHaveTextContent("This one needs your answer first.");
  expect(screen.queryByText("VERTIGO is playing", { selector: ".alert-headline" })).toBeNull();
  expect(screen.getByText("A game post is waiting", { selector: ".alert-headline" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Clear" })).toBeNull();                 // nothing left to clear
  confirm.mockRestore();
});

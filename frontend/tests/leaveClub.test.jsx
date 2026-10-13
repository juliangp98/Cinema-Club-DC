import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LeaveClub } from "../src/pages/ClubPage";
import { mockApi, renderPage, reply } from "./support";

// Leaving a club (R11): asked first; the last admin can't.

const GROUP = { name: "Film Club", slug: "film-club" };

test("asked first; leaving calls the server and moves on", async () => {
  const calls = mockApi({ "DELETE /api/groups/film-club/members/5": { ok: true } });
  const onLeft = vi.fn();
  vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
  renderPage(<LeaveClub group={GROUP} apiBase="" userId={5} onLeft={onLeft} />);
  const btn = screen.getByRole("button", { name: "Leave this club" });
  await userEvent.click(btn);
  expect(calls).toHaveLength(0);
  await userEvent.click(btn);
  expect(calls).toEqual([{ method: "DELETE", path: "/api/groups/film-club/members/5", body: undefined }]);
  expect(onLeft).toHaveBeenCalled();
});

test("the only admin is told why not", async () => {
  mockApi({ "DELETE /api/groups/film-club/members/5": reply(400, { error: "Make someone else an admin first." }) });
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const onLeft = vi.fn();
  renderPage(<LeaveClub group={GROUP} apiBase="" userId={5} onLeft={onLeft} />);
  await userEvent.click(screen.getByRole("button", { name: "Leave this club" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Make someone else an admin first.");
  expect(onLeft).not.toHaveBeenCalled();
});

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GroupDiscovery from "../src/pages/GroupDiscovery";
import { mockApi, renderPage } from "./support";

// Clubs (/groups, 7f): your clubs and ones to find as cards, the shared
// search bar, and Start a club beside them.

const club = (id, name, extra = {}) => ({ id, name, slug: `c${id}`, member_count: 3, ...extra });

test("your clubs, clubs to find, asking to join", async () => {
  const setGroupId = vi.fn();
  const calls = mockApi({
    "GET /api/theatres": [{ slug: "afi", name: "AFI Silver", short_name: "AFI" }],
    "GET /api/groups": [club(1, "Night Owls", { role: "admin" }), club(2, "Film Prints Only", { role: "member" })],
    "GET /api/groups/discover": body => ({ groups: [club(3, "Horror Heads", { description: "Midnight movies." }), club(1, "Night Owls", { membership_status: "active" })], page: 1, pages: 1 }),
    "POST /api/groups/c3/join": { ok: true },
  });
  renderPage(<GroupDiscovery apiBase="" activeGroupId={1} setGroupId={setGroupId} />);
  expect(await screen.findByRole("heading", { name: "Clubs" })).toBeInTheDocument();
  const night = (await screen.findAllByRole("article")).find(a => a.textContent.includes("Night Owls") && a.textContent.includes("Viewing"));
  expect(within(night).getByRole("button", { name: "Settings" })).toBeInTheDocument();         // you're its admin
  const prints = screen.getAllByRole("article").find(a => a.textContent.includes("Film Prints Only"));
  await userEvent.click(within(prints).getByRole("button", { name: "Switch to it" }));
  expect(setGroupId).toHaveBeenCalledWith(2);
  const horror = screen.getAllByRole("article").find(a => a.textContent.includes("Horror Heads"));
  expect(horror).toHaveTextContent("Midnight movies.");
  await userEvent.click(within(horror).getByRole("button", { name: "Ask to join" }));
  expect(calls.some(c => c.method === "POST" && c.path === "/api/groups/c3/join")).toBe(true);
  expect(document.querySelector("form.ui-search")).not.toBeNull();                               // the one search bar
  expect(screen.getByRole("complementary", { name: "Start a club" })).toHaveTextContent("Start a club");
});

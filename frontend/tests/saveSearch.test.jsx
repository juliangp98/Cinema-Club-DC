import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SaveSearch } from "../src/pages/BrowsePage";
import { mockApi, renderPage, reply } from "./support";

// "🔔 Alert me" on Browse (R10a): save a search, hear when a new film fits.

test("nothing to save without a filter", async () => {
  mockApi({ "GET /api/searches": [] });
  const { container } = renderPage(<SaveSearch apiBase="" groupId={1} query={{ when: "week" }} />);
  await new Promise(r => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
});

test("saving a search, then turning its alerts off", async () => {
  const calls = mockApi({
    "GET /api/searches": [],
    "POST /api/searches": body => ({ search: { id: 9, params: body.params, group_id: 1 }, fitting_now: 2 }),
    "DELETE /api/searches/9": { ok: true },
  });
  renderPage(<SaveSearch apiBase="" groupId={1} query={{ when: "week", format: "35mm,70MM" }} />);
  await userEvent.click(await screen.findByRole("button", { name: "🔔 Alert me" }));
  expect(calls.find(c => c.method === "POST").body).toEqual({ params: { format: "35mm,70mm" }, group_id: 1 });
  expect(await screen.findByRole("status")).toHaveTextContent("Saved. We'll tell you when a theatre books a new film that fits (2 already do).");
  const on = screen.getByRole("button", { name: "🔔 Alerts on" });
  expect(on).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(on);
  expect(await screen.findByRole("status")).toHaveTextContent("Alerts off for this search.");
  expect(calls.at(-1)).toMatchObject({ method: "DELETE", path: "/api/searches/9" });
});

test("the server's reason when it can't save", async () => {
  mockApi({ "GET /api/searches": [], "POST /api/searches": reply(400, { error: "You have 20 saved searches already." }) });
  renderPage(<SaveSearch apiBase="" groupId={null} query={{ genres: "horror" }} />);
  await userEvent.click(await screen.findByRole("button", { name: "🔔 Alert me" }));
  expect(await screen.findByRole("status")).toHaveTextContent("You have 20 saved searches already.");
});

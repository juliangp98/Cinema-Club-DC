import { getJson, send, HttpError, cachedJson } from "../src/api";
import { mockApi, reply } from "./support";

// One way to talk to the server (R12): every page uses these.

test("send: JSON both ways, the server's words when it says no", async () => {
  const calls = mockApi({
    "POST /api/things": body => ({ got: body }),
    "DELETE /api/things/1": reply(403, { error: "Only admins can do that." }),
  });
  expect(await send("/api/things", "POST", { a: 1 })).toEqual({ got: { a: 1 } });
  expect(fetch.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include",
                                                  headers: { "Content-Type": "application/json" } });
  const err = await send("/api/things/1", "DELETE").catch(e => e);
  expect(err).toBeInstanceOf(HttpError);
  expect([err.status, err.message, err.data.error]).toEqual([403, "Only admins can do that.", "Only admins can do that."]);
  expect(calls.map(c => c.method)).toEqual(["POST", "DELETE"]);
});

test("send: uploads go as they are; no server at all is its own message", async () => {
  mockApi({ "POST /api/me/picture": { ok: true } });
  const form = new FormData();
  form.append("file", new Blob(["x"]), "a.png");
  await send("/api/me/picture", "POST", form);
  const opts = fetch.mock.calls[0][1];
  expect(opts.body).toBe(form);
  expect(opts.headers).toBeUndefined();                                  // the browser sets the boundary
  globalThis.fetch = vi.fn(async () => { throw new TypeError("Failed to fetch"); });
  const err = await send("/api/x", "POST", {}).catch(e => e);
  expect([err.status, err.message]).toEqual([0, "Couldn't reach the server — try again."]);
});

test("getJson: one retry after a server error; remembered unless told not to", async () => {
  let n = 0;
  mockApi({ "GET /api/flaky": () => (n++ ? { fine: true } : reply(502, {})), "GET /api/live": { now: 1 } });
  expect(await getJson("/api/flaky")).toEqual({ fine: true });
  expect(n).toBe(2);
  expect(cachedJson("/api/flaky")).toEqual({ fine: true });
  await getJson("/api/live", { cache: false });
  expect(cachedJson("/api/live")).toBeUndefined();
  mockApi({ "GET /api/gone": reply(404, { error: "Not found" }) });
  await expect(getJson("/api/gone")).rejects.toMatchObject({ status: 404 });
  expect(fetch).toHaveBeenCalledTimes(1);                                 // a 4xx isn't retried
});

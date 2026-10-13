import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ShellContext } from "../src/shell/AppShell";

// A fake server for one test: routes are "METHOD /path?query" (or just
// "METHOD /path", matching any query) → the JSON to answer with, a
// function (body, path) → JSON, or reply(status, json). Unknown routes
// answer 404. Returns the list of calls made: {method, path, body}.
export function mockApi(routes = {}) {
  const calls = [];
  globalThis.fetch = vi.fn(async (url, opts = {}) => {
    const method = (opts.method || "GET").toUpperCase();
    const path = String(url).replace(/^https?:\/\/[^/]+/, "");
    const body = typeof opts.body === "string" ? JSON.parse(opts.body) : opts.body;
    calls.push({ method, path, body });
    let h = routes[`${method} ${path}`] ?? routes[`${method} ${path.split("?")[0]}`];
    if (typeof h === "function") h = await h(body, path);
    const { status, json } = h?.__reply ? h : h === undefined ? reply(404, { error: `no mock for ${method} ${path}` }) : reply(200, h);
    return { ok: status < 400, status, json: async () => json };
  });
  return calls;
}

export const reply = (status, json) => ({ __reply: true, status, json });

// Render inside a router (and, if given, the app shell's context).
export function renderPage(ui, { route = "/", shell } = {}) {
  const tree = <MemoryRouter initialEntries={[route]}>{ui}</MemoryRouter>;
  return render(shell ? <ShellContext.Provider value={shell}>{tree}</ShellContext.Provider> : tree);
}

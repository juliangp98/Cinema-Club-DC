import { readdirSync, readFileSync, statSync } from "fs";
import { join, resolve } from "path";

// No dead ends (R15): every page the app routes to is linked from somewhere
// other than itself — /polls once lived only behind the poll editor's back
// link. Redirects and the sign-in links (which come by email or ?next=) are
// exempt. A param route counts as linked when something builds its path
// ("/films/" + id, `/people/${id}`).

const SRC = resolve(__dirname, "../src");
const EXEMPT = new Set(["*", "/auth/verify", "/invite/:token"]);

function files(dir) {
  return readdirSync(dir).flatMap(f => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.jsx?$/.test(f) ? [p] : [];
  });
}

function routes() {
  const app = readFileSync(join(SRC, "App.jsx"), "utf8");
  const where = {};
  for (const m of app.matchAll(/const (\w+) = lazyPage\(\(\) => import\("\.\/([^"]+)"\)/g)) where[m[1]] = m[2];
  for (const m of app.matchAll(/^import (\w+) from "\.\/(pages\/[^"]+)";/gm)) where[m[1]] = m[2];
  const out = [];
  for (const m of app.matchAll(/<Route path="([^"]+)" element=\{([\s\S]*?)\} \/>/g)) {
    const [path, element] = [m[1], m[2]];
    if (EXEMPT.has(path) || /^\s*<Navigate/.test(element)) continue;
    const page = element.replace(/<RequireSignIn[^>]*>/, "").match(/<(\w+)/)?.[1];
    out.push({ path, file: where[page] && join(SRC, where[page].replace(/(\.jsx)?$/, ".jsx")) });
  }
  return out;
}

const linkTo = path => {
  const fixed = path.split("/:")[0];
  const end = `(?:["'\`?#$]|$)`;                     // the path ends, or a query / ${…} follows
  return new RegExp(`["'\`]${fixed.replace(/[/]/g, "\\/")}${path.includes("/:") ? "\\/" : end}`);
};

test("every page is linked from somewhere else", () => {
  const all = routes();
  expect(all.length).toBeGreaterThan(15);
  const sources = files(SRC).filter(f => !f.endsWith("App.jsx")).map(f => [f, readFileSync(f, "utf8")]);
  const orphans = all.filter(({ path, file }) => {
    const re = linkTo(path);
    return !sources.some(([f, src]) => f !== file && re.test(src));
  }).map(r => r.path);
  expect(orphans).toEqual([]);
});

test("old addresses still land somewhere", () => {
  const app = readFileSync(join(SRC, "App.jsx"), "utf8");
  for (const [from, to] of [["/polls", "/play#polls"], ["/members", "/club?tab=members"], ["/leaderboard", "/club?tab=leaderboard"]]) {
    expect(app).toMatch(new RegExp(`path="${from}" element=\\{<Navigate to="${to.replace(/[?]/g, "\\?")}" replace />\\}`));
  }
});

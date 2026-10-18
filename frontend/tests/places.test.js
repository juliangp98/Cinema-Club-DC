import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { LINK, PLACES, SECTIONS, TOPICS, hrefOf } from "../src/help";
import { PAGE_TOURS } from "../src/shell/pageTours";

// The places (7f, help.json): every link in Help goes somewhere real — a
// page the site has, and an #anchor some page draws — and every topic and
// section has its own address.

const SRC = join(__dirname, "../src");
const files = dir => readdirSync(dir).flatMap(f => (statSync(join(dir, f)).isDirectory() ? files(join(dir, f)) : [join(dir, f)]));
// The app's routes (App.jsx), as patterns: "/films/:id" matches "/films/12".
const routes = [...readFileSync(join(SRC, "App.jsx"), "utf8").matchAll(/<Route path="([^"]+)"/g)]
  .map(m => m[1]).filter(p => p !== "*").map(p => new RegExp(`^${p.replace(/:[a-zA-Z]+/g, "[^/]+")}$`));
const code = files(SRC).filter(f => /\.(jsx?|js)$/.test(f)).map(f => readFileSync(f, "utf8")).join("\n");

test("every place's #anchor is drawn by some page", () => {
  for (const [id, p] of Object.entries(PLACES)) {
    const anchor = p.to.split("#")[1];
    if (!anchor) continue;
    const literal = code.includes(`id="${anchor}"`);
    const shelf = anchor.startsWith("shelf-") && code.includes("id={`shelf-${");     // Discover's shelves
    expect(literal || shelf, `${id}: #${anchor}`).toBe(true);
  }
});

test("every place is on a page the site has", () => {
  for (const [id, p] of Object.entries(PLACES)) {
    const path = p.to.split(/[?#]/)[0];
    expect(routes.some(r => r.test(path)), `${id}: ${path}`).toBe(true);
  }
});

test("every link in Help goes somewhere, and ids don't clash", () => {
  const ids = [...SECTIONS.map(s => s.id), ...Object.keys(TOPICS)];
  expect(new Set(ids).size).toBe(ids.length);
  for (const t of Object.values(TOPICS)) {
    for (const m of t.a.matchAll(LINK)) expect(hrefOf(m[2]), `${t.id}: ${m[2]}`).toBeTruthy();
  }
  expect(Object.keys(PAGE_TOURS).every(k => PAGE_TOURS[k].steps.every(s => s.title && s.body))).toBe(true);
});

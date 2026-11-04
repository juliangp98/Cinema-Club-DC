import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

// Go easy on em dashes (docs/contributing.md, Writing): one where it reads
// best, never two in one line of what members read. Help's answers, the
// tours, and the site's text and messages (string literals and JSX text).
// A dash at either end of a string is a placeholder ("— none —", "— done"),
// not punctuation, so it doesn't count.

const SRC = join(__dirname, "..", "src");
const files = (dir, ext) => readdirSync(dir).flatMap(name => {
  const path = join(dir, name);
  return statSync(path).isDirectory() ? files(path, ext) : ext.test(name) ? [path] : [];
});
const inner = text => {
  const t = text.trim();
  return [...t].filter((c, i, all) => c === "—" && i > 0 && i < all.length - 1).length;
};

function strings(value) {
  if (typeof value === "string") return [value];
  if (Array.isArray(value)) return value.flatMap(strings);
  if (value && typeof value === "object") return Object.values(value).flatMap(strings);
  return [];
}

test("Help: no answer with more than one em dash", () => {
  const help = JSON.parse(readFileSync(join(SRC, "help.json"), "utf8"));
  expect(strings(help).filter(s => inner(s) > 1)).toEqual([]);
});

test("the site's text: no line with more than one em dash", () => {
  const found = [];
  for (const path of files(SRC, /\.jsx?$/)) {
    const src = readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/^\s*\/\/.*$/gm, "").replace(/\s\/\/ .*$/gm, "");
    const pieces = [
      ...src.matchAll(/"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/g),              // string literals
      ...src.matchAll(/>([^<>{}]+)(?=[<{])/g),                               // JSX text
    ].map(m => m[1] ?? m[0]);
    for (const p of pieces) if (inner(p.replace(/^["`]|["`]$/g, "")) > 1) found.push(`${path.slice(SRC.length + 1)}: ${p.trim().slice(0, 80)}`);
  }
  expect(found).toEqual([]);
});

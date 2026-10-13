import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";

// A component that declares a function or variable with the same name as
// something it imports hides the import — that's how the watchlist button
// ended up calling itself instead of the shared toggleWatch(). Never again.

function files(dir) {
  return readdirSync(dir).flatMap(f => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p) : /\.jsx?$/.test(f) ? [p] : [];
  });
}

test("no component hides a name it imports", () => {
  const found = [];
  for (const path of files(join(__dirname, "../src"))) {
    const src = readFileSync(path, "utf8");
    const names = new Set();
    for (const m of src.matchAll(/^import\s+(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s+from/gm)) {
      if (m[1]) names.add(m[1]);
      for (const n of (m[2] || "").split(",")) if (n.trim()) names.add(n.trim().split(/\s+as\s+/).pop());
    }
    for (const name of names) {
      if (new RegExp(`(?:function\\s+${name}\\s*\\(|(?:const|let|var)\\s+${name}\\s*=)`).test(src)) found.push(`${path}: ${name}`);
    }
  }
  expect(found).toEqual([]);
});

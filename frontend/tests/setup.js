import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { clearCache } from "../src/api";

// Newer Node has its own localStorage global (empty without a file) that hides
// jsdom's: give the components an in-memory one.
if (!globalThis.localStorage) {
  const store = new Map();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: {
    getItem: k => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
    removeItem: k => store.delete(k), clear: () => store.clear(), key: i => [...store.keys()][i] ?? null,
    get length() { return store.size; },
  } });
}

// Each test starts with nothing remembered from the last one.
afterEach(() => {
  cleanup();
  clearCache();
  localStorage.clear();
  delete globalThis.fetch;
});

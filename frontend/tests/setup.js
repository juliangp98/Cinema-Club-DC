import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { clearCache } from "../src/api";

// Each test starts with nothing remembered from the last one.
afterEach(() => {
  cleanup();
  clearCache();
  delete globalThis.fetch;
});

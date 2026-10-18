import { readdirSync, readFileSync, statSync } from "fs";
import { join } from "path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import Prompt from "../src/ui/Prompt";
import StyleguidePage from "../src/pages/StyleguidePage";
import { renderPage } from "./support";

// The style system (R15): one card surface, one prompt card, one badge, and
// the admins' style guide that shows them all.

const SRC = join(__dirname, "../src");
function files(dir, ext) {
  return readdirSync(dir).flatMap(f => {
    const p = join(dir, f);
    return statSync(p).isDirectory() ? files(p, ext) : ext.test(f) ? [p] : [];
  });
}
const css = files(SRC, /\.css$/).map(path => [path, readFileSync(path, "utf8").replace(/\/\*[\s\S]*?\*\//g, "")]);

test("a question asked in place is the one small card, with × to put it away", async () => {
  const onClose = vi.fn();
  render(<Prompt question="Share your RSVP in #movies?" label="Share in Discord" hint="Only club members see it."
                 onClose={onClose} actions={<button>Share</button>}><label><input type="checkbox" /> Always</label></Prompt>);
  const card = screen.getByRole("group", { name: "Share in Discord" });
  expect(card).toHaveClass("ui-panel", "ui-panel-prompt");
  expect(card.querySelector(".ui-panel-body")).toHaveTextContent("Share your RSVP in #movies?");
  expect(card.querySelector(".ui-panel-body")).toHaveTextContent("Only club members see it.");
  expect(card.querySelector(".ui-panel-actions")).toContainElement(screen.getByRole("button", { name: "Share" }));
  await userEvent.click(screen.getByRole("button", { name: "Not now" }));
  expect(onClose).toHaveBeenCalled();
});

test("boxes on the card surface use the card tokens", () => {
  // Background bg3 + a border + the large radius is a card: it takes --card-*
  // so every card changes together. (The map's frame is a picture, not a card.)
  const allowed = new Set([".theatre-map iframe"]);
  const off = [];
  for (const [path, src] of css) {
    for (const [, sel, body] of src.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (/background:\s*var\(--bg3\)/.test(body) && /border:\s*1px solid/.test(body)
          && /border-radius:\s*var\(--radius-lg\)/.test(body) && !allowed.has(sel.trim())) off.push(`${path}: ${sel.trim()}`);
    }
  }
  expect(off).toEqual([]);
  const root = css.find(([p]) => p.endsWith("index.css"))[1];
  for (const token of ["--card-bg", "--card-border", "--card-radius", "--card-pad"]) expect(root).toContain(`${token}:`);
});

test("the old one-off prompt and badge styles are gone", () => {
  const retired = ["share-prompt", "share-remember", "watch-discord-prompt", "alert-ask", "list-chip", "pv-status",
                   "chat-via", "theatre-card-tonight", "feed-action"];
  const left = [];
  for (const path of files(SRC, /\.(css|jsx?)$/)) {
    const src = readFileSync(path, "utf8");
    for (const name of retired) if (new RegExp(`\\b${name}\\b`).test(src)) left.push(`${path}: ${name}`);
  }
  expect(left).toEqual([]);
});

const group = { id: 1, name: "Cinema Club DC", slug: "ccdc", emoji: "🎬" };

test("the style guide shows the kit to admins", () => {
  renderPage(<StyleguidePage />, { shell: { group, role: "admin" } });
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Style guide");
  for (const h of ["Buttons", "Chips and badges", "Choices", "Panels", "Text", "People and clubs"]) {
    expect(screen.getByRole("heading", { name: h })).toBeInTheDocument();
  }
  expect(screen.getByRole("group", { name: "A question asked in place?" })).toHaveClass("ui-panel-prompt");
  expect(document.querySelectorAll(".ui-badge")).toHaveLength(6);
  expect(screen.getByRole("link", { name: "‹ Club settings" })).toHaveAttribute("href", "/club?tab=settings");
});

test("everyone else goes back to the Club page", () => {
  renderPage(<Routes><Route path="/styleguide" element={<StyleguidePage />} /><Route path="/club" element={<p>club page</p>} /></Routes>,
             { route: "/styleguide", shell: { group, role: "member" } });
  expect(screen.getByText("club page")).toBeInTheDocument();
});

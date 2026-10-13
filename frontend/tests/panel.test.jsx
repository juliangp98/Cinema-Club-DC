import { render, screen } from "@testing-library/react";
import Panel from "../src/ui/Panel";

// The one bordered box (R12): games, prompts and callouts.

test("title, hint, aside and actions in their places", () => {
  render(<Panel tone="go" title="🎬 Did you make it?" kicker hint="two screenings" aria-label="Did you make it?"
                aside={<button>×</button>} actions={<button>Went</button>}><p>VERTIGO</p></Panel>);
  const box = screen.getByRole("region", { name: "Did you make it?" });
  expect(box).toHaveClass("ui-panel", "ui-panel-go");
  expect(box.querySelector(".ui-panel-title")).toHaveClass("kicker");
  expect(box.querySelector(".ui-panel-head .ui-hint")).toHaveTextContent("two screenings");
  expect(box.querySelector(".ui-panel-aside")).toContainElement(screen.getByRole("button", { name: "×" }));
  expect(box.querySelector(".ui-panel-actions")).toContainElement(screen.getByRole("button", { name: "Went" }));
});

test("a callout keeps its text together beside the actions", () => {
  const { container } = render(<Panel tone="callout" title="Keep your profile" actions={<button>Keep it</button>}>
    <p>This guest profile lives only in this browser.</p></Panel>);
  const body = container.querySelector(".ui-panel-body");
  expect(body).toHaveTextContent("Keep your profile");
  expect(body).toHaveTextContent("lives only in this browser");
  expect(container.querySelector(".ui-panel-title")).toHaveClass("deco");
  expect(body).not.toContainElement(screen.getByRole("button", { name: "Keep it" }));
});

test("no head when there's nothing to put in it; any element", () => {
  const { container } = render(<Panel as="div" tone="tile">just this</Panel>);
  expect(container.querySelector(".ui-panel-head")).toBeNull();
  expect(container.firstChild.tagName).toBe("DIV");
});

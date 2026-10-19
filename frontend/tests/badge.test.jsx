import { render } from "@testing-library/react";
import { ClubBadge, initialsNudge } from "../src/ui/Avatar";

// A club's initials look centered: letters open on the right (C, F, P…) nudge
// the pair right; symmetric ones only give back the trailing letter-spacing.

test("open-right initials sit a little right; symmetric ones don't", () => {
  expect(initialsNudge("MH")).toBeCloseTo(0.02);
  expect(initialsNudge("MP")).toBeCloseTo(0.08);
  expect(initialsNudge("FF")).toBeCloseTo(0.14);
  const { container } = render(<ClubBadge group={{ name: "Film Friends" }} size={64} />);
  expect(container.firstChild).toHaveTextContent("FF");
  expect(container.firstChild.style.paddingLeft).toBe("0.14em");
  const emoji = render(<ClubBadge group={{ name: "Film Friends", emoji: "🎬" }} />).container.firstChild;
  expect(emoji.style.paddingLeft).toBe("");                                  // only initials are nudged
});

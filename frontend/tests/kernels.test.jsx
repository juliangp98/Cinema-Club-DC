import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { KernelPanel } from "../src/pages/Feed";
import { renderPage } from "./support";

// Giving and taking kernels on a feed card (R10b), within the weekly allowance.

const person = (id, name, mine, did = "went") => ({ user: { id, name }, did, net: mine, mine });

test("give or take for each person, within what you have left", async () => {
  const onToss = vi.fn();
  renderPage(<KernelPanel people={[person(2, "Bo", 0), person(3, "Cy", 3), person(4, "Di", -1)]}
                          allowance={{ give_left: 4, take_left: 0 }} onToss={onToss} />);
  expect(screen.getByRole("link", { name: "Bo" })).toHaveAttribute("href", "/people/2");      // their page
  expect(screen.getByText(/This week you have/)).toHaveTextContent("This week you have 4 to give · 0 to take");
  await userEvent.click(screen.getByRole("button", { name: "Give Bo a kernel" }));
  expect(onToss).toHaveBeenCalledWith(2, 1);
  expect(screen.getByRole("button", { name: "Take a kernel from Bo" })).toBeDisabled();       // none left to take
  expect(screen.getByRole("button", { name: "Give Cy a kernel" })).toBeDisabled();            // 3 per screening
  await userEvent.click(screen.getByRole("button", { name: "Give Cy one less kernel" }));
  expect(onToss).toHaveBeenLastCalledWith(3, -1);
  expect(screen.getByRole("button", { name: "Give back the kernel you took from Di" })).toBeEnabled();
});

test("while one is saving nothing else can be pressed; errors show", () => {
  renderPage(<KernelPanel people={[person(2, "Bo", 0)]} allowance={{ give_left: 4, take_left: 2 }} busy
                          error="Nobody can lose more than 5 a week." onToss={() => {}} />);
  expect(screen.getAllByRole("button").every(b => b.disabled)).toBe(true);
  expect(screen.getByRole("status")).toHaveTextContent("Nobody can lose more than 5 a week.");
});

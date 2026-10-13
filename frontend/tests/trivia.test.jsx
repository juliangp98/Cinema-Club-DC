import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import TriviaCard from "../src/ui/TriviaCard";
import { mockApi, renderPage, reply } from "./support";

// Club trivia (R10d): off until an admin turns it on; one try per question.

const URL = "GET /api/trivia/today?group_id=1";
const QUESTION = { id: 7, prompt: "Who directed VERTIGO?", options: ["Hitchcock", "Lang", "Wilder", "Ford"],
                   kernels: 2, anytime: false };

test("off: admins get the switch, others a note only where asked", async () => {
  mockApi({ [URL]: { enabled: false } });
  const { unmount } = renderPage(<TriviaCard apiBase="" groupId={1} role="admin" />);
  expect(await screen.findByRole("link", { name: "Turn it on in Club settings" })).toHaveAttribute("href", "/club?tab=settings");
  unmount();
  const { container, unmount: u2 } = renderPage(<TriviaCard apiBase="" groupId={1} role="member" />);
  await new Promise(r => setTimeout(r, 0));
  expect(container).toBeEmptyDOMElement();
  u2();
  renderPage(<TriviaCard apiBase="" groupId={1} role="member" offNote />);
  expect(await screen.findByText(/isn't on in this club yet/)).toHaveClass("ui-note");
});

test("answering the question of the day", async () => {
  const calls = mockApi({
    [URL]: { enabled: true, daily: true, anytime: false, question: QUESTION },
    "POST /api/trivia/answer": body => ({ ...QUESTION, mine: { choice: body.choice, correct: true }, answer: 0,
                                          earned: 2, stats: { correct: 3, answered: 4 } }),
  });
  renderPage(<TriviaCard apiBase="" groupId={1} role="member" />);
  expect(await screen.findByRole("region", { name: /Question of the day/ })).toHaveClass("ui-panel");
  expect(screen.getByText("One try · +2 🍿 if you're right")).toHaveClass("ui-hint");
  await userEvent.click(screen.getByRole("button", { name: /Hitchcock/ }));
  expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/trivia/answer", body: { group_id: 1, question_id: 7, choice: 0 } });
  expect(await screen.findByRole("status")).toHaveTextContent("✅ Right! +2 🍿 3 of 4 got it so far.");
  expect(screen.getAllByRole("button", { name: /Hitchcock|Lang|Wilder|Ford/ }).every(b => b.disabled)).toBe(true);
});

test("the server's reason when an answer is refused; read-only members can't answer", async () => {
  mockApi({ [URL]: { enabled: true, daily: true, anytime: false, question: QUESTION },
            "POST /api/trivia/answer": reply(400, { error: "You already answered this one." }) });
  const { unmount } = renderPage(<TriviaCard apiBase="" groupId={1} role="member" />);
  await userEvent.click(await screen.findByRole("button", { name: /Lang/ }));
  expect(await screen.findByText("You already answered this one.")).toBeInTheDocument();
  unmount();
  renderPage(<TriviaCard apiBase="" groupId={1} role="viewer" />);
  expect(await screen.findByText("Read-only members can't answer.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Hitchcock/ })).toBeDisabled();
});

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import ChallengesSection from "../src/components/Challenges";
import ChallengePage from "../src/pages/ChallengePage";
import { mockApi, renderPage } from "./support";

// Challenges (challenges.py): Play's section and the new-challenge sheet,
// and a challenge's page — accept, play against the clock, see the results.

const ana = { id: 1, name: "Ana" }, bo = { id: 2, name: "Bo" }, cy = { id: 3, name: "Cy" };
const you = (extra = {}) => ({ status: null, can_accept: false, can_join: false, can_play: false, can_back: false, can_cancel: false,
                               can_end: false, can_rematch: false, can_set_games: false, ...extra });
const player = (user, status, extra = {}) => ({ user, status, seat: false, score: null, round_scores: null, rounds_won: null,
                                                took_ms: null, net: null, winner: false, backers: 0, ...extra });
const challenge = (extra = {}) => ({
  id: 5, group_id: 1, kind: "who_said", emoji: "🗣️", label: "Who said it", games_line: "🗣️ Who said it", gauntlet: false,
  rounds: [{ kind: "who_said", emoji: "🗣️", label: "Who said it", questions: 2 }], questions: 2, stake: 3, pot: 6, seats: 0,
  seats_left: 0, visibility: "club", reveal: "sealed", status: "open", closes_at: new Date(Date.now() + 3600e3).toISOString(),
  created_at: new Date().toISOString(), decided_at: null, created_by: { id: 1, name: "Ana" }, rematch_of: null, rematch: null,
  players: [player(ana, "accepted"), player(bo, "invited")], available: 17,
  backing: { open: true, total: 0, count: 0, allowed: true, mine: null, max: 10 }, you: you(), game_choices: null, ...extra,
});
const SETTINGS = { enabled: true, games: [{ kind: "who_said", emoji: "🗣️", label: "Who said it" }, { kind: "trivia", emoji: "🧠", label: "Trivia" }],
                   max_stake: 10, backing: true, max_bet: 10, max_players: 8, max_seats: 6, questions: [1, 10], max_rounds: 6,
                   deadlines: { hour: "In an hour", tonight: "Tonight", days: "In 3 days" }, available: 17, on_the_line: 3 };
const SHELL = { role: "member", group: { id: 1, slug: "club", discord: false }, user: { id: 2, share_prefs: {} } };

test("Play's challenges: yours first, then the club's, then results — and a new one", async () => {
  const calls = mockApi({
    "GET /api/challenges": { ...SETTINGS, challenges: [
      challenge({ id: 5, you: you({ status: "invited", can_accept: true }) }),
      challenge({ id: 6, players: [player(ana, "finished"), player(cy, "accepted")], you: you({ can_back: true }) }),
      challenge({ id: 7, status: "done", players: [player(ana, "finished", { score: 4, winner: true, net: 3 }), player(bo, "finished", { score: 2, net: -3 })] }),
    ] },
    "GET /api/groups/club/members": [{ status: "active", user: ana }, { status: "active", user: bo }, { status: "active", user: cy }],
    "POST /api/challenges": body => challenge({ id: 9, ...body }),
  });
  renderPage(<ChallengesSection apiBase="" groupId={1} viewerId={2} />, { shell: SHELL });
  expect(await screen.findByRole("heading", { name: "Waiting for you" })).toBeInTheDocument();
  const [mine, live, done] = ["Waiting for you", "Live in the club", "Decided"].map(t => screen.getByRole("heading", { name: t }).nextSibling);
  expect(within(mine).getByRole("button", { name: "Accept or decline" })).toHaveClass("btn-primary");
  expect(within(live).getByRole("button", { name: "🍿 Back a player" })).toBeInTheDocument();
  expect(within(done).getByText("🏆 Ana")).toBeInTheDocument();
  expect(screen.getByText(/You have 17 🍿 to put in · 3 🍿 on the line/)).toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: "⚔️ Challenge someone" }));
  const sheet = within(screen.getByRole("dialog", { name: "New challenge" }));
  await userEvent.click(sheet.getByRole("button", { name: "🧩 Gauntlet" }));
  const games = sheet.getAllByRole("combobox", { name: /Game \d/ });
  expect(games).toHaveLength(3);
  await userEvent.selectOptions(games[0], "trivia");
  await userEvent.click(await sheet.findByRole("button", { name: /Cy/ }));
  await userEvent.click(sheet.getByRole("button", { name: "5 🍿" }));
  await userEvent.click(sheet.getByRole("button", { name: "Live" }));
  await userEvent.click(sheet.getByRole("button", { name: "⚔️ Send the challenge" }));
  const sent = calls.find(c => c.method === "POST").body;
  expect(sent).toMatchObject({ group_id: 1, opponents: [3], stake: 5, reveal: "live", visibility: "club", deadline: "tonight",
                               rounds: [{ kind: "trivia", questions: 5 }, { kind: "random", questions: 5 }, { kind: "random", questions: 5 }] });
  expect(sent.announce).toBeUndefined();                        // no Discord here: nothing to post
});

test("a challenge's page: accept, play against the clock, then the results", async () => {
  const q = (n, extra = {}) => ({ id: 5, challenge: true, kind: "who_said", emoji: "🗣️", label: "Who said it", done: false, round: 0,
                                  rounds: 1, q: n, of: 2, score: n, round_score: n, last: null, each: 1, by_step: false,
                                  quote: `Line ${n + 1}`, film: { title: "Casablanca", year: 1942 }, options: ["Rick", "Ilsa", "Victor", "Louis"],
                                  ends_at: new Date(Date.now() + 30e3).toISOString(), ...extra });
  let state = challenge({ you: you({ status: "invited", can_accept: true }) });
  const calls = mockApi({
    "GET /api/challenges/5": () => state,
    "POST /api/challenges/5/respond": () => (state = challenge({ players: [player(ana, "accepted"), player(bo, "accepted")], you: you({ status: "accepted", can_play: true }) })),
    "GET /api/challenges/5/play": () => ({ question: q(0), challenge: state }),
    "POST /api/challenges/5/play": () => ({ answered: q(0, { done: true, answer: 0, last: { right: true, paid: 1, points: 1 } }),
                                            question: q(1, { last: { right: true, paid: 1, points: 1 } }), challenge: state }),
  });
  renderPage(<Routes><Route path="/challenges/:challengeId" element={<ChallengePage apiBase="" />} /></Routes>, { route: "/challenges/5" });
  expect(await screen.findByText(/The kernels you score decide the winner/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "✓ Accept (3 🍿)" }));
  expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/challenges/5/respond", body: { accept: true } });
  await userEvent.click(await screen.findByRole("button", { name: "▶ Play now" }));
  expect(await screen.findByRole("timer")).toHaveTextContent(/⏱️ (29|30)s/);
  expect(screen.getByText("“Line 1”")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /A Rick/ }));
  expect(await screen.findByText("“Line 2”")).toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("✅ Right! +1 🍿");                        // kernels, like the solo games
  expect(screen.getByText(/Question 2 of 2 · 1 🍿 scored/)).toBeInTheDocument();
});

test("decided: game by game, side by side, and a rematch", async () => {
  const done = challenge({
    status: "done", gauntlet: true, games_line: "🧩 Gauntlet: Who said it, Trivia", kind: "gauntlet", emoji: "🧩", label: "Gauntlet",
    rounds: [{ kind: "who_said", emoji: "🗣️", label: "Who said it", questions: 1 }, { kind: "trivia", emoji: "🧠", label: "Trivia", questions: 1 }],
    players: [player(ana, "finished", { score: 3, rounds_won: 2, winner: true, net: 3 }), player(bo, "finished", { score: 0, rounds_won: 0, net: -3 })],
    you: you({ status: "finished", can_rematch: true }),
    results: [{ round: 0, kind: "who_said", emoji: "🗣️", label: "Who said it", winners: [1],
                questions: [{ q: 0, summary: "Casablanca (1942)", answers: { 1: { right: true, points: 1 }, 2: { right: false, points: 0 } } }] },
              { round: 1, kind: "trivia", emoji: "🧠", label: "Trivia", winners: [1],
                questions: [{ q: 0, summary: "Who directed Vertigo? — Hitchcock", answers: { 1: { right: true, points: 2 }, 2: { timeout: true, points: 0 } } }] }],
  });
  const calls = mockApi({ "GET /api/challenges/5": done, "POST /api/challenges/5/rematch": challenge({ id: 8, stake: 6 }), "GET /api/challenges/8": challenge({ id: 8 }) });
  renderPage(<Routes><Route path="/challenges/:challengeId" element={<ChallengePage apiBase="" />} /></Routes>, { route: "/challenges/5" });
  expect(await screen.findByText("Game 1: 🗣️ Who said it")).toBeInTheDocument();
  expect(screen.getByText("🏆 2 games · 3 🍿 scored")).toBeInTheDocument();
  const trivia = screen.getByText("Game 2: 🧠 Trivia").closest(".ui-panel");
  expect(within(trivia).getAllByRole("cell").map(c => c.textContent)).toEqual(["✓ +2", "⏱️"]);
  await userEvent.click(screen.getByRole("button", { name: "🔁 Double or nothing" }));
  expect(calls.find(c => c.path === "/api/challenges/5/rematch").body).toEqual({ double: true });
});

import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import ChallengesSection from "../src/components/Challenges";
import TournamentPage from "../src/pages/TournamentPage";
import { prizes } from "../src/components/Tournaments";
import { mockApi, renderPage } from "./support";

// Play's Challenges arena (scout.py, tournaments.py): your record and the
// club's best, who you should challenge — the roast, their habits, a
// challenge pre-filled — tournaments in the lists and the "new tournament"
// sheet; and a tournament's page with its bracket.

const ana = { id: 1, name: "Ana" }, bo = { id: 2, name: "Bo" }, cy = { id: 3, name: "Cy" };
const SETTINGS = { enabled: true, games: [{ kind: "who_said", emoji: "🗣️", label: "Who said it" }, { kind: "trivia", emoji: "🧠", label: "Trivia" }],
                   max_stake: 10, backing: true, max_bet: 10, max_players: 8, max_seats: 6, questions: [1, 10], max_rounds: 6,
                   deadlines: { hour: "In an hour", tonight: "Tonight", days: "In 3 days" }, available: 17, on_the_line: 0, challenges: [] };
const SHELL = { role: "member", group: { id: 1, slug: "club", discord: false }, user: { id: 1, share_prefs: {} } };
const you = (extra = {}) => ({ status: null, can_accept: false, can_join: false, can_back: false, can_start: false, can_cancel: false,
                               match: null, ...extra });
const entrant = (user, extra = {}) => ({ user, status: "accepted", seat: false, seed: null, place: null, net: null, alive: true, backers: 0, ...extra });
const side = (user, seed) => ({ user, seed });
const match = (key, label, a, b, extra = {}) => ({ key, section: key[0] === "W" ? "winners" : key[0] === "L" ? "losers" : "final",
  round: Number(key[1]) || 1, slot: 0, label, a, b, from: [], challenge_id: null, status: "waiting", winner_id: null, scores: {},
  played: {}, games: null, closes_at: null, ...extra });
const tournament = (extra = {}) => ({
  id: 4, group_id: 1, title: "🏆 Double elimination", format: "double", format_label: "Double elimination", emoji: "🏆",
  games_line: "🗣️ Who said it", rounds: [{ kind: "who_said", emoji: "🗣️", label: "Who said it", questions: 3 }], stake: 3, pot: 9,
  payout: "all", payout_label: "Winner takes all", prizes: [9], seats: 0, seats_left: 0, seeding: "random", match_time: "day",
  match_time_label: "A day", visibility: "club", reveal: "sealed", status: "open", min_players: 3, max_players: 16,
  closes_at: new Date(Date.now() + 3600e3).toISOString(), created_at: new Date().toISOString(), started_at: null, decided_at: null,
  created_by: ana, players: [entrant(ana), entrant(bo, { status: "invited" }), entrant(cy)],
  bracket: { winners: [], losers: [], league: [], final: [] }, standings: null, places: null,
  backing: { open: true, total: 0, count: 0, allowed: true, mine: null, max: 10 }, you: you(), available: 17, ...extra,
});
const SCOUT = {
  stats: { decided: 3, kernels_moved: 9, you: { played: 3, won: 1, lost: 2, streak: 0, titles: 0, win_rate: 33, kernels: -2,
                                                  nemesis: { user: bo, won: 0, lost: 2, tied: 0, played: 2 }, victim: null,
                                                  best_game: { kind: "who_said", emoji: "🗣️", label: "Who said it", played: 3, win_rate: 33 }, biggest_win: 2 },
           club: [{ key: "wins", icon: "👑", label: "Most wins", user: bo, value: "2–0 (100%)" },
                  { key: "rivalry", icon: "⚔️", label: "Fiercest rivalry", user: ana, other: bo, value: "2 meetings · 0–2" }] },
  picks: [{ user: bo, tag: { key: "grudge", emoji: "😤", label: "Grudge match" }, score: 5, why: ["They're 2–0 up on you. Settle it."],
            kernels: { them: 24, you: 18 }, record: { played: 2, won: 2, lost: 0, streak: 2, titles: 0, win_rate: 100 },
            versus: { won: 0, lost: 2, tied: 0, played: 2 }, best_game: null, worst_game: null,
            suggest: { kind: "trivia", emoji: "🧠", label: "Trivia", stake: 3 }, roastable: true,
            habits: [{ icon: "📋", label: "On the watchlist", you: "3", them: "87" }]},
          { user: cy, tag: { key: "fresh", emoji: "🆕", label: "Fresh meat" }, score: 2, why: ["You've never played them."],
            kernels: { them: 20, you: 18 }, record: { played: 0, won: 0, lost: 0, streak: 0, titles: 0, win_rate: null },
            versus: { won: 0, lost: 0, tied: 0, played: 0 }, best_game: null, worst_game: null,
            suggest: { kind: "who_said", emoji: "🗣️", label: "Who said it", stake: 3 }, roastable: false, habits: [] }],
};
const OPTIONS = { formats: { double: "Double elimination", round_robin: "Round robin + final" },
                  players: { double: [3, 16], round_robin: [3, 6] }, payouts: { all: "Winner takes all", top3: "60 / 30 / 10" },
                  match_times: { hour: "An hour", tonight: "Till tonight", day: "A day" },
                  seedings: { random: "Random", record: "By challenge record" }, max_seats: 8 };

test("the arena: your record, the club's best, and who to challenge — roast, habits, a challenge ready to send", async () => {
  const calls = mockApi({
    "GET /api/challenges": SETTINGS,
    "GET /api/challenges/scout": SCOUT,
    "GET /api/tournaments": { ...OPTIONS, tournaments: [tournament({ players: [entrant(ana), entrant(bo, { status: "invited" })], you: you({ status: "invited", can_accept: true }) })] },
    "POST /api/challenges/scout/2/roast": body => ({ roast: body.again ? "Bo again" : "Bo has 87 films on his watchlist and has seen 3.", by: "facts", more: !body.again }),
    "GET /api/groups/club/members": [{ status: "active", user: ana }, { status: "active", user: bo }, { status: "active", user: cy }],
  });
  renderPage(<ChallengesSection apiBase="" groupId={1} viewerId={1} />, { shell: SHELL });
  const record = await screen.findByRole("list", { name: "Your challenges" });
  expect(record).toHaveTextContent("1–2");
  expect(record).toHaveTextContent("Your nemesisBobeat you 2 times");
  expect(screen.getByRole("list", { name: "The club's challenge stats" })).toHaveTextContent("Fiercest rivalryAna vs Bo");
  const bo$ = within(screen.getByRole("article", { name: "Challenge Bo?" }));
  expect(bo$.getByText("😤 Grudge match")).toBeInTheDocument();
  expect(bo$.getByText("Try: 🧠 Trivia for 3 🍿")).toBeInTheDocument();
  await userEvent.click(bo$.getByRole("button", { name: "🔥 Roast" }));
  expect(await bo$.findByText("🔥 Bo has 87 films on his watchlist and has seen 3.")).toBeInTheDocument();
  await userEvent.click(bo$.getByRole("button", { name: "🔥 Another" }));
  expect(await bo$.findByText("🔥 Bo again")).toBeInTheDocument();
  expect(calls.filter(c => c.path === "/api/challenges/scout/2/roast").map(c => c.body.again)).toEqual([false, true]);
  await userEvent.click(bo$.getByRole("button", { name: "📊 Habits" }));
  expect(bo$.getByRole("row", { name: /On the watchlist 3 87/ })).toBeInTheDocument();
  const cy$ = within(screen.getByRole("article", { name: "Challenge Cy?" }));
  expect(cy$.queryByRole("button", { name: "🔥 Roast" })).toBeNull();
  expect(cy$.getByText("🛡️ Roasts off")).toBeInTheDocument();

  const waiting = screen.getByRole("heading", { name: "Waiting for you" }).nextSibling;
  expect(within(waiting).getByRole("button", { name: "Join or decline" })).toHaveClass("btn-primary");

  await userEvent.click(bo$.getByRole("button", { name: "⚔️ Challenge" }));         // the sheet, filled in from the pick
  const sheet = within(screen.getByRole("dialog", { name: "New challenge" }));
  expect(sheet.getByRole("combobox", { name: "Game" })).toHaveValue("trivia");
  expect(await sheet.findByRole("button", { name: /Bo/ })).toHaveAttribute("aria-pressed", "true");
  expect(sheet.getByRole("button", { name: "3 🍿" })).toHaveAttribute("aria-pressed", "true");
});

test("a new tournament: round robin, three invited, 60 / 30 / 10", async () => {
  const calls = mockApi({
    "GET /api/challenges": SETTINGS,
    "GET /api/tournaments": { ...OPTIONS, tournaments: [] },
    "GET /api/groups/club/members": [{ status: "active", user: ana }, { status: "active", user: bo }, { status: "active", user: cy },
                                     { status: "active", user: { id: 5, name: "Di" } }],
    "POST /api/tournaments": body => tournament({ id: 9, ...body }),
  });
  renderPage(<ChallengesSection apiBase="" groupId={1} viewerId={1} />, { shell: SHELL });
  await userEvent.click(await screen.findByRole("button", { name: "🏆 Start a tournament" }));
  const sheet = within(screen.getByRole("dialog", { name: "New tournament" }));
  await userEvent.click(sheet.getByRole("button", { name: "Round robin + final" }));
  expect(sheet.getByText(/3–6 players. Everyone plays everyone once/)).toBeInTheDocument();
  const send = sheet.getByRole("button", { name: "🏆 Send the invites" });
  await userEvent.click(await sheet.findByRole("button", { name: /Bo/ }));
  expect(send).toBeDisabled();
  expect(sheet.getByText(/It needs 1 more/)).toBeInTheDocument();
  await userEvent.click(sheet.getByRole("button", { name: /Cy/ }));
  await userEvent.click(sheet.getByRole("button", { name: /Di/ }));
  await userEvent.click(sheet.getByRole("button", { name: "5 🍿" }));
  await userEvent.click(sheet.getByRole("button", { name: "60 / 30 / 10" }));
  expect(sheet.getByText("Pot: 20 🍿 with 4 in: 🥇 12, 🥈 6, 🥉 2.")).toBeInTheDocument();
  await userEvent.click(send);
  expect(calls.find(c => c.method === "POST").body).toMatchObject({
    group_id: 1, format: "round_robin", players: [2, 3, 5], stake: 5, payout: "top3", seeding: "random", deadline: "tonight",
    match_time: "day", visibility: "club", rounds: [{ kind: "random", questions: 5 }] });
});

test("a tournament's page: your match, the bracket with its bye, and backing a winner", async () => {
  const running = tournament({
    status: "running", started_at: new Date().toISOString(),
    players: [entrant(ana, { seed: 1 }), entrant(bo, { seed: 2 }), entrant(cy, { seed: 3 })],
    bracket: {
      winners: [match("W1-0", "Winners' round 1", side(ana, 1), { bye: true }, { status: "bye", winner_id: 1 }),
                match("W1-1", "Winners' round 1", side(bo, 2), side(cy, 3), { status: "open", challenge_id: 31, played: { 2: "finished", 3: "accepted" } }),
                match("W2-0", "Winners' final", side(ana, 1), null)],
      losers: [match("L1-0", "Losers' round 1", { bye: true }, null), match("L2-0", "Losers' final", null, null)],
      league: [], final: [match("GF", "Grand final", null, null)] },
    you: you({ status: "accepted" }),
  });
  const watcher = { ...running, players: running.players, you: you({ can_back: true }) };
  const calls = mockApi({ "GET /api/tournaments/4": () => watcher,
                          "POST /api/tournaments/4/back": body => ({ ...watcher, backing: { ...watcher.backing, count: 1, total: body.amount,
                                                                                             mine: { backing_id: body.user_id, amount: body.amount, net: null } } }) });
  renderPage(<Routes><Route path="/tournaments/:tournamentId" element={<TournamentPage apiBase="" user={{ id: 7 }} />} /></Routes>,
             { route: "/tournaments/4" });
  expect(await screen.findByRole("heading", { name: "Winners' bracket" })).toBeInTheDocument();
  const wins = within(screen.getByRole("region", { name: "Winners' bracket" }));
  expect(wins.getAllByText("bye")).toHaveLength(1);
  expect(wins.getByRole("link", { name: "Watch" })).toHaveAttribute("href", "/challenges/31");
  expect(wins.getAllByText("TBD")).toHaveLength(1);
  expect(screen.getByRole("region", { name: "Losers' bracket" })).toHaveTextContent("Losers' final");
  expect(screen.getByRole("region", { name: "Grand final" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Cy" }));
  await userEvent.click(screen.getByRole("button", { name: "Back them" }));
  expect(calls.at(-1)).toEqual({ method: "POST", path: "/api/tournaments/4/back", body: { user_id: 3, amount: 2 } });
  expect(await screen.findByText(/You backed/)).toHaveTextContent("You backed Cy with 2 🍿");
});

test("decided: the round robin's standings, medals and prizes", async () => {
  const done = tournament({
    format: "round_robin", format_label: "Round robin + final", title: "🏆 Round robin + final", status: "done", payout: "top3",
    payout_label: "60 / 30 / 10", prizes: [6, 2, 1], pot: 9, decided_at: new Date().toISOString(),
    players: [entrant(ana, { seed: 1, place: 3, net: -2 }), entrant(bo, { seed: 2, place: 1, net: 3 }), entrant(cy, { seed: 3, place: 2, net: -1 })],
    standings: [{ user_id: 2, user: bo, played: 2, won: 2, lost: 0, score: 6 }, { user_id: 3, user: cy, played: 2, won: 1, lost: 1, score: 3 },
                { user_id: 1, user: ana, played: 2, won: 0, lost: 2, score: 1 }],
    bracket: { winners: [], losers: [], league: [], final: [match("F", "Final", side(bo, 2), side(cy, 3), { status: "done", challenge_id: 40, winner_id: 2, scores: { 2: 3, 3: 1 } })] },
  });
  mockApi({ "GET /api/tournaments/4": done });
  renderPage(<Routes><Route path="/tournaments/:tournamentId" element={<TournamentPage apiBase="" user={{ id: 1 }} />} /></Routes>,
             { route: "/tournaments/4" });
  expect(await screen.findByText(/Prizes: 🥇 6 🍿, 🥈 2 🍿, 🥉 1 🍿/)).toBeInTheDocument();
  const players = within(screen.getByText("Players").closest(".ch-players")).getAllByRole("listitem").map(li => li.textContent);
  expect(players[0]).toMatch(/Bo.*🥇 Champion.*\+3 🍿/);
  expect(players[2]).toMatch(/Ana.*🥉 Third.*−2 🍿/);
  expect(within(screen.getByRole("region", { name: "Standings" })).getAllByRole("row").map(r => r.textContent))
    .toEqual(["#PlayerWonLost🍿 scored", "1Bo206", "2Cy113", "3Ana021"]);
  expect(within(screen.getByRole("region", { name: "Final" })).getByRole("link", { name: "Results" })).toHaveAttribute("href", "/challenges/40");
  expect(prizes(16, "top3")).toEqual([11, 4, 1]);
  expect(prizes(9, "all")).toEqual([9]);
});

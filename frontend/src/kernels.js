// Where kernels come from (kernels.PARTS on the server), in the order they're
// shown — one list for the leaderboard's bars, Play and members' pages.
export const KERNEL_PARTS = [
  { key: "polls", label: "polls" },
  { key: "going_out", label: "going out" },
  { key: "trivia", label: "trivia" },
  { key: "bingo", label: "bingo" },
  { key: "games", label: "games" },
  { key: "members", label: "from members" },
];

// 🥇🥈🥉 for the top three places (ties share one, from the server's `place`) — none at 0 kernels.
const MEDALS = ["🥇", "🥈", "🥉"];
export const medal = (place, kernels) => (kernels > 0 && MEDALS[place - 1]) || place;

// "polls 2 · going out 10 · from members 1" — trivia, bingo and games only when there are some.
export const kernelParts = breakdown => KERNEL_PARTS
  .filter(({ key }) => !["trivia", "bingo", "games"].includes(key) || breakdown[key])
  .map(({ key, label }) => `${label} ${breakdown[key]}`).join(" · ");

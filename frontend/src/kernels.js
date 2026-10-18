// Where kernels come from (kernels.PARTS on the server), in the order they're
// shown — one list for the leaderboard's bars, Play and members' pages.
export const KERNEL_PARTS = [
  { key: "polls", label: "polls" },
  { key: "going_out", label: "going out" },
  { key: "trivia", label: "trivia" },
  { key: "bingo", label: "bingo" },
  { key: "members", label: "from members" },
];

// "polls 2 · going out 10 · from members 1" — trivia and bingo only when there are some.
export const kernelParts = breakdown => KERNEL_PARTS
  .filter(({ key }) => !["trivia", "bingo"].includes(key) || breakdown[key])
  .map(({ key, label }) => `${label} ${breakdown[key]}`).join(" · ");

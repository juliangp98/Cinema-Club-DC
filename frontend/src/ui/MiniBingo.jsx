// A bingo card at a glance (R10e; shared since 7g): nine cells, filled or
// not. A line gives it a gold edge, the full card a double one. The feed's
// rail, the club strip on Play, and a member's past cards.
export default function MiniBingo({ cells, line, full, size = "sm", label }) {
  return (
    <span className={`mini-bingo ${size}${full ? " full" : line ? " line" : ""}`} role={label ? "img" : undefined}
          aria-label={label} aria-hidden={label ? undefined : "true"}>
      {cells.map((on, i) => <span key={i} className={on ? "on" : ""} />)}
    </span>
  );
}

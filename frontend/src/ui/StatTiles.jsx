// Numbers at a glance (7g): a row of tiles — a label, the number, a line
// under it. Game records on Play and members' pages, the club's totals.
// items: [{label, value, sub?}] (falsy items are skipped).
export default function StatTiles({ items, label }) {
  const shown = items.filter(Boolean);
  if (!shown.length) return null;
  return (
    <ul className="ui-stats" aria-label={label}>
      {shown.map(it => (
        <li key={it.label} className="ui-stat">
          <span className="ui-stat-label">{it.label}</span>
          <strong className="ui-stat-value">{it.value}</strong>
          {it.sub && <span className="ui-stat-sub">{it.sub}</span>}
        </li>
      ))}
    </ul>
  );
}

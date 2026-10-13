// Your taste (R13), shared by the editor, your profile and others' (when
// they show it). The definitions themselves live on the server (taste.py).

export const PEOPLE_KINDS = [
  { status: "director", label: "Directors", one: "director" },
  { status: "actor", label: "Actors", one: "actor" },
  { status: "writer", label: "Writers", one: "writer" },
];
export const PERSON_KIND = Object.fromEntries(PEOPLE_KINDS.map(k => [k.status, k.one]));

// Someone's taste at a glance: {genres, ways, theatres, movies, people}
// (labels, as /api/users/:id/profile and /api/me/taste's `summary` give it).
export default function TasteChips({ taste, empty = null }) {
  const items = [
    ...(taste?.genres || []).map(g => ({ key: `g${g}`, label: g })),
    ...(taste?.ways || []).map(w => ({ key: `w${w}`, label: w })),
    ...(taste?.theatres || []).map(t => ({ key: `t${t}`, label: `📍 ${t}` })),
    ...(taste?.movies || []).map(m => ({ key: `m${m.key}`, label: `🎬 ${m.label}` })),
    ...(taste?.people || []).map(p => ({ key: `p${p.kind}${p.label}`, label: `${p.label} · ${PERSON_KIND[p.kind] || p.kind}` })),
  ];
  if (!items.length) return empty;
  return (
    <ul className="filter-chips taste-chips" aria-label="Taste">
      {items.map(i => <li key={i.key}><span className="chip">{i.label}</span></li>)}
    </ul>
  );
}

// How alike your taste is to someone's (R13) — only when they show theirs:
// {score: 0–100 | null, shared: [labels]}.
export function TasteMatch({ match }) {
  if (!match || match.score == null) return null;
  return (
    <div className="taste-match">
      <span className="chip gold">🎨 Taste match {match.score}%</span>
      {match.shared.length > 0 && <span className="ui-hint">You both love {match.shared.slice(0, 6).join(", ")}</span>}
    </div>
  );
}

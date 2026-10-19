import HELP from "./help.json";

// The Help guide's content and the site's places (7f), one copy for the Help
// page, the page tours and the AI answers (the backend reads help.json too).
// A place is somewhere a link can take you — {label, to}; `to`'s #anchor is
// the element the arrival glow lights. Text links: [words](place-id), or
// [words](help:topic-id) for another Help topic.
export const SECTIONS = HELP.sections;
export const PLACES = HELP.places;
export const TOPICS = Object.fromEntries(SECTIONS.flatMap(s => s.items.map(i => [i.id, { ...i, section: s.id }])));

export const LINK = /\[([^\]]+)\]\(([a-z0-9-]+(?::[a-z0-9-]+)?)\)/g;

// Where a link reference goes: a place's address, a Help topic, or null.
export function hrefOf(ref) {
  if (ref.startsWith("help:")) return TOPICS[ref.slice(5)] ? `/help#${ref.slice(5)}` : null;
  return PLACES[ref]?.to || null;
}

// A place outside the site (the code on GitHub): opened in a new tab.
export const isOutside = to => /^https?:\/\//.test(to || "");

// The words alone, for searching and plain-text uses.
export const plain = text => (text || "").replace(LINK, "$1");

// The topics likeliest to answer a question in your own words — the same
// ranking ✨ Ask starts from (help_ai.retrieve): words in the question count
// most, then the section's title, then the answer.
const STOP = new Set(HELP.stopwords);
const stem = w => { for (const end of ["ing", "ed", "es", "s"]) if (w.length > end.length + 3 && w.endsWith(end)) return w.slice(0, -end.length); return w; };
export const words = text => (text || "").toLowerCase().match(/[a-z0-9]+/g)?.filter(w => w.length > 2 && !STOP.has(w)).map(stem) || [];
export function rank(q, n = 5) {
  const ws = new Set(words(q));
  if (!ws.size) return [];
  const hits = list => words(list).filter((w, i, all) => ws.has(w) && all.indexOf(w) === i).length;
  return Object.values(TOPICS)
    .map(t => ({ t, score: 3 * hits(t.q) + 2 * hits(SECTIONS.find(s => s.id === t.section).title) + hits(plain(t.a)) }))
    .filter(x => x.score).sort((a, b) => b.score - a.score).slice(0, n).map(x => x.t);
}

import { useJson } from "./api";

// Cities and theatres (the backend's cities.py and places.py): every theatre
// is in a city and an area of it (DC / Maryland / Virginia); a showtime is on
// its city's clock. City menus, headings and tags show only when more than
// one city has theatres (`multi`).

export const DEFAULT_CITY = "dc";

// {cities: [{slug, name, short, tz, phrase, areas: [{key, label}]}], multi, default}
export const useCities = (apiBase = "") => useJson(`${apiBase}/api/cities`).data;
// Every active theatre: {slug, name, short_name, color, city, area, area_label, …}
export const useTheatres = (apiBase = "") => useJson(`${apiBase}/api/theatres`).data || [];

export const cityOf = (cities, slug) => cities?.find(c => c.slug === slug) || null;

// Minutes ahead of UTC in a time zone right now ("America/Chicago" → -300 or -360).
export function zoneOffset(tz, at = new Date()) {
  try {
    const name = new Intl.DateTimeFormat("en-US", { timeZone: tz, timeZoneName: "shortOffset" })
      .formatToParts(at).find(p => p.type === "timeZoneName")?.value || "GMT";
    const m = name.match(/GMT([+-])(\d+)(?::(\d+))?/);
    return m ? (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] || 0)) : 0;
  } catch {
    return 0;
  }
}

// A first visit's city, from the browser's time zone: the city in that zone,
// else the one closest in time, else the first.
export function guessCity(cities) {
  if (!cities?.length) return null;
  let tz = null;
  try { tz = Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { /* old browsers */ }
  const exact = cities.find(c => c.tz === tz);
  if (exact) return exact.slug;
  const mine = -new Date().getTimezoneOffset();
  return [...cities].sort((a, b) => Math.abs(zoneOffset(a.tz) - mine) - Math.abs(zoneOffset(b.tz) - mine))[0].slug;
}

// Remembered on this device (and on your account, when signed in).
const KEY = "cinemaclub_city";
export function readCity() { try { return localStorage.getItem(KEY); } catch { return null; } }
export function writeCity(slug) { try { if (slug) localStorage.setItem(KEY, slug); else localStorage.removeItem(KEY); } catch { /* private mode */ } }

// [[area label, theatres]] in the city's own area order (unknown areas last).
export function byArea(theatres, city) {
  const order = (city?.areas || []).map(a => a.label);
  const groups = new Map();
  for (const t of theatres) {
    const k = t.area_label || "Other";
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(t);
  }
  const rank = k => (order.includes(k) ? order.indexOf(k) : order.length);
  return [...groups.entries()].sort((a, b) => rank(a[0]) - rank(b[0]));
}

// {home: theatres in `home`, others: [[city, theatres]]} — other cities in
// the site's order, each theatre once.
export function byCity(theatres, home, cities) {
  const cityOfT = t => t.city || home;              // (a theatre that doesn't say: the home city's)
  const others = new Map();
  for (const t of theatres) {
    if (cityOfT(t) === home) continue;
    if (!others.has(t.city)) others.set(t.city, []);
    others.get(t.city).push(t);
  }
  const rank = slug => { const i = (cities || []).findIndex(c => c.slug === slug); return i < 0 ? 99 : i; };
  return {
    home: theatres.filter(t => cityOfT(t) === home),
    others: [...others.entries()].sort((a, b) => rank(a[0]) - rank(b[0]))
      .map(([slug, list]) => [cityOf(cities, slug) || { slug, name: slug, short: slug, areas: [] }, list]),
  };
}

import { useEffect } from "react";

// What search engines see for a page (SEO, Oct 2026): the site is one app
// with one <head>, so each public page sets its own title, description,
// canonical address and share-card tags here, and structured data (JSON-LD)
// where it helps — a film and its screenings, a theatre, Help's questions.
// Private pages say noindex (nginx's X-Robots-Tag and robots.txt do too).
const SITE = "Cinema Club DC";
const ORIGIN = typeof window !== "undefined" ? window.location.origin : "";
export const DEFAULT_DESCRIPTION = "Every screening at the DC area's independent and repertory theatres — AFI, Suns, Alamo, "
  + "the Smithsonian and more — film prints, Q&As and one-night-only shows, in one place.";

function tag(selector, make) {
  let el = document.head.querySelector(selector);
  if (!el) { el = make(); document.head.appendChild(el); }
  return el;
}
const meta = (attr, key, content) => {
  const el = tag(`meta[${attr}="${key}"]`, () => {
    const m = document.createElement("meta");
    m.setAttribute(attr, key);
    return m;
  });
  el.setAttribute("content", content);
};

export function setPageMeta({ title, description = DEFAULT_DESCRIPTION, path, image, jsonLd, noindex = false }) {
  const full = title ? `${title} · ${SITE}` : `${SITE} — repertory and independent film in DC`;
  document.title = full;
  meta("name", "description", description);
  meta("name", "robots", noindex ? "noindex, follow" : "index, follow");
  meta("property", "og:title", title || SITE);
  meta("property", "og:description", description);
  meta("property", "og:type", "website");
  if (image) meta("property", "og:image", image);
  const canonical = tag('link[rel="canonical"]', () => Object.assign(document.createElement("link"), { rel: "canonical" }));
  canonical.href = `${ORIGIN}${path ?? window.location.pathname}`;
  meta("property", "og:url", canonical.href);
  const ld = tag('script[type="application/ld+json"]#page-ld', () => Object.assign(document.createElement("script"), { type: "application/ld+json", id: "page-ld" }));
  ld.textContent = jsonLd ? JSON.stringify(jsonLd) : "";
}

// In a page: its title and description (and anything else above), kept in
// step with `deps` (the page's data as it loads). Until `make` has something
// (null: still loading), the shell's defaults for the address stand.
export default function usePageMeta(make, deps = []) {
  useEffect(() => {
    const m = make();
    if (m) setPageMeta(m);
  }, deps);   // eslint-disable-line react-hooks/exhaustive-deps
}

// Showtimes are DC wall-clock times; structured data wants the offset too
// ("2026-10-24T19:30:00-04:00" — EDT, or -05:00 in winter).
export function withDcOffset(iso) {
  if (!iso || /[zZ]|[+-]\d\d:\d\d$/.test(iso)) return iso;
  const [d, t] = iso.split("T");
  const guess = new Date(`${d}T${t || "12:00:00"}Z`);
  const name = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", timeZoneName: "shortOffset" })
    .formatToParts(guess).find(p => p.type === "timeZoneName")?.value || "GMT-5";
  const m = name.match(/GMT([+-])(\d+)(?::(\d+))?/);
  const off = m ? `${m[1]}${m[2].padStart(2, "0")}:${(m[3] || "00").padStart(2, "0")}` : "-05:00";
  return `${iso.length === 16 ? `${iso}:00` : iso}${off}`;
}

// Structured data builders.
export function filmLd(movie, showtimes = []) {
  const film = { "@type": "Movie", name: movie.title, ...(movie.release_year && { dateCreated: String(movie.release_year) }),
                 ...(movie.director && { director: { "@type": "Person", name: movie.director } }),
                 ...(movie.poster_url && { image: movie.poster_url }), ...(movie.description && { description: movie.description }) };
  const events = showtimes.slice(0, 20).map(s => ({
    "@type": "ScreeningEvent", name: movie.title, startDate: withDcOffset(s.start_time), workPresented: { "@type": "Movie", name: movie.title },
    eventAttendanceMode: "https://schema.org/OfflineEventAttendanceMode",
    eventStatus: s.is_cancelled ? "https://schema.org/EventCancelled" : "https://schema.org/EventScheduled",
    ...(s.format_label && { videoFormat: s.format_label }),
    location: { "@type": "MovieTheater", name: s.theatre.name, ...(s.theatre.address && { address: s.theatre.address }) },
    ...(s.purchase_link && { offers: { "@type": "Offer", url: s.purchase_link,
                                    availability: s.is_sold_out ? "https://schema.org/SoldOut" : "https://schema.org/InStock" } }),
  }));
  return { "@context": "https://schema.org", "@graph": [film, ...events] };
}

export function theatreLd(t) {
  return { "@context": "https://schema.org", "@type": "MovieTheater", name: t.name, ...(t.address && { address: t.address }),
           ...(t.website && { url: t.website }),
           ...(t.lat != null && t.lon != null && { geo: { "@type": "GeoCoordinates", latitude: t.lat, longitude: t.lon } }) };
}

export function faqLd(items) {
  return { "@context": "https://schema.org", "@type": "FAQPage",
           mainEntity: items.map(i => ({ "@type": "Question", name: i.q, acceptedAnswer: { "@type": "Answer", text: i.a } })) };
}

// Every page's defaults, from its address (set by the app shell on each
// navigation; film, theatre and Help pages add their specifics as they load).
// Private pages — accounts, clubs, games — are noindex; Browse's filtered
// addresses too (the same films in endless combinations), with /browse as
// their canonical.
const PRIVATE = /^\/(me|club|feed|play|polls|people|groups|signin|auth|invite|styleguide)(\/|$)/;
const ROUTES = [
  [/^\/$/, {}],
  [/^\/calendar$/, { title: "Calendar", description: "Every showtime at the DC area's repertory and independent theatres, day by day — film prints, Q&As, one-night-only shows and what's coming soon." }],
  [/^\/browse$/, { title: "Browse films", description: "Browse every film playing at DC's repertory and independent theatres by date, theatre, genre, decade, format and mood." }],
  [/^\/theatres$/, { title: "Theatres", description: "The DC area's independent and repertory theatres — AFI Silver, Suns, Alamo, the Smithsonian and more: what's on at each, maps and how to get there." }],
  [/^\/theatres\/[^/]+$/, { title: "Theatre" }],
  [/^\/films\/[^/]+$/, { title: "Film" }],
  [/^\/help$/, { title: "Help", description: "How Cinema Club DC works: finding films, making plans with a club, alerts, Discord and more." }],
];
const PRIVATE_TITLES = { me: "Me", club: "Club", feed: "Club feed", play: "Play", polls: "Poll", people: "Member", groups: "Clubs",
                         signin: "Sign in", auth: "Signing in", invite: "Invite", styleguide: "Style guide" };

export function routeMeta(pathname, search = "") {
  const priv = pathname.match(PRIVATE);
  if (priv) return { title: PRIVATE_TITLES[priv[1]], noindex: true, path: pathname };
  const found = ROUTES.find(([re]) => re.test(pathname));
  const base = found ? found[1] : { title: null };
  if (pathname === "/browse" && search.length > 1) return { ...base, noindex: true, path: "/browse" };
  return { ...base, path: pathname };
}

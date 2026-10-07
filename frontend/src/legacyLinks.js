// Links shared before the Feed became the home page (Discord embeds, DMs,
// emails) point at /?showtime=<id> or /?theatre=<slug>: those belong to the
// calendar. Imported first in main.jsx so it runs before the calendar module,
// which reads its deep link once, at load.
const url = new URL(window.location.href);
if (url.pathname === "/" && (url.searchParams.has("showtime") || url.searchParams.has("theatre"))) {
  window.history.replaceState(null, "", `/calendar${url.search}${url.hash}`);
}

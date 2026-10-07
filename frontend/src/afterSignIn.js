// Where to go once signed in (R5a): /signin?next=… remembers it here, so the
// emailed link (often opened as a fresh page) still lands you back there.
const KEY = "cinemaclub_after_signin";
export const safeNext = next => (next && next.startsWith("/") && !next.startsWith("//") ? next : null);
export function rememberNext(next) {
  try { safe(next) ? localStorage.setItem(KEY, next) : localStorage.removeItem(KEY); } catch { /* private mode */ }
}
export function takeNext() {
  try { const n = localStorage.getItem(KEY); localStorage.removeItem(KEY); return safeNext(n); } catch { return null; }
}
function safe(n) { return !!safeNext(n); }

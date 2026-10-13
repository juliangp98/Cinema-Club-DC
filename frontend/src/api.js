import { useState, useEffect, useCallback, useRef } from "react";

// Loading data (R7b) — one way for every page:
//  · a timeout and one automatic retry (a slow or dropped first request after
//    a quiet spell used to leave pages empty until a refresh);
//  · what's already loaded is kept in memory for this tab, so going back to
//    a page shows it at once while it refreshes. Never written to the device.

const memory = new Map();                 // url -> data
const MAX_ENTRIES = 80;
const sleep = ms => new Promise(r => setTimeout(r, ms));

export class HttpError extends Error {
  constructor(status, data) {
    super((data && data.error) || `Request failed (${status})`);
    this.status = status;
    this.data = data;
  }
}

function remember(url, data) {
  memory.delete(url);
  memory.set(url, data);
  if (memory.size > MAX_ENTRIES) memory.delete(memory.keys().next().value);
}

export const cachedJson = url => memory.get(url);
export const clearCache = () => memory.clear();           // on sign-in / sign-out

// `cache: false` for lookups not worth remembering (type-ahead, polling).
export async function getJson(url, { timeout = 25000, retries = 1, signal, cache = true } = {}) {
  for (let attempt = 0; ; attempt += 1) {
    const ctl = new AbortController();
    const abort = () => ctl.abort();
    signal?.addEventListener("abort", abort);
    const timer = setTimeout(abort, timeout);
    try {
      const r = await fetch(url, { credentials: "include", signal: ctl.signal });
      const data = await r.json().catch(() => null);
      if (r.ok) {
        if (cache) remember(url, data);
        return data;
      }
      const err = new HttpError(r.status, data);
      if (r.status < 500 || attempt >= retries) throw err;      // a 4xx won't fix itself
    } catch (e) {
      if (signal?.aborted || e instanceof HttpError || attempt >= retries) throw e;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
    }
    await sleep(800 * (attempt + 1));
  }
}

// { data, error, loading, reload } for a URL (null = don't load). Shows the
// remembered copy straight away, then the fresh one.
export function useJson(url, { keep = false } = {}) {
  const [data, setData] = useState(() => (url ? cachedJson(url) ?? null : null));
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(!!url);
  const [tick, setTick] = useState(0);
  const last = useRef(data);
  last.current = data;

  useEffect(() => {
    if (!url) { setLoading(false); return undefined; }
    const ctl = new AbortController();
    const hit = cachedJson(url);
    setData(hit ?? (keep ? last.current : null));
    setError(null);
    setLoading(true);
    getJson(url, { signal: ctl.signal })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { if (!ctl.signal.aborted) { setError(e); setLoading(false); } });
    return () => ctl.abort();
  }, [url, tick, keep]);

  const reload = useCallback(() => setTick(t => t + 1), []);
  return { data, error, loading, reload };
}

// Sending (R9b): one way to POST / PUT / DELETE — the session cookie, JSON
// both ways (or a FormData upload), and the server's own message when it
// says no (an HttpError).
export async function send(url, method = "POST", body) {
  const form = body instanceof FormData;
  let r;
  try {
    r = await fetch(url, {
      method, credentials: "include",
      headers: body === undefined || form ? undefined : { "Content-Type": "application/json" },
      body: body === undefined || form ? body : JSON.stringify(body),
    });
  } catch {
    throw new HttpError(0, { error: "Couldn't reach the server — try again." });
  }
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new HttpError(r.status, data);
  return data;
}

// The actions many pages share.
export const rsvp = (apiBase, showtimeId, status, groupId) =>
  send(`${apiBase}/api/rsvp`, "POST", { showtime_id: showtimeId, status, group_id: groupId });
export const attend = (apiBase, showtimeId, status) =>
  send(`${apiBase}/api/attendance`, "POST", { showtime_id: showtimeId, status });
export const toggleWatch = (apiBase, movieId) => send(`${apiBase}/api/watchlist`, "POST", { movie_id: movieId });
export const hideFilm = (apiBase, movieId) =>                       // "Not for me" (R13): out of For you
  send(`${apiBase}/api/me/taste/items`, "POST", { kind: "hide", movie_id: movieId });

import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

// Where you land (7f): a single-page app, so the browser never moves the
// page for us on navigation. A new page starts at the top; Back (and Forward) returns
// to where you were; and a link to a specific thing (#id) brings it into
// view and lights it gold for GLOW_MS — on every page (Help's links, tours,
// the bell, the bot's links). It waits for slow pages to draw the thing (up
// to WAIT_MS), keeps it in place while the page finishes loading above it
// (SETTLE_MS, until you scroll yourself), opens a closed <details> it's in,
// and never blocks the page: the glow is a class that removes itself.
export const GLOW_MS = 2500;
const WAIT_MS = 6000;
const SETTLE_MS = 1500;
const GAP = 12;                                           // room above a target at the top

const scroller = () => document.scrollingElement || document.documentElement;

// The top of what you can see in `box`: for the page, just below the pinned top bar.
function viewTop(box) {
  if (box === scroller()) return Math.max(document.querySelector(".topbar")?.getBoundingClientRect().bottom || 0, 0);
  return Math.max(box.getBoundingClientRect().top, 0);
}

// What scrolls `el`: a sheet it's in, or the page.
function scrollerOf(el) {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if ((y === "auto" || y === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return scroller();
}

// Bring `el` into view inside what scrolls it: the top of a tall thing (or,
// `atTop`, of anything — a section menu's jump), the middle of anything else.
export function bringIntoView(el, atTop = false) {
  const box = scrollerOf(el);
  const top = viewTop(box);
  const r = el.getBoundingClientRect();
  const height = box === scroller() ? window.innerHeight - top
    : Math.min(box.getBoundingClientRect().height, window.innerHeight - top);
  const offset = atTop || r.height > height * 0.6 ? GAP : (height - r.height) / 2;
  box.scrollTop += r.top - top - offset;
}

// `quiet`: just bring it to the top (a section menu's jump), no glow.
export function glow(el, quiet = false) {
  for (let d = el.closest("details"); d; d = d.parentElement?.closest("details")) d.open = true;
  bringIntoView(el, quiet);
  if (quiet) return;
  // The glow follows the thing's own corners — or the site's, if it has none.
  el.classList.toggle("arrive-round", !(parseFloat(getComputedStyle(el).borderTopLeftRadius) > 0));
  el.classList.remove("arrive-glow");
  void el.offsetWidth;                                   // restart the animation if it's already glowing
  el.classList.add("arrive-glow");
  clearTimeout(el._arriveTimer);
  el._arriveTimer = setTimeout(() => el.classList.remove("arrive-glow", "arrive-round"), GLOW_MS);
}

// Stop adjusting the moment the reader scrolls on their own.
function onUserScroll(stop) {
  const events = ["wheel", "touchstart", "keydown", "mousedown"];
  events.forEach(e => window.addEventListener(e, stop, { passive: true, once: true }));
  return () => events.forEach(e => window.removeEventListener(e, stop));
}

// In the app shell, on every navigation.
export default function useArrival() {
  const { pathname, hash, key, state } = useLocation();
  const quiet = state?.arrive === "quiet";
  const action = useNavigationType();
  const positions = useRef({});                          // location key -> where you'd scrolled
  const last = useRef({ pathname, key });

  useEffect(() => {                                      // remember where you are on each page
    const save = () => { positions.current[last.current.key] = scroller().scrollTop; };
    window.addEventListener("scroll", save, { passive: true });   // the page's scroll is the window's
    return () => window.removeEventListener("scroll", save);
  }, []);

  useLayoutEffect(() => {
    const before = last.current;
    last.current = { pathname, key };
    if (hash.length > 1 || key === before.key) return undefined;
    const box = scroller();
    if (action === "POP") {                              // Back / Forward: where you were, once there's room
      const to = positions.current[key] || 0;
      let stopped = false;
      const off = onUserScroll(() => { stopped = true; });
      const until = Date.now() + 2000;
      let timer;
      const restore = () => {
        if (stopped) return;
        box.scrollTop = to;
        if (Math.abs(box.scrollTop - to) > 2 && Date.now() < until) timer = setTimeout(restore, 100);
      };
      restore();
      return () => { clearTimeout(timer); off(); };
    }
    if (pathname !== before.pathname) box.scrollTop = 0;   // a new page starts at the top (not a filter or tab)
    return undefined;
  }, [pathname, hash, key, action]);

  useEffect(() => {
    if (hash.length < 2) return undefined;
    const id = decodeURIComponent(hash.slice(1));
    const found = Date.now() + WAIT_MS;
    let timer, settleUntil, el, stopped = false;
    const off = onUserScroll(() => { stopped = true; });
    const settle = () => {                               // content loading above it pushes it down: put it back
      if (stopped || Date.now() > settleUntil || !el.isConnected) return;
      const want = el._arriveTop;
      const now = el.getBoundingClientRect().top - viewTop(scrollerOf(el));
      if (Math.abs(now - want) > 8) bringIntoView(el, quiet);
      timer = setTimeout(settle, 150);
    };
    const look = () => {
      el = document.getElementById(id);
      if (el) {
        glow(el, quiet);
        el._arriveTop = el.getBoundingClientRect().top - viewTop(scrollerOf(el));
        settleUntil = Date.now() + SETTLE_MS;
        timer = setTimeout(settle, 150);
        return;
      }
      if (Date.now() < found) timer = setTimeout(look, 100);
    };
    timer = setTimeout(look, 60);
    return () => { clearTimeout(timer); off(); };
  }, [hash, key, quiet]);
}

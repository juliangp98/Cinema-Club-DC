import { useEffect, useLayoutEffect, useRef } from "react";
import { useLocation, useNavigationType } from "react-router-dom";

// Where you land (7f): pages scroll inside .shell-main, so the browser never
// moves it for us. A new page starts at the top; Back (and Forward) returns
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

const scroller = () => document.querySelector(".shell-main") || document.scrollingElement || document.documentElement;

// What scrolls `el`: a sheet it's in (Edit profile), or the page.
function scrollerOf(el) {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const y = getComputedStyle(p).overflowY;
    if ((y === "auto" || y === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return scroller();
}

// Bring `el` into view inside what scrolls it: the top of a tall thing, the
// middle of anything else.
export function bringIntoView(el) {
  const box = scrollerOf(el);
  const view = box.getBoundingClientRect?.() || { top: 0, height: window.innerHeight };
  const r = el.getBoundingClientRect();
  const height = Math.min(view.height, window.innerHeight - Math.max(view.top, 0));
  const offset = r.height > height * 0.6 ? GAP : (height - r.height) / 2;
  box.scrollTop += r.top - Math.max(view.top, 0) - offset;
}

export function glow(el) {
  for (let d = el.closest("details"); d; d = d.parentElement?.closest("details")) d.open = true;
  bringIntoView(el);
  el.classList.remove("arrive-glow");
  void el.offsetWidth;                                   // restart the animation if it's already glowing
  el.classList.add("arrive-glow");
  clearTimeout(el._arriveTimer);
  el._arriveTimer = setTimeout(() => el.classList.remove("arrive-glow"), GLOW_MS);
}

// Stop adjusting the moment the reader scrolls on their own.
function onUserScroll(stop) {
  const events = ["wheel", "touchstart", "keydown", "mousedown"];
  events.forEach(e => window.addEventListener(e, stop, { passive: true, once: true }));
  return () => events.forEach(e => window.removeEventListener(e, stop));
}

// In the app shell, on every navigation.
export default function useArrival() {
  const { pathname, hash, key } = useLocation();
  const action = useNavigationType();
  const positions = useRef({});                          // location key -> where you'd scrolled
  const last = useRef({ pathname, key });

  useEffect(() => {                                      // remember where you are on each page
    const box = scroller();
    const save = () => { positions.current[last.current.key] = box.scrollTop; };
    box.addEventListener("scroll", save, { passive: true });
    return () => box.removeEventListener("scroll", save);
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
      const view = scrollerOf(el).getBoundingClientRect?.() || { top: 0 };
      const want = el._arriveTop;
      const now = el.getBoundingClientRect().top - Math.max(view.top, 0);
      if (Math.abs(now - want) > 8) bringIntoView(el);
      timer = setTimeout(settle, 150);
    };
    const look = () => {
      el = document.getElementById(id);
      if (el) {
        glow(el);
        const view = scrollerOf(el).getBoundingClientRect?.() || { top: 0 };
        el._arriveTop = el.getBoundingClientRect().top - Math.max(view.top, 0);
        settleUntil = Date.now() + SETTLE_MS;
        timer = setTimeout(settle, 150);
        return;
      }
      if (Date.now() < found) timer = setTimeout(look, 100);
    };
    timer = setTimeout(look, 60);
    return () => { clearTimeout(timer); off(); };
  }, [hash, key]);
}

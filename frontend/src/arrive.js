import { useEffect } from "react";
import { useLocation } from "react-router-dom";

// The arrival glow (7f): any link to a specific thing — #id in the address —
// brings it into view and lights it with a gold glow for GLOW_MS, on every
// page (Help's links, tours, the bell, the bot's links). It waits for slow
// pages to draw the thing (up to WAIT_MS), opens a closed <details> it's in,
// and never blocks the page: the glow is a class that removes itself.
export const GLOW_MS = 2500;
const WAIT_MS = 6000;

const reduced = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

export function glow(el) {
  for (let d = el.closest("details"); d; d = d.parentElement?.closest("details")) d.open = true;
  const tall = el.getBoundingClientRect().height > window.innerHeight * 0.6;
  el.scrollIntoView?.({ block: tall ? "start" : "center", behavior: reduced() ? "auto" : "smooth" });
  el.classList.remove("arrive-glow");
  void el.offsetWidth;                                   // restart the animation if it's already glowing
  el.classList.add("arrive-glow");
  clearTimeout(el._arriveTimer);
  el._arriveTimer = setTimeout(() => el.classList.remove("arrive-glow"), GLOW_MS);
}

// In the app shell: glow the #target of every navigation (a new location
// key, so the same link twice glows twice).
export default function useArrival() {
  const { hash, key } = useLocation();
  useEffect(() => {
    if (!hash || hash.length < 2) return undefined;
    const id = decodeURIComponent(hash.slice(1));
    const until = Date.now() + WAIT_MS;
    let timer;
    const look = () => {
      const el = document.getElementById(id);
      if (el) { glow(el); return; }
      if (Date.now() < until) timer = setTimeout(look, 100);
    };
    timer = setTimeout(look, 60);
    return () => clearTimeout(timer);
  }, [hash, key]);
}

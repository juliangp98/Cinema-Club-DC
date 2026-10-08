import { useState, useEffect } from "react";

// "Add to Home Screen" (R7a). After a visit on a second day, a small card
// offers to install the site as an app: one tap where the browser supports it
// (Android, desktop Chrome/Edge), short steps on iPhone/iPad. "Not now" hides
// it for two months; it never shows once installed.

const KEY = "cinemaclub_install";
const SNOOZE_DAYS = 60;

let deferred = null;                       // the browser's install prompt, kept for our button
const listeners = new Set();
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", e => {
    e.preventDefault();
    deferred = e;
    listeners.forEach(fn => fn());
  });
  window.addEventListener("appinstalled", () => { deferred = null; listeners.forEach(fn => fn()); });
}

function read() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch { return {}; }
}
function write(state) {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch { /* private mode */ }
}
const installed = () => window.matchMedia?.("(display-mode: standalone)").matches || window.navigator.standalone === true;
const isIos = () => /iphone|ipad|ipod/i.test(navigator.userAgent)
  || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);      // iPadOS reports as a Mac

export default function InstallPrompt() {
  const [, rerender] = useState(0);
  const [eligible, setEligible] = useState(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const fn = () => rerender(n => n + 1);
    listeners.add(fn);
    const state = read();
    const today = new Date().toISOString().slice(0, 10);
    const days = [...new Set([...(state.days || []), today])].slice(-10);
    write({ ...state, days });
    const snoozed = state.snoozed && Date.now() - state.snoozed < SNOOZE_DAYS * 864e5;
    setEligible(days.length >= 2 && !snoozed && !installed());
    return () => listeners.delete(fn);
  }, []);

  const ios = isIos();
  if (!eligible || hidden || (!deferred && !ios)) return null;

  const snooze = () => { write({ ...read(), snoozed: Date.now() }); setHidden(true); };
  async function install() {
    const e = deferred;
    if (!e) return;
    e.prompt();
    const choice = await e.userChoice.catch(() => null);
    deferred = null;
    if (choice?.outcome !== "accepted") snooze(); else setHidden(true);
  }

  return (
    <aside className="install-card" role="dialog" aria-label="Add Cinema Club to your home screen">
      <img src="/pwa-192.png" alt="" className="install-icon" />
      <div className="install-text">
        <strong>Add Cinema Club to your home screen</strong>
        {deferred
          ? <span>It opens like an app, full screen — one tap away.</span>
          : <span>Tap <span className="install-share" aria-label="the Share button">Share <ShareGlyph /></span>, then <b>Add to Home Screen</b>.</span>}
      </div>
      <div className="install-actions">
        {deferred && <button type="button" className="btn btn-sm btn-primary" onClick={install}>Install</button>}
        <button type="button" className="btn btn-sm btn-ghost" onClick={snooze}>{deferred ? "Not now" : "Got it"}</button>
      </div>
    </aside>
  );
}

function ShareGlyph() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M12 3v12M8 7l4-4 4 4M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7" />
    </svg>
  );
}

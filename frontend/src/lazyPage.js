import { lazy } from "react";
import { cleanReload } from "./ui/ErrorBoundary";

// Pages load when first visited (R9e), so the first visit downloads only
// what it shows. A tab left open across a deploy may ask for a page file the
// new version no longer has: reload once (cleanly) to pick up the new one.
const RETRIED = "cinemaclub_page_reload";

export default function lazyPage(load, name = "default") {
  return lazy(() => load()
    .then(m => {
      try { sessionStorage.removeItem(RETRIED); } catch { /* private mode */ }
      return { default: m[name] };
    })
    .catch(err => {
      let retried = false;
      try { retried = !!sessionStorage.getItem(RETRIED); sessionStorage.setItem(RETRIED, "1"); } catch { /* private mode */ }
      if (retried) throw err;                 // still failing: the error screen offers Reload
      cleanReload();
      return new Promise(() => {});           // the page is reloading
    }));
}

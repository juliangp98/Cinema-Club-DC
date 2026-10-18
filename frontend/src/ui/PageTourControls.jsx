import { useShell } from "../shell/AppShell";
import { PAGE_TOURS } from "../shell/pageTours";
import Prompt from "./Prompt";

// A page's tour controls (7f): the ? button that (re)plays it, and — the
// first time you open the page — a small card offering it. Nothing pops up
// over the page; "No thanks" (or taking it) means it's not offered again.
export function TourButton({ page }) {
  const shell = useShell() || {};
  if (!PAGE_TOURS[page] || !shell.startPageTour) return null;
  return (
    <button type="button" className="btn btn-sm btn-ghost tour-q" aria-label={`Tour of ${PAGE_TOURS[page].title}`}
            title={`A quick tour of ${PAGE_TOURS[page].title}`} onClick={() => shell.startPageTour(page)}>?</button>
  );
}

export function TourOffer({ page }) {
  const shell = useShell() || {};
  if (!shell.offerPageTour?.(page)) return null;
  return (
    <Prompt className="tour-offer" question={`New here? A 30-second tour of ${PAGE_TOURS[page].title}.`}
            label="Page tour" hint="Or tap ? any time."
            actions={<>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => shell.startPageTour(page)}>Show me</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => shell.markPageTour(page)}>No thanks</button>
            </>} />
  );
}

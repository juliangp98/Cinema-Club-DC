import { useLocation } from "react-router-dom";
import { useShell } from "../shell/AppShell";
import { PAGE_TOURS, tourFor } from "../shell/pageTours";
import { HelpIcon } from "./icons";
import Prompt from "./Prompt";

// A page's tour controls (7f): the ? in the top bar, beside the bell, on
// pages that have a tour — and, the first time you open one, a small card
// under its header offering it. Nothing pops up over the page; "No thanks"
// (or taking it) means it's not offered again.
export function TopbarTour() {
  const shell = useShell() || {};
  const page = tourFor(useLocation().pathname);
  if (!page || !shell.startPageTour) return null;
  return (
    <button type="button" className="topbar-icon topbar-tour" aria-label={`Tour of ${PAGE_TOURS[page].title}`}
            title={`A quick tour of ${PAGE_TOURS[page].title}`} onClick={() => shell.startPageTour(page)}>
      <HelpIcon />
    </button>
  );
}

export function TourOffer({ page }) {
  const shell = useShell() || {};
  if (!shell.offerPageTour?.(page)) return null;
  return (
    <Prompt className="tour-offer" question={`New here? A 30-second tour of ${PAGE_TOURS[page].title}.`}
            label="Page tour" hint="Or tap ? at the top any time."
            actions={<>
              <button type="button" className="btn btn-sm btn-primary" onClick={() => shell.startPageTour(page)}>Show me</button>
              <button type="button" className="btn btn-sm btn-ghost" onClick={() => shell.markPageTour(page)}>No thanks</button>
            </>} />
  );
}

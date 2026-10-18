import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link, useNavigate } from "react-router-dom";

// The welcome tour (R11, short since 7f): a few slides with the essentials,
// one spotlight on the menu, then Your taste. Each page has its own tour
// (PageTour, pageTours.js) — offered the first time you open it, replayable
// from its ? button. New accounts see the welcome tour on their own; anyone
// can replay it from the account menu, the Me page or Help. Steps for things
// that aren't on screen (no club, phones) are skipped.

const SLIDES = [
  { emoji: "🎬", title: "Welcome to Cinema Club DC",
    body: "Everything playing at the DC area's independent and repertory theatres — film prints, Q&As, one-night-only screenings — in one place, and a club to see them with." },
  { emoji: "🎟️", title: "Make plans together",
    body: "Tap any screening to say you're Going or Maybe. Your club sees who's going and can talk about it; afterwards, check in to say you went." },
  { emoji: "🍿", title: "Your club", club: true,
    body: "The feed shows what your club is up to, and the Club page who's in it and how the month's going. Earn kernels by going out, in polls and in games — and give a few to each other." },
  { emoji: "🔕", title: "Nothing sent without a yes",
    body: "No emails, Discord DMs or push notifications unless you turn them on — and nothing posts to Discord unless you choose to. It's all in your profile." },
];

// Last of all (R13): an invitation to set up Your taste, or leave it for later.
const TASTE = { emoji: "✨", title: "Make it yours",
  body: "Tell us the genres, films, people and theatres you love — and what you're not into — and Discover and each theatre's page lead with films for you. Change it any time in Edit profile." };

const STEPS = [
  { target: "menu", title: "Find your way around",
    body: "Discover, the Calendar, your club's feed, Play and Theatres. Each page has its own short tour — tap ? next to its title any time — and Help has the rest." },
];

const visible = el => el && el.offsetParent !== null && el.getBoundingClientRect().width > 0;

function findTarget(target) {
  if (target === "menu") return [document.querySelector(".topbar-nav"), document.querySelector(".tabbar")].find(visible) || null;
  if (target.startsWith("nav:")) {
    const href = target.slice(4);
    return [...document.querySelectorAll(`.topbar-nav a[href="${href}"], .tabbar a[href="${href}"]`)].find(visible) || null;
  }
  if (target === "account") {
    return [document.querySelector(".topbar-avatar"), document.querySelector('.tabbar a[href="/me"]')].find(visible) || null;
  }
  return [...document.querySelectorAll(target)].find(visible) || null;
}

const PAD = 6;     // room around the target…
const EDGE = 6;    // …but the gold outline (2px, 2px out) always stays on screen

// The hole around a target: PAD each side where there's room, less near the
// screen's edges, so the outline is never cut off. Targets in a bar (the top
// bar, the phone tab bar) all get that bar's height — menu links, the club
// switcher, the bell and the avatar look alike.
export function holeFor(rect, vw, vh, bar = null) {
  const clamp = (lo, hi, min, max) => [Math.max(lo, min), Math.min(hi, max)];
  const [left, right] = clamp(rect.left - PAD, rect.right + PAD, EDGE, vw - EDGE);
  const [top, bottom] = bar ? [Math.max(bar.top, 0) + EDGE, Math.min(bar.bottom, vh) - EDGE]   // the outline stays in the bar
    : clamp(rect.top - PAD, rect.bottom + PAD, EDGE, vh - EDGE);
  return { top, left, width: right - left, height: bottom - top };
}

function Spotlight({ step, index, count, onNext, onBack, onSkip }) {
  const [rect, setRect] = useState(null);
  const [bar, setBar] = useState(null);
  const nextRef = useRef(null);
  const measure = useCallback(() => {
    const el = findTarget(step.target);
    setRect(el ? el.getBoundingClientRect() : null);
    setBar(el?.closest(".topbar, .tabbar")?.getBoundingClientRect() || null);
  }, [step]);
  useLayoutEffect(() => {
    const el = findTarget(step.target);                 // a page's widget may be below the fold
    if (el && !el.closest(".topbar, .tabbar")) {
      const r = el.getBoundingClientRect();
      if (r.top < 70 || r.bottom > window.innerHeight - 200) el.scrollIntoView?.({ block: r.height > window.innerHeight * 0.5 ? "start" : "center" });
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [measure]);
  useEffect(() => { nextRef.current?.focus(); }, [index]);
  if (!rect) return null;

  const vw = window.innerWidth, vh = window.innerHeight;
  const hole = holeFor(rect, vw, vh, bar);
  const width = Math.min(340, vw - 32);
  const below = rect.bottom + 12 + 190 < vh;
  const left = Math.min(Math.max(16, rect.left + rect.width / 2 - width / 2), vw - width - 16);
  const card = below ? { top: hole.top + hole.height + 10, left, width } : { bottom: vh - hole.top + 10, left, width };
  return (
    <>
      <div className="tour-hole" aria-hidden="true" style={hole} />
      <div className="tour-card" style={card} role="dialog" aria-modal="true" aria-labelledby="tour-step-title">
        <div className="tour-count">{index + 1} of {count}</div>
        <h2 id="tour-step-title" className="tour-title">{step.title}</h2>
        <p className="tour-body">{step.body}</p>
        <div className="tour-actions">
          <button type="button" className="linkish" onClick={onSkip}>Skip tour</button>
          <span className="tour-spacer" />
          {index > 0 && <button type="button" className="btn btn-sm" onClick={onBack}>Back</button>}
          <button type="button" ref={nextRef} className="btn btn-sm btn-primary" onClick={onNext}>
            {index === count - 1 ? "Done" : "Next"}
          </button>
        </div>
      </div>
    </>
  );
}

function Slides({ slides, index, onNext, onBack, onSkip, final, skipLabel = "Skip", help = true }) {
  const s = slides[index];
  const last = index === slides.length - 1;
  const nextRef = useRef(null);
  useEffect(() => { nextRef.current?.focus(); }, [index]);
  return (
    <div className="tour-slide-wrap">
      <div className="tour-card tour-slide" role="dialog" aria-modal="true" aria-labelledby="tour-slide-title">
        <div className="tour-slide-emoji" aria-hidden="true">{s.emoji}</div>
        <h2 id="tour-slide-title" className="tour-title">{s.title}</h2>
        <p className="tour-body">{s.body}</p>
        <div className="tour-dots" aria-hidden="true">
          {slides.map((x, i) => <span key={x.title} className={i === index ? "on" : ""} />)}
        </div>
        <div className="tour-actions">
          <button type="button" className="linkish" onClick={onSkip}>{skipLabel}</button>
          <span className="tour-spacer" />
          {index > 0 && <button type="button" className="btn btn-sm" onClick={onBack}>Back</button>}
          {last
            ? <button type="button" ref={nextRef} className="btn btn-sm btn-primary" onClick={final.onClick}>{final.label}</button>
            : <button type="button" ref={nextRef} className="btn btn-sm btn-primary" onClick={onNext}>Next</button>}
        </div>
        {last && help && <p className="tour-help">Or browse the <Link to="/help" onClick={onSkip}>Help guide</Link>.</p>}
      </div>
    </div>
  );
}

export default function Tour({ inClub, onFinish, onTaste }) {
  const slides = SLIDES.filter(s => !s.club || inClub);
  const [phase, setPhase] = useState("slides");
  const [i, setI] = useState(0);
  const [steps, setSteps] = useState([]);

  const toTaste = () => (onTaste ? setPhase("taste") : onFinish());       // the last card, if there's a sheet to open
  const startSpotlight = () => {
    const on = STEPS.filter(s => (!s.club || inClub) && findTarget(s.target));
    if (!on.length) { toTaste(); return; }
    setSteps(on);
    setI(0);
    setPhase("spotlight");
  };
  useEffect(() => {
    const onKey = e => {
      if (e.key === "Escape") { e.preventDefault(); onFinish(); }
    };
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = prev; };
  }, [onFinish]);

  return createPortal(
    <div className={`tour-layer tour-${phase}`}>
      {phase === "slides" ? (
        <Slides slides={slides} index={i} onNext={() => setI(i + 1)} onBack={() => setI(i - 1)}
                onSkip={onFinish} final={{ label: "Show me around", onClick: startSpotlight }} />
      ) : phase === "taste" ? (
        <Slides slides={[TASTE]} index={0} onSkip={onFinish} skipLabel="Later" help={false}
                final={{ label: "Pick what you like", onClick: () => { onFinish(); onTaste(); } }} />
      ) : (
        <Spotlight step={steps[i]} index={i} count={steps.length} onSkip={onFinish} onBack={() => setI(i - 1)}
                   onNext={() => (i === steps.length - 1 ? toTaste() : setI(i + 1))} />
      )}
    </div>,
    document.body,
  );
}


// A page's tour (7f): its steps (pageTours.js) on the page as it is, then a
// card to its part of Help.
export function PageTour({ tour, onFinish }) {
  const navigate = useNavigate();
  const [steps] = useState(() => tour.steps.filter(st => findTarget(st.target)));
  const [i, setI] = useState(0);
  useEffect(() => {
    const onKey = e => { if (e.key === "Escape") { e.preventDefault(); onFinish(); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onFinish]);
  const toHelp = () => { onFinish(); navigate(`/help#${tour.help}`); };
  const card = { emoji: "📖", title: "There's more in Help",
                 body: `Everything about ${tour.title} — with links straight to each thing — is in Help.` };
  return createPortal(
    <div className={`tour-layer tour-${i < steps.length ? "spotlight" : "slides"}`}>
      {i < steps.length ? (
        <Spotlight step={steps[i]} index={i} count={steps.length + 1} onSkip={onFinish} onBack={() => setI(i - 1)}
                   onNext={() => setI(i + 1)} />
      ) : (
        <Slides slides={[card]} index={0} onSkip={onFinish} skipLabel="Done" help={false}
                final={{ label: "Open Help", onClick: toHelp }} />
      )}
    </div>,
    document.body,
  );
}

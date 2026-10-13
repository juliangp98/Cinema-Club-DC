import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";

// The welcome tour (R11): a few slides with the essentials, then a spotlight
// on the real navigation for the rest. New accounts (and everyone once, the
// first time it shipped) see it on their own; anyone can replay it from the
// account menu, the Me page or Help. Steps for things you can't use yet (no
// club) or that aren't on screen (phones show fewer tabs) are skipped.

const SLIDES = [
  { emoji: "🎬", title: "Welcome to Cinema Club DC",
    body: "Everything playing at the DC area's independent and repertory theatres — film prints, Q&As, one-night-only screenings — in one place, and a club to see them with." },
  { emoji: "🎟️", title: "Make plans together",
    body: "Tap any screening to say you're Going or Maybe. Your club sees who's going and can talk about it; afterwards, check in to say you went." },
  { emoji: "🍿", title: "Your club", club: true,
    body: "The feed shows what your club is up to. Earn kernels by going out, in polls and in games — and give a few to each other." },
  { emoji: "🔕", title: "Nothing sent without a yes",
    body: "No emails, Discord DMs or push notifications unless you turn them on — and nothing posts to Discord unless you choose to. It's all in your profile." },
];

const STEPS = [
  { target: "nav:/", title: "Discover",
    body: "What's worth seeing: rare screenings, film prints, spotlights and double features. Search, or describe what you're in the mood for and tap ✨." },
  { target: "nav:/calendar", title: "Calendar",
    body: "Every showtime at your club's theatres. Filter by theatre, format or time; tap one to RSVP, see who's going, or add it to your own calendar." },
  { target: "nav:/feed", title: "Feed", club: true,
    body: "What the club's up to — plans, check-ins, comments and Monday recaps. Tap 🍿 Kernels on a screening to give (or take) a few." },
  { target: "nav:/play", title: "Play", club: true,
    body: "Polls, plus trivia and bingo when your club turns them on — with your kernels and the leaderboard." },
  { target: "nav:/theatres", title: "Theatres",
    body: "Each theatre's page: what's on, how to get there, and what members say about the screenings there." },
  { target: ".topbar-groupmenu", title: "Your clubs", club: true,
    body: "In more than one club? Switch here — the calendar, feed and games follow." },
  { target: ".topbar-bell", title: "The bell",
    body: "Club activity and your alerts. Alerts are opt-in: watchlist a film, or tap 🔔 Alert me on a Browse search, to hear when a theatre books it." },
  { target: "account", title: "You",
    body: "Your profile and lists: link Discord, connect Letterboxd, choose your notifications. Replay this tour, or find Help, here any time." },
];

const visible = el => el && el.offsetParent !== null && el.getBoundingClientRect().width > 0;

function findTarget(target) {
  if (target.startsWith("nav:")) {
    const href = target.slice(4);
    return [...document.querySelectorAll(`.topbar-nav a[href="${href}"], .tabbar a[href="${href}"]`)].find(visible) || null;
  }
  if (target === "account") {
    return [document.querySelector(".topbar-avatar"), document.querySelector('.tabbar a[href="/me"]')].find(visible) || null;
  }
  const el = document.querySelector(target);
  return visible(el) ? el : null;
}

const PAD = 6;

function Spotlight({ step, index, count, onNext, onBack, onSkip }) {
  const [rect, setRect] = useState(null);
  const nextRef = useRef(null);
  const measure = useCallback(() => {
    const el = findTarget(step.target);
    setRect(el ? el.getBoundingClientRect() : null);
  }, [step]);
  useLayoutEffect(() => {
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => { window.removeEventListener("resize", measure); window.removeEventListener("scroll", measure, true); };
  }, [measure]);
  useEffect(() => { nextRef.current?.focus(); }, [index]);
  if (!rect) return null;

  const vw = window.innerWidth, vh = window.innerHeight;
  const width = Math.min(340, vw - 32);
  const below = rect.bottom + 12 + 190 < vh;
  const left = Math.min(Math.max(16, rect.left + rect.width / 2 - width / 2), vw - width - 16);
  const card = below ? { top: rect.bottom + PAD + 10, left, width } : { bottom: vh - rect.top + PAD + 10, left, width };
  return (
    <>
      <div className="tour-hole" aria-hidden="true"
           style={{ top: rect.top - PAD, left: rect.left - PAD, width: rect.width + PAD * 2, height: rect.height + PAD * 2 }} />
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

function Slides({ slides, index, onNext, onBack, onSkip, onTour }) {
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
          <button type="button" className="linkish" onClick={onSkip}>Skip</button>
          <span className="tour-spacer" />
          {index > 0 && <button type="button" className="btn btn-sm" onClick={onBack}>Back</button>}
          {last
            ? <button type="button" ref={nextRef} className="btn btn-sm btn-primary" onClick={onTour}>Show me around</button>
            : <button type="button" ref={nextRef} className="btn btn-sm btn-primary" onClick={onNext}>Next</button>}
        </div>
        {last && <p className="tour-help">Or browse the <Link to="/help" onClick={onSkip}>Help guide</Link>.</p>}
      </div>
    </div>
  );
}

export default function Tour({ inClub, onFinish }) {
  const slides = SLIDES.filter(s => !s.club || inClub);
  const [phase, setPhase] = useState("slides");
  const [i, setI] = useState(0);
  const [steps, setSteps] = useState([]);

  const startSpotlight = () => {
    const on = STEPS.filter(s => (!s.club || inClub) && findTarget(s.target));
    if (!on.length) { onFinish(); return; }
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
                onSkip={onFinish} onTour={startSpotlight} />
      ) : (
        <Spotlight step={steps[i]} index={i} count={steps.length} onSkip={onFinish} onBack={() => setI(i - 1)}
                   onNext={() => (i === steps.length - 1 ? onFinish() : setI(i + 1))} />
      )}
    </div>,
    document.body,
  );
}

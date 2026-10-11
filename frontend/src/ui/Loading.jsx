import { useState, useEffect } from "react";

// While films load (R7b): a spinning reel and a movie line that fits where
// you are, changing every few seconds. Still for people who prefer reduced
// motion. LoadError is the matching "that didn't work — try again".

const LINES = {
  discover: [["Round up the usual suspects.", "Casablanca"], ["Show me the movies!", "after Jerry Maguire"],
             ["I'll have what she's having.", "When Harry Met Sally…"],
             ["This is the beginning of a beautiful friendship.", "Casablanca"]],
  calendar: [["Roads? Where we're going, we don't need roads.", "Back to the Future"], ["Tomorrow is another day.", "Gone with the Wind"],
             ["I'll be back.", "The Terminator"], ["Great Scott — checking every date…", "after Back to the Future"]],
  browse: [["Follow the yellow brick road.", "The Wizard of Oz"], ["You're gonna need a bigger list.", "after Jaws"],
           ["Toto, I've a feeling we're not in Kansas anymore.", "The Wizard of Oz"], ["Play it, Sam.", "Casablanca"]],
  film: [["Mr. DeMille, I'm ready for my close-up.", "Sunset Boulevard"], ["Rosebud…", "Citizen Kane"],
         ["Of all the gin joints in all the towns…", "Casablanca"]],
  theatre: [["If you build it, they will come.", "Field of Dreams"], ["There's no place like home.", "The Wizard of Oz"],
            ["Fasten your seatbelts. It's going to be a bumpy night.", "All About Eve"]],
  general: [["The stuff that dreams are made of.", "The Maltese Falcon"], ["Here's looking at you, kid.", "Casablanca"],
            ["Wait a minute, wait a minute, you ain't heard nothin' yet!", "The Jazz Singer"]],
};

function Reel({ size = 44 }) {
  return (
    <svg className="loading-reel-svg" viewBox="0 0 48 48" width={size} height={size} aria-hidden="true">
      <circle cx="24" cy="24" r="21" fill="none" stroke="currentColor" strokeWidth="3" />
      <circle cx="24" cy="24" r="4" fill="currentColor" />
      {[0, 72, 144, 216, 288].map(a => (
        <circle key={a} cx={24 + 12 * Math.cos((a * Math.PI) / 180)} cy={24 + 12 * Math.sin((a * Math.PI) / 180)} r="5"
                fill="none" stroke="currentColor" strokeWidth="2.5" />
      ))}
    </svg>
  );
}

export default function Loading({ context = "general", label = "Loading" }) {
  const lines = LINES[context] || LINES.general;
  const [i, setI] = useState(() => Math.floor(Math.random() * lines.length));
  useEffect(() => {
    const t = setInterval(() => setI(n => (n + 1) % lines.length), 3200);
    return () => clearInterval(t);
  }, [lines]);
  const [line, film] = lines[i % lines.length];
  return (
    <div className="loading-reel" role="status" aria-live="polite">
      <Reel />
      <p className="loading-quote" aria-hidden="true">“{line}” <cite>— {film}</cite></p>
      <span className="sr-only">{label}…</span>
    </div>
  );
}

export function LoadError({ what = "this", onRetry }) {
  return (
    <div className="loading-reel error" role="alert">
      <Reel size={36} />
      <p className="loading-quote">“Houston, we have a problem.” <cite>— Apollo 13</cite></p>
      <p className="loading-error-text">Couldn't load {what}.</p>
      {onRetry && <button type="button" className="btn btn-sm btn-primary" onClick={onRetry}>Try again</button>}
    </div>
  );
}

import { useState, useEffect } from "react";

// Initials for a title, skipping a leading article: "The Thing" → "T",
// "In the Mouth of Madness" → "IM".
const ARTICLES = new Set(["the", "a", "an"]);
export function posterInitials(title) {
  const words = (title || "").replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  const rest = words.length > 1 && ARTICLES.has(words[0].toLowerCase()) ? words.slice(1) : words;
  const minor = new Set(["of", "and", "in", "on", "at", "to", "the", "a", "an", "for"]);
  const picked = [rest[0], ...rest.slice(1).filter(w => !minor.has(w.toLowerCase()))].filter(Boolean).slice(0, 2);
  return picked.map(w => w[0]).join("").toUpperCase() || "🎬";
}

// A film's poster, everywhere on the site. With no poster (or one that fails
// to load) it shows the title centered — or, when the poster is small (under
// ~80px wide, decided by a container query), the title's initials. `className`
// sizes it; `fill` makes it fill a sized parent.
export default function Poster({ movie, className = "", fill = false, loading = "lazy", alt = "" }) {
  const [broken, setBroken] = useState(false);
  const src = movie?.poster_url;
  useEffect(() => setBroken(false), [src]);
  const cls = `${className}${fill ? " poster-fill" : ""}`;
  if (src && !broken) {
    return <img className={`poster-img ${cls}`} src={src} alt={alt} loading={loading} onError={() => setBroken(true)} />;
  }
  return (
    <span className={`poster-ph ${cls}`} role="img" aria-label={movie?.title || "No poster"}>
      <span className="poster-ph-title">{movie?.title}</span>
      <span className="poster-ph-initials" aria-hidden="true">{posterInitials(movie?.title)}</span>
    </span>
  );
}

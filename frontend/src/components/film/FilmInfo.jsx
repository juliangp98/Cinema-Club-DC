// Film details shared by the screening sheet and the film page.

const RATING_LABELS = {
  "Internet Movie Database": "IMDb",
  "Rotten Tomatoes": "RT",
  "Metacritic": "MC",
};

// Initials shown when a poster image is missing or fails to load.
export function posterInitials(title) {
  const words = (title || "").replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length) return "🎬";
  return words.slice(0, 2).map(w => w[0]).join("").toUpperCase();
}

// OMDb only gives a summary string (e.g. "Won 3 Oscars. 44 wins & 27
// nominations total"). Pull out the marquee award + totals for a clean display.
export function parseAwards(str) {
  if (!str || str === "N/A") return null;
  const won = str.match(/Won (\d+) ([A-Za-z][A-Za-z ]*?)(?:\.|,|$)/);
  const nom = str.match(/Nominated for (\d+) ([A-Za-z][A-Za-z ]*?)(?:\.|,|$)/);
  const wins = str.match(/(\d+)\s+wins?/i);
  const noms = str.match(/(\d+)\s+nominations?/i);
  return {
    raw: str,
    headline: won ? `Won ${won[1]} ${won[2].trim()}`
            : nom ? `Nominated for ${nom[1]} ${nom[2].trim()}`
            : null,
    wins: wins ? parseInt(wins[1], 10) : null,
    nominations: noms ? parseInt(noms[1], 10) : null,
  };
}

export function metaLine(movie) {
  return [
    movie.director && `Dir. ${movie.director}`,
    movie.release_year,
    movie.runtime_minutes && `${movie.runtime_minutes} min`,
  ].filter(Boolean).join("  ·  ");
}

export function RatingBadges({ movie }) {
  const ratings = movie.ratings || [];
  return (
    <>
      {movie.vote_average > 0 && (
        <span className="drawer-rating-badge tmdb">TMDB {movie.vote_average.toFixed(1)}</span>
      )}
      {ratings.map((r, i) => (
        <span key={i} className="drawer-rating-badge">{RATING_LABELS[r.source] || r.source} {r.value}</span>
      ))}
    </>
  );
}

export function Awards({ movie }) {
  const awards = parseAwards(movie.awards);
  if (!awards) return null;
  return (
    <>
      <div className="drawer-awards-stats">
        {awards.headline && <span className="drawer-award-stat marquee">🏆 {awards.headline}</span>}
        {awards.wins != null && (
          <span className="drawer-award-stat"><b>{awards.wins}</b> win{awards.wins !== 1 ? "s" : ""}</span>
        )}
        {awards.nominations != null && (
          <span className="drawer-award-stat">
            <b>{awards.nominations}</b> nomination{awards.nominations !== 1 ? "s" : ""}
          </span>
        )}
      </div>
      <p className="drawer-awards-raw">{awards.raw}</p>
    </>
  );
}

export function CastScroll({ cast }) {
  if (!cast?.length) return null;
  return (
    <div className="drawer-cast-scroll">
      {cast.map((c, i) => (
        <div key={i} className="drawer-cast-card">
          {c.profile_path ? (
            <img className="drawer-cast-photo" src={c.profile_path} alt={c.name} loading="lazy" />
          ) : (
            <div className="drawer-cast-photo-placeholder">{c.name.slice(0, 2).toUpperCase()}</div>
          )}
          <div className="drawer-cast-name">{c.name}</div>
          {c.character && <div className="drawer-cast-character">{c.character}</div>}
        </div>
      ))}
    </div>
  );
}

export function Trailer({ movie }) {
  if (movie.trailer_key) {
    return (
      <div className="drawer-trailer-embed">
        <iframe
          src={`https://www.youtube.com/embed/${movie.trailer_key}`}
          title={`${movie.title} trailer`}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
        />
      </div>
    );
  }
  if (movie.trailer_link) {
    return (
      <a href={movie.trailer_link} target="_blank" rel="noopener noreferrer" className="trailer-link">
        &#9654; Watch Trailer
      </a>
    );
  }
  return null;
}

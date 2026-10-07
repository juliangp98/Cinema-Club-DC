import { Link } from "react-router-dom";

const when = iso => {
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-US", { weekday: "short" });
  const t = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" }).replace(":00 ", " ");
  return `${day} ${t}`;
};

// A film as a poster tile: links to its film page. Used by Discover's
// shelves and Browse results (and Home, later).
export default function PosterCard({ card, size = "md" }) {
  const { movie, next, reasons = [], club = {} } = card;
  return (
    <Link to={`/films/${movie.id}`} className={`poster-card ${size}`}>
      <div className="poster-card-img">
        {movie.poster_url ? (
          <img src={movie.poster_url} alt="" loading="lazy" />
        ) : (
          <span className="poster-card-ph">{movie.title}</span>
        )}
        {(club.you_going || club.going > 0 || club.wanted > 0) && (
          <span className="poster-card-badge">
            {club.you_going ? "✓ Going" : club.going > 0 ? `${club.going} going` : `${club.wanted} want`}
          </span>
        )}
      </div>
      <div className="poster-card-title">
        {movie.title}{movie.year ? <span className="poster-card-year"> ({movie.year})</span> : null}
      </div>
      {next && <div className="poster-card-next">{when(next.start_time)} · {next.theatre}</div>}
      {reasons.length > 0 && <div className="poster-card-reasons">{reasons.slice(0, 3).join(" · ")}</div>}
    </Link>
  );
}

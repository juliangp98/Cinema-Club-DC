import { Link } from "react-router-dom";
import CityTag from "./CityTag";

// A theatre, wherever it's named (R7b): a small button in its color that
// opens the theatre's page. `theatre` needs slug and a name (short_name is
// used when `short`). With more than one city, a theatre outside yours
// says which it's in (CityTag).
export default function TheatreLink({ theatre, short = false, onClick, className = "" }) {
  if (!theatre?.slug) return <span>{theatre?.short_name || theatre?.name || ""}</span>;
  const name = short ? theatre.short_name || theatre.name : theatre.name || theatre.short_name;
  return (
    <Link to={`/theatres/${theatre.slug}`} className={`theatre-link ${className}`} style={{ "--tcolor": theatre.color }}
          onClick={e => { e.stopPropagation(); onClick?.(e); }} title={`About ${theatre.name || name}`}>
      <span className="theatre-link-dot" aria-hidden="true" />{name}<CityTag city={theatre.city} />
    </Link>
  );
}

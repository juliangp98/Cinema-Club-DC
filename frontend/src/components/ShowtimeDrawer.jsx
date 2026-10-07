import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import Sheet from "../ui/Sheet";
import TicketRow from "../ui/TicketRow";
import Avatar from "../ui/Avatar";
import ReactionBar from "./ReactionBar";
import ChatSection from "./ChatSection";
import { useShell } from "../shell/AppShell";
import { posterInitials, metaLine, RatingBadges, Awards, CastScroll, Trailer, parseAwards } from "./film/FilmInfo";

// Collapsible accordion section used for the sheet's informational blocks.
function Collapsible({ title, count, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="drawer-section">
      <button type="button" className="drawer-section-toggle" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        <span>
          {title}
          {count != null && <span className="drawer-section-count"> ({count})</span>}
        </span>
        <span className="drawer-section-caret">{open ? "▴" : "▾"}</span>
      </button>
      {open && <div className="drawer-section-body">{children}</div>}
    </div>
  );
}

function dedupeUsers(showtimes, field) {
  const seen = new Map();
  for (const s of showtimes) for (const a of (s[field] || [])) seen.set(a.id, a);
  return [...seen.values()];
}

// One screening (or a day's screenings of a film at one theatre): the
// tickets to RSVP to, who's going, the discussion, and the film's details —
// with a link to the film page for every other showing. In public mode (no
// club, R5a) there's no discussion or who's going, just anonymous counts; your
// RSVP, watchlist and reactions are personal (a visitor's first one makes a
// private guest profile, R5b).
export default function ShowtimeDrawer({ showtimes, user, groupId, apiBase, onClose, onRsvp, onAttendance, onViewProfile }) {
  const primary = showtimes[0];
  const { movie, theatre } = primary;
  const [reactions, setReactions] = useState(primary.reactions || {});
  const shell = useShell();
  const [watching, setWatching] = useState(user ? null : false); // null until your watchlist loads
  const [posterOk, setPosterOk] = useState(true);
  const [heroOk, setHeroOk] = useState(true);

  useEffect(() => {
    if (!user) return;                    // visitors: nothing on it yet
    fetch(`${apiBase}/api/watchlist`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(items => setWatching(items.some(i => i.movie && i.movie.id === movie.id)))
      .catch(() => setWatching(false));
  }, [apiBase, movie.id, user]);

  useEffect(() => {
    setReactions(primary.reactions || {});
    setPosterOk(true);
    setHeroOk(true);
  }, [primary]);

  async function toggleWatch() {
    if (!user && !(await shell.ensureProfile())) return;
    const next = !watching;
    setWatching(next);
    try {
      const r = await fetch(`${apiBase}/api/watchlist`, {
        method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
        body: JSON.stringify({ movie_id: movie.id }),
      });
      if (r.ok) setWatching((await r.json()).watching);
      else setWatching(!next);
    } catch {
      setWatching(!next);
    }
  }

  const club = !!groupId;
  const interest = primary.interest || {};
  // Outside a club, your RSVP is private (a guest's lives in this browser until they keep it).
  const here = encodeURIComponent(window.location.pathname + window.location.search);
  const readOnly = club && shell && !shell.canParticipate;          // read-only in this club (R5c)
  const rsvpNote = readOnly ? { text: "You're read-only in this club." } : club ? null : user?.is_guest
    ? { text: "Only you see your plans — saved in this browser.", to: `/signin?next=${here}`, label: "Keep your profile" }
    : { text: "Only you see your plans." };
  const personal = fn => async (...args) => {
    if (!club && !(await shell.ensureProfile())) return undefined;
    return fn?.(...args);
  };
  const going = dedupeUsers(showtimes, "attendees");
  const maybes = dedupeUsers(showtimes, "maybes");
  const heroImage = movie.backdrop_url || movie.poster_url || "";
  const meta = metaLine(movie);
  const hasTrailer = !!(movie.trailer_key || movie.trailer_link);

  return (
    <Sheet onClose={onClose} label={movie.title} className="drawer">
      {/* Hero banner: backdrop, or the poster blurred as a fallback; a plain
          banner if the image is missing or fails to load. */}
      {heroImage && heroOk ? (
        <div className={`drawer-hero${!movie.backdrop_url ? " poster-fallback" : ""}`}>
          <img className="drawer-backdrop" src={heroImage} alt="" onError={() => setHeroOk(false)} />
          <div className="drawer-backdrop-fade" />
        </div>
      ) : (
        <div className="drawer-hero drawer-hero-blank"><div className="drawer-backdrop-fade" /></div>
      )}

      <div className="drawer-content">
        <div className="drawer-header">
          {movie.poster_url && posterOk ? (
            <img className="drawer-poster-thumb" src={movie.poster_url} alt={movie.title} onError={() => setPosterOk(false)} />
          ) : (
            <div className="drawer-poster-thumb drawer-poster-thumb-ph">{posterInitials(movie.title)}</div>
          )}
          <div className="drawer-header-text">
            <div className="drawer-badge-row">
              <span className="drawer-theatre-badge" data-theatre={theatre.slug} style={{ "--tcolor": theatre.color }}>
                {theatre.name}
              </span>
              {movie.content_rating && <span className="drawer-content-rating">{movie.content_rating}</span>}
              {primary.recommended && <span className="drawer-rec-badge">&#9733; For you</span>}
            </div>
            <h2 className="drawer-title">{movie.title}</h2>
            {movie.tagline && <p className="drawer-tagline">{movie.tagline}</p>}
            {meta && <p className="drawer-meta">{meta}</p>}
          </div>
        </div>

        <div className="drawer-ratings-row">
          <RatingBadges movie={movie} />
          {watching !== null && (
            <button
              className={`btn btn-sm${watching ? " btn-primary" : ""}`}
              style={{ marginLeft: "auto" }}
              onClick={toggleWatch}
              title={watching ? "On your watchlist — the digest tells you when it's playing" : "Add to watchlist"}
            >
              {watching ? "✓ On your watchlist" : "＋ Watchlist"}
            </button>
          )}
        </div>

        <div className="drawer-tickets">
          {showtimes.map(s => (
            <TicketRow key={s.id} showtime={{ ...s, theatre }} apiBase={apiBase} groupId={readOnly ? null : groupId}
                       onRsvp={readOnly ? undefined : personal(onRsvp)} onAttendance={user ? onAttendance : undefined}
                       rsvpNote={rsvpNote} showTheatre={false} />
          ))}
          <Link className="drawer-film-link" to={`/films/${movie.id}`} onClick={onClose}>
            All showings &amp; film details →
          </Link>
        </div>

        {(going.length > 0 || maybes.length > 0) && (
          <Collapsible title="Who's going" count={going.length + maybes.length} defaultOpen>
            {[["Going", going], ["Maybe", maybes]].filter(([, list]) => list.length).map(([label, list]) => (
              <div key={label} className="drawer-who">
                <span className="drawer-section-label">{label} ({list.length})</span>
                <div className="attendee-list">
                  {list.map(a => (
                    <button key={a.id} type="button" className={`attendee-chip clickable${label === "Maybe" ? " maybe" : ""}`}
                            onClick={() => onViewProfile?.(a.id)}>
                      <Avatar user={a} size={24} />
                      {a.name}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </Collapsible>
        )}

        {!club && (interest.going || interest.want) && (
          <p className="drawer-interest">
            {[interest.going && `${interest.going} people going`, interest.want && `${interest.want} want to see it`].filter(Boolean).join(" · ")}
          </p>
        )}

        {!club && (
          <div className="drawer-public-reactions">
            <ReactionBar reactions={reactions} showtimeId={primary.id} groupId={null} apiBase={apiBase} onUpdate={setReactions}
                         beforeReact={async () => !!(user || await shell.ensureProfile())} />
          </div>
        )}

        {club && <Collapsible title="Reactions & discussion" defaultOpen>
          <ReactionBar reactions={reactions} showtimeId={primary.id} groupId={groupId} apiBase={apiBase} onUpdate={setReactions}
                       readOnly={readOnly} />
          <ChatSection showtimeId={primary.id} groupId={groupId} apiBase={apiBase} onViewProfile={onViewProfile}
                       discordThreadUrl={primary.discord_thread_url} discord={readOnly ? null : primary.discord} readOnly={readOnly} />
        </Collapsible>}

        {(movie.description || (!movie.cast?.length && movie.starring)) && (
          <Collapsible title="About" defaultOpen>
            {movie.description && <p className="drawer-desc">{movie.description}</p>}
            {!movie.cast?.length && movie.starring && <p className="drawer-starring">Starring {movie.starring}</p>}
          </Collapsible>
        )}
        {parseAwards(movie.awards) && <Collapsible title="Awards"><Awards movie={movie} /></Collapsible>}
        {movie.cast?.length > 0 && (
          <Collapsible title="Cast" count={movie.cast.length}><CastScroll cast={movie.cast} /></Collapsible>
        )}
        {hasTrailer && <Collapsible title="Trailer"><Trailer movie={movie} /></Collapsible>}
      </div>
    </Sheet>
  );
}

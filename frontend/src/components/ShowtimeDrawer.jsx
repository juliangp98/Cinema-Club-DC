import { useState, useEffect, useRef } from "react";
import ReactionBar from "./ReactionBar";
import ChatSection from "./ChatSection";

const MONTHS_SHORT = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
const DAYS_FULL = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

function formatFullDate(iso) {
  const d = new Date(iso);
  return `${DAYS_FULL[d.getDay()]}, ${MONTHS_SHORT[d.getMonth()]} ${d.getDate()}`;
}

function formatTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true });
}

const RSVP_OPTIONS = [
  { status: "going",     label: "Going" },
  { status: "maybe",     label: "Maybe" },
  { status: "not_going", label: "Can't go" },
];

// Rating source display helpers
const RATING_LABELS = {
  "Internet Movie Database": "IMDb",
  "Rotten Tomatoes": "RT",
  "Metacritic": "MC",
};

// Initials shown when a poster image is missing or fails to load.
function posterInitials(title) {
  const words = (title || "").replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length) return "🎬";
  return words.slice(0, 2).map(w => w[0]).join("").toUpperCase();
}

// OMDb only gives a summary string (e.g. "Won 3 Oscars. 44 wins & 27
// nominations total"). Pull out the marquee award + totals for a clean display.
function parseAwards(str) {
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

// Collapsible accordion section used for the drawer's informational blocks.
function Collapsible({ title, count, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="drawer-section">
      <button
        type="button"
        className="drawer-section-toggle"
        aria-expanded={open}
        onClick={() => setOpen(o => !o)}
      >
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

export default function ShowtimeDrawer({ showtimes, user, groupId, apiBase, onClose, onRsvp, onViewProfile }) {
  const drawerRef = useRef(null);
  const primary = showtimes[0];
  const [reactions, setReactions] = useState(primary.reactions || {});
  const [watching, setWatching] = useState(null); // null until watchlist loads
  const [posterOk, setPosterOk] = useState(true);
  const [heroOk, setHeroOk] = useState(true);

  useEffect(() => {
    fetch(`${apiBase}/api/watchlist`, { credentials: "include" })
      .then(r => (r.ok ? r.json() : []))
      .then(items => {
        setWatching(items.some(i => i.movie && i.movie.id === primary.movie.id));
      })
      .catch(() => setWatching(false));
  }, [apiBase, primary.movie.id]);

  async function toggleWatch() {
    const next = !watching;
    setWatching(next);
    try {
      const r = await fetch(`${apiBase}/api/watchlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ movie_id: primary.movie.id }),
      });
      if (r.ok) setWatching((await r.json()).watching);
      else setWatching(!next);
    } catch {
      setWatching(!next);
    }
  }

  function handleOverlayClick(e) {
    if (e.target === e.currentTarget) onClose();
  }

  useEffect(() => {
    function onKey(e) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    setReactions(primary.reactions || {});
    setPosterOk(true);
    setHeroOk(true);
  }, [primary]);

  const { movie, theatre } = primary;

  async function handleRsvpClick(showtimeId, status, currentRsvp) {
    const newStatus = currentRsvp === status ? null : status;
    await onRsvp(showtimeId, newStatus);
  }

  async function handleGoogleCal(showtimeId) {
    try {
      const r = await fetch(`${apiBase}/api/showtimes/${showtimeId}/gcal-url`, { credentials: "include" });
      if (r.ok) {
        const data = await r.json();
        window.open(data.url, "_blank");
      }
    } catch { /* ignore */ }
  }

  const metaParts = [
    movie.director && `Dir. ${movie.director}`,
    movie.release_year,
    movie.runtime_minutes && `${movie.runtime_minutes} min`,
  ].filter(Boolean);

  function dedupeUsers(showtimes, field) {
    const seen = new Set();
    const result = [];
    for (const s of showtimes) {
      for (const a of (s[field] || [])) {
        if (!seen.has(a.id)) {
          seen.add(a.id);
          result.push(a);
        }
      }
    }
    return result;
  }

  const allAttendees = dedupeUsers(showtimes, "attendees");
  const allMaybes = dedupeUsers(showtimes, "maybes");

  const cast = movie.cast || [];
  const ratings = movie.ratings || [];
  const heroImage = movie.backdrop_url || movie.poster_url || "";
  const hasTrailer = !!(movie.trailer_key || movie.trailer_link);
  const whoCount = allAttendees.length + allMaybes.length;
  const awards = parseAwards(movie.awards);
  const DOT = "·";

  return (
    <div className="drawer-overlay" onClick={handleOverlayClick}>
      <div className="drawer" ref={drawerRef}>
        <button className="drawer-close" onClick={onClose}>&times;</button>

        {/* Hero banner: backdrop, or the poster blurred as a fallback. If the
            image is missing or fails to load, a plain gradient banner is shown
            instead of a broken-image icon. */}
        {heroImage && heroOk ? (
          <div className={`drawer-hero${!movie.backdrop_url ? " poster-fallback" : ""}`}>
            <img className="drawer-backdrop" src={heroImage} alt="" onError={() => setHeroOk(false)} />
            <div className="drawer-backdrop-fade" />
          </div>
        ) : (
          <div className="drawer-hero drawer-hero-blank">
            <div className="drawer-backdrop-fade" />
          </div>
        )}

        <div className="drawer-content">
          {/* Header: poster thumbnail + title block */}
          <div className="drawer-header">
            {movie.poster_url && posterOk ? (
              <img
                className="drawer-poster-thumb"
                src={movie.poster_url}
                alt={movie.title}
                onError={() => setPosterOk(false)}
              />
            ) : (
              <div className="drawer-poster-thumb drawer-poster-thumb-ph">
                {posterInitials(movie.title)}
              </div>
            )}
            <div className="drawer-header-text">
              <div className="drawer-badge-row">
                <span className="drawer-theatre-badge" data-theatre={theatre.slug} style={{ "--tcolor": theatre.color }}>
                  {theatre.name}
                </span>
                {movie.content_rating && (
                  <span className="drawer-content-rating">{movie.content_rating}</span>
                )}
                {primary.recommended && (
                  <span className="drawer-rec-badge">&#9733; For you</span>
                )}
              </div>
              <h2 className="drawer-title">{movie.title}</h2>
              {movie.tagline && <p className="drawer-tagline">{movie.tagline}</p>}
              {metaParts.length > 0 && (
                <p className="drawer-meta">{metaParts.join(`  ${DOT}  `)}</p>
              )}
            </div>
          </div>

          {/* Ratings + watchlist */}
          {(ratings.length > 0 || movie.vote_average > 0 || watching !== null) && (
            <div className="drawer-ratings-row">
              {movie.vote_average > 0 && (
                <span className="drawer-rating-badge tmdb">TMDB {movie.vote_average.toFixed(1)}</span>
              )}
              {ratings.map((r, i) => (
                <span key={i} className="drawer-rating-badge">
                  {RATING_LABELS[r.source] || r.source} {r.value}
                </span>
              ))}
              {watching !== null && (
                <button
                  className={`drawer-watch-btn${watching ? " active" : ""}`}
                  onClick={toggleWatch}
                  title={watching ? "On your watchlist — you'll get pinged about new showtimes" : "Add to watchlist"}
                >
                  {watching ? "👀 Watching" : "＋ Watchlist"}
                </button>
              )}
            </div>
          )}

          {/* Screenings + RSVP (always visible) */}
          <div className="drawer-block">
            <span className="drawer-section-label">
              {showtimes.length > 1 ? `Screenings (${showtimes.length})` : "This Screening"}
            </span>
            {showtimes.map(s => (
              <div key={s.id} className="drawer-screening-item">
                <div className="drawer-showtime-row">
                  <div style={{ flex: 1 }}>
                    <div className={`drawer-showtime-time${s.is_sold_out ? " sold-out" : ""}`}>
                      {formatFullDate(s.start_time)} {DOT} {formatTime(s.start_time)}
                      {s.end_time && ` – ${formatTime(s.end_time)}`}
                      {s.is_sold_out && `  ${DOT} SOLD OUT`}
                    </div>
                    <div className="rsvp-buttons" style={{ marginTop: "0.6rem" }}>
                      {RSVP_OPTIONS.map(opt => (
                        <button
                          key={opt.status}
                          className={`rsvp-btn${s.user_rsvp === opt.status ? ` ${opt.status}` : ""}`}
                          onClick={() => handleRsvpClick(s.id, opt.status, s.user_rsvp)}
                        >
                          {opt.label}
                        </button>
                      ))}
                    </div>
                  </div>
                  {s.purchase_link && !s.is_sold_out && (
                    <a
                      href={s.purchase_link}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="drawer-ticket-link"
                    >
                      Tickets {"↗"}
                    </a>
                  )}
                </div>
                <div className="cal-export-row">
                  <button className="cal-export-btn" onClick={() => handleGoogleCal(s.id)}>
                    Google Calendar
                  </button>
                  <a
                    className="cal-export-btn"
                    href={`${apiBase}/api/showtimes/${s.id}/ical`}
                    download
                  >
                    Apple Calendar
                  </a>
                </div>
              </div>
            ))}
            <ReactionBar
              reactions={reactions}
              showtimeId={primary.id}
              groupId={groupId}
              apiBase={apiBase}
              onUpdate={setReactions}
            />
          </div>

          {/* About */}
          {(movie.description || (!cast.length && movie.starring)) && (
            <Collapsible title="About" defaultOpen>
              {movie.description && <p className="drawer-desc">{movie.description}</p>}
              {!cast.length && movie.starring && (
                <p className="drawer-starring">Starring {movie.starring}</p>
              )}
            </Collapsible>
          )}

          {/* Awards */}
          {awards && (
            <Collapsible title="Awards" defaultOpen>
              <div className="drawer-awards-stats">
                {awards.headline && (
                  <span className="drawer-award-stat marquee">🏆 {awards.headline}</span>
                )}
                {awards.wins != null && (
                  <span className="drawer-award-stat">
                    <b>{awards.wins}</b> win{awards.wins !== 1 ? "s" : ""}
                  </span>
                )}
                {awards.nominations != null && (
                  <span className="drawer-award-stat">
                    <b>{awards.nominations}</b> nomination{awards.nominations !== 1 ? "s" : ""}
                  </span>
                )}
              </div>
              <p className="drawer-awards-raw">{awards.raw}</p>
            </Collapsible>
          )}

          {/* Cast */}
          {cast.length > 0 && (
            <Collapsible title="Cast" count={cast.length}>
              <div className="drawer-cast-scroll">
                {cast.map((c, i) => (
                  <div key={i} className="drawer-cast-card">
                    {c.profile_path ? (
                      <img className="drawer-cast-photo" src={c.profile_path} alt={c.name} />
                    ) : (
                      <div className="drawer-cast-photo-placeholder">
                        {c.name.slice(0, 2).toUpperCase()}
                      </div>
                    )}
                    <div className="drawer-cast-name">{c.name}</div>
                    {c.character && <div className="drawer-cast-character">{c.character}</div>}
                  </div>
                ))}
              </div>
            </Collapsible>
          )}

          {/* Trailer */}
          {hasTrailer && (
            <Collapsible title="Trailer">
              {movie.trailer_key ? (
                <div className="drawer-trailer-embed">
                  <iframe
                    src={`https://www.youtube.com/embed/${movie.trailer_key}`}
                    title="Trailer"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              ) : (
                <a
                  href={movie.trailer_link}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="trailer-link"
                >
                  &#9654; Watch Trailer
                </a>
              )}
            </Collapsible>
          )}

          {/* Who's going */}
          {whoCount > 0 && (
            <Collapsible title="Who's Going" count={whoCount} defaultOpen>
              {allAttendees.length > 0 && (
                <>
                  <span className="drawer-section-label">Going ({allAttendees.length})</span>
                  <div className="attendee-list">
                    {allAttendees.map(a => (
                      <div
                        key={a.id}
                        className="attendee-chip clickable"
                        onClick={() => onViewProfile?.(a.id)}
                      >
                        <div className="attendee-avatar" style={{ background: a.avatar_color, color: "#0d0c09" }}>
                          {a.name.slice(0, 2).toUpperCase()}
                        </div>
                        {a.name}
                      </div>
                    ))}
                  </div>
                </>
              )}
              {allMaybes.length > 0 && (
                <div style={{ marginTop: "0.75rem" }}>
                  <span className="drawer-section-label">Maybe ({allMaybes.length})</span>
                  <div className="attendee-list">
                    {allMaybes.map(a => (
                      <div
                        key={a.id}
                        className="attendee-chip clickable"
                        style={{ opacity: 0.65 }}
                        onClick={() => onViewProfile?.(a.id)}
                      >
                        <div className="attendee-avatar" style={{ background: a.avatar_color, color: "#0d0c09" }}>
                          {a.name.slice(0, 2).toUpperCase()}
                        </div>
                        {a.name}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </Collapsible>
          )}

          {/* Discussion */}
          <Collapsible title="Discussion">
            <ChatSection
              showtimeId={primary.id}
              groupId={groupId}
              apiBase={apiBase}
              onViewProfile={onViewProfile}
            />
          </Collapsible>
        </div>
      </div>
    </div>
  );
}

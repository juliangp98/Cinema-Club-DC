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

export default function ShowtimeDrawer({ showtimes, user, groupId, apiBase, onClose, onRsvp, onViewProfile }) {
  const drawerRef = useRef(null);
  const primary = showtimes[0];
  const [reactions, setReactions] = useState(primary.reactions || {});
  const [watching, setWatching] = useState(null); // null until watchlist loads

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
  const hasBackdrop = !!movie.backdrop_url;

  return (
    <div className="drawer-overlay" onClick={handleOverlayClick}>
      <div className="drawer" ref={drawerRef}>
        <button className="drawer-close" onClick={onClose}>&times;</button>

        {/* Hero: backdrop + poster */}
        {hasBackdrop ? (
          <div className="drawer-hero">
            <img className="drawer-backdrop" src={movie.backdrop_url} alt="" />
            <div className="drawer-backdrop-fade" />
            {movie.poster_url && (
              <img className="drawer-hero-poster" src={movie.poster_url} alt={movie.title} />
            )}
          </div>
        ) : movie.poster_url ? (
          <img className="drawer-poster" src={movie.poster_url} alt={movie.title} />
        ) : (
          <div className="drawer-poster-placeholder">
            {movie.title.toUpperCase()}
          </div>
        )}

        <div className="drawer-content">
          {/* Badge row */}
          <div className="drawer-badge-row">
            <span className="drawer-theatre-badge" data-theatre={theatre.slug} style={{ "--tcolor": theatre.color }}>
              {theatre.name}
            </span>
            {movie.content_rating && (
              <span className="drawer-content-rating">{movie.content_rating}</span>
            )}
            {primary.recommended && (
              <span className="drawer-rec-badge">&#9733; Recommended for you</span>
            )}
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

          {/* Title */}
          <h2 className="drawer-title">{movie.title}</h2>

          {/* Tagline */}
          {movie.tagline && (
            <p className="drawer-tagline">{movie.tagline}</p>
          )}

          {/* Meta */}
          {metaParts.length > 0 && (
            <p className="drawer-meta">{metaParts.join("  \u00B7  ")}</p>
          )}

          {/* Ratings row */}
          {ratings.length > 0 && (
            <div className="drawer-ratings-row">
              {movie.vote_average > 0 && (
                <span className="drawer-rating-badge tmdb">
                  TMDB {movie.vote_average.toFixed(1)}
                </span>
              )}
              {ratings.map((r, i) => (
                <span key={i} className="drawer-rating-badge">
                  {RATING_LABELS[r.source] || r.source} {r.value}
                </span>
              ))}
            </div>
          )}

          {/* Awards */}
          {movie.awards && (
            <p className="drawer-awards">{movie.awards}</p>
          )}

          {/* Description */}
          {movie.description && (
            <p className="drawer-desc">
              {movie.description.length > 400
                ? movie.description.slice(0, 400) + "\u2026"
                : movie.description}
            </p>
          )}

          {/* Cast */}
          {cast.length > 0 && (
            <div style={{ marginBottom: "1.25rem" }}>
              <span className="drawer-section-label">Cast</span>
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
                    {c.character && (
                      <div className="drawer-cast-character">{c.character}</div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Screenings */}
          <span className="drawer-section-label">
            {showtimes.length > 1 ? `Screenings (${showtimes.length})` : "This Screening"}
          </span>

          {showtimes.map(s => (
            <div key={s.id} className="drawer-screening-item">
              <div className="drawer-showtime-row">
                <div style={{ flex: 1 }}>
                  <div className={`drawer-showtime-time${s.is_sold_out ? " sold-out" : ""}`}>
                    {formatFullDate(s.start_time)} &middot; {formatTime(s.start_time)}
                    {s.end_time && ` \u2013 ${formatTime(s.end_time)}`}
                    {s.is_sold_out && "  \u00B7 SOLD OUT"}
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
                    Tickets ↗
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

          {/* Reactions */}
          <ReactionBar
            reactions={reactions}
            showtimeId={primary.id}
            groupId={groupId}
            apiBase={apiBase}
            onUpdate={setReactions}
          />

          {/* Who's going */}
          {(allAttendees.length > 0 || allMaybes.length > 0) && (
            <div style={{ marginTop: "1.25rem" }}>
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
                        <div
                          className="attendee-avatar"
                          style={{ background: a.avatar_color, color: "#0d0c09" }}
                        >
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
                        <div
                          className="attendee-avatar"
                          style={{ background: a.avatar_color, color: "#0d0c09" }}
                        >
                          {a.name.slice(0, 2).toUpperCase()}
                        </div>
                        {a.name}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Chat */}
          <ChatSection
            showtimeId={primary.id}
            groupId={groupId}
            apiBase={apiBase}
            onViewProfile={onViewProfile}
          />

          {/* Starring (fallback if no cast cards) */}
          {!cast.length && movie.starring && (
            <div style={{ marginTop: "1.25rem" }}>
              <span className="drawer-section-label">Starring</span>
              <p style={{ fontSize: "0.75rem", color: "var(--muted)", lineHeight: 1.5 }}>
                {movie.starring}
              </p>
            </div>
          )}

          {/* Trailer embed or link */}
          {movie.trailer_key ? (
            <div className="drawer-trailer-embed">
              <iframe
                src={`https://www.youtube.com/embed/${movie.trailer_key}`}
                title="Trailer"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
              />
            </div>
          ) : movie.trailer_link ? (
            <a
              href={movie.trailer_link}
              target="_blank"
              rel="noopener noreferrer"
              className="trailer-link"
            >
              &#9654; Watch Trailer
            </a>
          ) : null}
        </div>
      </div>
    </div>
  );
}

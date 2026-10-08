import { useState, useEffect, useCallback, useMemo } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { SectionTitle } from "../ui/PageHeader";
import Avatar from "../ui/Avatar";
import UserProfileDrawer from "../components/UserProfileDrawer";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { useShell } from "../shell/AppShell";
import Poster from "../ui/Poster";
import { metaLine, RatingBadges, Awards, CastScroll, Trailer, parseAwards } from "../components/film/FilmInfo";
import "./FilmPage.css";
import { groupParam } from "../scope";
import { WatchDiscordPrompt } from "../ui/DiscordShare";

const dayLabel = iso => new Date(iso).toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
const timeLabel = iso => new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

function People({ label, people, onView }) {
  if (!people.length) return null;
  return (
    <div className="film-club-group">
      <span className="film-club-label">{label}</span>
      <div className="film-club-people">
        {people.slice(0, 8).map(p => <Avatar key={p.id} user={p} size={28} onClick={() => onView(p.id)} />)}
        <span className="film-club-names">
          {people.slice(0, 3).map(p => p.name).join(", ")}{people.length > 3 ? ` +${people.length - 3}` : ""}
        </span>
      </div>
    </div>
  );
}

// One page per film: details, every upcoming showing at the club's theatres,
// and where the club stands on it. Showings open the screening sheet to RSVP.
export default function FilmPage({ user, apiBase, groupId }) {
  const { id } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [theatre, setTheatre] = useState("all");
  const [watching, setWatching] = useState(false);
  const [watchPrompt, setWatchPrompt] = useState(false);     // "mention you in the Discord digest?"
  const [copied, setCopied] = useState(false);
  const [profileUserId, setProfileUserId] = useState(null);
  const shell = useShell();

  const load = useCallback(() => {
    fetch(`${apiBase}/api/films/${id}?${groupParam(groupId)}`, { credentials: "include" })
      .then(async r => {
        if (!r.ok) throw new Error(r.status === 404 ? "That film isn't in our listings." : "Couldn't load this film.");
        return r.json();
      })
      .then(d => { setData(d); setWatching(d.viewer_wants); setError(""); })
      .catch(e => setError(e.message));
  }, [apiBase, id, groupId]);

  useEffect(() => { setData(null); setTheatre("all"); load(); }, [load]);

  const { openShowtime, sheet } = useShowtimeSheet({
    user, apiBase, groupId, onViewProfile: setProfileUserId, onChange: load,
  });

  const theatres = useMemo(() => {
    const seen = new Map();
    for (const s of data?.showtimes || []) seen.set(s.theatre.slug, s.theatre);
    return [...seen.values()];
  }, [data]);

  const days = useMemo(() => {
    const groups = new Map();
    for (const s of data?.showtimes || []) {
      if (theatre !== "all" && s.theatre.slug !== theatre) continue;
      const key = s.start_time.slice(0, 10);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(s);
    }
    return [...groups.values()];
  }, [data, theatre]);

  async function toggleWatch() {
    if (!user && !(await shell.ensureProfile())) return;      // a visitor's first save makes a guest profile
    const next = !watching;
    setWatching(next);
    const r = await fetch(`${apiBase}/api/watchlist`, {
      method: "POST", headers: { "Content-Type": "application/json" }, credentials: "include",
      body: JSON.stringify({ movie_id: Number(id) }),
    }).catch(() => null);
    if (r?.ok) {
      const d = await r.json();
      setWatching(d.watching);
      setWatchPrompt(!!d.discord_prompt);
      load();
    } else setWatching(!next);
  }

  async function share() {
    const url = `${window.location.origin}/films/${id}`;
    try {
      if (navigator.share && window.matchMedia("(max-width: 767px)").matches) {
        await navigator.share({ title: data.movie.title, url });
        return;
      }
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* cancelled */ }
  }

  if (error) {
    return (
      <div className="page narrow film-empty">
        <p>{error}</p>
        <button className="btn" onClick={() => navigate(-1)}>‹ Back</button>
      </div>
    );
  }
  if (!data) return <div className="page narrow film-empty"><p>Loading…</p></div>;

  const { movie, club, rare, interest } = data;           // club is null in public mode (R5a)
  const genres = (movie.genres || "").split(",").map(g => g.trim()).filter(Boolean);
  const hasClub = club ? club.wanters.length || club.going.length || club.seen.length : 0;

  return (
    <div className="film-page">
      <section className={`film-hero${movie.backdrop_url ? "" : " no-backdrop"}`}>
        {movie.backdrop_url && <img className="film-backdrop" src={movie.backdrop_url} alt="" />}
        <div className="film-hero-inner">
          <button className="ui-page-back" onClick={() => navigate(-1)}>‹ Back</button>
          <div className="film-hero-row">
            <Poster movie={movie} className="film-poster" loading="eager" />
            <div className="film-hero-text">
              <h1 className="film-title">{movie.title}</h1>
              {movie.tagline && <p className="film-tagline">{movie.tagline}</p>}
              <p className="film-meta">{metaLine(movie)}</p>
              {(genres.length > 0 || rare) && (
                <div className="film-chips">
                  {rare?.reasons.map(r => <span key={r} className="chip gold">{r}</span>)}
                  {genres.map(g => <span key={g} className="chip">{g}</span>)}
                </div>
              )}
              <div className="film-ratings"><RatingBadges movie={movie} /></div>
              {!club && interest?.want && <p className="film-interest">{interest.want} people want to see it</p>}
              <div className="film-actions">
                <button className={`btn${watching ? " btn-primary" : ""}`} onClick={toggleWatch}>
                  {watching ? "✓ On your watchlist" : "＋ Watchlist"}
                </button>
                <button className="btn" onClick={share}>{copied ? "Link copied" : "Share"}</button>
                {(movie.trailer_key || movie.trailer_link) && (
                  <a className="btn btn-ghost" href="#trailer">▶ Trailer</a>
                )}
              </div>
              {watching && watchPrompt && (
                <WatchDiscordPrompt apiBase={apiBase} movieId={movie.id} onDone={() => setWatchPrompt(false)} />
              )}
            </div>
          </div>
        </div>
      </section>

      <div className="page film-body">
        {hasClub > 0 && (
          <section className="film-club">
            <People label="Going" people={club.going} onView={setProfileUserId} />
            <People label="Want to see it" people={club.wanters} onView={setProfileUserId} />
            <People label="Seen it" people={club.seen} onView={setProfileUserId} />
          </section>
        )}

        <SectionTitle>Showtimes</SectionTitle>
        {theatres.length > 1 && (
          <div className="film-filter" role="group" aria-label="Theatre">
            <button className={`chip${theatre === "all" ? " gold" : ""}`} onClick={() => setTheatre("all")}>
              All theatres
            </button>
            {theatres.map(t => (
              <button key={t.slug} className={`chip${theatre === t.slug ? " gold" : ""}`} onClick={() => setTheatre(t.slug)}>
                {t.short_name || t.name}
              </button>
            ))}
          </div>
        )}
        {(theatres.length === 1 || theatre !== "all") && (() => {
          const t = theatres.length === 1 ? theatres[0] : theatres.find(x => x.slug === theatre);
          return t && <Link className="film-theatre-link" to={`/theatres/${t.slug}`}>About {t.name} · map and what else is on →</Link>;
        })()}
        {days.length === 0 ? (
          <p className="film-none">
            {club ? "No upcoming showings at your club's theatres." : "No upcoming showings at the theatres we track."}
            {user && !watching && " Add it to your watchlist and the weekly digest will tell you when it's back."}
          </p>
        ) : (
          <div className="film-days">
            {days.map(list => (
              <div key={list[0].start_time.slice(0, 10)} className="film-day">
                <div className="film-day-label">{dayLabel(list[0].start_time)}</div>
                <div className="film-shows">
                  {list.map(s => {
                    const friends = (s.attendees || []).filter(a => a.id !== user?.id);
                    return (
                      <button key={s.id} type="button" onClick={() => openShowtime(s.id)}
                              className={`show-chip${s.user_rsvp === "going" ? " going" : s.user_rsvp === "maybe" ? " maybe" : ""}${s.is_sold_out ? " sold-out" : ""}`}>
                        <span className="show-time">{timeLabel(s.start_time)}</span>
                        <span className="show-where">{s.theatre.short_name || s.theatre.name}</span>
                        {s.format_label && <span className="show-format">{s.format_label}</span>}
                        {s.user_rsvp === "going" && <span className="show-you">You're going</span>}
                        {friends.length > 0 && (
                          <span className="show-friends" title={friends.map(f => f.name).join(", ")}>
                            {friends.slice(0, 3).map(f => <Avatar key={f.id} user={f} size={18} />)}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}

        {(movie.description || movie.starring) && (
          <>
            <SectionTitle>About</SectionTitle>
            {movie.description && <p className="film-desc">{movie.description}</p>}
            {!movie.cast?.length && movie.starring && <p className="film-desc">Starring {movie.starring}</p>}
          </>
        )}
        {movie.cast?.length > 0 && (<><SectionTitle>Cast</SectionTitle><CastScroll cast={movie.cast} /></>)}
        {parseAwards(movie.awards) && (<><SectionTitle>Awards</SectionTitle><Awards movie={movie} /></>)}
        {(movie.trailer_key || movie.trailer_link) && (
          <div id="trailer"><SectionTitle>Trailer</SectionTitle><Trailer movie={movie} /></div>
        )}
      </div>

      {sheet}
      {profileUserId && (
        <UserProfileDrawer userId={profileUserId} viewerId={user?.id} apiBase={apiBase}
                           onClose={() => setProfileUserId(null)}
                           onOpenShowtime={sid => { setProfileUserId(null); openShowtime(sid); }} />
      )}
    </div>
  );
}

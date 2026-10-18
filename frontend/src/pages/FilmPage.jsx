import { Fragment, useState, useEffect, useCallback, useMemo } from "react";
import { Link, useParams } from "react-router-dom";
import { BackLink, SectionTitle } from "../ui/PageHeader";
import Avatar from "../ui/Avatar";
import PersonLink from "../ui/PersonLink";
import useShowtimeSheet from "../shell/useShowtimeSheet";
import { useShell } from "../shell/AppShell";
import Poster from "../ui/Poster";
import Loading, { LoadError } from "../ui/Loading";
import TheatreLink from "../ui/TheatreLink";
import { useJson, toggleWatch } from "../api";
import { metaLine, RatingBadges, Awards, CastScroll, Trailer, parseAwards } from "../components/film/FilmInfo";
import "./FilmPage.css";
import { groupParam } from "../scope";
import { WatchDiscordPrompt } from "../ui/DiscordShare";
import { WatchAlertPrompt, watchPromptOf } from "../ui/AlertPrompts";
import { longDayDate, time, monthDay } from "../dates";

const dayLabel = longDayDate, timeLabel = time, shortDay = monthDay;
const dateRange = (a, b) => (!a ? "" : shortDay(a) === shortDay(b) ? shortDay(a) : `${shortDay(a)} – ${shortDay(b)}`);

function People({ label, people }) {
  if (!people.length) return null;
  return (
    <div className="film-club-group">
      <span className="film-club-label">{label}</span>
      <div className="film-club-people">
        {people.slice(0, 8).map(p => <Avatar key={p.id} user={p} size={28} link />)}
        <span className="film-club-names">
          {people.slice(0, 3).map((p, i) => <Fragment key={p.id}>{i > 0 && ", "}<PersonLink user={p} /></Fragment>)}
          {people.length > 3 ? ` +${people.length - 3}` : ""}
        </span>
      </div>
    </div>
  );
}

// One page per film: details, every upcoming showing at the club's theatres,
// and where the club stands on it. Showings open the screening sheet to RSVP.
export default function FilmPage({ user, apiBase, groupId }) {
  const { id } = useParams();
  const [theatre, setTheatre] = useState("all");
  const [showAll, setShowAll] = useState(false);       // a crowded film's every showtime at once
  const [watching, setWatching] = useState(false);
  const [watchPrompt, setWatchPrompt] = useState(null);     // {alerts, digest}: what to ask after a watchlist add
  const [copied, setCopied] = useState(false);
  const shell = useShell();

  const { data, error: loadError, reload: load } = useJson(`${apiBase}/api/films/${id}?${groupParam(groupId)}`);
  useEffect(() => { setTheatre("all"); setShowAll(false); }, [id]);
  useEffect(() => { if (data) setWatching(data.viewer_wants); }, [data]);
  const missing = loadError?.status === 404;

  const { openShowtime, sheet } = useShowtimeSheet({
    user, apiBase, groupId, onChange: load,
  });

  const theatres = useMemo(() => {
    const seen = new Map();
    for (const s of data?.showtimes || []) seen.set(s.theatre.slug, s.theatre);
    return [...seen.values()];
  }, [data]);

  // Where it's playing (R7b): showings, dates and formats per theatre. With
  // lots of showings at several theatres, you pick a theatre first instead of
  // scrolling a wall of times.
  const venues = useMemo(() => theatres.map(t => {
    const shows = (data?.showtimes || []).filter(s => s.theatre.slug === t.slug);
    return { t, count: shows.length, first: shows[0]?.start_time, last: shows[shows.length - 1]?.start_time,
             formats: [...new Set(shows.map(s => s.format_label).filter(Boolean))] };
  }), [theatres, data]);
  const crowded = (data?.showtimes?.length || 0) > 12 && theatres.length > 1;
  const picking = crowded && theatre === "all" && !showAll;

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

  async function onWatch() {      // (not "toggleWatch": that's the shared call it makes)
    if (!user && !(await shell.ensureProfile())) return;      // a visitor's first save makes a guest profile
    const next = !watching;
    setWatching(next);
    const d = await toggleWatch(apiBase, Number(id)).catch(() => null);
    if (d) {
      setWatching(d.watching);
      setWatchPrompt(watchPromptOf(d));
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

  if (loadError && !data && !missing) return <div className="page narrow"><LoadError what="this film" onRetry={load} /></div>;
  if (missing) {
    return (
      <div className="page narrow film-empty">
        <p>That film isn't in our listings.</p>
        <Link className="btn" to="/">Go to Discover</Link>
      </div>
    );
  }
  if (!data) return <div className="page narrow"><Loading context="film" /></div>;

  const { movie, club, rare, interest } = data;           // club is null in public mode (R5a)
  const genres = (movie.genres || "").split(",").map(g => g.trim()).filter(Boolean);
  const hasClub = club ? club.wanters.length || club.going.length || club.seen.length : 0;

  return (
    <div className="film-page">
      <section className={`film-hero${movie.backdrop_url ? "" : " no-backdrop"}`}>
        {movie.backdrop_url && <img className="film-backdrop" src={movie.backdrop_url} alt="" />}
        <div className="film-hero-inner">
          <BackLink />
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
                <button className={`btn${watching ? " btn-primary" : ""}`} onClick={onWatch}>
                  {watching ? "✓ On your watchlist" : "＋ Watchlist"}
                </button>
                <button className="btn" onClick={share}>{copied ? "Link copied" : "Share"}</button>
                {(movie.trailer_key || movie.trailer_link) && (
                  <a className="btn btn-ghost" href="#trailer">▶ Trailer</a>
                )}
              </div>
              {watching && watchPrompt && (
                (watchPrompt.alerts
            ? <WatchAlertPrompt apiBase={apiBase} movieId={movie.id} digest={watchPrompt.digest} onDone={() => setWatchPrompt(null)} />
            : <WatchDiscordPrompt apiBase={apiBase} movieId={movie.id} onDone={() => setWatchPrompt(null)} />)
              )}
            </div>
          </div>
        </div>
      </section>

      <div className="page film-body">
        {hasClub > 0 && (
          <section className="film-club">
            <People label="Going" people={club.going} />
            <People label="Want to see it" people={club.wanters} />
            <People label="Seen it" people={club.seen} />
          </section>
        )}

        <SectionTitle>Showtimes</SectionTitle>
        {data.announced?.map(a => (
          <div key={a.theatre.slug} className="film-announced" style={{ "--tcolor": a.theatre.color }}>
            <div>
              <strong>Coming to <TheatreLink theatre={a.theatre} /> · {shortDay(`${a.date}T12:00:00`)}</strong>
              <span> — announced; tickets aren't on sale yet.</span>
            </div>
            <div className="film-announced-hint">
              {!user ? "Sign in and add it to your watchlist to hear the moment tickets go on sale."
                : watching ? "It's on your watchlist — we'll tell you the moment tickets go on sale."
                : "Add it to your watchlist and we'll tell you the moment tickets go on sale."}
              {a.url && <> · <a href={a.url} target="_blank" rel="noreferrer">The theatre's page ↗</a></>}
            </div>
          </div>
        ))}
        {theatres.length > 1 && (
          <div className="film-venues" role="group" aria-label="Where it's playing">
            {venues.map(({ t, count, first, last, formats }) => (
              <button key={t.slug} type="button" style={{ "--tcolor": t.color }} aria-pressed={theatre === t.slug}
                      className={`film-venue${theatre === t.slug ? " on" : ""}`} onClick={() => setTheatre(theatre === t.slug ? "all" : t.slug)}>
                <span className="film-venue-name"><span className="theatre-link-dot" aria-hidden="true" />{t.name}</span>
                <span className="film-venue-meta">
                  {count} showing{count === 1 ? "" : "s"} · {dateRange(first, last)}{formats.length ? ` · ${formats.join(", ")}` : ""}
                </span>
              </button>
            ))}
            <button type="button" className={`film-venue all${theatre === "all" && !picking ? " on" : ""}`}
                    onClick={() => { setTheatre("all"); setShowAll(true); }}>
              <span className="film-venue-name">All theatres</span>
              <span className="film-venue-meta">{data.showtimes.length} showings</span>
            </button>
          </div>
        )}
        {(theatres.length === 1 || theatre !== "all") && (() => {
          const t = theatres.length === 1 ? theatres[0] : theatres.find(x => x.slug === theatre);
          return t && <p className="film-theatre-link">About <TheatreLink theatre={t} /> — its map and what else is on.</p>;
        })()}
        {picking ? (
          <p className="film-none">Pick a theatre above to see its showtimes.</p>
        ) : days.length === 0 ? (data.announced?.length ? null : (
          <p className="film-none">
            {club ? "No upcoming showings at your club's theatres." : "No upcoming showings at the theatres we track."}
            {user && !watching && " Add it to your watchlist and we'll tell you when a theatre books it."}
          </p>
        )) : (
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
                        {theatre === "all" && <span className="show-where">{s.theatre.short_name || s.theatre.name}</span>}
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
    </div>
  );
}

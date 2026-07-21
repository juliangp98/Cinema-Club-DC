"""DB persistence for scraped movies + showtimes, with change detection.

sync_to_db() upserts one theatre's scrape results and records a ScrapeRun.
When a scrape adds a burst of new showtimes (a venue "dropping" its next
month of programming) it emits a ScrapeEvent that the Discord bot announces.
"""

import datetime
import json

from .base import normalize_title


def _match_movie(Movie, m, enrich_movie):
    """Find an existing Movie for scraped dict `m`, enriching if needed.

    Returns (movie_or_None, enriched_or_None). Ladder: exact title →
    tmdb_id (post-enrichment) → normalized title + matching year.
    """
    title = m['title']
    movie = Movie.query.filter_by(title=title).first()
    if movie:
        enriched = None
        if not movie.tmdb_id:
            enriched = _enrich_with_fallback(enrich_movie, title, m.get('release_year') or movie.release_year)
        return movie, enriched

    enriched = _enrich_with_fallback(enrich_movie, title, m.get('release_year') or None)

    if enriched and enriched.get('tmdb_id'):
        movie = Movie.query.filter_by(tmdb_id=enriched['tmdb_id']).first()
        if movie:
            return movie, enriched

    norm = normalize_title(title)
    if norm:
        year = m.get('release_year') or (enriched.get('release_year') if enriched else None)
        year = str(year) if year else ''
        for cand in Movie.query.filter_by(title_normalized=norm).all():
            # Same normalized title; require year agreement when both sides have one
            if year and cand.release_year and str(cand.release_year) != year:
                continue
            return cand, enriched

    return None, enriched


def _enrich_with_fallback(enrich_movie, title, year):
    """Enrich by raw title; on a TMDB miss retry with the normalized title so
    venue format tags ('Alien (4K Restoration)', 'ALIEN 45th Anniversary')
    still find the film."""
    enriched = enrich_movie(title, year)
    if not enriched or not enriched.get('tmdb_id'):
        norm = normalize_title(title)
        if norm and norm != title.strip().casefold():
            enriched = enrich_movie(norm, year) or enriched
    return enriched


def _apply_movie_fields(movie, m, enriched):
    """Enriched API data takes priority; scraped data is fallback; existing DB value last."""
    if enriched:
        movie.director = enriched.get('director') or m.get('director') or movie.director
        movie.release_year = enriched.get('release_year') or m.get('release_year') or movie.release_year
        movie.runtime_minutes = enriched.get('runtime_minutes') or m.get('runtime_minutes') or movie.runtime_minutes or 120
        movie.starring = enriched.get('starring') or m.get('starring') or movie.starring
        movie.description = enriched.get('description') or m.get('description') or movie.description
        movie.trailer_link = enriched.get('trailer_link') or m.get('trailer_link') or movie.trailer_link
        movie.poster_url = enriched.get('poster_url') or m.get('poster_url') or movie.poster_url
        movie.genres = enriched.get('genres') or movie.genres or ''
        movie.tmdb_id = enriched.get('tmdb_id') or movie.tmdb_id
        movie.imdb_id = enriched.get('imdb_id') or movie.imdb_id
        movie.backdrop_url = enriched.get('backdrop_url') or movie.backdrop_url
        movie.tagline = enriched.get('tagline') or movie.tagline
        movie.vote_average = enriched.get('vote_average') or movie.vote_average
        movie.content_rating = enriched.get('content_rating') or movie.content_rating
        movie.cast_json = enriched.get('cast_json') or movie.cast_json
        movie.crew_json = enriched.get('crew_json') or movie.crew_json
        movie.awards = enriched.get('awards') or movie.awards
        movie.ratings_json = enriched.get('ratings_json') or movie.ratings_json
        movie.trailer_key = enriched.get('trailer_key') or movie.trailer_key
    else:
        movie.director = m.get('director') or movie.director
        movie.release_year = m.get('release_year') or movie.release_year
        movie.runtime_minutes = m.get('runtime_minutes') or movie.runtime_minutes or 120
        movie.starring = m.get('starring') or movie.starring
        movie.description = m.get('description') or movie.description
        movie.trailer_link = m.get('trailer_link') or movie.trailer_link
        movie.poster_url = m.get('poster_url') or movie.poster_url

    movie.title_normalized = normalize_title(movie.title)
    movie.last_updated = datetime.datetime.utcnow()


def sync_to_db(cfg, scraped_movies):
    """Upsert scraped movies + showtimes for one theatre and emit change events.

    `cfg` is a TheatreConfig from the registry. Returns the ScrapeRun id, or
    None if the theatre isn't seeded yet.
    """
    from app import app, db, Theatre, Movie, Showtime, ScrapeRun, ScrapeEvent
    from enrich import enrich_movie

    with app.app_context():
        theatre = Theatre.query.filter_by(slug=cfg.slug).first()
        if not theatre:
            print(f"  Theatre '{cfg.slug}' not found in DB. Run app.py first to seed theatres.")
            return None

        now = datetime.datetime.now()
        run = ScrapeRun(theatre_id=theatre.id, started_at=datetime.datetime.utcnow(),
                        movies_found=len(scraped_movies))
        db.session.add(run)

        # Snapshot pre-sync future state for diffing
        prev_future = Showtime.query.filter(
            Showtime.theatre_id == theatre.id,
            Showtime.start_time > now,
        ).all()
        prev_pairs = {(s.movie_id, s.start_time) for s in prev_future}
        prev_max_date = max((s.start_time for s in prev_future), default=None)

        if not scraped_movies:
            run.status = 'empty'
            run.finished_at = datetime.datetime.utcnow()
            run.prev_max_date = prev_max_date
            run.new_max_date = prev_max_date
            db.session.commit()
            print(f"  {cfg.slug}: scrape returned no movies — skipping sync (nothing changed)")
            return run.id

        new_movie_count = 0
        new_showtimes = []          # newly inserted Showtime rows
        scraped_pairs = set()       # every (movie_id, start_time) seen this run

        for m in scraped_movies:
            if not m.get('title'):
                continue

            movie, enriched = _match_movie(Movie, m, enrich_movie)
            if movie is None:
                movie = Movie(title=m['title'])
                db.session.add(movie)
                new_movie_count += 1

            _apply_movie_fields(movie, m, enriched)
            db.session.flush()

            for st in m.get('showtimes', []):
                start = st['start_time']
                scraped_pairs.add((movie.id, start))
                existing = Showtime.query.filter_by(
                    movie_id=movie.id,
                    theatre_id=theatre.id,
                    start_time=start
                ).first()
                if not existing:
                    showtime = Showtime(
                        movie_id=movie.id,
                        theatre_id=theatre.id,
                        start_time=start,
                        end_time=st.get('end_time'),
                        purchase_link=st.get('purchase_link'),
                        is_sold_out=st.get('is_sold_out', False)
                    )
                    db.session.add(showtime)
                    new_showtimes.append(showtime)
                else:
                    existing.is_sold_out = st.get('is_sold_out', False)
                    existing.purchase_link = st.get('purchase_link') or existing.purchase_link
                    if existing.is_cancelled:
                        existing.is_cancelled = False

        # Stale cleanup: future showtimes no longer on the venue's calendar.
        # Guarded by the non-empty check above so a broken scraper can't
        # mass-cancel a theatre's schedule.
        cancelled_count = 0
        for s in prev_future:
            if (s.movie_id, s.start_time) not in scraped_pairs and not s.is_cancelled:
                s.is_cancelled = True
                cancelled_count += 1

        db.session.flush()

        # Post-sync future state
        future_after = Showtime.query.filter(
            Showtime.theatre_id == theatre.id,
            Showtime.start_time > now,
            Showtime.is_cancelled.isnot(True),
        ).all()
        new_max_date = max((s.start_time for s in future_after), default=None)

        # Only count genuinely-new *future* showtimes toward drop detection
        new_future = [s for s in new_showtimes
                      if s.start_time > now and (s.movie_id, s.start_time) not in prev_pairs]

        run.status = 'ok'
        run.finished_at = datetime.datetime.utcnow()
        run.new_movies = new_movie_count
        run.new_showtimes = len(new_future)
        run.cancelled_showtimes = cancelled_count
        run.prev_max_date = prev_max_date
        run.new_max_date = new_max_date

        _emit_events(db, ScrapeEvent, cfg, theatre, run, new_future, prev_max_date, new_max_date)

        db.session.commit()
        print(f"  Synced {len(scraped_movies)} movies for {cfg.slug} "
              f"({len(new_future)} new showtimes, {cancelled_count} cancelled)")
        return run.id


def _emit_events(db, ScrapeEvent, cfg, theatre, run, new_future, prev_max_date, new_max_date):
    if cfg.announce_mode == 'none' or not new_future:
        return

    extends_horizon = (
        prev_max_date is not None and new_max_date is not None
        and new_max_date > prev_max_date + datetime.timedelta(days=cfg.drop_horizon_days)
    )
    # First-ever scrape of a venue is also a "drop" (whole calendar appears at once)
    is_drop = (len(new_future) >= cfg.drop_min_count
               or extends_horizon
               or prev_max_date is None)

    if is_drop:
        event_type = 'new_drop'
    elif cfg.announce_mode == 'all':
        event_type = 'new_showtimes'
    else:
        return

    # Summarize the new showtimes per movie for the announcement embed
    by_movie = {}
    for s in new_future:
        by_movie.setdefault(s.movie_id, []).append(s)
    summaries = []
    for movie_id, sts in by_movie.items():
        movie = sts[0].movie
        summaries.append({
            'movie_id': movie_id,
            'title': movie.title if movie else '',
            'poster_url': (movie.poster_url or '') if movie else '',
            'first_showtime': min(s.start_time for s in sts).isoformat(),
            'showtime_count': len(sts),
        })
    summaries.sort(key=lambda x: -x['showtime_count'])

    payload = {
        'theatre_slug': cfg.slug,
        'theatre_name': theatre.name,
        'new_showtime_count': len(new_future),
        'new_movie_count': run.new_movies,
        'cancelled_count': run.cancelled_showtimes,
        'date_min': min(s.start_time for s in new_future).isoformat(),
        'date_max': max(s.start_time for s in new_future).isoformat(),
        'movie_ids': list(by_movie.keys()),
        'movie_summaries': summaries[:10],
        'first_scrape': prev_max_date is None,
    }
    db.session.add(ScrapeEvent(
        theatre_id=theatre.id,
        run=run,
        event_type=event_type,
        payload_json=json.dumps(payload),
    ))


def record_scrape_error(cfg, error_text):
    """Record a failed scrape as a ScrapeRun + (rate-limited) ScrapeEvent."""
    from app import app, db, Theatre, ScrapeRun, ScrapeEvent

    with app.app_context():
        theatre = Theatre.query.filter_by(slug=cfg.slug).first()
        if not theatre:
            return

        run = ScrapeRun(theatre_id=theatre.id, started_at=datetime.datetime.utcnow(),
                        finished_at=datetime.datetime.utcnow(), status='error',
                        error_text=str(error_text)[:2000])
        db.session.add(run)

        # At most one error event per theatre per 24h to avoid bot spam
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
        recent = ScrapeEvent.query.filter(
            ScrapeEvent.theatre_id == theatre.id,
            ScrapeEvent.event_type == 'scrape_error',
            ScrapeEvent.created_at > cutoff,
        ).first()
        if not recent:
            db.session.add(ScrapeEvent(
                theatre_id=theatre.id,
                run=run,
                event_type='scrape_error',
                payload_json=json.dumps({
                    'theatre_slug': cfg.slug,
                    'theatre_name': theatre.name,
                    'error': str(error_text)[:500],
                }),
            ))
        db.session.commit()

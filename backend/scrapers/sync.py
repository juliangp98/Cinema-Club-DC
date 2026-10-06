"""DB persistence for scraped movies + showtimes, with change detection.

sync_to_db() upserts one theatre's scrape results and records a ScrapeRun.
When a scrape adds a burst of new showtimes (a venue "dropping" its next
month of programming) it emits a ScrapeEvent that the Discord bot announces.
"""

import datetime
import json

from .base import (event_label, extract_format_label, normalize_title,
                   parse_movie_title, title_search_variants)

# A film with no TMDB match is looked up again at most this often. Titles that
# never match (shorts programs, trivia nights) would otherwise cost API calls on
# every scrape of every venue.
ENRICH_RETRY_AFTER = datetime.timedelta(days=7)


def enrichment_due(movie, force=False):
    if movie.tmdb_id:
        return False
    return (force or not movie.enrich_attempted_at
            or datetime.datetime.utcnow() - movie.enrich_attempted_at >= ENRICH_RETRY_AFTER)


def lookup_film(enrich_movie, label, scraped_year=None):
    """Enrich a venue label. Searches each title variant (full clean title
    first), preferring a year written in the label over the scraped one, which
    is often a re-release date ('HIS GIRL FRIDAY (1940)' listed as 2026)."""
    _, title_year = parse_movie_title(label)
    variants = title_search_variants(label)
    return enrich_movie(variants[0], title_year or scraped_year or None, alternates=variants[1:])


def adopt_matched_title(movie, enriched, label):
    """A film titled from a program billing ("Count Gore De Vol presents THE
    FLY") that TMDB identified through the stripped title takes that title;
    the billing lives on as its screenings' event label. Only applies when the
    film was titled from this very label, so a film's established title never
    flips between venues. Returns the old title when renamed, else None."""
    query = (enriched or {}).get('matched_query')
    own = normalize_title(label)
    if query and normalize_title(movie.title) == own and normalize_title(query) != own:
        old, movie.title = movie.title, query[:200]
        return old
    return None


def _match_movie(Movie, MovieAlias, m, enrich_movie):
    """Find the Movie for scraped dict `m`.

    Returns (movie_or_None, enriched_or_None, looked_up). Ladder: a venue label
    seen before → TMDB id → same clean title with an agreeing year. Known labels
    cost no API calls, apart from the weekly retry for films still unmatched.
    """
    label = m['title'].strip()[:255]
    alias = MovieAlias.query.filter_by(title=label).first()
    movie = alias.movie if alias else Movie.query.filter_by(title=label).first()
    if movie:
        if not enrichment_due(movie):
            return movie, None, False
        return movie, lookup_film(enrich_movie, label, m.get('release_year') or movie.release_year), True

    enriched = lookup_film(enrich_movie, label, m.get('release_year'))
    if enriched:
        movie = Movie.query.filter_by(tmdb_id=enriched['tmdb_id']).first()
        if movie:
            return movie, enriched, True

    _, title_year = parse_movie_title(label)
    year = str((enriched or {}).get('release_year') or title_year or m.get('release_year') or '')
    for cand in Movie.query.filter_by(title_normalized=normalize_title(label)).all():
        # Same clean title; require year agreement when both sides have one
        if year and cand.release_year and str(cand.release_year) != year:
            continue
        return cand, enriched, True
    return None, enriched, True


_FILL_COLUMNS = ('director', 'release_year', 'runtime_minutes', 'starring', 'description',
                 'trailer_link', 'poster_url', 'genres', 'imdb_id', 'backdrop_url', 'tagline',
                 'vote_average', 'content_rating', 'cast_json', 'crew_json', 'awards',
                 'ratings_json', 'trailer_key')


def _merge_movie(db, MovieAlias, Showtime, Watchlist, keep, dup):
    """Fold `dup` into `keep`: screenings, watchlists and venue labels move over;
    `keep` adopts any metadata it's missing."""
    for col in _FILL_COLUMNS:
        if getattr(keep, col) in (None, '') and getattr(dup, col) not in (None, ''):
            setattr(keep, col, getattr(dup, col))
    Showtime.query.filter_by(movie_id=dup.id).update({'movie_id': keep.id})
    MovieAlias.query.filter_by(movie_id=dup.id).update({'movie_id': keep.id})
    for w in Watchlist.query.filter_by(movie_id=dup.id).all():
        if Watchlist.query.filter_by(user_id=w.user_id, movie_id=keep.id).first():
            db.session.delete(w)
        else:
            w.movie_id = keep.id
    db.session.delete(dup)


def consolidate_catalog():
    """Idempotent catalog cleanup (run by backfill_enrichment.py):

      1. remember every film's current title as a venue label, so the renames
         below never make the scraper look a film up again;
      2. retitle films to their clean title ('LICORICE PIZZA in 70mm' →
         'LICORICE PIZZA');
      3. merge films that are the same TMDB film — or an unmatched film with the
         same clean title and an agreeing year as a matched one;
      4. label existing screenings with the format and billing of the venue
         title their film was created from.
    Returns counts of what changed."""
    from app import app, db, Movie, MovieAlias, Showtime, Watchlist

    with app.app_context():
        movies = Movie.query.order_by(Movie.id).all()
        raw_title = {mv.id: mv.title for mv in movies}
        origin = dict(db.session.query(Showtime.id, Showtime.movie_id).all())
        stats = {'retitled': 0, 'merged': 0, 'labelled': 0}

        known = {a.title for a in MovieAlias.query.all()}
        for mv in movies:
            if mv.title not in known:
                db.session.add(MovieAlias(title=mv.title[:255], movie_id=mv.id))
                known.add(mv.title)
            clean = parse_movie_title(mv.title)[0]
            if clean != mv.title:
                mv.title = clean
                stats['retitled'] += 1
            mv.title_normalized = normalize_title(mv.title)
        db.session.flush()

        # Same TMDB film. Keep the shortest title — the plain film name rather
        # than a program billing like "EPIC SUNDAY: BATMAN BEGINS".
        by_tmdb, gone = {}, set()
        for mv in movies:
            if mv.tmdb_id:
                by_tmdb.setdefault(mv.tmdb_id, []).append(mv)
        for group in by_tmdb.values():
            keep = min(group, key=lambda mv: (len(mv.title), mv.id))
            for dup in group:
                if dup is not keep:
                    _merge_movie(db, MovieAlias, Showtime, Watchlist, keep, dup)
                    gone.add(dup.id)
                    stats['merged'] += 1
        db.session.flush()

        # Unmatched film with the same clean title as exactly one matched film.
        matched = {}
        for mv in movies:
            if mv.tmdb_id and mv.id not in gone:
                matched.setdefault(mv.title_normalized, []).append(mv)
        for mv in movies:
            if mv.tmdb_id or mv.id in gone:
                continue
            cands = [c for c in matched.get(mv.title_normalized, [])
                     if not (mv.release_year and c.release_year
                             and str(mv.release_year) != str(c.release_year))]
            if len(cands) == 1:
                _merge_movie(db, MovieAlias, Showtime, Watchlist, cands[0], mv)
                gone.add(mv.id)
                stats['merged'] += 1
        db.session.flush()

        final_title = {mv.id: mv.title for mv in movies if mv.id not in gone}
        for st in Showtime.query.filter(db.or_(Showtime.format_label.is_(None),
                                               Showtime.event_label.is_(None))).all():
            raw = raw_title.get(origin.get(st.id))
            if raw is None or st.movie_id not in final_title:
                continue
            fmt = st.format_label or extract_format_label(raw)
            billing = st.event_label or event_label(raw, final_title[st.movie_id])
            if (fmt, billing) != (st.format_label, st.event_label):
                st.format_label, st.event_label = fmt, billing
                stats['labelled'] += 1

        db.session.commit()
        return stats


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
    from app import app, db, Theatre, Movie, MovieAlias, Showtime, ScrapeRun, ScrapeEvent
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

            label = m['title'].strip()[:255]
            movie, enriched, looked_up = _match_movie(Movie, MovieAlias, m, enrich_movie)
            if movie is None:
                # Title a new film by the variant TMDB matched ("THE FLY", not
                # "Count Gore De Vol presents THE FLY"), else the clean label.
                title = (enriched or {}).get('matched_query') or parse_movie_title(label)[0]
                movie = Movie(title=title[:200])
                db.session.add(movie)
                new_movie_count += 1
            if looked_up and not enriched:
                movie.enrich_attempted_at = datetime.datetime.utcnow()
            adopt_matched_title(movie, enriched, label)

            _apply_movie_fields(movie, m, enriched)
            db.session.flush()
            if not MovieAlias.query.filter_by(title=label).first():
                db.session.add(MovieAlias(title=label, movie_id=movie.id))

            format_label = extract_format_label(label)
            billing = event_label(label, movie.title)
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
                        is_sold_out=st.get('is_sold_out', False),
                        format_label=format_label,
                        event_label=billing,
                    )
                    db.session.add(showtime)
                    new_showtimes.append(showtime)
                else:
                    existing.is_sold_out = st.get('is_sold_out', False)
                    existing.purchase_link = st.get('purchase_link') or existing.purchase_link
                    existing.format_label = format_label
                    existing.event_label = billing
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

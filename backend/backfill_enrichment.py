"""
Catalog maintenance: clean up film titles, merge duplicate films, label
screenings with their format, and look up films that have no TMDB match yet.
Safe to re-run, and it never triggers Discord announcements.

Unmatched films are retried at most weekly (the scraper does the same); pass
--force to retry all of them now. --refresh re-downloads TMDB/OMDb details for
films already matched (repairs details a venue overwrote before Oct 2026; about
two API calls per film).

Usage:
    # Local
    cd backend && ./venv/bin/python backfill_enrichment.py [--force] [--refresh]

    # Inside the production container
    sudo docker exec cinemaclub-backend python backfill_enrichment.py [--force] [--refresh]
"""

import argparse
import datetime
import time

from app import app, db, Movie, MovieAlias, Showtime
from enrich import enrich_by_tmdb_id, enrich_movie
from scrapers.base import event_label, parse_movie_title
from scrapers.sync import (_apply_movie_fields, adopt_matched_title, consolidate_catalog,
                           enrichment_due, lookup_film)


def _report(stats):
    print(f"  retitled {stats['retitled']}, merged {stats['merged']}, "
          f"labelled {stats['labelled']} screenings")


def lookup_unmatched(force=False):
    with app.app_context():
        movies = [m for m in Movie.query.filter(Movie.tmdb_id.is_(None)).all()
                  if enrichment_due(m, force)]
        print(f"Looking up {len(movies)} unmatched films…")
        matched = 0
        for i, movie in enumerate(movies, 1):
            print(f"[{i}/{len(movies)}] {movie.title}")
            labels = [a.title for a in MovieAlias.query.filter_by(movie_id=movie.id)] or [movie.title]
            labels.sort(key=lambda t: parse_movie_title(t)[1] is None)  # "(YYYY)" labels first
            data = label = None
            for label in labels:
                data = lookup_film(enrich_movie, label, movie.release_year)
                if data:
                    break
            movie.enrich_attempted_at = datetime.datetime.utcnow()
            if data:
                old = adopt_matched_title(movie, data, label)
                if old:
                    Showtime.query.filter_by(movie_id=movie.id, event_label=None).update(
                        {'event_label': event_label(old, movie.title)})
                _apply_movie_fields(movie, {}, data)
                matched += 1
            if i % 10 == 0:
                db.session.commit()
                time.sleep(0.5)   # stay well inside TMDB's rate limit
        db.session.commit()
        print(f"Matched {matched} of {len(movies)}.")


def refresh_matched():
    """Re-apply TMDB/OMDb details to every matched film."""
    with app.app_context():
        movies = Movie.query.filter(Movie.tmdb_id.isnot(None)).order_by(Movie.id).all()
        print(f"Refreshing details for {len(movies)} matched films…")
        refreshed = 0
        for i, movie in enumerate(movies, 1):
            data = enrich_by_tmdb_id(movie.tmdb_id, movie.title)
            if data:
                _apply_movie_fields(movie, {}, data)
                refreshed += 1
            if i % 10 == 0:
                db.session.commit()
                time.sleep(0.5)
        db.session.commit()
        print(f"Refreshed {refreshed} of {len(movies)}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--force', action='store_true',
                        help='retry every unmatched film, ignoring the weekly retry window')
    parser.add_argument('--refresh', action='store_true',
                        help='re-download details for films already matched')
    args = parser.parse_args()

    print('Cleaning up the catalog…')
    _report(consolidate_catalog())
    lookup_unmatched(force=args.force)
    if args.refresh:
        refresh_matched()
    print('Merging films matched in this run…')
    _report(consolidate_catalog())


if __name__ == '__main__':
    main()

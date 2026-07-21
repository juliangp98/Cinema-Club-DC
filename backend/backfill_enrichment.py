"""
One-time backfill: enrich any Movie rows that don't yet have a tmdb_id.

Usage:
    # Local
    cd backend && ./venv/bin/python backfill_enrichment.py

    # Inside the production container
    sudo docker exec cinemaclub-backend python backfill_enrichment.py
"""

import time
from app import app, db, Movie
from enrich import enrich_movie


def backfill():
    with app.app_context():
        movies = Movie.query.filter(Movie.tmdb_id.is_(None)).all()
        total = len(movies)
        print(f"Backfilling {total} unenriched movies...")

        ok = 0
        miss = 0
        for i, movie in enumerate(movies, 1):
            print(f"[{i}/{total}] {movie.title} ({movie.release_year})")
            data = enrich_movie(movie.title, movie.release_year)
            if not data:
                miss += 1
                continue

            # API data takes priority; existing data is fallback
            movie.director = data.get('director') or movie.director
            movie.release_year = data.get('release_year') or movie.release_year
            movie.runtime_minutes = data.get('runtime_minutes') or movie.runtime_minutes
            movie.starring = data.get('starring') or movie.starring
            movie.description = data.get('description') or movie.description
            movie.trailer_link = data.get('trailer_link') or movie.trailer_link
            movie.poster_url = data.get('poster_url') or movie.poster_url
            movie.genres = data.get('genres') or movie.genres or ''
            movie.tmdb_id = data.get('tmdb_id')
            movie.imdb_id = data.get('imdb_id') or movie.imdb_id
            movie.backdrop_url = data.get('backdrop_url') or movie.backdrop_url
            movie.tagline = data.get('tagline') or movie.tagline
            movie.vote_average = data.get('vote_average') or movie.vote_average
            movie.content_rating = data.get('content_rating') or movie.content_rating
            movie.cast_json = data.get('cast_json') or movie.cast_json
            movie.crew_json = data.get('crew_json') or movie.crew_json
            movie.awards = data.get('awards') or movie.awards
            movie.ratings_json = data.get('ratings_json') or movie.ratings_json
            movie.trailer_key = data.get('trailer_key') or movie.trailer_key
            ok += 1

            # Commit every 10 movies and rate-limit gently
            if i % 10 == 0:
                db.session.commit()
                time.sleep(0.5)

        db.session.commit()
        print(f"\nDone. Enriched: {ok}, no match: {miss}, total: {total}")


if __name__ == '__main__':
    backfill()

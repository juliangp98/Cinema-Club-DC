"""
Movie enrichment via TMDB and OMDb APIs.
Called by the scraper to fill in metadata for newly discovered movies.
"""

import os
import json
import requests
from dotenv import load_dotenv

# Load the backend env when the scraper is run standalone (mirrors app.py).
# load_dotenv never overrides variables already in the environment, so the
# Docker-injected values still win in production.
_env_dev = os.path.join(os.path.dirname(__file__), '.env.development')
load_dotenv(_env_dev) if os.path.exists(_env_dev) else load_dotenv()

TMDB_BASE = 'https://api.themoviedb.org/3'
TMDB_IMG_POSTER = 'https://image.tmdb.org/t/p/w500'
TMDB_IMG_BACKDROP = 'https://image.tmdb.org/t/p/w1280'
TMDB_IMG_PROFILE = 'https://image.tmdb.org/t/p/w185'

# Read tokens at call time so late-loaded env is still picked up.
def _tmdb_token():
    return os.environ.get('TMDB_API_TOKEN', '')


def _omdb_key():
    return os.environ.get('OMDB_API_KEY', '')


# Warn about missing tokens only once per run instead of twice per movie.
_warned = set()


def _warn_once(key, message):
    if key not in _warned:
        _warned.add(key)
        print(message)


def _tmdb_headers():
    return {'Authorization': f'Bearer {_tmdb_token()}', 'Accept': 'application/json'}


def enrich_from_tmdb(title, year=None):
    """Search TMDB for a movie and return enriched metadata dict, or None on failure."""
    if not _tmdb_token():
        _warn_once('tmdb', "  [enrich] TMDB_API_TOKEN not set — skipping TMDB enrichment "
                           "(set it in the environment the scraper runs in)")
        return None

    try:
        # Search
        params = {'query': title}
        if year:
            params['year'] = year
        r = requests.get(f'{TMDB_BASE}/search/movie', headers=_tmdb_headers(), params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get('results', [])

        if not results:
            print(f"  [enrich] TMDB: no results for '{title}' ({year})")
            return None

        # Pick best match: prefer exact title match, else first result
        match = results[0]
        for res in results:
            if res.get('title', '').lower().strip() == title.lower().strip():
                match = res
                break

        tmdb_id = match['id']

        # Fetch full details with credits and videos
        r2 = requests.get(
            f'{TMDB_BASE}/movie/{tmdb_id}',
            headers=_tmdb_headers(),
            params={'append_to_response': 'credits,videos'},
            timeout=10,
        )
        r2.raise_for_status()
        detail = r2.json()

        # Extract cast (top 6)
        cast = []
        for c in detail.get('credits', {}).get('cast', [])[:6]:
            cast.append({
                'name': c.get('name', ''),
                'character': c.get('character', ''),
                'profile_path': f"{TMDB_IMG_PROFILE}{c['profile_path']}" if c.get('profile_path') else None,
            })

        # Extract key crew (director + top writers)
        crew = []
        for c in detail.get('credits', {}).get('crew', []):
            if c.get('job') in ('Director', 'Writer', 'Screenplay'):
                crew.append({'name': c.get('name', ''), 'job': c.get('job', '')})

        # Find trailer (prefer Official Trailer, else first YouTube video)
        trailer_key = None
        videos = detail.get('videos', {}).get('results', [])
        for v in videos:
            if v.get('site') == 'YouTube' and v.get('type') == 'Trailer' and 'Official' in v.get('name', ''):
                trailer_key = v['key']
                break
        if not trailer_key:
            for v in videos:
                if v.get('site') == 'YouTube' and v.get('type') == 'Trailer':
                    trailer_key = v['key']
                    break
        if not trailer_key:
            for v in videos:
                if v.get('site') == 'YouTube':
                    trailer_key = v['key']
                    break

        # Genres
        genres = ','.join(g['name'].lower() for g in detail.get('genres', []))

        # Starring string from top cast
        starring = ', '.join(c['name'] for c in cast[:4])

        # Director from crew
        director = next((c['name'] for c in crew if c['job'] == 'Director'), None)

        result = {
            'tmdb_id': tmdb_id,
            'imdb_id': detail.get('imdb_id'),
            'description': detail.get('overview'),
            'runtime_minutes': detail.get('runtime'),
            'release_year': (detail.get('release_date') or '')[:4] or None,
            'poster_url': f"{TMDB_IMG_POSTER}{detail['poster_path']}" if detail.get('poster_path') else None,
            'backdrop_url': f"{TMDB_IMG_BACKDROP}{detail['backdrop_path']}" if detail.get('backdrop_path') else None,
            'tagline': detail.get('tagline') or None,
            'vote_average': detail.get('vote_average'),
            'genres': genres,
            'cast_json': json.dumps(cast),
            'crew_json': json.dumps(crew),
            'trailer_key': trailer_key,
            'trailer_link': f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else None,
            'starring': starring,
            'director': director,
        }

        print(f"  [enrich] TMDB: matched '{title}' → id={tmdb_id} ({detail.get('title')})")
        return result

    except Exception as e:
        print(f"  [enrich] TMDB error for '{title}': {e}")
        return None


def enrich_from_omdb(title, year=None, imdb_id=None):
    """Fetch awards and ratings from OMDb. Returns dict or None."""
    if not _omdb_key():
        _warn_once('omdb', "  [enrich] OMDB_API_KEY not set — skipping OMDb enrichment "
                           "(set it in the environment the scraper runs in)")
        return None

    try:
        params = {'apikey': _omdb_key()}
        if imdb_id:
            params['i'] = imdb_id
        else:
            params['t'] = title
            if year:
                params['y'] = year

        r = requests.get('http://www.omdbapi.com/', params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if data.get('Response') == 'False':
            print(f"  [enrich] OMDb: no match for '{title}' ({year})")
            return None

        ratings = []
        for rating in data.get('Ratings', []):
            ratings.append({
                'source': rating.get('Source', ''),
                'value': rating.get('Value', ''),
            })

        result = {
            'awards': data.get('Awards') if data.get('Awards') != 'N/A' else None,
            'ratings_json': json.dumps(ratings) if ratings else None,
            'content_rating': data.get('Rated') if data.get('Rated') != 'N/A' else None,
        }

        # Backup director from OMDb if TMDB didn't provide one
        if data.get('Director') and data['Director'] != 'N/A':
            result['director_backup'] = data['Director']

        print(f"  [enrich] OMDb: matched '{title}' → awards={result['awards'] or 'none'}")
        return result

    except Exception as e:
        print(f"  [enrich] OMDb error for '{title}': {e}")
        return None


def enrich_movie(title, year=None):
    """
    Orchestrate TMDB + OMDb enrichment for a movie.
    Returns a merged dict of all enrichment fields.
    """
    result = {}

    # TMDB first (richer data)
    tmdb = enrich_from_tmdb(title, year)
    if tmdb:
        result.update(tmdb)

    # OMDb for awards + ratings (use imdb_id from TMDB if available)
    imdb_id = result.get('imdb_id')
    omdb = enrich_from_omdb(title, year, imdb_id=imdb_id)
    if omdb:
        # Don't overwrite TMDB director with OMDb backup unless missing
        director_backup = omdb.pop('director_backup', None)
        if not result.get('director') and director_backup:
            result['director'] = director_backup
        result.update(omdb)

    return result if result else None

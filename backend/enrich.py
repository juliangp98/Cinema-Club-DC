"""
Movie enrichment via TMDB and OMDb APIs.
Called by the scraper to fill in metadata for newly discovered movies.
"""

import os
import json
import re
import unicodedata
from difflib import SequenceMatcher

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


def _norm(s):
    """Lowercase, accent- and punctuation-free form for comparing titles."""
    s = unicodedata.normalize('NFKD', s or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return ' '.join(re.sub(r'[^\w\s]', ' ', s).casefold().split())


def _title_ok(query, candidate):
    """Guard against loose search hits: accept a TMDB result only when its title
    plausibly is the film asked for. TMDB search is fuzzy — "Surprise Film"
    happily returns a short called "Surprise"."""
    q, c = _norm(query), _norm(candidate)
    if not q or not c:
        return False
    if q == c:
        return True
    qt, ct = set(q.split()), set(c.split())
    if qt <= ct:                               # query is a shortened full title
        return True
    if ct <= qt and len(ct) * 2 >= len(qt):    # a few extra words in the query
        return True
    return SequenceMatcher(None, q, c).ratio() >= 0.85   # venue typos


def _pick(results, query, year):
    """Best plausible result: exact titles first, then the release-year match,
    then TMDB's own relevance order."""
    ok = [r for r in results
          if _title_ok(query, r.get('title')) or _title_ok(query, r.get('original_title'))]
    exact = [r for r in ok
             if _norm(query) in (_norm(r.get('title')), _norm(r.get('original_title')))]
    pool = exact or ok
    if year:
        for r in pool:
            if (r.get('release_date') or '')[:4] == str(year):
                return r
    return pool[0] if pool else None


def search_tmdb(title, year=None):
    """Best TMDB search result for `title`, or None. One call, plus a year-less
    retry when the year filter finds nothing plausible — a scraped year is often
    a re-release date ('HIS GIRL FRIDAY' listed with 2026)."""
    if not _tmdb_token():
        _warn_once('tmdb', "  [enrich] TMDB_API_TOKEN not set — skipping TMDB enrichment "
                           "(set it in the environment the scraper runs in)")
        return None

    def search(params):
        r = requests.get(f'{TMDB_BASE}/search/movie', headers=_tmdb_headers(), params=params, timeout=10)
        r.raise_for_status()
        return r.json().get('results', [])

    try:
        match = _pick(search({'query': title, 'year': year} if year else {'query': title}), title, year)
        if not match and year:
            match = _pick(search({'query': title}), title, year)
        return match
    except Exception as e:
        print(f"  [enrich] TMDB search error for '{title}': {e}")
        return None


def tmdb_details(tmdb_id):
    """Full metadata for one TMDB film (credits + videos in the same call)."""
    try:
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
            'tmdb_title': detail.get('title'),
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

        return result

    except Exception as e:
        print(f"  [enrich] TMDB details error for id={tmdb_id}: {e}")
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


def enrich_movie(title, year=None, alternates=()):
    """Identify a film on TMDB, then add OMDb awards + ratings.

    Tries `title`, then each of `alternates`, using TMDB *search* only; the first
    match gets one details fetch and one OMDb lookup. Unidentified titles cost no
    OMDb calls (its free tier is 1,000/day). Returns a dict of movie fields, or
    None when nothing matched.
    """
    match = query = None
    for query in dict.fromkeys([title, *alternates]):
        match = search_tmdb(query, year)
        if match:
            break
    if not match:
        if _tmdb_token():
            print(f"  [enrich] TMDB: no match for '{title}' ({year})")
        return None

    result = tmdb_details(match['id'])
    if not result:
        return None
    result['matched_query'] = query   # which title variant identified the film
    print(f"  [enrich] TMDB: matched '{query}' → id={result['tmdb_id']} ({result['tmdb_title']})")

    omdb = enrich_from_omdb(result['tmdb_title'] or title, result.get('release_year'),
                            imdb_id=result.get('imdb_id'))
    if omdb:
        director_backup = omdb.pop('director_backup', None)
        if not result.get('director') and director_backup:
            result['director'] = director_backup
        result.update(omdb)
    return result

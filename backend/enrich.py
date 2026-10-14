"""
Movie enrichment via TMDB and OMDb APIs.
Called by the scraper to fill in metadata for newly discovered movies.
"""

import os
import json
import time
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


def _make_http():
    """One connection pool for every TMDB / OMDb call. Reused (keep-alive)
    connections mean a DNS lookup per host instead of per request — the NAS's
    router resolver drops some lookups when a backfill fires thousands — and a
    failed connection (a lookup that didn't resolve, a reset) or a 429/5xx is
    retried a few times with a short backoff instead of skipping the film."""
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
    retry = Retry(total=3, connect=3, read=1, status=3, backoff_factor=1,
                  status_forcelist=(429, 500, 502, 503, 504), allowed_methods=frozenset({'GET'}),
                  respect_retry_after_header=True, raise_on_status=False)
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry, pool_maxsize=4)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session


_http = _make_http()


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
        r = _http.get(f'{TMDB_BASE}/search/movie', headers=_tmdb_headers(), params=params, timeout=10)
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


TMDB_DEPARTMENTS = {'Directing': 'director', 'Acting': 'actor', 'Writing': 'writer'}


def tmdb_people(query, limit=8):
    """TMDB's people for a typed name (R13: favorite directors, actors,
    writers): [{name, kind}], by what they're known for. [] without a token
    or on errors."""
    if not _tmdb_token() or len((query or '').strip()) < 2:
        return []
    try:
        r = _http.get(f'{TMDB_BASE}/search/person', headers=_tmdb_headers(),
                         params={'query': query.strip(), 'include_adult': 'false'}, timeout=8)
        r.raise_for_status()
        return [{'name': x['name'], 'kind': TMDB_DEPARTMENTS[x.get('known_for_department')]}
                for x in r.json().get('results', [])[:limit]
                if x.get('name') and x.get('known_for_department') in TMDB_DEPARTMENTS]
    except Exception as e:
        print(f"  [enrich] TMDB person search error for '{query}': {e}")
        return []


def tmdb_search_list(query, limit=8):
    """TMDB's films for a typed title, most relevant first (R8c: watchlist any
    film): [{tmdb_id, title, year, poster_url}]. [] without a token or on errors."""
    if not _tmdb_token() or not (query or '').strip():
        return []
    try:
        r = _http.get(f'{TMDB_BASE}/search/movie', headers=_tmdb_headers(),
                         params={'query': query.strip(), 'include_adult': 'false'}, timeout=8)
        r.raise_for_status()
        out = []
        for x in r.json().get('results', [])[:limit]:
            y = (x.get('release_date') or '')[:4]
            out.append({'tmdb_id': x['id'], 'title': x.get('title') or x.get('original_title') or '',
                        'year': int(y) if y.isdigit() else None,
                        'poster_url': f"{TMDB_IMG_PROFILE}{x['poster_path']}" if x.get('poster_path') else None})
        return out
    except Exception as e:
        print(f"  [enrich] TMDB list search error for '{query}': {e}")
        return []


def tmdb_details(tmdb_id):
    """Full metadata for one TMDB film (credits + videos in the same call)."""
    try:
        r2 = _http.get(
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

        # Genres, in taste.py's terms (TMDB's names, lowercased)
        import taste
        genres = taste.merge_genres([g['name'] for g in detail.get('genres', [])])

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
            'original_language': detail.get('original_language') or None,
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


# OMDb's free tier allows 1,000 calls a day; past that it answers 401
# ("Request limit reached!"). After a refusal, OMDb is left alone for a while
# instead of spending the rest of a run on calls it'll refuse.
OMDB_FAILED = object()                      # "OMDb didn't answer" — unlike None, "OMDb has no such film"
OMDB_REST = 60 * 60                         # seconds to leave OMDb alone after a refusal
_omdb_refused_at = [None]


def omdb_limited():
    """Has OMDb refused us (its daily limit) in the last OMDB_REST seconds?"""
    return _omdb_refused_at[0] is not None and time.monotonic() - _omdb_refused_at[0] < OMDB_REST


def enrich_from_omdb(title, year=None, imdb_id=None):
    """Fetch awards and ratings from OMDb: a dict, None (OMDb has no such
    film), or OMDB_FAILED (it didn't answer — its daily limit, the network)."""
    if omdb_limited():
        return OMDB_FAILED
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

        r = _http.get('http://www.omdbapi.com/', params=params, timeout=10)
        if r.status_code == 401:                       # the daily limit (or a bad key)
            _omdb_refused_at[0] = time.monotonic()
            print(f"  [enrich] OMDb refused ({(r.json() if r.content else {}).get('Error', 'HTTP 401')}) — "
                  f"leaving it alone for an hour")
            return OMDB_FAILED
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
            # IMDb's genres add what TMDB has no name for (film noir, musical, biography, sport)
            'omdb_genres': [g for g in (data.get('Genre') or '').split(',') if g.strip() and data.get('Genre') != 'N/A'],
        }

        # Backup director from OMDb if TMDB didn't provide one
        if data.get('Director') and data['Director'] != 'N/A':
            result['director_backup'] = data['Director']

        print(f"  [enrich] OMDb: matched '{title}' → awards={result['awards'] or 'none'}")
        return result

    except Exception as e:
        print(f"  [enrich] OMDb error for '{title}': {e}")
        return OMDB_FAILED


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

    result = enrich_by_tmdb_id(match['id'], title)
    if result:
        result['matched_query'] = query   # which title variant identified the film
        print(f"  [enrich] TMDB: matched '{query}' → id={result['tmdb_id']} ({result['tmdb_title']})")
    return result


def enrich_by_tmdb_id(tmdb_id, title=''):
    """Full TMDB details plus OMDb awards + ratings for an identified film."""
    result = tmdb_details(tmdb_id)
    if not result:
        return None
    omdb = enrich_from_omdb(result['tmdb_title'] or title, result.get('release_year'),
                            imdb_id=result.get('imdb_id'))
    result['omdb_ok'] = omdb is not OMDB_FAILED          # answered, even if "no such film"
    if omdb and omdb is not OMDB_FAILED:
        import taste
        result['genres'] = taste.merge_genres(result.get('genres', '').split(','), omdb.pop('omdb_genres', []))
        director_backup = omdb.pop('director_backup', None)
        if not result.get('director') and director_backup:
            result['director'] = director_backup
        result.update(omdb)
    return result

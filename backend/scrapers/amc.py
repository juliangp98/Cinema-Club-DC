"""AMC Theatres — official developer API (developers.amctheatres.com).

Needs AMC_API_KEY, and AMC has to authorize it (a new key answers
"Unauthorized VendorKey" until then). The AMC theatres in the registry say
needs='amc': each full scrape run asks key_check() first, and they're shown
and scraped only while it passes — they switch on by themselves.

Uses Theatre/Showtime API v2. The theatre id may be the numeric theatre
number or the URL slug (e.g. 'amc-georgetown-14'). Showtimes are fetched
per-date: GET /v2/theatres/{id}/showtimes/{MM-DD-YYYY}, paginated via
_links.next; entries carry movieName, showDateTimeLocal, runTime,
isSoldOut, isCanceled, purchaseUrl and media.posterDynamic.
"""

import datetime
import os
import time

import requests

import places

from .base import finish_scrape, show_end

API_BASE = 'https://api.amctheatres.com'
DAYS_AHEAD = 45
REQUEST_SLEEP = 0.35


def _session():
    key = os.environ.get('AMC_API_KEY', '')
    if not key:
        raise RuntimeError('AMC_API_KEY not set — apply at developers.amctheatres.com')
    s = requests.Session()
    s.headers.update({
        'X-AMC-Vendor-Key': key,
        'Accept': 'application/json',
        'User-Agent': 'CinemaClubDC/1.0',
    })
    return s


def key_check(theatre_id):
    """(True, '') if AMC accepts the key (asked about one theatre), else (False, why)."""
    if not os.environ.get('AMC_API_KEY', ''):
        return False, "AMC_API_KEY isn't set, so the AMC theatres wait."
    try:
        r = _session().get(f'{API_BASE}/v2/theatres/{theatre_id}', timeout=20)
    except Exception as e:
        return False, f"Couldn't reach AMC's API to check the key ({e}); the AMC theatres wait."
    if r.status_code in (401, 403):
        return False, ("AMC hasn't authorized the API key yet (it answers \"Unauthorized VendorKey\"), so the AMC "
                       "theatres wait — they switch on by themselves once it does.")
    return True, ''


def scrape_amc(theatre_id, theatre_slug):
    """Scrape one AMC theatre via the official API. Returns list of movie dicts."""
    print(f"Scraping AMC ({theatre_slug})...")
    movies = {}
    missed = set()
    today = places.today_in()          # the days to ask the site for
    offset = 0
    error = None

    try:
        s = _session()

        for offset in range(DAYS_AHEAD):
            day = today + datetime.timedelta(days=offset)
            url = f"{API_BASE}/v2/theatres/{theatre_id}/showtimes/{day.strftime('%m-%d-%Y')}"
            while url:
                r = s.get(url, timeout=20)
                if r.status_code == 404:
                    break
                r.raise_for_status()
                payload = r.json()
                for st in payload.get('_embedded', {}).get('showtimes', []):
                    _ingest_showtime(movies, st, theatre_slug)
                url = payload.get('_links', {}).get('next', {}).get('href')
            time.sleep(REQUEST_SLEEP)

    except Exception as e:
        error = e
        # Days from the failure on weren't checked: keep their showtimes.
        missed = {today + datetime.timedelta(days=o) for o in range(offset, DAYS_AHEAD)}

    results = [m for m in movies.values() if m['showtimes']]
    if error is not None:
        print(f"  AMC {theatre_slug}: stopped at {today + datetime.timedelta(days=offset)} ({error})")
    # The unread days are missed, so a failure partway needn't make the run partial.
    return finish_scrape(f'AMC {theatre_slug}', results, None if results else error, missed_dates=missed)


def _ingest_showtime(movies, st, theatre_slug):
    title = (st.get('movieName') or '').strip()
    raw = st.get('showDateTimeLocal')
    if not title or not raw:
        return
    try:
        start = datetime.datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return

    movie = movies.get(title)
    if movie is None:
        media = st.get('media') or {}
        movie = movies[title] = {
            'title': title,
            'director': '',
            'release_year': '',
            'runtime_minutes': int(st.get('runTime') or 0) or 120,
            'starring': '',
            'description': '',
            'trailer_link': '',
            'poster_url': media.get('posterDynamic') or media.get('poster') or '',
            'showtimes': [],
        }

    movie['showtimes'].append({
        'start_time': start,
        'end_time': show_end(start, movie['runtime_minutes']),
        'purchase_link': st.get('purchaseUrl')
                         or f'https://www.amctheatres.com/movie-theatres/{theatre_slug}',
        'is_sold_out': bool(st.get('isSoldOut')),
        'is_cancelled': bool(st.get('isCanceled')),      # AMC says so outright (others just drop it)
    })

"""AMC Theatres — official developer API (developers.amctheatres.com).

DISABLED until an API key is approved: apply at developers.amctheatres.com,
then set AMC_API_KEY in the backend .env and flip enabled=True for the AMC
entries in scrapers/__init__.py.

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


def scrape_amc(theatre_id, theatre_slug):
    """Scrape one AMC theatre via the official API. Returns list of movie dicts."""
    print(f"Scraping AMC ({theatre_slug})...")
    movies = {}

    try:
        s = _session()
        today = datetime.date.today()

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
        print(f"  ERROR scraping AMC {theatre_slug}: {e}")

    results = [m for m in movies.values() if m['showtimes']]
    print(f"  Found {len(results)} movies at AMC {theatre_slug}")
    return results


def _ingest_showtime(movies, st, theatre_slug):
    title = (st.get('movieName') or '').strip()
    raw = st.get('showDateTimeLocal')
    if not title or not raw or st.get('isCanceled'):
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

    end = start + datetime.timedelta(minutes=movie['runtime_minutes'] + 20)
    movie['showtimes'].append({
        'start_time': start,
        'end_time': end,
        'purchase_link': st.get('purchaseUrl')
                         or f'https://www.amctheatres.com/movie-theatres/{theatre_slug}',
        'is_sold_out': bool(st.get('isSoldOut')),
    })

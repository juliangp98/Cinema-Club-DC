"""Angelika Film Centers (Mosaic, Union Market Pop-Up) — Reading Cinemas API.

The SPA at angelikafilmcenter.com calls production-api.readingcinemas.com.
An anonymous JWT is handed out by /settings/6; /films then returns
nowShowing.data.movies[] with showdates[].showtypes[].showtimes[]
(date_time carries the local UTC offset, soldout is a bool).
"""

import datetime
import re
import time

import requests

from .base import with_retry

API_BASE = 'https://production-api.readingcinemas.com'
SITE = 'https://angelikafilmcenter.com'
COUNTRY_ID = '6'
MAX_DATES = 60
REQUEST_SLEEP = 0.3

_session = None


def _api_session():
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({
            'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/126.0.0.0 Safari/537.36'),
            'Accept': 'application/json, text/plain, */*',
            'Origin': SITE,
            'Referer': SITE + '/',
        })
        def fetch_token():
            r = s.get(f'{API_BASE}/settings/{COUNTRY_ID}', timeout=20)
            r.raise_for_status()
            return r.json()['data']['settings']['token']

        s.headers['Authorization'] = 'Bearer ' + with_retry(fetch_token, label='Angelika token')
        _session = s
    return _session


def _parse_runtime(raw):
    if not raw:
        return 120
    if isinstance(raw, int):
        return raw or 120
    m = re.search(r'(\d+)\s*hr', raw)
    h = int(m.group(1)) if m else 0
    m = re.search(r'(\d+)\s*min', raw)
    mins = int(m.group(1)) if m else 0
    total = h * 60 + mins
    if total:
        return total
    m = re.search(r'\d+', str(raw))
    return int(m.group()) if m else 120


def _strip_html(text):
    return re.sub(r'<[^>]+>', ' ', text or '').replace('&rsquo;', "'").replace('&nbsp;', ' ').strip()


def scrape_angelika(cinema_id, site_path):
    """Scrape one Angelika venue ('0000000006' Mosaic, '0000000007' Union Market)."""
    print(f"Scraping Angelika ({site_path})...")
    movies = []

    by_slug = {}

    def _films(selected_date):
        s = _api_session()
        r = s.get(f'{API_BASE}/films', params={
            'countryId': COUNTRY_ID, 'cinemaId': cinema_id,
            'status': 'getShows', 'flag': 'initial', 'selectedDate': selected_date,
        }, timeout=25)
        r.raise_for_status()
        return r.json().get('nowShowing', {}).get('data', {})

    try:
        # The API returns one day per call; the first call also lists every
        # bookable date in filter.session.
        data = _films('')
        day_movies = data.get('movies', [])
        dates = [f.get('value') for f in data.get('filter', {}).get('session', [])
                 if f.get('value')]
        today = datetime.date.today().isoformat()

        _ingest(by_slug, day_movies, cinema_id, site_path)
        for d in sorted(set(dates))[:MAX_DATES]:
            if d == today:
                continue
            time.sleep(REQUEST_SLEEP)
            try:
                _ingest(by_slug, _films(d).get('movies', []), cinema_id, site_path)
            except Exception as e:
                print(f"  Angelika {site_path}: failed {d}: {e}")

        movies = [m for m in by_slug.values() if m['showtimes']]
        for movie in movies:
            movie['showtimes'].sort(key=lambda s: s['start_time'])

    except Exception as e:
        print(f"  ERROR scraping Angelika {site_path}: {e}")

    print(f"  Found {len(movies)} movies at Angelika {site_path}")
    return movies


def _ingest(by_slug, day_movies, cinema_id, site_path):
    """Merge one day's movies payload into the by_slug accumulator."""
    for mv in day_movies:
        title = (mv.get('name') or '').strip()
        if not title:
            continue
        slug = mv.get('movieSlug') or title

        movie = by_slug.get(slug)
        if movie is None:
            movie = by_slug[slug] = {
                'title': title,
                'director': mv.get('director') or '',
                'release_year': (mv.get('release_date') or '')[:4],
                'runtime_minutes': _parse_runtime(mv.get('length')),
                'starring': ', '.join((mv.get('cast') or '').replace('\xa0', ' ').split(',')[:4]).strip(),
                'description': _strip_html(mv.get('synopsis')),
                'trailer_link': mv.get('youtube_id') or '',
                'poster_url': mv.get('moviePoster') or mv.get('poster_image')
                              or mv.get('film_image_medium_size') or '',
                'showtimes': [],
            }
        page = f"{SITE}/{site_path}/movies/details/{mv.get('movieSlug', '')}"
        seen = {s['start_time'] for s in movie['showtimes']}

        for day in mv.get('showdates', []):
            for st_type in day.get('showtypes', []):
                for st in st_type.get('showtimes', []):
                    raw = st.get('date_time')
                    if not raw:
                        continue
                    try:
                        start = datetime.datetime.fromisoformat(raw)
                    except ValueError:
                        continue
                    # Offset in the string is the venue's local offset —
                    # the wall-clock time is already local, so drop tzinfo.
                    start = start.replace(tzinfo=None)
                    if start in seen:
                        continue
                    seen.add(start)
                    end = start + datetime.timedelta(minutes=movie['runtime_minutes'] + 20)
                    movie['showtimes'].append({
                        'start_time': start,
                        'end_time': end,
                        'purchase_link': page,
                        'is_sold_out': bool(st.get('soldout')),
                    })

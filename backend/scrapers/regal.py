"""Regal — internal JSON API on regmovies.com.

The site sits behind Cloudflare with TLS fingerprinting, so plain requests
gets a JS challenge; curl_cffi with Chrome impersonation passes. One call
per date: /api/getShowtimes?theatres=<code>&date=MM-DD-YYYY returns that
day's shows plus `datesWithShows` (all bookable dates) and a `movies[]`
metadata array (Duration, Actors, Directors, TrailerUrl, Description).
"""

import datetime
import time

API_URL = 'https://www.regmovies.com/api/getShowtimes'
MAX_DATES = 90          # safety cap on per-date requests per run
REQUEST_SLEEP = 0.4


def _fetch_day(cffi_requests, theatre_code, date_str):
    for attempt in range(2):
        r = cffi_requests.get(API_URL, params={
            'theatres': theatre_code, 'date': date_str,
            'hoCode': '', 'ignoreCache': 'false', 'moviesOnly': 'false',
        }, impersonate='chrome', timeout=25)
        if r.status_code == 429 and attempt == 0:
            time.sleep(5)
            continue
        r.raise_for_status()
        return r.json()


def scrape_regal(theatre_code, theatre_path):
    """Scrape one Regal theatre. Returns list of movie dicts."""
    print(f"Scraping Regal ({theatre_path})...")
    movies_by_code = {}
    results = []

    try:
        from curl_cffi import requests as cffi_requests

        today = datetime.date.today()
        first = _fetch_day(cffi_requests, theatre_code, today.strftime('%m-%d-%Y'))

        dates = []
        for ds in first.get('datesWithShows', []):
            try:
                d = datetime.datetime.fromisoformat(ds).date()
            except ValueError:
                continue
            if d >= today:
                dates.append(d)
        dates = sorted(set(dates))[:MAX_DATES]

        meta = {}   # MasterMovieCode -> movies[] metadata entry

        def ingest(payload):
            for mv in payload.get('movies', []):
                code = mv.get('MasterMovieCode')
                if code and code not in meta:
                    meta[code] = mv
            for day in payload.get('shows', []):
                # Only this theatre's showtimes — the API is single-theatre per
                # request, but guard against nearby-theatre bleed-through.
                if str(day.get('TheatreCode') or '') != str(theatre_code):
                    continue
                for film in day.get('Film', []):
                    code = film.get('MasterMovieCode')
                    title = (film.get('Title') or '').strip()
                    if not code or not title:
                        continue
                    entry = movies_by_code.setdefault(code, {'title': title, 'perfs': []})
                    entry['perfs'].extend(film.get('Performances', []))

        ingest(first)
        for d in dates:
            if d == today:
                continue
            time.sleep(REQUEST_SLEEP)
            try:
                ingest(_fetch_day(cffi_requests, theatre_code, d.strftime('%m-%d-%Y')))
            except Exception as e:
                print(f"  Regal {theatre_path}: failed {d}: {e}")

        page_url = f"https://www.regmovies.com/theatres/{theatre_path}"
        for code, entry in movies_by_code.items():
            mv = meta.get(code, {})
            duration = mv.get('Duration') or 120
            movie = {
                'title': entry['title'],
                'director': ', '.join(mv.get('Directors') or []),
                'release_year': '',
                'runtime_minutes': int(duration) if duration else 120,
                'starring': ', '.join((mv.get('Actors') or [])[:4]),
                'description': mv.get('Description') or '',
                'trailer_link': mv.get('TrailerUrl') or '',
                'poster_url': mv.get('GraphicUrl') or '',
                'showtimes': [],
            }
            seen = set()
            for p in entry['perfs']:
                ts = p.get('CalendarShowTime')
                if not ts or ts in seen:
                    continue
                seen.add(ts)
                try:
                    start = datetime.datetime.fromisoformat(ts)
                except ValueError:
                    continue
                end = start + datetime.timedelta(minutes=movie['runtime_minutes'] + 20)
                movie['showtimes'].append({
                    'start_time': start,
                    'end_time': end,
                    'purchase_link': page_url,
                    'is_sold_out': bool(p.get('StopSales')),
                })
            if movie['showtimes']:
                results.append(movie)

    except Exception as e:
        print(f"  ERROR scraping Regal {theatre_path}: {e}")

    print(f"  Found {len(results)} movies at Regal {theatre_path}")
    return results

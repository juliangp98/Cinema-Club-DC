"""Regal — internal JSON API on regmovies.com.

The site sits behind Cloudflare with TLS fingerprinting, so plain requests
gets a JS challenge; curl_cffi with Chrome impersonation passes. One call
per date: /api/getShowtimes?theatres=<codes>&date=MM-DD-YYYY returns that
day's shows for every theatre asked about (one `shows[]` entry each), plus
`datesWithShows` (all bookable dates) and a `movies[]` metadata array
(Duration, Actors, Directors, TrailerUrl, Description).

Regal rate-limits bursts (HTTP 429): about 25 requests, then it refuses for
minutes. So all our Regals share one request per date (fetched once per
process), every run checks the next two weeks, and the dates further out are
checked on one run a day, slowly. Retry-After is honored with growing
back-off, and after 3 failed dates in a row it stops for the run. Dates it
didn't get are reported so their showtimes are kept as they are.
"""

import datetime
import time

import places

from .base import PerDateFetcher, finish_scrape, retry_after, show_end

API_URL = 'https://www.regmovies.com/api/getShowtimes'
def codes():
    """Every enabled Regal in the registry (its theatre code) — one request covers them all."""
    from . import THEATRE_REGISTRY
    return tuple(c.args[0] for c in THEATRE_REGISTRY if c.enabled and c.scraper == 'regal')
MAX_DATES = 90              # safety cap on per-date requests per run
NEAR_DAYS = 14              # checked on every run
DEEP_EVERY = datetime.timedelta(hours=20)    # the dates past NEAR_DAYS: once a day
DEEP_KEY = 'regal_deep_at'  # BotSetting: when they were last all checked
REQUEST_PAUSE = 2.0         # seconds between near requests (plus up to 1s jitter)
FAR_PAUSE = 20.0            # …and between far ones, which stay under the limit
FAR_BUDGET = 40 * 60        # a deep run gives up on far dates after this long
BACKOFF = (15, 45, 120)     # waits after successive 429s on one request

_days = None                # {date: payload} for this process's run, shared by the Regals
_missed = set()
_error = None               # …or why the first request failed (not retried per theatre)


def _fetch_day(cffi_requests, date_str):
    for attempt in range(len(BACKOFF) + 1):
        r = cffi_requests.get(API_URL, params={
            'theatres': ','.join(codes()), 'date': date_str,
            'hoCode': '', 'ignoreCache': 'false', 'moviesOnly': 'false',
        }, impersonate='chrome', timeout=25)
        if r.status_code in (429, 503) and attempt < len(BACKOFF):
            wait = retry_after(r, BACKOFF[attempt])
            print(f"  Regal: {r.status_code} on {date_str}; waiting {wait:.0f}s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        return r.json()


def deep_due(now=None):
    """Whether this run also checks the far dates (last full check 20h+ ago)."""
    from app import app, db, BotSetting
    now = now or datetime.datetime.utcnow()
    with app.app_context():
        row = db.session.get(BotSetting, DEEP_KEY)
        try:
            return not row or now - datetime.datetime.fromisoformat(row.value) >= DEEP_EVERY
        except ValueError:
            return True


def _mark_deep(now=None):
    from app import app, db, BotSetting
    with app.app_context():
        row = db.session.get(BotSetting, DEEP_KEY) or BotSetting(key=DEEP_KEY)
        row.value = (now or datetime.datetime.utcnow()).isoformat()
        db.session.add(row)
        db.session.commit()


def _load_days(deep=None):
    """Every date's payload, fetched once per process for all the Regals (codes())."""
    global _days, _missed, _error
    if _error is not None:
        raise _error
    if _days is not None:
        return _days, _missed
    from curl_cffi import requests as cffi_requests

    today = places.today_in()          # the days to ask the site for
    try:
        first = _fetch_day(cffi_requests, today.strftime('%m-%d-%Y'))
    except Exception as e:
        _error = e
        raise
    days = {today: first}
    dates = set()
    for ds in first.get('datesWithShows', []):
        try:
            d = datetime.datetime.fromisoformat(ds).date()
        except ValueError:
            continue
        if d > today:
            dates.add(d)
    dates = sorted(dates)[:MAX_DATES]
    cut = today + datetime.timedelta(days=NEAR_DAYS)
    near, far = [d for d in dates if d < cut], [d for d in dates if d >= cut]
    fetch = lambda d: (d, _fetch_day(cffi_requests, d.strftime('%m-%d-%Y')))
    keep = lambda got: days.__setitem__(*got)

    near_f = PerDateFetcher('Regal', pause=REQUEST_PAUSE)
    near_f.run(near, fetch, keep)
    missed = set(near_f.missed)
    if deep is None:
        deep = deep_due()
    if far and deep and not near_f.tripped:
        far_f = PerDateFetcher('Regal (far dates)', pause=FAR_PAUSE, budget=FAR_BUDGET)
        far_f.run(far, fetch, keep)
        missed |= far_f.missed
        if not far_f.missed:
            _mark_deep()
    else:
        missed |= set(far)                 # not checked this run: their showtimes stay as they are
    _days, _missed = days, missed
    return days, missed


def scrape_regal(theatre_code, theatre_path, deep=None):
    """Scrape one Regal theatre. Returns a ScrapeResult of movie dicts."""
    label = f'Regal {theatre_path}'
    print(f"Scraping {label}...")
    results = []
    try:
        days, missed = _load_days(deep)
        movies_by_code, meta = {}, {}      # MasterMovieCode -> showings / movies[] metadata entry
        for payload in days.values():
            for mv in payload.get('movies', []):
                code = mv.get('MasterMovieCode')
                if code and code not in meta:
                    meta[code] = mv
            for day in payload.get('shows', []):
                if str(day.get('TheatreCode') or '') != str(theatre_code):
                    continue
                for film in day.get('Film', []):
                    code = film.get('MasterMovieCode')
                    title = (film.get('Title') or '').strip()
                    if not code or not title:
                        continue
                    entry = movies_by_code.setdefault(code, {'title': title, 'perfs': []})
                    entry['perfs'].extend(film.get('Performances', []))

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
                movie['showtimes'].append({
                    'start_time': start,
                    'end_time': show_end(start, movie['runtime_minutes']),
                    'purchase_link': page_url,
                    'is_sold_out': bool(p.get('StopSales')),
                })
            if movie['showtimes']:
                results.append(movie)
    except Exception as e:
        return finish_scrape(label, results, e)
    return finish_scrape(label, results, missed_dates=missed)

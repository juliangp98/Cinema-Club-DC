"""Scraper pacing, 429 back-off, the circuit breaker, and a sync that keeps
showtimes on dates that couldn't be checked — no network."""
import datetime
import sys
import types

import pytest

from helpers import setup_db


@pytest.fixture
def sleeps(monkeypatch):
    """time.sleep records instead of sleeping (put back after the test)."""
    from scrapers import base
    slept = []
    monkeypatch.setattr(base.time, 'sleep', slept.append)
    return slept


def resp(status, headers=None):
    return types.SimpleNamespace(status_code=status, headers=headers or {})


def test_retry_after():
    from scrapers.base import retry_after
    assert retry_after(resp(429, {'Retry-After': '30'}), 15) == 30
    assert retry_after(resp(429), 15) == 15 and retry_after(resp(429, {'Retry-After': 'soon'}), 15) == 15
    assert retry_after(resp(429, {'Retry-After': '900'}), 15) == 120              # capped at 2 minutes


def test_paced_requests_and_the_circuit_breaker(sleeps):
    from scrapers.base import PerDateFetcher
    got, fetched = [], []

    def fetch(d):
        fetched.append(d)
        if d in (2, 3, 4):
            raise RuntimeError('429')
        return d
    f = PerDateFetcher('T', pause=2.0, jitter=1.0)
    f.run([1, 2, 3, 4, 5, 6], fetch, got.append)
    assert len(sleeps) == 4 and all(2.0 <= s <= 3.0 for s in sleeps)               # 2–3 s before each request
    assert fetched == [1, 2, 3, 4] and f.tripped                                   # 3 failures in a row: stop
    assert f.missed == {2, 3, 4, 5, 6}                                             # failed and skipped dates


def test_scattered_failures_dont_trip_the_breaker(sleeps):
    from scrapers.base import PerDateFetcher

    def fetch(d):
        if d in (1, 3):
            raise RuntimeError()
        return d
    f = PerDateFetcher('T', pause=0)
    f.run([1, 2, 3, 4], fetch, lambda x: None)
    assert not f.tripped and f.missed == {1, 3}


@pytest.fixture
def regal_site(monkeypatch, sleeps):
    """A fake Regal API over six days; `throttled[day]` = 429s to send first
    ('always' = every time)."""
    today = datetime.date.today()
    days = [today + datetime.timedelta(days=i) for i in range(6)]
    calls, throttled = [], {}

    def payload(day):
        return {'datesWithShows': [d.isoformat() for d in days], 'movies': [{'MasterMovieCode': 'M1', 'Duration': 100}],
                'shows': [{'TheatreCode': '1551', 'Film': [{'MasterMovieCode': 'M1', 'Title': 'SINNERS',
                           'Performances': [{'CalendarShowTime': f'{day.isoformat()}T19:00:00'}]}]}]}

    class Resp:
        def __init__(self, status, day, headers=None):
            self.status_code, self.day, self.headers = status, day, headers or {}

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f'HTTP {self.status_code}')

        def json(self):
            return payload(self.day)

    def get(url, params=None, **k):
        day = datetime.datetime.strptime(params['date'], '%m-%d-%Y').date()
        calls.append(day)
        n = throttled.get(day)
        if n == 'always':
            return Resp(429, day)
        if n:
            throttled[day] -= 1
            return Resp(429, day, {'Retry-After': '7'})
        return Resp(200, day)
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(requests=types.SimpleNamespace(get=get)))
    return types.SimpleNamespace(days=days, calls=calls, throttled=throttled, sleeps=sleeps)


def test_regal_waits_as_long_as_asked_then_succeeds(regal_site):
    from scrapers import regal
    regal_site.throttled[regal_site.days[1]] = 1
    out = regal.scrape_regal('1551', 'regal-gallery-place-4dx-1551')
    assert 7 in regal_site.sleeps and regal_site.calls.count(regal_site.days[1]) == 2
    assert len(out) == 1 and len(out[0]['showtimes']) == 6 and out.missed_dates == set()


def test_regal_backs_off_then_stops_for_the_night(regal_site):
    from scrapers import regal
    days = regal_site.days
    for d in days[1:4]:
        regal_site.throttled[d] = 'always'
    out = regal.scrape_regal('1551', 'regal-gallery-place-4dx-1551')
    assert [s for s in regal_site.sleeps if s >= 15][:3] == [15, 45, 120]          # 15 s, 45 s, 2 min per date
    assert days[4] not in regal_site.calls and days[5] not in regal_site.calls     # three throttled days: stop asking
    assert out.missed_dates == set(days[1:6])
    assert sorted(s['start_time'].date() for s in out[0]['showtimes']) == [days[0]]   # what it got is kept


@pytest.fixture
def keeper(monkeypatch):
    """KEEPER at Regal Gallery on the next four days."""
    import enrich
    from app import app, db, seed_theatres, Showtime, Movie, Theatre
    setup_db()
    monkeypatch.setattr(enrich, 'enrich_movie', lambda *a, **k: None)
    today = datetime.date.today()
    with app.app_context():
        seed_theatres()
        th = Theatre.query.filter_by(slug='regal-gallery').first()
        m = Movie(title='KEEPER')
        db.session.add(m)
        db.session.flush()
        t0 = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(19))
        for i in range(4):
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=t0 + datetime.timedelta(days=i)))
        db.session.commit()
        return {'movie': m.id, 'theatre': th.id, 'day': lambda n: today + datetime.timedelta(days=n)}


def sync(scraped):
    from scrapers import THEATRE_REGISTRY
    from scrapers.sync import sync_to_db
    sync_to_db(next(c for c in THEATRE_REGISTRY if c.slug == 'regal-gallery'), scraped)


def cancelled_by_day(k):
    from app import app, Showtime
    with app.app_context():
        return {s.start_time.date(): s.is_cancelled for s in Showtime.query.filter_by(movie_id=k['movie'], theatre_id=k['theatre'])}


def other_film(k):
    return {'title': 'OTHER FILM', 'showtimes': [{'start_time': datetime.datetime.combine(k['day'](5), datetime.time(12))}]}


def test_sync_keeps_showtimes_on_dates_it_couldnt_check(keeper):
    from scrapers.base import ScrapeResult
    day = keeper['day']
    sync(ScrapeResult([other_film(keeper)], missed_dates={day(2), day(3), day(4)}))
    st = cancelled_by_day(keeper)
    assert st[day(1)] is True                                  # checked, and gone: cancelled
    assert st[day(2)] is False and st[day(3)] is False         # couldn't be fetched: kept


def test_a_complete_scrape_cancels_what_disappeared(keeper):
    sync([other_film(keeper)])
    assert all(cancelled_by_day(keeper).values())

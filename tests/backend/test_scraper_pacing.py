"""Scraper pacing, 429 back-off, circuit breaker, and missed-date-safe sync — no network."""
from helpers import H, client, Checks, WORK


def test_scraper_pacing():
    checks = Checks()
    check = checks.check
    import sys, types, datetime
    from scrapers import base, regal
    from scrapers.base import PerDateFetcher, ScrapeResult, retry_after


    sleeps = []
    base.time.sleep = regal.time.sleep = lambda s: sleeps.append(s)

    print('--- helpers ---')
    R = lambda status, headers=None: types.SimpleNamespace(status_code=status, headers=headers or {})
    check('Retry-After honored', retry_after(R(429, {'Retry-After': '30'}), 15) == 30)
    check('…default when absent or junk', retry_after(R(429), 15) == 15 and retry_after(R(429, {'Retry-After': 'soon'}), 15) == 15)
    check('…capped at 2 minutes', retry_after(R(429, {'Retry-After': '900'}), 15) == 120)

    sleeps.clear()
    got, fetched = [], []
    def fetch(d):
        fetched.append(d)
        if d in (2, 3, 4):
            raise RuntimeError('429')
        return d
    f = PerDateFetcher('T', pause=2.0, jitter=1.0)
    f.run([1, 2, 3, 4, 5, 6], fetch, got.append)
    check('paced: a 2–3s pause before each request', len(sleeps) == 4 and all(2.0 <= s <= 3.0 for s in sleeps), sleeps)
    check('3 failures in a row trip the breaker: no more requests this run', fetched == [1, 2, 3, 4] and f.tripped)
    check('failed and skipped dates are all reported missed', f.missed == {2, 3, 4, 5, 6}, f.missed)
    f2 = PerDateFetcher('T', pause=0)
    f2.run([1, 2, 3, 4], lambda d: (_ for _ in ()).throw(RuntimeError()) if d in (1, 3) else d, lambda x: None)
    check('a success in between resets the count (no trip on scattered failures)', not f2.tripped and f2.missed == {1, 3})

    print('--- Regal ---')
    today = datetime.date.today()
    days = [today + datetime.timedelta(days=i) for i in range(6)]
    calls = []
    def payload(day):
        return {'datesWithShows': [d.isoformat() for d in days],
                'movies': [{'MasterMovieCode': 'M1', 'Duration': 100}],
                'shows': [{'TheatreCode': '1551', 'Film': [{'MasterMovieCode': 'M1', 'Title': 'SINNERS',
                           'Performances': [{'CalendarShowTime': f'{day.isoformat()}T19:00:00'}]}]}]}
    class Resp:
        def __init__(self, status, day, headers=None): self.status_code, self.day, self.headers = status, day, headers or {}
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError(f'HTTP {self.status_code}')
        def json(self): return payload(self.day)
    throttled = {}
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
    sys.modules['curl_cffi'] = types.SimpleNamespace(requests=types.SimpleNamespace(get=get))

    sleeps.clear(); calls.clear()
    throttled.update({days[1]: 1})
    out = regal.scrape_regal('1551', 'regal-gallery-place-4dx-1551')
    check('a 429 waits as long as Regal asks, then succeeds', 7 in sleeps and calls.count(days[1]) == 2, sleeps)
    check('every day collected; nothing missed', len(out) == 1 and len(out[0]['showtimes']) == 6 and out.missed_dates == set(), out.missed_dates)

    sleeps.clear(); calls.clear(); throttled.clear()
    throttled.update({days[1]: 'always', days[2]: 'always', days[3]: 'always'})
    out = regal.scrape_regal('1551', 'regal-gallery-place-4dx-1551')
    backoffs = [s for s in sleeps if s >= 15]
    check('persistent 429: backs off 15s, 45s, 2min per date before giving up on it', backoffs[:3] == [15, 45, 120], backoffs)
    check('after 3 throttled days it stops asking for the night', days[4] not in calls and days[5] not in calls, calls)
    check("…and reports those days as missed, keeping what it got", out.missed_dates == set(days[1:6])
          and sorted(s['start_time'].date() for s in out[0]['showtimes']) == [days[0]], out.missed_dates)

    print('--- sync keeps showtimes on unchecked dates ---')
    from app import app, db, migrate, Showtime, Movie, Theatre
    from scrapers import THEATRE_REGISTRY
    from scrapers.sync import sync_to_db
    cfg = next(c for c in THEATRE_REGISTRY if c.slug == 'regal-gallery')
    with app.app_context():
        db.create_all(); migrate()
        from app import seed_theatres; seed_theatres()
        th = Theatre.query.filter_by(slug='regal-gallery').first()
        m = Movie(title='KEEPER'); db.session.add(m); db.session.flush()
        t0 = datetime.datetime.combine(today + datetime.timedelta(days=1), datetime.time(19))
        for i in range(4):
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=t0 + datetime.timedelta(days=i)))
        db.session.commit()
        MID, TID = m.id, th.id
    checked_day, missed_day = (today + datetime.timedelta(days=1)), (today + datetime.timedelta(days=2))
    scraped = ScrapeResult([{'title': 'OTHER FILM', 'showtimes': [{'start_time': datetime.datetime.combine(today + datetime.timedelta(days=5), datetime.time(12))}]}],
                           missed_dates={missed_day, today + datetime.timedelta(days=3), today + datetime.timedelta(days=4)})
    import enrich; enrich.enrich_movie = lambda *a, **k: None
    sync_to_db(cfg, scraped)
    with app.app_context():
        st = {s.start_time.date(): s.is_cancelled for s in Showtime.query.filter_by(movie_id=MID, theatre_id=TID)}
    check('a showtime gone from a date that WAS checked is cancelled', st[checked_day] is True, st)
    check("showtimes on dates that couldn't be fetched are kept", st[missed_day] is False and st[today + datetime.timedelta(days=3)] is False, st)
    sync_to_db(cfg, [{'title': 'OTHER FILM', 'showtimes': [{'start_time': datetime.datetime.combine(today + datetime.timedelta(days=5), datetime.time(12))}]}])
    with app.app_context():
        st = {s.start_time.date(): s.is_cancelled for s in Showtime.query.filter_by(movie_id=MID, theatre_id=TID)}
    check('a complete scrape (plain list) still cancels what disappeared', all(st.values()), st)
    checks.done()

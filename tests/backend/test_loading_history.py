"""R7b: Calendar history + compact responses; keeping public pages warm."""
from helpers import H, client, Checks, WORK


def test_loading_history():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta
    from app import app, db, migrate, Showtime, Movie, Theatre, INTERNAL_API_TOKEN
    import app as A

    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        now = datetime.now().replace(hour=19, minute=0, second=0, microsecond=0)
        m = Movie(title='HISTORY FILM', cast_json='[{"name": "Someone"}]', description='x' * 500); db.session.add(m); db.session.flush()
        for d in (-70, -20, -3, 2, 3, 4):
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=d)))
        db.session.commit()
        MID = m.id
    c = app.test_client()
    day = lambda n: (now + timedelta(days=n)).date().isoformat()

    print('--- calendar ---')
    r = c.get('/api/discover/calendar', query_string={'from': day(-25), 'to': day(6)}).json
    mine = [s for s in r['showtimes'] if s['movie_id'] == MID]
    check('past days show (recent history)', len(mine) == 5, len(mine))
    r2 = c.get('/api/discover/calendar', query_string={'from': day(-80), 'to': day(-60)}).json
    check('…back to 60 days, no further', not [s for s in r2['showtimes'] if s['movie_id'] == MID])
    check('each film is sent once (screenings point to it)', str(MID) in {str(k) for k in r['movies']} and all('movie' not in s for s in r['showtimes'])
          and r['movies'][str(MID)]['title'] == 'HISTORY FILM' and all(str(s['theatre_id']) in {str(k) for k in r['theatres']} for s in r['showtimes']))
    b = c.get('/api/discover/browse', query_string={'from': day(-25), 'to': day(6)}).json
    check("Browse still starts today (history is the Calendar's)", all(f['next']['start_time'] >= datetime.now().isoformat()[:10]
          for f in b['films'] if f['movie']['id'] == MID))

    print('--- warm-up ---')
    builds = []
    with app.test_request_context('/'):
        A._public_cache.clear()
        A.public_cached(('t',), lambda: builds.append(1) or 1)
        A.public_cached(('t',), lambda: builds.append(1) or 2)
    check('a public response is reused while fresh', len(builds) == 1)
    with app.test_request_context('/', headers={'X-Internal-Token': INTERNAL_API_TOKEN, 'X-Warm': '1'}):
        A.public_cached(('t',), lambda: builds.append(1) or 3)
    check('the warm-up (with the internal token) rebuilds it', len(builds) == 2)
    with app.test_request_context('/', headers={'X-Internal-Token': 'wrong', 'X-Warm': '1'}):
        A.public_cached(('t',), lambda: builds.append(1) or 4)
    check("…nobody else can force rebuilds", len(builds) == 2)
    urls = A._warm_urls(now.date())
    check('warm-up covers Discover, Browse and the Calendar views the site opens',
          urls[0] == '/api/discover' and any('calendar' in u and f'to={day(6)}' in u for u in urls) and any(f'to={day(13)}' in u for u in urls))
    for u in urls:
        r = c.get(u, headers={'X-Internal-Token': INTERNAL_API_TOKEN, 'X-Warm': '1'})
        if r.status_code != 200:
            break
    check('every warm-up URL answers', r.status_code == 200)
    checks.done()

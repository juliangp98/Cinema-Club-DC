"""R7b: the Calendar shows recent history and sends each film once; public
pages are kept warm (and only the warm-up may force a rebuild)."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db


@pytest.fixture
def history():
    """HISTORY FILM at AFI: 70, 20 and 3 days ago, and in 2, 3 and 4 days."""
    from app import app, db, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        now = datetime.now().replace(hour=19, minute=0, second=0, microsecond=0)
        m = Movie(title='HISTORY FILM', cast_json='[{"name": "Someone"}]', description='x' * 500)
        db.session.add(m)
        db.session.flush()
        for d in (-70, -20, -3, 2, 3, 4):
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=d)))
        db.session.commit()
        return {'movie': m.id, 'day': lambda n: (now + timedelta(days=n)).date().isoformat(), 'now': now}


def calendar(frm, to):
    return client().get('/api/discover/calendar', query_string={'from': frm, 'to': to}).json


def test_the_calendar_keeps_60_days_of_history(history):
    day, mid = history['day'], history['movie']
    assert len([s for s in calendar(day(-25), day(6))['showtimes'] if s['movie_id'] == mid]) == 5
    assert not [s for s in calendar(day(-80), day(-60))['showtimes'] if s['movie_id'] == mid]


def test_each_film_and_theatre_is_sent_once(history):
    day, mid = history['day'], str(history['movie'])
    r = calendar(day(-25), day(6))
    assert all('movie' not in s for s in r['showtimes'])
    assert r['movies'][mid]['title'] == 'HISTORY FILM'
    assert all(str(s['theatre_id']) in {str(k) for k in r['theatres']} for s in r['showtimes'])


def test_browse_still_starts_today(history):
    day = history['day']
    b = client().get('/api/discover/browse', query_string={'from': day(-25), 'to': day(6)}).json
    today = datetime.now().isoformat()[:10]
    assert all(f['next']['start_time'] >= today for f in b['films'] if f['movie']['id'] == history['movie'])


def test_only_the_warm_up_forces_a_rebuild():
    import app as A
    from app import app, INTERNAL_API_TOKEN
    builds = []
    with app.test_request_context('/'):
        A.public_cached(('t',), lambda: builds.append(1) or 1)
        A.public_cached(('t',), lambda: builds.append(1) or 2)
    assert len(builds) == 1                                         # reused while fresh
    with app.test_request_context('/', headers={'X-Internal-Token': INTERNAL_API_TOKEN, 'X-Warm': '1'}):
        A.public_cached(('t',), lambda: builds.append(1) or 3)
    assert len(builds) == 2                                         # the warm-up rebuilds
    with app.test_request_context('/', headers={'X-Internal-Token': 'wrong', 'X-Warm': '1'}):
        A.public_cached(('t',), lambda: builds.append(1) or 4)
    assert len(builds) == 2                                         # nobody else can


def test_the_warm_up_covers_the_pages_the_site_opens(history):
    import app as A
    day = history['day']
    urls = A._warm_urls('dc', history['now'].date())
    assert urls[0] == '/api/discover?city=dc' and all('city=dc' in u for u in urls)      # what the site asks for
    assert any('calendar' in u and f'to={day(6)}' in u for u in urls) and any(f'to={day(13)}' in u for u in urls)
    for u in urls:
        assert client().get(u, headers={**H, 'X-Warm': '1'}).status_code == 200, u

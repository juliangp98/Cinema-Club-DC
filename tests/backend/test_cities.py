"""Cities: every theatre is in one, a showtime is on its city's clock, and the
site sorts everything by city — public pages, clubs, alerts, calendars. The
second city here, Testville (Central time), exists only in these tests."""
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from helpers import H, client, setup_db

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def two_cities(monkeypatch):
    """DC (as always) plus Testville: one theatre (Testville House, downtown),
    a film playing there in 30 minutes (Testville's clock) and tomorrow, a DC
    member (Dee) and a Testville club with Tess, both wanting that film."""
    import cities
    import places
    tv = cities.City('testville', 'Testville', 'TV', 'America/Chicago', 'Testville-area', 41.88, -87.63, areas=(
        cities.Area('downtown', 'Downtown', r"\bdowntown\b"), cities.Area('northside', 'Northside', r"\bnorthside\b")),
        hint='The Loop is Downtown.')
    monkeypatch.setattr(cities, 'CITIES', cities.CITIES + [tv])
    monkeypatch.setitem(cities._BY_SLUG, 'testville', tv)
    from app import app, db, Group, GroupMembership, Movie, Showtime, Theatre, User, Watchlist
    setup_db()
    with app.app_context():
        house = Theatre(slug='tv-house', name='Testville House', short_name='TV HOUSE', city='testville',
                        area='downtown', color='#123456', is_active=True)
        film = Movie(title='PRAIRIE NOIR', release_year='1952')
        db.session.add_all([house, film])
        db.session.flush()
        soon = places.now_in('testville').replace(second=0, microsecond=0) + timedelta(minutes=30)
        db.session.add_all([Showtime(movie_id=film.id, theatre_id=house.id, start_time=soon),
                            Showtime(movie_id=film.id, theatre_id=house.id, start_time=soon + timedelta(days=1))])
        club = Group(name='Testville Club', slug='testville-club', city='testville', theatres='tv-house', is_public=True)
        db.session.add(club)
        db.session.flush()
        tess = User(name='Tess', email='tess@t.dev', is_active=True)
        dee = User(name='Dee', email='dee@t.dev', is_active=True)
        db.session.add_all([tess, dee])
        db.session.flush()
        db.session.add(GroupMembership(user_id=tess.id, group_id=club.id, status='active', role='admin'))
        db.session.add(GroupMembership(user_id=dee.id, group_id=1, status='active'))
        for u in (tess, dee):
            db.session.add(Watchlist(user_id=u.id, movie_id=film.id))
        db.session.commit()
        return {'house': house.id, 'film': film.id, 'soon': soon, 'club': club.id, 'tess': tess.id, 'dee': dee.id}


def titles(payload):
    return {m['title'] for m in payload['movies'].values()} if 'movies' in payload else set()


def test_the_cities_the_site_covers():
    setup_db()
    one = client().get('/api/cities').json
    assert [c['slug'] for c in one['cities']] == ['dc'] and one['multi'] is False      # one city: no city UI


def test_a_second_city_appears_once_it_has_theatres(two_cities):
    got = client().get('/api/cities').json
    assert [c['slug'] for c in got['cities']] == ['dc', 'testville'] and got['multi'] is True
    assert {a['key'] for a in got['cities'][1]['areas']} == {'downtown', 'northside'}
    house = next(t for t in client().get('/api/theatres').json if t['slug'] == 'tv-house')
    assert house['city'] == 'testville' and house['area_label'] == 'Downtown'


def test_a_showtime_is_on_its_citys_clock(two_cities):
    """Testville is an hour behind DC: its 30-minutes-from-now show has
    started by DC's clock, not by its own."""
    import places
    from app import app, db, Showtime
    with app.app_context():
        s = Showtime.query.filter_by(theatre_id=two_cities['house'], start_time=two_cities['soon']).one()
        assert places.now_in('dc') - places.now_in('testville') > timedelta(minutes=55)
        assert not places.has_started(s) and s.start_time < places.now_in('dc')
        assert s.id in {x.id for x in places.upcoming(Showtime.query)}
        assert places.starts_at(s).endswith(('-05:00', '-06:00'))                       # Central
        assert places.to_utc(s.start_time, 'testville') - s.start_time in (timedelta(hours=5), timedelta(hours=6))


def test_public_pages_show_the_viewers_city(two_cities):
    day = two_cities['soon'].date().isoformat()
    to = (two_cities['soon'] + timedelta(days=2)).date().isoformat()
    cal = lambda city: client().get('/api/discover/calendar', query_string={'from': day, 'to': to, 'city': city}).json
    assert 'PRAIRIE NOIR' in titles(cal('testville'))
    assert 'PRAIRIE NOIR' not in titles(cal('dc'))                                        # cached apart, too
    assert 'PRAIRIE NOIR' not in titles(cal(None))                                         # no city: the first
    film = client().get(f"/api/films/{two_cities['film']}").json                          # a film's page: every city
    assert {s['theatre']['city'] for s in film['showtimes']} == {'testville'} and film['showtimes'][0]['starts_at']
    overview = client().get('/api/theatres-overview').json
    assert {t['city'] for t in overview} == {'dc', 'testville'}


def test_a_clubs_theatres_and_clock_are_its_citys(two_cities):
    import places
    from app import app, db, Group
    r = client(two_cities['tess']).post('/api/groups', json={'name': 'Loop Club', 'city': 'testville'})
    assert r.status_code == 201 and r.json['city'] == 'testville' and r.json['theatres'] == ['tv-house']
    with app.app_context():
        g = db.session.get(Group, two_cities['club'])
        assert places.club_slugs(g) == {'tv-house'} and places.club_city(g) == 'testville'
        assert abs((places.club_now(g) - places.now_in('testville')).total_seconds()) < 5
    week = client(two_cities['tess']).get('/api/discover/browse',
                                          query_string={'group_id': two_cities['club'], 'when': 'week'}).json
    assert [f['movie']['title'] for f in week['films']] == ['PRAIRIE NOIR']
    assert client(two_cities['tess']).put('/api/groups/testville-club', json={'city': 'nowhere'}).status_code == 400
    assert client(two_cities['tess']).put('/api/groups/testville-club', json={'city': 'dc'}).json['city'] == 'dc'


def test_clubs_in_your_city_come_first(two_cities):
    listed = client(two_cities['tess']).get('/api/groups/discover', query_string={'city': 'testville'}).json['groups']
    assert listed[0]['city'] == 'testville'


def test_alerts_only_for_your_cities(two_cities):
    """Dee (a DC club) doesn't hear that Testville booked her watchlist film; Tess does."""
    import notify
    from app import app, db, Notification, Showtime, Theatre
    with app.app_context():
        house = db.session.get(Theatre, two_cities['house'])
        made = notify.alert_new_showings(house, Showtime.query.filter_by(theatre_id=house.id).all(), set())
        db.session.commit()
        assert made == 1 and {n.user_id for n in Notification.query.filter_by(kind='showings')} == {two_cities['tess']}


def test_your_own_city(two_cities):
    import places
    from app import app, db, User
    me = client(two_cities['dee'])
    assert me.put('/api/auth/profile', json={'city': 'testville'}).json['user']['city'] == 'testville'
    assert me.put('/api/auth/profile', json={'city': 'atlantis'}).json['user']['city'] is None     # unknown: unset
    with app.app_context():
        dee = db.session.get(User, two_cities['dee'])
        assert places.person_city(dee) == 'dc'                                          # her club's
        assert places.viewer_city(dee, None, 'testville') == 'testville'


def test_calendar_files_are_in_utc_from_the_theatres_city(two_cities):
    import ics
    import places
    from app import app
    with app.app_context():
        start = two_cities['soon']
        body = '\n'.join(ics.event('x', start, start + timedelta(hours=2), 'PRAIRIE NOIR', city='testville'))
        expect = places.to_utc(start, 'testville').strftime('%Y%m%dT%H%M%SZ')
        assert f'DTSTART:{expect}' in body


def test_saved_searches_remember_their_city(two_cities):
    r = client(two_cities['dee']).post('/api/searches', json={'params': {'genres': 'drama'}, 'city': 'testville'})
    assert r.status_code == 200
    from app import app, SavedSearch
    with app.app_context():
        assert SavedSearch.query.one().city == 'testville'


def test_the_bot_lists_the_clubs_theatres_first(two_cities):
    r = client().get('/api/internal/theatres', query_string={'group_id': two_cities['club']}, headers=H).json
    assert r['multi'] is True and r['city'] == 'testville'
    assert r['theatres'][0]['slug'] == 'tv-house' and r['theatres'][0]['yours']
    assert not any(t['yours'] for t in r['theatres'][1:])
    public = client().get('/api/internal/theatres', query_string={'city': 'testville'}, headers=H).json
    assert public['theatres'][0]['slug'] == 'tv-house'                                   # an unconnected server's city


# ─── The registry and the clock rule ──────────────────────────────────────────

def test_every_theatre_knows_its_city_and_area():
    import cities
    from scrapers import THEATRE_REGISTRY
    slugs, shorts = set(), set()
    colors = {}
    for cfg in THEATRE_REGISTRY:
        assert cities.get(cfg.city), cfg.slug
        assert cities.area(cfg.city, cfg.area), (cfg.slug, cfg.area)
        assert cfg.lat and cfg.lon, cfg.slug
        assert cfg.slug not in slugs and cfg.short_name not in shorts, cfg.slug          # unique site-wide
        slugs.add(cfg.slug)
        shorts.add(cfg.short_name)
        if cfg.enabled:
            assert cfg.color not in colors.setdefault(cfg.city, set()), cfg.slug        # distinct within a city
            colors[cfg.city].add(cfg.color)
    keys = [a.key for c in cities.CITIES for a in c.areas]
    assert len(keys) == len(set(keys))                                                   # area keys unique (URLs)


CLOCK = re.compile(r"\b(datetime\.)?(datetime\.now\(\)|date\.today\(\)|datetime\.today\(\))")


def test_nothing_reads_the_server_clock_but_places():
    """A showtime is on its city's clock, so "now" comes from places.py
    (now_in, now_at, club_now, person_now — or server_now for bookkeeping)."""
    found = []
    for folder in ('backend', 'bot'):
        for path in (ROOT / folder).rglob('*.py'):
            rel = path.relative_to(ROOT).as_posix()
            if any(part in rel for part in ('/venv/', '/.venv/', '__pycache__')) or rel == 'backend/places.py':
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if CLOCK.search(line.split('#')[0]):
                    found.append(f'{rel}:{n}: {line.strip()}')
    assert found == []

"""Watchlist any film (R8c): TMDB search on the site and in /watch, adding a
film no theatre has listed, and the alert when a theatre later books it."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db

STALKER = {'tmdb_id': 1398, 'title': 'Stalker', 'year': 1979, 'poster_url': 'https://image.tmdb.org/t/p/w185/s.jpg'}
DETAILS = {1398: {'tmdb_id': 1398, 'tmdb_title': 'Stalker', 'release_year': '1979', 'director': 'Andrei Tarkovsky',
                  'runtime_minutes': 162, 'poster_url': 'https://image.tmdb.org/t/p/w500/s.jpg', 'genres': 'drama,sci-fi'}}


@pytest.fixture
def tmdb(monkeypatch):
    """A fake TMDB that counts searches; Ana is signed up (email)."""
    import app as A
    import enrich
    setup_db()
    calls = []

    def search_list(q, limit=8):
        calls.append(q)
        return [STALKER] if 'stalk' in q.lower() else []
    monkeypatch.setattr(enrich, 'tmdb_search_list', search_list)
    monkeypatch.setattr(enrich, 'enrich_by_tmdb_id', lambda tid, title='': dict(DETAILS[tid]) if tid in DETAILS else None)
    monkeypatch.setattr(enrich, 'search_tmdb', lambda title, year=None: {'id': 1398} if 'stalk' in title.lower() else None)
    monkeypatch.setattr(A, 'send_email', lambda *a: None)
    with A.app.app_context():
        ana = A.User(name='Ana', email='ana@t.dev', is_active=True)
        A.db.session.add(ana)
        A.db.session.commit()
        return {'ana': ana.id, 'calls': calls}


def test_search_tmdb_on_the_site(tmdb):
    c = client(tmdb['ana'])
    r = c.get('/api/films/tmdb-search?q=stalker').json['results']
    assert r == [{**STALKER, 'movie_id': None}]
    c.get('/api/films/tmdb-search?q=Stalker')                       # cached: TMDB asked once
    assert tmdb['calls'] == ['stalker']
    assert client().get('/api/films/tmdb-search?q=stalker').status_code == 401


def test_searching_has_a_limit(tmdb, monkeypatch):
    import app as A
    monkeypatch.setattr(A, 'TMDB_SEARCHES_PER_HOUR', 2)
    c = client(tmdb['ana'])
    assert [c.get(f'/api/films/tmdb-search?q=film {i}').status_code for i in range(3)] == [200, 200, 429]


def test_opening_a_tmdb_film_adds_it_once(tmdb):
    c = client(tmdb['ana'])
    mid = c.post('/api/films/from-tmdb', json={'tmdb_id': 1398}).json['movie_id']
    assert c.post('/api/films/from-tmdb', json={'tmdb_id': 1398}).json['movie_id'] == mid
    page = client().get(f'/api/films/{mid}').json
    assert page['movie']['title'] == 'Stalker' and page['movie']['director'] == 'Andrei Tarkovsky'
    assert page['showtimes'] == []
    assert c.get('/api/films/tmdb-search?q=stalker').json['results'][0]['movie_id'] == mid
    assert c.post('/api/films/from-tmdb', json={'tmdb_id': 5}).status_code == 404


def test_a_watched_tmdb_film_alerts_when_a_theatre_books_it(tmdb, monkeypatch):
    import enrich
    import notify
    from scrapers import get_config
    from scrapers.base import new_movie_dict, make_showtime
    from scrapers.sync import sync_to_db
    c = client(tmdb['ana'])
    mid = c.post('/api/films/from-tmdb', json={'tmdb_id': 1398}).json['movie_id']
    c.post('/api/watchlist', json={'movie_id': mid})
    # Suns has been scraped before; now it lists "STALKER (35mm)", which TMDB identifies.
    monkeypatch.setattr(enrich, 'enrich_movie', lambda title, year=None, alternates=():
                        {**DETAILS[1398], 'matched_query': 'STALKER'} if 'STALKER' in title else None)
    from app import app, db, Movie, Showtime, Theatre
    with app.app_context():
        filler = Movie(title='FILLER')
        db.session.add(filler)
        db.session.flush()
        db.session.add(Showtime(movie_id=filler.id, theatre_id=Theatre.query.filter_by(slug='suns').first().id,
                                start_time=datetime.now() + timedelta(days=1)))
        db.session.commit()
    m = new_movie_dict()
    m['title'], m['showtimes'] = 'STALKER (35mm)', [make_showtime(datetime.now() + timedelta(days=5), 162)]
    f = new_movie_dict()
    f['title'], f['showtimes'] = 'FILLER', [make_showtime(datetime.now() + timedelta(days=1), 90)]
    sync_to_db(get_config('suns'), [m, f])
    notify.release()
    items = c.get('/api/notifications').json['items']
    assert [(i['headline'], i['movie_id']) for i in items] == [('Stalker is playing', mid)]


def test_watch_any_film_from_discord(tmdb):
    from app import app, User
    with app.app_context():
        from app import db
        db.session.add(User(name='Dee', discord_user_id='8801', is_active=True))
        db.session.commit()
    found = client().get('/api/internal/films/find?q=stalker', headers=H).json
    assert found == [{'name': 'Stalker (1979)', 'value': 'tmdb:1398'}]
    r = client().post('/api/internal/watch', headers=H, json={'discord_user_id': '8801', 'title': 'tmdb:1398', 'action': 'add'}).json
    assert r['watching'] is True and r['movie_title'] == 'Stalker'
    found = client().get('/api/internal/films/find?q=stalker', headers=H).json
    assert found[0]['value'].startswith('movie:')                   # ours now
    typed = client().post('/api/internal/watch', headers=H,
                          json={'discord_user_id': '8801', 'title': 'stalker', 'action': 'remove'}).json
    assert typed['watching'] is False

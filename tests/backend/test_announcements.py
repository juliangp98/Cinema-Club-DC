"""Films announced before tickets (R8b): reading Suns' film posts, keeping
the ones not on sale yet, showing them, and alerting watchers when they're
announced and when tickets go on sale."""
from datetime import date, datetime, timedelta

import pytest

from helpers import client, setup_db


def post(title, day, **kw):
    """A dated film as scrape_suns_announced returns it."""
    from scrapers.base import new_movie_dict
    m = new_movie_dict()
    m.update(title=title, announced_for=day, url=f'https://sunscinema.com/movies/{title.lower()}/',
             release_year='1975', director='Ray Marsh', **kw)
    return m


@pytest.fixture
def world(monkeypatch):
    """Ana (email) watches LORD SHANGO; Bo watches it but turned on-sale alerts
    off. Suns already sells tickets for ON SALE NOW."""
    import app as A
    from scrapers.base import normalize_title
    setup_db()
    monkeypatch.setattr(A, 'send_email', lambda *a: None)
    with A.app.app_context():
        suns = A.Theatre.query.filter_by(slug='suns').first()
        shango = A.Movie(title='LORD SHANGO', release_year='1975', title_normalized=normalize_title('LORD SHANGO'))
        selling = A.Movie(title='ON SALE NOW', release_year='1990', title_normalized=normalize_title('ON SALE NOW'))
        A.db.session.add_all([shango, selling])
        A.db.session.flush()
        A.db.session.add(A.Showtime(movie_id=selling.id, theatre_id=suns.id, start_time=datetime.now() + timedelta(days=3)))
        ana = A.User(name='Ana', email='ana@t.dev', is_active=True)
        bo = A.User(name='Bo', email='bo@t.dev', is_active=True, notify_prefs='{"types": {"on_sale": false}}')
        A.db.session.add_all([ana, bo])
        A.db.session.flush()
        for u in (ana, bo):
            A.db.session.add(A.Watchlist(user_id=u.id, movie_id=shango.id))
        A.db.session.commit()
        return {'ana': ana.id, 'bo': bo.id, 'shango': shango.id, 'soon': date.today() + timedelta(days=12)}


def announce(*items):
    from scrapers import get_config
    from scrapers.sync import sync_announced
    import notify
    n = sync_announced(get_config('suns'), list(items))
    notify.release()
    return n


def heads(uid):
    return [(i['kind'], i['headline']) for i in client(uid).get('/api/notifications').json['items']]


def test_announced_films_are_kept_shown_and_alerted(world):
    soon = world['soon']
    assert announce(post('LORD SHANGO', soon), post('BRAND NEW FILM', soon + timedelta(days=2)),
                    post('ON SALE NOW', soon), post('OLD NEWS', date.today() - timedelta(days=1))) == 2
    shown = client().get('/api/discover').json['announced']
    assert [(a['movie']['title'], a['date'], a['theatre']['slug']) for a in shown] == [
        ('LORD SHANGO', soon.isoformat(), 'suns'), ('BRAND NEW FILM', (soon + timedelta(days=2)).isoformat(), 'suns')]
    page = client().get(f"/api/films/{world['shango']}").json
    assert page['announced'][0]['url'] == 'https://sunscinema.com/movies/lord shango/' and page['showtimes'] == []
    assert heads(world['ana']) == [('announced', 'LORD SHANGO is coming')]
    item = client(world['ana']).get('/api/notifications').json['items'][0]
    assert item['detail'] == f"Suns Cinema · {soon.strftime('%a, %b %-d')} · tickets not on sale yet"
    assert announce(post('LORD SHANGO', soon)) == 0                  # seen again: no repeat
    assert len(heads(world['ana'])) == 1


def test_tickets_going_on_sale(world):
    from scrapers import get_config
    from scrapers.base import new_movie_dict, make_showtime
    from scrapers.sync import sync_to_db
    import notify
    soon = world['soon']
    announce(post('LORD SHANGO', soon))
    m = new_movie_dict()
    m['title'] = 'LORD SHANGO'
    start = datetime.combine(soon, datetime.min.time()) + timedelta(hours=19)
    m['showtimes'] = [make_showtime(start, 92), make_showtime(start + timedelta(hours=2), 92)]
    keep = new_movie_dict()
    keep['title'], keep['showtimes'] = 'ON SALE NOW', [make_showtime(datetime.now() + timedelta(days=3), 90)]
    sync_to_db(get_config('suns'), [m, keep])
    notify.release()
    assert heads(world['ana'])[0] == ('on_sale', 'Tickets on sale: LORD SHANGO')     # not also "is playing"
    assert [k for k, _ in heads(world['ana'])] == ['on_sale', 'announced']
    assert [k for k, _ in heads(world['bo'])] == ['announced']                        # turned on-sale alerts off
    assert client().get('/api/discover').json['announced'] == []
    assert announce(post('LORD SHANGO', soon)) == 0                                   # the same post, now on sale


def test_reading_suns_posts(monkeypatch):
    from scrapers import suns
    stamp = int(datetime(2026, 10, 26, 0, 0, tzinfo=suns.ET).timestamp())
    posts = [
        {'status': 'publish', '_start_date': str(stamp), 'title': {'rendered': 'GANJA &amp; HESS &#8211; FUNDRAISER'},
         'link': 'https://sunscinema.com/movies/ganja/', '_tmdb_id': '28', '_release_date': '1973-04-20', '_length': '110',
         'director': [{'name': 'Bill Gunn'}], 'cast': [{'name': 'Duane Jones'}, {'name': 'Marlene Clark'}],
         'featured_media_url': 'https://img/ganja.jpg', 'content': {'rendered': '<p>A <em>landmark</em>.</p>'}},
        {'status': 'publish', '_start_date': '', 'title': {'rendered': '28 YEARS LATER'}},      # undated: skipped
        {'status': 'draft', '_start_date': str(stamp), 'title': {'rendered': 'NOT YET'}},
    ]
    monkeypatch.setattr(suns, 'get_json', lambda session, url, **kw: posts if kw['params']['page'] == 1 else [])
    [m] = suns.scrape_suns_announced()
    assert m['title'] == 'GANJA & HESS – FUNDRAISER' and m['announced_for'] == date(2026, 10, 26)
    assert (m['tmdb_id'], m['release_year'], m['runtime_minutes']) == (28, '1973', 110)
    assert m['director'] == 'Bill Gunn' and m['starring'] == 'Duane Jones, Marlene Clark'
    assert m['description'] == 'A landmark.'

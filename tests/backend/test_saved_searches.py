"""Saved-search alerts (R10a): save any Browse search; after a scrape run, a
film that newly fits it (at a theatre) makes one alert — never for what
already fit when it was saved, never twice, and only where the person said."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db

ON_FILM_AT_AFI = {'format': 'film', 'theatres': 'afi'}


@pytest.fixture
def world():
    """Ana in club 1 (Discord linked, email); Gus is a guest. Already playing:
    OLD PRINT on 35mm at AFI in 3 days."""
    from app import app, db, User, GroupMembership, Theatre
    setup_db()
    with app.app_context():
        ana = User(email='ana@r10.test', name='Ana', is_active=True, discord_user_id='9301')
        gus = User(name='Gus', is_active=True, is_guest=True)
        db.session.add_all([ana, gus])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active'))
        ids = {'ana': ana.id, 'gus': gus.id, 'afi': Theatre.query.filter_by(slug='afi').first().id,
               'suns': Theatre.query.filter_by(slug='suns').first().id}
        db.session.commit()
    ids['old'] = book('OLD PRINT', 'afi', days=3, fmt='35mm')
    return ids


def book(title, theatre, days, fmt=None, year='1975'):
    """A theatre books a film (as a scrape would). Returns the movie id."""
    from app import app, db, Movie, Showtime, Theatre
    with app.app_context():
        m = Movie.query.filter_by(title=title).first() or Movie(title=title, release_year=year)
        db.session.add(m)
        db.session.flush()
        th = Theatre.query.filter_by(slug=theatre).first()
        db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, format_label=fmt,
                                start_time=(datetime.now() + timedelta(days=days)).replace(hour=19, minute=30, second=0, microsecond=0)))
        db.session.commit()
        return m.id


def save(w, params=ON_FILM_AT_AFI, who='ana', group_id=1):
    return client(w[who]).post('/api/searches', json={'params': params, 'group_id': group_id})


def run_alerts():
    import notify
    return notify.alert_saved_searches()


def alerts(uid):
    from app import app, Notification
    with app.app_context():
        return [(n.kind, n.movie.title, n.channels) for n in Notification.query.filter_by(user_id=uid).order_by(Notification.id)]


# ── saving ──

def test_a_saved_search_is_tidied_and_labelled(world):
    r = save(world, {'theatres': 'AFI', 'format': 'film', 'when': 'week', 'sort': 'soonest', 'club': 'going'})
    assert r.status_code == 200
    s = r.json['search']
    assert s['params'] == {'format': 'film', 'theatres': 'afi'}                 # no window, sort or "the club"
    assert s['label'] == 'On film · AFI' and s['path'].startswith('/browse?')
    assert r.json['fitting_now'] == 1 and r.json['alert_prompt'] is True        # the one-time "how should we tell you?"
    again = save(world, {'format': 'film', 'theatres': 'afi'})
    assert again.json['search']['id'] == s['id'] and again.json['alert_prompt'] is False   # the same search is one


def test_labels_name_every_filter(world):
    s = save(world, {'genres': 'horror', 'time': 'late', 'rarity': 'repertory', 'decade': '1970'}).json['search']
    assert s['label'] == 'Horror · 1970s · Late nights · Repertory'


def test_what_cant_be_saved(world):
    assert save(world, {'when': 'week', 'sort': 'rarest'}).status_code == 400   # no filter at all
    assert save(world, who='gus').status_code == 403                             # guests can't get alerts
    for i in range(10):
        assert save(world, {'q': f'film {i}'}).status_code == 200
    r = save(world, {'q': 'one too many'})
    assert r.status_code == 400 and 'up to 10' in r.json['error']


def test_a_club_you_left_means_every_theatre(world):
    from app import app, db, Group
    with app.app_context():
        g = Group(name='Elsewhere', slug='elsewhere-r10', is_public=False)
        db.session.add(g)
        db.session.commit()
        gid = g.id
    assert save(world, group_id=gid).json['search']['group_id'] is None


def test_listing_and_removing(world):
    sid = save(world).json['search']['id']
    assert [s['id'] for s in client(world['ana']).get('/api/searches').json] == [sid]
    assert [s['id'] for s in client(world['ana']).get('/api/me/notifications').json['searches']] == [sid]
    assert client(world['gus']).delete(f'/api/searches/{sid}').status_code == 404     # only your own
    assert client(world['ana']).delete(f'/api/searches/{sid}').status_code == 200
    assert client(world['ana']).get('/api/searches').json == []


def test_removing_from_discord(world):
    sid = save(world).json['search']['id']
    r = client().post('/api/internal/notifications/settings', headers=H,
                      json={'discord_user_id': '9301', 'remove_search': sid})
    assert r.status_code == 200 and r.json['searches'] == []


# ── alerts ──

def test_what_already_fit_never_alerts(world):
    save(world)
    assert run_alerts() == 0 and alerts(world['ana']) == []


def test_a_newly_booked_film_that_fits_alerts_once(world):
    import notify
    from app import app, Notification
    save(world)
    book('NEW PRINT', 'afi', days=10, fmt='70mm')
    book('NEW PRINT', 'afi', days=11, fmt='70mm')
    assert run_alerts() == 1
    assert alerts(world['ana']) == [('search', 'NEW PRINT', '')]                 # the bell only: no channel chosen
    with app.app_context():
        d = notify.describe(Notification.query.filter_by(kind='search').first())
    assert d['headline'] == 'New: NEW PRINT' and d['detail'].startswith('Fits “On film · AFI” · AFI Silver Theatre · ')
    assert '+1 more' in d['detail'] and d['detail'].endswith('70mm')
    assert run_alerts() == 0                                                     # never twice


def test_films_that_dont_fit_stay_quiet(world):
    save(world)
    book('DIGITAL ONLY', 'afi', days=5)                                          # not on film
    book('SUNS PRINT', 'suns', days=5, fmt='35mm')                               # another theatre
    assert run_alerts() == 0


def test_a_film_fitting_two_searches_alerts_once(world):
    save(world)
    save(world, {'format': 'film'})
    book('NEW PRINT', 'afi', days=10, fmt='35mm')
    assert run_alerts() == 1


def test_no_second_alert_after_a_watchlist_one(world):
    from app import app, db, Notification
    save(world)
    mid = book('NEW PRINT', 'afi', days=10, fmt='35mm')
    with app.app_context():
        db.session.add(Notification(user_id=world['ana'], kind='showings', movie_id=mid, theatre_id=world['afi']))
        db.session.commit()
    assert run_alerts() == 0


def test_alerts_follow_the_notification_setting(world):
    c = client(world['ana'])
    save(world)
    c.put('/api/me/notifications', json={'channels': {'discord': True}})
    book('FIRST', 'afi', days=10, fmt='35mm')
    run_alerts()
    c.put('/api/me/notifications', json={'types': {'searches': False}})
    book('SECOND', 'afi', days=12, fmt='35mm')
    run_alerts()
    assert alerts(world['ana']) == [('search', 'FIRST', 'discord')]              # off: nothing for SECOND


def test_a_film_back_after_a_while_alerts_again(world):
    from app import app, db, SavedSearchHit, Showtime
    save(world)
    with app.app_context():
        Showtime.query.filter_by(movie_id=world['old']).delete()                # OLD PRINT's run ended…
        SavedSearchHit.query.update({'seen_at': datetime.utcnow() - timedelta(days=4)})
        db.session.commit()
    assert run_alerts() == 0
    book('OLD PRINT', 'afi', days=20, fmt='35mm')                               # …and it's booked again
    assert run_alerts() == 1


def test_bundles_name_what_they_hold():
    import notify
    from types import SimpleNamespace as N
    assert notify.bundle_title([N(kind='showings'), N(kind='on_sale')]) == '2 updates on your watchlist'
    assert notify.bundle_title([N(kind='showings'), N(kind='search')]) == '2 new alerts'

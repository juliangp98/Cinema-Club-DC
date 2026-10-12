"""Personal alerts (R8a): one notification setting per person, the
"your watchlist film is playing" alert from a scrape, the bell, and bundled
delivery by email and Discord DM."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db


def scraped(title, *starts, fmt=None):
    from scrapers.base import new_movie_dict, make_showtime
    m = new_movie_dict()
    m['title'], m['runtime_minutes'] = f'{title} ({fmt})' if fmt else title, 100   # venues bill the format in the title
    m['showtimes'] = [make_showtime(s, 100) for s in starts]
    return m


@pytest.fixture
def world(monkeypatch):
    """Suns has been scraped before (PAST FILM is running); Ana (Discord) and
    Bo (email) watch STALKER; Cy watches it but turned that alert off."""
    import app as A
    setup_db()
    sent = []
    monkeypatch.setattr(A, 'send_email', lambda to, subject, body: sent.append((to, subject, body)))
    with A.app.app_context():
        suns = A.Theatre.query.filter_by(slug='suns').first()
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)
        from scrapers.base import normalize_title
        stalker = A.Movie(title='STALKER', release_year='1979', title_normalized=normalize_title('STALKER'))
        running = A.Movie(title='PAST FILM', release_year='2001', title_normalized=normalize_title('PAST FILM'))
        A.db.session.add_all([stalker, running])
        A.db.session.flush()
        A.db.session.add(A.Showtime(movie_id=running.id, theatre_id=suns.id, start_time=day + timedelta(hours=18)))
        ana = A.User(name='Ana', discord_user_id='9001', is_active=True)
        bo = A.User(name='Bo', email='bo@t.dev', is_active=True)
        cy = A.User(name='Cy', email='cy@t.dev', is_active=True, notify_prefs='{"types": {"showings": false}}')
        A.db.session.add_all([ana, bo, cy])
        A.db.session.flush()
        for u in (ana, bo, cy):
            A.db.session.add(A.Watchlist(user_id=u.id, movie_id=stalker.id))
        A.db.session.add(A.Watchlist(user_id=bo.id, movie_id=running.id))
        A.db.session.commit()
        return {'day': day, 'ana': ana.id, 'bo': bo.id, 'cy': cy.id, 'stalker': stalker.id}


def scrape_suns(*movies):
    from scrapers import get_config
    from scrapers.sync import sync_to_db
    import notify
    sync_to_db(get_config('suns'), list(movies))
    return notify.release()


def alerts(uid):
    return client(uid).get('/api/notifications').json


def test_default_channels_follow_the_account():
    import app as A
    import notify
    setup_db()
    with A.app.app_context():
        discord = A.User(name='D', discord_user_id='1')
        both = A.User(name='B', discord_user_id='2', email='b@t.dev')
        mail = A.User(name='M', email='m@t.dev')
        assert notify.prefs(discord)['channels'] == {'discord': True, 'email': False, 'push': False}
        assert notify.prefs(both)['channels'] == {'discord': True, 'email': False, 'push': False}
        assert notify.prefs(mail)['channels'] == {'discord': False, 'email': True, 'push': False}
        notify.set_prefs(mail, {'channels': {'discord': True, 'email': False}, 'types': {'bogus': True}})
        assert notify.prefs(mail)['channels'] == {'discord': False, 'email': False, 'push': False}   # no Discord to DM
        assert notify.prefs(mail)['types'] == {'showings': True, 'on_sale': True, 'attendance': True}


def test_a_booked_watchlist_film_alerts_its_watchers_once(world):
    d = world['day']
    emailed = scrape_suns(scraped('STALKER', d + timedelta(hours=19), d + timedelta(days=1, hours=19), fmt='35mm'),
                          scraped('PAST FILM', d + timedelta(hours=18), d + timedelta(days=3, hours=18)))
    ana, bo = alerts(world['ana']), alerts(world['bo'])
    assert ana['unread'] == 1 and ana['items'][0]['headline'] == 'STALKER is playing'
    assert 'Suns' in ana['items'][0]['detail'] and '+1 more' in ana['items'][0]['detail'] and '35mm' in ana['items'][0]['detail']
    assert [i['title'] for i in bo['items']] == ['STALKER']        # PAST FILM was already running: not news
    assert alerts(world['cy'])['items'] == []                        # turned that alert off
    assert emailed == 1                                              # Bo (email); Ana is on Discord

    # The next run adds more STALKER times: no new alert.
    scrape_suns(scraped('STALKER', d + timedelta(hours=19), d + timedelta(days=1, hours=19), d + timedelta(days=4, hours=19)))
    assert alerts(world['ana'])['unread'] == 1


def test_email_is_one_bundle_per_run(world, monkeypatch):
    import app as A
    sent = []
    monkeypatch.setattr(A, 'send_email', lambda to, subject, body: sent.append((to, subject, body)))
    with A.app.app_context():
        mirror = A.Movie(title='MIRROR', release_year='1975')
        A.db.session.add(mirror)
        A.db.session.flush()
        A.db.session.add(A.Watchlist(user_id=world['bo'], movie_id=mirror.id))
        A.db.session.commit()
    d = world['day']
    scrape_suns(scraped('STALKER', d + timedelta(hours=19)), scraped('MIRROR', d + timedelta(hours=21)),
                scraped('PAST FILM', d + timedelta(hours=18)))
    assert [(to, subject) for to, subject, _ in sent] == [('bo@t.dev', '2 updates on your watchlist')]
    assert 'STALKER is playing' in sent[0][2] and 'MIRROR is playing' in sent[0][2]
    assert 'https://cinemaclubdc.com/films/' in sent[0][2]


def test_discord_dms_wait_for_the_run_then_go_once(world):
    from app import app, db, Notification
    d = world['day']
    from scrapers import get_config
    from scrapers.sync import sync_to_db
    sync_to_db(get_config('suns'), [scraped('STALKER', d + timedelta(hours=19)), scraped('PAST FILM', d + timedelta(hours=18))])
    assert client().get('/api/internal/notifications/dm', headers=H).json == []      # run not finished
    import notify
    notify.release()
    dms = client().get('/api/internal/notifications/dm', headers=H).json
    assert [x['discord_user_id'] for x in dms] == ['9001']
    assert dms[0]['items'][0]['headline'] == 'STALKER is playing'
    assert dms[0]['items'][0]['url'].startswith('https://cinemaclubdc.com/films/')
    client().post('/api/internal/notifications/dm-sent', json={'ids': dms[0]['ids']}, headers=H)
    assert client().get('/api/internal/notifications/dm', headers=H).json == []
    with app.app_context():                     # a run that crashed before release still goes out later
        db.session.add(Notification(user_id=world['ana'], kind='showings', movie_id=world['stalker'],
                                    payload_json='{"title": "LATE"}', channels='discord',
                                    created_at=datetime.utcnow() - timedelta(hours=1)))
        db.session.commit()
    assert [i['headline'] for x in client().get('/api/internal/notifications/dm', headers=H).json
            for i in x['items']] == ['LATE is playing']


def test_the_bell_marks_read(world):
    d = world['day']
    scrape_suns(scraped('STALKER', d + timedelta(hours=19)), scraped('PAST FILM', d + timedelta(hours=18)))
    c = client(world['ana'])
    assert c.get('/api/notifications?count=1').json == {'unread': 1}
    c.post('/api/notifications/read', json={})
    assert c.get('/api/notifications?count=1').json == {'unread': 0}
    assert c.get('/api/notifications').json['items'][0]['read'] is True
    assert client().get('/api/notifications').status_code == 401


def test_settings_on_the_site_and_in_discord(world):
    c = client(world['bo'])
    s = c.get('/api/me/notifications').json
    assert s['channels']['email'] is True and s['available'] == {'discord': False, 'email': True, 'push': False}
    s = c.put('/api/me/notifications', json={'types': {'showings': False}}).json
    assert s['types']['showings'] is False and s['channels']['email'] is True
    r = client().post('/api/internal/notifications/settings', headers=H,
                      json={'discord_user_id': '9001', 'channels': {'discord': False}}).json
    assert r['channels']['discord'] is False
    assert client().post('/api/internal/notifications/settings', headers=H,
                         json={'discord_user_id': '424242'}).status_code == 404


def test_attendance_dms_follow_the_setting(world):
    import app as A
    with A.app.app_context():
        st = A.Showtime(movie_id=world['stalker'], theatre_id=A.Theatre.query.filter_by(slug='suns').first().id,
                        start_time=datetime.now() - timedelta(hours=6), end_time=datetime.now() - timedelta(hours=4))
        A.db.session.add(st)
        A.db.session.flush()
        A.db.session.add(A.RSVP(user_id=world['ana'], showtime_id=st.id, status='going'))
        A.db.session.commit()
    ask = lambda: [p['discord_user_id'] for p in client().get('/api/internal/attendance/prompts', headers=H).json]
    assert ask() == ['9001']
    client(world['ana']).put('/api/me/notifications', json={'types': {'attendance': False}})
    assert ask() == []

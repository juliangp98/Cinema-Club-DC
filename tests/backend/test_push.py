"""Web push (R8d): turning it on for a device, alerts going out as one push
per person per run, and devices that went away being forgotten."""
import json
from types import SimpleNamespace

import pytest

from helpers import client, setup_db

SUB = {'endpoint': 'https://push.example/abc', 'keys': {'p256dh': 'BKEY', 'auth': 'AUTH'}}


@pytest.fixture
def pushy(monkeypatch):
    """Push set up on the server; a fake push service that records what it's
    sent (and answers 410 Gone for endpoints ending in /gone)."""
    import app as A
    import pywebpush
    setup_db()
    monkeypatch.setattr(A, 'VAPID_PUBLIC_KEY', 'PUBLICKEY')
    monkeypatch.setattr(A, 'VAPID_PRIVATE_KEY', 'PRIVATEKEY')
    monkeypatch.setattr(A, 'send_email', lambda *a: None)
    sent = []

    def webpush(subscription_info, data, **kw):
        if subscription_info['endpoint'].endswith('/gone'):
            raise pywebpush.WebPushException('gone', response=SimpleNamespace(status_code=410))
        sent.append((subscription_info['endpoint'], json.loads(data)))
    monkeypatch.setattr(pywebpush, 'webpush', webpush)
    with A.app.app_context():
        u = A.User(name='Ana', email='ana@t.dev', is_active=True)
        A.db.session.add(u)
        A.db.session.commit()
        return {'ana': u.id, 'sent': sent}


def alert(uid, title):
    from app import app, db, Notification
    import notify
    with app.app_context():
        user = db.session.get(__import__('app').User, uid)
        notify._make(db, Notification, user, 'showings', None, None,
                     {'title': title, 'theatre': 'Suns Cinema', 'first': '2026-10-20T19:00:00', 'count': 1})
        db.session.commit()


def test_push_is_only_offered_when_set_up(monkeypatch):
    import app as A
    setup_db()
    monkeypatch.setattr(A, 'VAPID_PUBLIC_KEY', '')
    assert client().get('/api/push/key').json == {'key': None}
    with A.app.app_context():
        u = A.User(name='Bo', email='bo@t.dev', is_active=True)
        A.db.session.add(u)
        A.db.session.commit()
        uid = u.id
    s = client(uid).get('/api/me/notifications').json
    assert s['push_ready'] is False and s['channels']['push'] is False
    assert client(uid).post('/api/push/subscribe', json=SUB).status_code == 400


def test_turning_push_on_and_getting_alerts(pushy):
    import notify
    c = client(pushy['ana'])
    assert c.get('/api/push/key').json == {'key': 'PUBLICKEY'}
    s = c.post('/api/push/subscribe', json=SUB).json
    assert s['available']['push'] is True and s['channels']['push'] is True and s['channels']['email'] is False
    alert(pushy['ana'], 'STALKER')
    alert(pushy['ana'], 'MIRROR')
    notify.release()
    assert pushy['sent'] == [('https://push.example/abc', {
        'title': '2 updates on your watchlist', 'body': 'STALKER is playing · MIRROR is playing',
        'url': '/?alerts=1', 'tag': pushy['sent'][0][1]['tag']})]
    notify.release()
    assert len(pushy['sent']) == 1                                   # never twice
    assert c.post('/api/push/test').json == {'sent': 1}
    assert pushy['sent'][-1][1]['title'] == 'Push is on 🎬'


def test_one_alert_links_to_its_film_and_gone_devices_are_forgotten(pushy):
    import notify
    from app import app, PushSubscription
    c = client(pushy['ana'])
    c.post('/api/push/subscribe', json=SUB)
    c.post('/api/push/subscribe', json={**SUB, 'endpoint': 'https://push.example/gone'})
    alert(pushy['ana'], 'STALKER')
    notify.release()
    assert [(e, m['title'], m['url']) for e, m in pushy['sent']] == [('https://push.example/abc', 'STALKER is playing', '/')]
    with app.app_context():
        assert [s.endpoint for s in PushSubscription.query.all()] == ['https://push.example/abc']
    s = c.post('/api/push/unsubscribe', json={'endpoint': SUB['endpoint']}).json
    assert s['available']['push'] is False and s['channels']['push'] is False

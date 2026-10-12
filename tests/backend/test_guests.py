"""R5b guest profiles: made on a visitor's first personal action, private
personal plans, anonymous counts (accounts only), staying out of clubs,
keeping the profile (email, an existing account, Discord), expiry."""
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from helpers import setup_db


def browser(uid=None, ip='198.51.100.1'):
    """A test client from a given address (as Cloudflare reports it)."""
    from app import app
    c = app.test_client()
    c.environ_base['HTTP_CF_CONNECTING_IP'] = ip
    if uid:
        with c.session_transaction() as s:
            s['user_id'] = uid
            s['seen'] = int(time.time())
    return c


@pytest.fixture
def world():
    """Club G (public) with its admin Olive (Discord 313131), who's going to
    GUEST FILM ONE and wants GUEST FILM TWO; three other accounts."""
    from app import app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Club G', slug='club-g-r5b', is_public=True)
        db.session.add(g)
        db.session.flush()
        owner = User(email='owner@r5b.test', name='Olive Owner', is_active=True, discord_user_id='313131')
        accts = [User(email=f'a{i}@r5b.test', name=f'Acct {i}', is_active=True) for i in range(3)]
        db.session.add_all([owner, *accts])
        db.session.flush()
        db.session.add(GroupMembership(user_id=owner.id, group_id=g.id, status='active', role='admin'))
        now = datetime.now()
        films = [Movie(title=t, release_year='2024') for t in ('GUEST FILM ONE', 'GUEST FILM TWO')]
        db.session.add_all(films)
        db.session.flush()
        s1 = Showtime(movie_id=films[0].id, theatre_id=th.id, start_time=now + timedelta(days=2))
        s2 = Showtime(movie_id=films[1].id, theatre_id=th.id, start_time=now + timedelta(days=3))
        db.session.add_all([s1, s2])
        db.session.flush()
        db.session.add(RSVP(user_id=owner.id, showtime_id=s1.id, group_id=g.id, status='going'))
        db.session.add(Watchlist(user_id=owner.id, movie_id=films[1].id))
        db.session.commit()
        return {'group': g.id, 'owner': owner.id, 's1': s1.id, 's2': s2.id, 'm1': films[0].id, 'm2': films[1].id,
                'accts': [a.id for a in accts]}


@pytest.fixture
def guest(world):
    """A visitor who became a guest and is going to GUEST FILM ONE."""
    v = browser()
    gu = v.post('/api/auth/guest').json['user']
    v.post('/api/rsvp', json={'showtime_id': world['s1'], 'status': 'going'})
    return {**world, 'v': v, 'guest': gu}


def test_a_guest_profile_is_made_once(world):
    from app import app, db, User
    v = browser()
    r = v.post('/api/auth/guest')
    gu = r.json['user']
    assert r.status_code == 201 and gu['is_guest'] and gu['name'] == 'Guest' and gu['email'] is None
    assert v.get('/api/auth/me').json['user']['id'] == gu['id']                     # signed in
    assert v.post('/api/auth/guest').json['user']['id'] == gu['id']                 # the same one next time
    with app.app_context():
        stored = db.session.get(User, gu['id']).guest_ip_hash
        assert stored and '198.51.100.1' not in stored and len(stored) == 64        # only a keyed hash of the address


def test_guest_creation_is_capped_per_visitor(world):
    assert [browser(ip='203.0.113.50').post('/api/auth/guest').status_code for _ in range(6)] == [201] * 5 + [429]
    assert browser(ip='203.0.113.51').post('/api/auth/guest').status_code == 201


def test_personal_plans_are_private(guest):
    v, S1 = guest['v'], guest['s1']
    r = v.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going'})
    assert r.json['user_rsvp'] == 'going' and r.json['public'] and r.json['attendees'] == []
    assert v.get(f'/api/showtimes/{S1}').json['user_rsvp'] == 'going'
    assert browser().get(f'/api/showtimes/{S1}').json['user_rsvp'] is None
    club = browser(guest['owner']).get(f'/api/showtimes/{S1}', query_string={'group_id': guest['group']}).json
    assert [a['name'] for a in club['attendees']] == ['Olive Owner']                    # never in a club's lists
    assert [i['showtime_id'] for i in v.get(f"/api/users/{guest['guest']['id']}/rsvps").json['items']] == [S1]
    assert browser(guest['owner']).get(f"/api/users/{guest['guest']['id']}/rsvps").status_code == 403
    mine = v.get('/api/discover/browse', query_string={'when': '2weeks', 'club': 'mine'}).json['films']
    assert [c['movie']['title'] for c in mine] == ['GUEST FILM ONE']


def test_guest_watchlists_and_no_names_in_next_showings(guest):
    guest['v'].post('/api/watchlist', json={'movie_id': guest['m2']})
    assert any(i['movie']['id'] == guest['m2'] for i in guest['v'].get('/api/watchlist').json)
    wl = browser(guest['owner']).get('/api/watchlist').json
    assert all(i['next_showtime']['attendees'] == [] for i in wl if i['next_showtime'])


def test_anonymous_counts_come_from_accounts_only(guest):
    S2 = guest['s2']
    for ip in ('192.0.2.1', '192.0.2.2', '192.0.2.3'):
        c = browser(ip=ip)
        c.post('/api/auth/guest')
        c.post('/api/rsvp', json={'showtime_id': S2, 'status': 'going'})
        c.post('/api/reactions', json={'showtime_id': S2, 'emoji': '🔥'})
    st = browser().get(f'/api/showtimes/{S2}').json
    assert st['interest']['going'] is None and st['reactions'] == {}                   # 3 guests: no count
    for uid in guest['accts']:
        c = browser(uid)
        c.post('/api/rsvp', json={'showtime_id': S2, 'status': 'going'})
        c.post('/api/reactions', json={'showtime_id': S2, 'emoji': '🔥'})
    st = browser().get(f'/api/showtimes/{S2}').json
    assert st['interest']['going'] == 3 and st['reactions'] == {'🔥': {'count': 3, 'users': [], 'user_reacted': False}}
    r = guest['v'].post('/api/reactions', json={'showtime_id': S2, 'emoji': '🍿'}).json
    assert r['🍿'] == {'count': None, 'users': [], 'user_reacted': True} and r['🔥']['count'] == 3


def test_guests_stay_out_of_clubs(guest):
    v = guest['v']
    assert v.post('/api/groups', json={'name': 'Guest club'}).json.get('code') == 'guest'
    assert v.post('/api/groups/club-g-r5b/join').status_code == 403
    assert v.post('/api/me/discord-link-code').status_code == 403
    assert v.get(f"/api/showtimes/{guest['s1']}", query_string={'group_id': guest['group']}).status_code == 403


@pytest.fixture
def emails(monkeypatch):
    """Sign-in emails captured instead of sent: returns the token of the last one."""
    import app as A
    sent = {}
    monkeypatch.setattr(A, 'email_signin_link', lambda email, link, purpose: sent.update(email=email, link=link))
    return lambda: parse_qs(urlparse(sent['link']).query)['token'][0]


def test_keeping_the_profile_with_a_new_email(guest, emails):
    assert guest['v'].post('/api/auth/signup', json={'email': 'kept@r5b.test', 'name': 'Kept'}).status_code == 200
    phone = browser(ip='198.51.100.9')                                                   # the link opened elsewhere
    u = phone.post('/api/auth/verify', json={'token': emails()}).json['user']
    assert u['id'] == guest['guest']['id'] and not u['is_guest'] and u['email'] == 'kept@r5b.test' and u['name'] == 'Kept'
    assert phone.get(f"/api/showtimes/{guest['s1']}").json['user_rsvp'] == 'going'       # plans came along


def test_keeping_the_profile_by_signing_into_an_account(world, emails):
    from app import app, db, User, RSVP, Watchlist
    v = browser(ip='198.51.100.20')
    g = v.post('/api/auth/guest').json['user']
    v.post('/api/rsvp', json={'showtime_id': world['s2'], 'status': 'maybe'})
    v.post('/api/watchlist', json={'movie_id': world['m2']})
    v.post('/api/auth/login', json={'email': 'owner@r5b.test'})
    r = browser().post('/api/auth/verify', json={'token': emails()})
    with app.app_context():
        assert r.json['user']['id'] == world['owner'] and db.session.get(User, g['id']) is None       # guest folded in
        assert RSVP.query.filter_by(user_id=world['owner'], showtime_id=world['s2'], group_id=None).first().status == 'maybe'
        assert Watchlist.query.filter_by(user_id=world['owner'], movie_id=world['m2']).count() == 1     # no duplicate
        assert db.session.get(User, world['owner']).discord_user_id == '313131'


@pytest.fixture
def discord_oauth(monkeypatch):
    import app as A
    import requests
    me = {}

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    monkeypatch.setattr(requests, 'post', lambda *a, **k: Resp({'access_token': 'tok'}))
    monkeypatch.setattr(requests, 'get', lambda *a, **k: Resp(me))
    monkeypatch.setattr(A, 'DISCORD_CLIENT_ID', 'cid')
    monkeypatch.setattr(A, 'DISCORD_CLIENT_SECRET', 'secret')
    return me


def sign_in_with_discord(c, connect=False):
    r = c.get('/api/auth/discord/start' + ('?mode=connect' if connect else ''))
    state = parse_qs(urlparse(r.headers['Location']).query)['state'][0]
    return c.get('/api/auth/discord/callback', query_string={'code': 'x', 'state': state})


def test_keeping_the_profile_with_discord(world, discord_oauth):
    from app import app, db, User, Watchlist
    v = browser(ip='198.51.100.30')
    g = v.post('/api/auth/guest').json['user']
    v.post('/api/rsvp', json={'showtime_id': world['s1'], 'status': 'going'})
    discord_oauth.update(id='777000', username='newbie', global_name='Newbie')
    sign_in_with_discord(v, connect=True)                                     # a guest "connecting" signs in instead
    me = v.get('/api/auth/me').json['user']
    assert me['id'] == g['id'] and not me['is_guest'] and me['discord_linked']
    v2 = browser(ip='198.51.100.31')
    g2 = v2.post('/api/auth/guest').json['user']
    v2.post('/api/watchlist', json={'movie_id': world['m1']})
    discord_oauth.update(id='313131', username='olive', global_name='Olive')
    sign_in_with_discord(v2)                                                   # an existing Discord account
    with app.app_context():
        assert v2.get('/api/auth/me').json['user']['id'] == world['owner'] and db.session.get(User, g2['id']) is None
        assert Watchlist.query.filter_by(user_id=world['owner'], movie_id=world['m1']).count() == 1


def test_idle_guests_expire_with_their_plans(world):
    from app import app, db, User, RSVP
    with app.app_context():
        old = User(name='Guest', is_guest=True, is_active=True, last_seen_at=datetime.now() - timedelta(days=95))
        db.session.add(old)
        db.session.flush()
        db.session.add(RSVP(user_id=old.id, showtime_id=world['s1'], group_id=None, status='going'))
        db.session.commit()
        old_id = old.id
    browser(ip='198.51.100.40').post('/api/auth/guest')
    with app.app_context():
        assert db.session.get(User, old_id) is None and RSVP.query.filter_by(user_id=old_id).count() == 0


def test_session_lengths(world):
    m = browser(world['owner'])
    with m.session_transaction() as s:
        s['seen'] = int(time.time()) - 31 * 86400
    assert m.get('/api/auth/me').json['user'] is None                       # members: signed out after 30 days away
    v = browser(ip='198.51.100.41')
    v.post('/api/auth/guest')
    with v.session_transaction() as s:
        s['seen'] = int(time.time()) - 60 * 86400
    assert v.get('/api/auth/me').json['user'] is not None                   # guests: 90

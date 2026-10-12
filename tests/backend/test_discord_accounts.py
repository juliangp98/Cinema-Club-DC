"""Accounts without an email (Discord-only), /link merging them into a site
account, and Sign in with Discord (OAuth)."""
import os
import sqlite3
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from helpers import H, client, setup_db

ANA = {'discord_user_id': '5001', 'discord_name': 'Ana (server nick)', 'discord_username': 'ana_d',
       'discord_avatar': 'https://cdn.discordapp.com/a.png', 'group_id': 1}


def test_the_email_nullable_migration_keeps_everything():
    import app as A
    from app import app, db, migrate, User, GroupMembership
    path = os.environ['DATABASE_URL'].replace('sqlite:///', '')
    con = sqlite3.connect(path)
    before = {t: con.execute(f'select count(*) from "{t}"').fetchone()[0] for t in ('user', 'rsvp', 'watchlist', 'group_membership')}
    con.close()
    with app.app_context():
        db.create_all()
        migrate()
        ddl = db.session.execute(db.text("select sql from sqlite_master where name='user'")).scalar()
        assert 'email VARCHAR(120) NOT NULL' not in ddl and 'email VARCHAR(120)' in ddl
        assert {t: db.session.execute(db.text(f'select count(*) from "{t}"')).scalar() for t in before} == before
        admin = User.query.filter_by(email='member4@example.test').first()        # the club's admin (fake fixture data)
        assert GroupMembership.query.filter_by(user_id=admin.id, group_id=1).first()
        assert os.path.exists(path + '.pre-discord-accounts.bak')                  # a backup first
        assert db.session.execute(db.text("select name from sqlite_master where type='index' "
                                          "and name='ux_user_discord_user_id'")).scalar() == 'ux_user_discord_user_id'
        migrate()                                                                   # a second boot
        ddl = db.session.execute(db.text("select sql from sqlite_master where name='user'")).scalar()
        assert 'NOT NULL' not in ddl.split('email')[1].split(',')[0]


@pytest.fixture
def sirat():
    from app import app, Movie, Showtime
    setup_db()
    with app.app_context():
        movie = Movie.query.filter_by(title='SIRÂT').first()
        return {'showtime': Showtime.query.filter_by(movie_id=movie.id).first().id, 'title': movie.title}


def rsvp(sirat, create):
    return client().post('/api/internal/rsvp', json={**ANA, 'create': create, 'showtime_id': sirat['showtime'], 'status': 'going'},
                         headers=H)


@pytest.fixture
def ana(sirat):
    """Ana used /rsvp and /watch in the server: a Discord-only account."""
    from app import app, User
    rsvp(sirat, True)
    client().post('/api/internal/watch', json={**ANA, 'create': True, 'discord_name': 'Ana B', 'title': sirat['title'],
                                               'action': 'add'}, headers=H)
    with app.app_context():
        return {**sirat, 'ana': User.query.filter_by(discord_user_id='5001').first().id}


def test_accounts_are_made_only_in_the_clubs_server(sirat):
    from app import app, User, GroupMembership
    r = rsvp(sirat, False)
    assert r.status_code == 404 and r.json['error'] == 'no_account'
    r = rsvp(sirat, True)
    assert r.status_code == 200 and any(a['name'] == 'Ana (server nick)' for a in r.json['attendees'])
    with app.app_context():
        u = User.query.filter_by(discord_user_id='5001').first()
        assert u.email is None and u.discord_username == 'ana_d' and u.avatar_url
        assert GroupMembership.query.filter_by(user_id=u.id, group_id=1, status='active').first()


def test_a_discord_only_member_uses_the_bot_like_anyone(ana):
    from app import app, db, User
    with app.app_context():
        assert User.query.filter_by(discord_user_id='5001').count() == 1           # no duplicate
        assert db.session.get(User, ana['ana']).name == 'Ana B'                   # name follows Discord
    d = client().get('/api/internal/watchlist', query_string={**ANA, 'create': True, 'discord_name': 'Ana B'}, headers=H).json
    assert d['owner'] == 'Ana B' and len(d['items']) == 1
    assert client().get('/api/internal/watchlist', query_string={'member_id': ana['ana']}, headers=H).json['owner'] == 'Ana B'
    assert any(m['id'] == ana['ana'] for m in client().get('/api/internal/members?group_id=1', headers=H).json)


def test_profiles_from_discord(ana):
    me = {**ANA, 'create': True, 'discord_name': 'Ana B'}
    p = client().get('/api/internal/profile', query_string=me, headers=H).json
    assert p['user']['id'] == ana['ana'] and 'horror' in p['genre_options'] and p['site_account'] is False and p['upcoming_rsvps'] == 0
    p = client().post('/api/internal/profile', headers=H, json={**me, 'favorite_genres': ['Horror', 'noir', 'not-a-genre'],
                                                                'bio': '  i like it scary  ', 'letterboxd_username': 'ana d!'}).json
    assert p['genres'] == ['horror', 'noir'] and p['user']['bio'] == 'i like it scary' and p['user']['letterboxd_username'] == 'anad'
    assert client().get('/api/internal/profile', query_string={'member_discord_id': '7777'}, headers=H).status_code == 404
    assert client().get('/api/internal/profile', query_string={'member_discord_id': '5001'}, headers=H).json['user']['name'] == 'Ana B'


@pytest.fixture
def linked(ana):
    """Ana also had a site account (pending in the club, a clashing 'maybe');
    she used /link with its code. Her Discord-only account had a reaction and
    a profile."""
    from app import app, db, User, GroupMembership, RSVP, Reaction
    client().post('/api/internal/profile', headers=H, json={**ANA, 'create': True, 'discord_name': 'Ana B',
                                                            'favorite_genres': ['horror', 'noir'], 'letterboxd_username': 'anad'})
    with app.app_context():
        site = User(email='ana@test.dev', name='Ana Site', is_active=True, discord_link_code='ABC234',
                    discord_link_code_expires=datetime.utcnow() + timedelta(minutes=5))
        db.session.add(site)
        db.session.flush()
        db.session.add(GroupMembership(user_id=site.id, group_id=1, status='pending'))
        db.session.add(RSVP(user_id=site.id, showtime_id=ana['showtime'], group_id=1, status='maybe'))
        db.session.add(Reaction(user_id=ana['ana'], showtime_id=ana['showtime'], group_id=1, emoji='🍿'))
        db.session.commit()
        site_id = site.id
    r = client().post('/api/internal/link/verify', json={'code': 'abc234', 'discord_user_id': '5001', 'discord_username': 'ana_d'},
                      headers=H)
    return {**ana, 'site': site_id, 'link': r}


def test_link_merges_the_discord_only_account(linked):
    from app import app, db, User, GroupMembership, RSVP, Reaction, Watchlist
    with app.app_context():
        site = db.session.get(User, linked['site'])
        assert linked['link'].status_code == 200 and site.discord_user_id == '5001'
        assert db.session.get(User, linked['ana']) is None
        assert Watchlist.query.filter_by(user_id=site.id).count() == 1 and Reaction.query.filter_by(user_id=site.id).count() == 1
        [r] = RSVP.query.filter_by(user_id=site.id, showtime_id=linked['showtime']).all()
        assert r.status == 'maybe'                                                  # the site account's own wins
        assert GroupMembership.query.filter_by(user_id=site.id, group_id=1).first().status == 'active'
        assert site.favorite_genres == 'horror,noir' and site.letterboxd_username == 'anad' and site.name == 'Ana Site'


@pytest.fixture
def discord_oauth(monkeypatch):
    """Discord's OAuth endpoints faked; `me` is who Discord says you are."""
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


def sign_in(browser, connect=False):
    r = browser.get('/api/auth/discord/start' + ('?mode=connect' if connect else ''))
    state = parse_qs(urlparse(r.headers['Location']).query)['state'][0]
    return browser.get('/api/auth/discord/callback', query_string={'code': 'x', 'state': state})


def test_providers_follow_configuration(monkeypatch):
    import app as A
    setup_db()
    assert client().get('/api/auth/providers').json == {'discord': False}
    monkeypatch.setattr(A, 'DISCORD_CLIENT_ID', 'cid')
    monkeypatch.setattr(A, 'DISCORD_CLIENT_SECRET', 'secret')
    assert client().get('/api/auth/providers').json == {'discord': True}


def test_the_oauth_round_trip_is_protected(discord_oauth):
    setup_db()
    b = client()
    r = b.get('/api/auth/discord/start')
    q = parse_qs(urlparse(r.headers['Location']).query)
    assert r.status_code == 302 and q['scope'] == ['identify'] and q['state']
    assert 'discord_error=expired' in b.get('/api/auth/discord/callback', query_string={'code': 'x', 'state': 'forged'}).headers['Location']


def test_signing_in_makes_one_account(discord_oauth):
    from app import app, User, GroupMembership
    setup_db()
    discord_oauth.update(id='6001', username='ben_h', global_name='Ben', avatar='abc')
    b = client()
    r = sign_in(b)
    me = b.get('/api/auth/me').json['user']
    assert 'discord=signed_in' in r.headers['Location'] and me['name'] == 'Ben' and me['discord_only']
    with app.app_context():
        assert GroupMembership.query.filter_by(user_id=me['id']).count() == 0     # joins clubs the normal way
    again = client()
    sign_in(again)
    assert again.get('/api/auth/me').json['user']['id'] == me['id']


def test_a_linked_member_signs_into_their_site_account(linked, discord_oauth):
    discord_oauth.update(id='5001', username='ana_d', global_name='Ana')
    b = client()
    sign_in(b)
    assert b.get('/api/auth/me').json['user']['id'] == linked['site']


def test_connecting_discord_to_a_site_account(discord_oauth):
    from app import app, db, User, Movie, Watchlist
    setup_db()
    discord_oauth.update(id='6001', username='ben_h', global_name='Ben')
    sign_in(client())                                                               # Ben: Discord-only, with a watchlist
    with app.app_context():
        ben = User.query.filter_by(discord_user_id='6001').first().id
        db.session.add(Watchlist(user_id=ben, movie_id=Movie.query.first().id))
        carl, dan = User(email='carl@test.dev', name='Carl', is_active=True), User(email='dan@test.dev', name='Dan', is_active=True)
        db.session.add_all([carl, dan])
        db.session.commit()
        carl_id, dan_id = carl.id, dan.id
    r = sign_in(client(carl_id), connect=True)
    with app.app_context():
        assert 'discord=connected' in r.headers['Location'] and db.session.get(User, ben) is None
        assert db.session.get(User, carl_id).discord_user_id == '6001' and Watchlist.query.filter_by(user_id=carl_id).count() == 1
    r = sign_in(client(dan_id), connect=True)                                        # already Carl's
    with app.app_context():
        assert 'discord_error=taken' in r.headers['Location']
        assert db.session.get(User, carl_id).discord_user_id == '6001' and db.session.get(User, dan_id).discord_user_id is None

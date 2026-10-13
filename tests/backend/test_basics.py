"""The basics: email sign-in, profiles, clubs (create, join, approve), RSVPs,
watchlists, reactions, comments, and the internal API's lock.

Written in the suite's preferred style: small tests, each on a fresh database
(see conftest.py), sharing setup through the helpers below.
"""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db


@pytest.fixture
def world():
    """A club with an admin and a member, an outsider, and a screening next week."""
    from app import app, db, User, Group, GroupMembership, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        m = Movie(title='BASICS FILM', runtime_minutes=100)
        db.session.add(m)
        db.session.flush()
        s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=datetime.now() + timedelta(days=3))
        g = Group(name='Basics Club', slug='basics-club', is_public=True)
        users = [User(email=f'{n}@basics.test', name=n.title(), is_active=True) for n in ('admin', 'member', 'outsider')]
        db.session.add_all([s, g, *users])
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=users[0].id, group_id=g.id, role='admin', status='active'),
                            GroupMembership(user_id=users[1].id, group_id=g.id, role='member', status='active')])
        db.session.commit()
        return {'admin': users[0].id, 'member': users[1].id, 'outsider': users[2].id, 'group': g.id, 'slug': g.slug,
                'showtime': s.id, 'movie': m.id}


@pytest.fixture
def mailbox(monkeypatch):
    """Sign-in emails, caught instead of sent: [(email, link, purpose)]."""
    import app as A
    sent = []
    monkeypatch.setattr(A, 'email_signin_link', lambda email, link, purpose: sent.append((email, link, purpose)))
    return sent


def token_of(link):
    return link.split('token=', 1)[1]


# ─── Signing in ───────────────────────────────────────────────────────────────

def test_sign_up_by_email(mailbox):
    setup_db()
    c = client()
    assert c.post('/api/auth/signup', json={'email': 'New@Person.test', 'name': 'New Person'}).status_code == 200
    (email, link, purpose), = mailbox
    assert (email, purpose) == ('new@person.test', 'signup')
    r = c.post('/api/auth/verify', json={'token': token_of(link)})
    assert r.status_code == 200 and r.json['user']['name'] == 'New Person'
    assert c.get('/api/auth/me').json['user']['email'] == 'new@person.test'


def test_sign_in_link_is_single_use(mailbox):
    setup_db()
    c = client()
    c.post('/api/auth/signup', json={'email': 'once@person.test', 'name': 'Once'})
    token = token_of(mailbox[0][1])
    assert c.post('/api/auth/verify', json={'token': token}).status_code == 200
    assert client().post('/api/auth/verify', json={'token': token}).status_code == 400
    assert client().post('/api/auth/verify', json={'token': 'made-up'}).status_code == 400


def test_sign_in_needs_an_account_and_signup_rejects_duplicates(world, mailbox):
    c = client()
    assert c.post('/api/auth/login', json={'email': 'nobody@basics.test'}).status_code == 404
    assert c.post('/api/auth/signup', json={'email': 'member@basics.test', 'name': 'Again'}).status_code == 409
    assert c.post('/api/auth/signup', json={'email': 'not-an-email', 'name': 'X'}).status_code == 400
    assert c.post('/api/auth/login', json={'email': 'member@basics.test'}).status_code == 200
    r = c.post('/api/auth/verify', json={'token': token_of(mailbox[-1][1])})
    assert r.json['user']['id'] == world['member']


def test_sign_in_emails_are_rate_limited(world, mailbox):
    codes = [client().post('/api/auth/login', json={'email': 'member@basics.test'}).status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[5] == 429


def test_sign_out(world):
    c = client(world['member'])
    assert c.get('/api/auth/me').json['user']['id'] == world['member']
    c.post('/api/auth/logout')
    assert c.get('/api/auth/me').json['user'] is None


# ─── Profiles ─────────────────────────────────────────────────────────────────

def test_profile_update_cleans_input(world):
    c = client(world['member'])
    r = c.put('/api/auth/profile', json={'name': '  Member Prime  ', 'avatar_color': '#000000', 'genres': 'horror,NOPE,comedy',
                                          'bio': 'x' * 900, 'letterboxd_username': 'mem ber!'}).json['user']
    assert r['name'] == 'Member Prime'
    assert r['avatar_color'] != '#000000'                      # only the palette's colors
    assert c.get('/api/me/taste').json['genres'] == ['comedy', 'horror']
    assert len(r['bio']) == 500 and r['letterboxd_username'] == 'member'


# ─── Clubs ────────────────────────────────────────────────────────────────────

def test_creating_a_club_makes_you_its_admin(world):
    c = client(world['outsider'])
    r = c.post('/api/groups', json={'name': 'Outsider Club', 'theatres': ['afi', 'not-a-theatre']})
    assert r.status_code == 201 and r.json['theatres'] == ['afi']
    mine = c.get('/api/groups').json
    assert [(g['name'], g['role']) for g in mine] == [('Outsider Club', 'admin')]
    assert c.post('/api/groups', json={'name': 'Outsider Club'}).status_code == 409


def test_joining_needs_an_admins_approval(world):
    out, admin, member = client(world['outsider']), client(world['admin']), client(world['member'])
    slug, uid = world['slug'], world['outsider']
    assert out.post(f'/api/groups/{slug}/join').status_code == 202
    assert out.get(f'/api/groups/{slug}/members').status_code == 403            # pending isn't in yet
    assert not any(m['user']['id'] == uid for m in member.get(f'/api/groups/{slug}/members').json)   # members don't see requests
    assert any(m['user']['id'] == uid and m['status'] == 'pending' for m in admin.get(f'/api/groups/{slug}/members').json)
    assert member.post(f'/api/groups/{slug}/members/{uid}/approve').status_code == 403
    assert admin.post(f'/api/groups/{slug}/members/{uid}/approve').status_code == 200
    assert out.get(f'/api/groups/{slug}/members').status_code == 200


def test_denied_and_removed_members_lose_access(world):
    out, admin = client(world['outsider']), client(world['admin'])
    slug = world['slug']
    out.post(f'/api/groups/{slug}/join')
    admin.post(f'/api/groups/{slug}/members/{world["outsider"]}/deny')
    assert out.get(f'/api/groups/{slug}/members').status_code == 403
    assert admin.delete(f'/api/groups/{slug}/members/{world["member"]}').status_code == 200
    assert client(world['member']).get(f'/api/groups/{slug}/members').status_code == 403


def test_private_clubs_are_not_listed(world):
    client(world['admin']).post('/api/groups', json={'name': 'Hidden Club', 'is_public': False})
    names = [g['name'] for g in client(world['outsider']).get('/api/groups/discover').json['groups']]
    assert 'Basics Club' in names and 'Hidden Club' not in names


# ─── RSVPs, watchlists, reactions, comments ──────────────────────────────────

def test_rsvp_going_maybe_and_clear(world):
    m = client(world['member'])
    body = {'showtime_id': world['showtime'], 'group_id': world['group']}
    d = m.post('/api/rsvp', json={**body, 'status': 'going'}).json
    assert d['user_rsvp'] == 'going' and [a['name'] for a in d['attendees']] == ['Member']
    d = m.post('/api/rsvp', json={**body, 'status': 'maybe'}).json
    assert d['user_rsvp'] == 'maybe' and d['attendees'] == [] and [a['name'] for a in d['maybes']] == ['Member']
    assert m.post('/api/rsvp', json={**body, 'status': None}).json['user_rsvp'] is None
    assert m.post('/api/rsvp', json={**body, 'status': 'sideways'}).status_code == 400


def test_rsvp_needs_club_membership(world):
    out = client(world['outsider'])
    r = out.post('/api/rsvp', json={'showtime_id': world['showtime'], 'group_id': world['group'], 'status': 'going'})
    assert r.status_code == 403
    assert client().post('/api/rsvp', json={'showtime_id': world['showtime'], 'status': 'going'}).status_code == 401


def test_watchlist_add_list_remove(world):
    m = client(world['member'])
    assert m.post('/api/watchlist', json={'movie_id': world['movie']}).json['watching'] is True
    assert [i['movie']['id'] for i in m.get('/api/watchlist').json] == [world['movie']]
    assert m.post('/api/watchlist', json={'movie_id': world['movie']}).json['watching'] is False
    assert m.get('/api/watchlist').json == []
    assert m.post('/api/watchlist', json={'movie_id': 999999}).status_code == 404


def test_reactions_toggle(world):
    from app import CINEMA_EMOJIS
    m = client(world['member'])
    body = {'showtime_id': world['showtime'], 'group_id': world['group'], 'emoji': CINEMA_EMOJIS[0]}
    on = m.post('/api/reactions', json=body).json
    assert on[CINEMA_EMOJIS[0]]['count'] == 1 and on[CINEMA_EMOJIS[0]]['user_reacted']
    assert m.post('/api/reactions', json=body).json == {}
    assert m.post('/api/reactions', json={**body, 'emoji': '🦖'}).status_code == 400
    assert client(world['outsider']).post('/api/reactions', json=body).status_code == 403


def test_comments_post_list_delete(world):
    m, a = client(world['member']), client(world['admin'])
    q = {'showtime_id': world['showtime'], 'group_id': world['group']}
    r = m.post('/api/messages', json={**q, 'body': 'See you there'})
    assert r.status_code == 201 and r.json['can_delete']
    assert [x['body'] for x in a.get('/api/messages', query_string=q).json] == ['See you there']
    assert a.delete(f"/api/messages/{r.json['id']}").status_code in (403, 404)          # not yours
    assert m.post('/api/messages', json={**q, 'body': '   '}).status_code == 400
    assert m.post('/api/messages', json={**q, 'body': 'x' * 2001}).status_code == 400
    assert m.delete(f"/api/messages/{r.json['id']}").status_code == 200
    assert a.get('/api/messages', query_string=q).json == []
    assert client(world['outsider']).get('/api/messages', query_string=q).status_code == 403


# ─── The internal API ─────────────────────────────────────────────────────────

@pytest.mark.parametrize('path', ['/api/internal/showtimes', '/api/internal/digest', '/api/internal/members'])
def test_internal_api_needs_the_token(world, path):
    c = client()
    assert c.get(path).status_code == 403
    assert c.get(path, headers={'X-Internal-Token': 'wrong'}).status_code == 403
    assert c.get(path, query_string={'group_id': 1}, headers=H).status_code == 200

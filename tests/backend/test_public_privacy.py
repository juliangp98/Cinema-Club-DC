"""R5a privacy: what visitors, club-less accounts and other clubs' members
can see — public pages show schedules and anonymous counts, never members."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db

SECRETS = ['Zelda Privatename', 'Quentin Hushwood', 'Ottoline Outsider', 'zelda@secret.test', 'quentin@secret.test',
           '445566778899', 'SECRET COMMENT BODY', 'discord.com/channels/']


@pytest.fixture
def world():
    """Club A (Zelda, Quentin), Club B (Ottoline), a club-less account (Lone,
    likes drama). POPULAR (horror): 3 going across clubs, 3 watchers; QUIET
    (drama): 2 going, 2 wanting (Zelda, Lone). A comment, a reaction and a
    Discord thread on POPULAR."""
    from app import (app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist, Message,
                     Reaction, ShowtimeThread)
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        ga, gb = Group(name='Club A', slug='club-a-r5', is_public=False), Group(name='Club B', slug='club-b-r5', is_public=False)
        db.session.add_all([ga, gb])
        db.session.flush()
        z = User(email='zelda@secret.test', name='Zelda Privatename', is_active=True, discord_user_id='445566778899',
                 favorite_genres='horror')
        q = User(email='quentin@secret.test', name='Quentin Hushwood', is_active=True)
        o = User(email='otto@secret.test', name='Ottoline Outsider', is_active=True)
        lone = User(email='lone@public.test', name='Lone', is_active=True, favorite_genres='drama')
        watchers = [User(email=f'w{i}@public.test', name=f'Watcher {i}', is_active=True) for i in range(3)]
        db.session.add_all([z, q, o, lone, *watchers])
        db.session.flush()
        for u in (z, q):
            db.session.add(GroupMembership(user_id=u.id, group_id=ga.id, status='active'))
        db.session.add(GroupMembership(user_id=o.id, group_id=gb.id, status='active'))
        now = datetime.now()

        def show(title, genres, days):
            m = Movie(title=title, release_year='1975', genres=genres)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id,
                         start_time=(now + timedelta(days=days)).replace(hour=20, minute=0, second=0, microsecond=0))
            db.session.add(s)
            db.session.flush()
            return m, s
        pop, sp = show('POPULAR PRIVATE TEST', 'Horror', 2)
        quiet, sq = show('QUIET PRIVATE TEST', 'Drama', 3)
        for u in (z, q, o):
            db.session.add(RSVP(user_id=u.id, showtime_id=sp.id, group_id=gb.id if u is o else ga.id, status='going'))
        for u in (z, q):
            db.session.add(RSVP(user_id=u.id, showtime_id=sq.id, group_id=ga.id, status='going'))
        for u in watchers:
            db.session.add(Watchlist(user_id=u.id, movie_id=pop.id))
        db.session.add_all([Watchlist(user_id=z.id, movie_id=quiet.id), Watchlist(user_id=lone.id, movie_id=quiet.id),
                            Message(user_id=z.id, showtime_id=sp.id, group_id=ga.id, body='SECRET COMMENT BODY', source='site'),
                            Reaction(user_id=z.id, showtime_id=sp.id, group_id=ga.id, emoji='🔥'),
                            ShowtimeThread(showtime_id=sp.id, group_id=ga.id, guild_id='1', channel_id='2', thread_id='998877')])
        db.session.commit()
        __import__('taste').migrate_legacy_genres()      # genres set the pre-R13 way, moved over
        return {'ga': ga.id, 'zelda': z.id, 'otto': o.id, 'lone': lone.id, 'sp': sp.id, 'sq': sq.id, 'pop': pop.id,
                'quiet': quiet.id, 'd0': now.strftime('%Y-%m-%d'), 'd13': (now + timedelta(days=13)).strftime('%Y-%m-%d')}


def public_routes(w):
    return [('/api/theatres', {}), ('/api/discover', {}), ('/api/discover/browse', {'when': '2weeks'}),
            ('/api/discover/browse', {'when': '2weeks', 'club': 'going'}),
            ('/api/discover/calendar', {'from': w['d0'], 'to': w['d13']}), ('/api/discover/surprise', {'when': 'week'}),
            (f"/api/showtimes/{w['sp']}", {}), (f"/api/films/{w['pop']}", {}), (f"/api/films/{w['quiet']}", {}),
            (f"/api/showtimes/{w['sp']}/gcal-url", {})]


@pytest.mark.parametrize('who', [None, 'lone', 'otto'], ids=['visitor', 'account without a club', 'member of another club'])
def test_public_routes_leak_nothing_about_members(world, who):
    c = client(world[who] if who else None)
    for path, qs in public_routes(world):
        r = c.get(path, query_string=qs)
        text = r.get_data(as_text=True)
        assert r.status_code in (200, 404), (path, r.status_code)
        assert not [s for s in SECRETS if s in text], path


def test_a_public_screening_shows_anonymous_counts_only(world):
    st = client().get(f"/api/showtimes/{world['sp']}").json
    assert st['attendees'] == [] and st['maybes'] == [] and st['reactions'] == {} and st['message_count'] == 0
    assert st['discord'] is None and st['discord_thread_url'] is None and st['public'] is True
    assert st['interest']['going'] == 3 and st['interest']['want'] == 3                   # shown from 3, across clubs
    assert client().get(f"/api/showtimes/{world['sq']}").json['interest'] == {'going': None, 'want': None}   # 2: withheld


def test_a_public_film_page(world):
    f = client().get(f"/api/films/{world['quiet']}").json
    assert f['club'] is None and f['interest'] == {'want': None} and f['viewer_wants'] is False
    assert client(world['lone']).get(f"/api/films/{world['quiet']}").json['viewer_wants'] is True   # your own mark


def test_public_discover_and_calendar(world):
    d = client().get('/api/discover').json
    cards = [c for s in d['shelves'] for c in s['items']]
    assert cards and all('club' not in c and 'interest' in c for c in cards)
    assert not any(s['key'] in ('friends', 'most-wanted', 'for-you') for s in d['shelves'])
    assert next(c for c in cards if c['movie']['id'] == world['pop'])['interest'] == {'want': 3, 'going': 3}
    window = {'from': world['d0'], 'to': world['d13']}
    cal = client().get('/api/discover/calendar', query_string=window).json
    assert cal['showtimes'] and all(s['public'] and s['attendees'] == [] for s in cal['showtimes'])
    mine = client(world['lone']).get('/api/discover/calendar', query_string=window).json['showtimes']
    assert any(s['recommended'] for s in mine if s['movie_id'] == world['quiet'])          # the viewer's own genres
    assert not any(s['recommended'] for s in cal['showtimes'])


def test_club_mode_stays_closed(world):
    GA, window = world['ga'], {'from': world['d0'], 'to': world['d13']}
    assert client().get('/api/discover', query_string={'group_id': GA}).status_code == 401
    assert client().get(f"/api/showtimes/{world['sp']}", query_string={'group_id': GA}).status_code == 401
    assert client(world['otto']).get(f"/api/films/{world['pop']}", query_string={'group_id': GA}).status_code == 403
    assert client(world['otto']).get('/api/discover/calendar', query_string={'group_id': GA, **window}).status_code == 403
    assert client(world['lone']).get(f"/api/showtimes/{world['sp']}", query_string={'group_id': GA}).status_code == 403
    m = client(world['zelda']).get(f"/api/showtimes/{world['sp']}", query_string={'group_id': GA}).json
    assert {a['name'] for a in m['attendees']} == {'Zelda Privatename', 'Quentin Hushwood'} and m['discord_thread_url']


@pytest.mark.parametrize('method, path', [('get', '/api/showtimes'), ('get', '/api/feed'), ('get', '/api/club/week'),
                                          ('get', '/api/messages'), ('post', '/api/rsvp'), ('post', '/api/reactions'),
                                          ('get', '/api/watchlist'), ('get', '/api/groups/{ga}/polls'), ('get', '/api/discord/prefs'),
                                          ('get', '/api/attendance/pending')])
def test_member_routes_refuse_visitors(world, method, path):
    r = getattr(client(), method)(path.format(ga=world['ga']), query_string={'group_id': world['ga'], 'showtime_id': world['sp']}, json={})
    assert r.status_code == 401


def test_visitors_share_a_cached_copy_signed_in_views_dont(world):
    assert client().get('/api/discover').get_data(as_text=True) == client().get('/api/discover').get_data(as_text=True)
    assert 'for-you' in [s['key'] for s in client(world['lone']).get('/api/discover').json['shelves']]

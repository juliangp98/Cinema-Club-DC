"""R6a.1: only members who've linked Discord AND are in the club's server
ever appear there (shares, comments, names, pings); everyone else is a
count. The bot reports who's in the server."""
import os
import sqlite3
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db

POLL = {'title': 'Best ZETA', 'categories': [{'title': 'Pick', 'options': [{'text': 'One'}, {'text': 'Two'}]}], 'announce': 'now'}


def test_digest_mentions_start_unchosen_after_the_migration():
    from app import app, db, migrate, Watchlist
    con = sqlite3.connect(os.environ['DATABASE_URL'].replace('sqlite:///', ''))
    (u1,), (u2,) = con.execute('select id from user order by id limit 2').fetchall()
    con.execute("update user set discord_user_id = '7190' where id = ?", (u1,))
    con.executemany('insert into watchlist (user_id, movie_id) values (?, 1)', [(u1,), (u2,)])
    con.commit()
    con.close()
    with app.app_context():
        db.create_all()
        migrate()
        rows = [w.share_discord for w in Watchlist.query.all() if w.user]
        assert rows and all(s is None for s in rows)                          # opt-in, linked or not


@pytest.fixture
def club():
    """Group 1: Ana (7101, organizer), Bo (7102), Cy (never linked), Dee
    (7104), Org (organizer, never linked). ZETA ONE and ZETA TWO this week."""
    from app import app, db, User, GroupMembership, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        did = {'Ana': '7101', 'Bo': '7102', 'Dee': '7104'}
        us = {n: User(email=f'{n.lower()}@r6d.test', name=n, is_active=True, discord_user_id=did.get(n))
              for n in ('Ana', 'Bo', 'Cy', 'Dee', 'Org')}
        db.session.add_all(us.values())
        db.session.flush()
        for n, u in us.items():
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role='organizer' if n in ('Ana', 'Org') else 'member'))
        now, ids = datetime.now(), {}
        for key, title, days in (('S1', 'ZETA ONE', 2), ('S2', 'ZETA TWO', 3)):
            m = Movie(title=title)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=(now + timedelta(days=days)).replace(hour=19, minute=0, second=0, microsecond=0))
            db.session.add(s)
            db.session.flush()
            ids[key], ids['M' + key[1]] = s.id, m.id
        db.session.commit()
        return {**ids, **{n: u.id for n, u in us.items()}}


def c(club, name):
    return client(club[name])


def sync(**body):
    return client().post('/api/internal/discord/members', json=body, headers=H).json


def due():
    return client().get('/api/internal/discord/posts/due', query_string={'group_id': 1}, headers=H).json


def rsvp(club, name, sid, status='going'):
    return c(club, name).post('/api/rsvp', json={'showtime_id': club[sid], 'status': status, 'group_id': 1}).json


def in_app(fn):
    from app import app
    with app.app_context():
        return fn()


@pytest.fixture
def synced(club):
    """The bot reported the server: Ana, Dee and a stranger."""
    sync(full=True, ids=['7101', '7104', '99999'])
    return club


@pytest.fixture
def going(synced):
    """Ana always shares RSVPs, and so would Bo and Cy. Everyone's going to
    ZETA ONE; Bo and Cy to ZETA TWO too."""
    c(synced, 'Ana').put('/api/discord/prefs', json={'rsvp': 'always'})
    for n in ('Bo', 'Cy'):
        c(synced, n).put('/api/discord/prefs', json={'rsvp': 'always', 'poll': 'always', 'comment': 'always'})
    for n in ('Ana', 'Bo', 'Cy', 'Dee'):
        rsvp(synced, n, 'S1')
    for n in ('Bo', 'Cy'):
        rsvp(synced, n, 'S2')
    return synced


def test_nobody_is_in_the_server_until_the_bot_says_so(club):
    c(club, 'Ana').put('/api/discord/prefs', json={'rsvp': 'always'})
    r = c(club, 'Ana').get('/api/discord/prefs').json
    assert r['available'] is False and r['reason'] == 'not_in_server'
    assert due() == []


def test_the_member_sync(club):
    assert sync(full=True, ids=['7101', '7104', '99999', 'junk']) == {'members': 3, 'joined': 3, 'left': 0}   # junk ignored
    assert sync(full=True, ids=['7101', '7104', '99999']) == {'members': 3, 'joined': 0, 'left': 0}
    assert c(club, 'Ana').get('/api/auth/me').json['user']['discord_clubs'] == [1]
    assert c(club, 'Bo').get('/api/auth/me').json['user']['discord_clubs'] == []
    prefs = {n: c(club, n).get('/api/discord/prefs').json for n in ('Ana', 'Bo', 'Cy')}
    assert prefs['Ana']['available'] and prefs['Bo']['reason'] == 'not_in_server' and prefs['Cy']['reason'] == 'not_linked'


def test_only_server_members_share(going):
    from app import DiscordPost
    g = going
    assert rsvp(g, 'Ana', 'S1')['discord']['my_share']                                # in the server + always
    assert rsvp(g, 'Bo', 'S2')['discord'] is None and rsvp(g, 'Cy', 'S2')['discord'] is None
    r = c(g, 'Cy').post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': g['S1']})
    assert r.status_code == 403 and r.json['code'] == 'not_on_discord'
    assert c(g, 'Bo').post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': g['S1']}).status_code == 403
    assert in_app(lambda: sorted({p.user_id for p in DiscordPost.query.filter(DiscordPost.status != 'cancelled')})) == [g['Ana']]


def test_polls_are_announced_only_for_server_members(synced):
    from app import app, db, DiscordPost, Poll, render_post
    p_org = c(synced, 'Org').post('/api/groups/1/polls', json=POLL).json
    p_ana = c(synced, 'Ana').post('/api/groups/1/polls', json={**POLL, 'title': 'Best ZETA 2'}).json
    anns = in_app(lambda: {p.ref_id: p.user_id for p in DiscordPost.query.filter_by(kind='poll')})
    assert p_org['id'] not in anns and anns.get(p_ana['id']) == synced['Ana']
    assert 'discord' not in c(synced, 'Org').get(f"/api/polls/{p_org['id']}").json
    assert 'discord' in c(synced, 'Ana').get(f"/api/polls/{p_ana['id']}").json
    with app.app_context():
        post = DiscordPost.query.filter_by(kind='poll', ref_id=p_ana['id']).first()
        assert render_post(post)['creator'] == 'Ana'
        db.session.get(Poll, p_ana['id']).created_by = synced['Org']
        db.session.commit()
        assert render_post(post)['creator'] is None                                  # never someone outside the server


def test_bot_lists_name_server_members_and_count_the_rest(going):
    from app import app, db, Reaction
    g = going
    with app.app_context():
        db.session.add_all([Reaction(user_id=g['Cy'], showtime_id=g['S1'], group_id=1, emoji='🔥'),
                            Reaction(user_id=g['Ana'], showtime_id=g['S1'], group_id=1, emoji='🔥')])
        db.session.commit()
    st = client().get('/api/internal/showtimes', query_string={'group_id': 1, 'movie_id': g['M1']}, headers=H).json[0]
    assert [a['name'] for a in st['attendees']] == ['Ana', 'Dee'] and st['attendees_more'] == 2
    assert st['reactions']['🔥']['count'] == 2 and [u['name'] for u in st['reactions']['🔥']['users']] == ['Ana']
    card = client().get('/api/internal/discussion/thread', query_string={'showtime_id': g['S1'], 'group_id': 1}, headers=H).json['card']
    assert [p['name'] for p in card['going']] == ['Ana', 'Dee'] and card['going_more'] == 2
    r = client().post('/api/internal/rsvp', headers=H, json={'discord_user_id': '7199', 'discord_name': 'Newbie', 'create': '1',
                                                            'group_id': 1, 'showtime_id': g['S1'], 'status': 'going'}).json
    assert [a['name'] for a in r['attendees']] == ['Ana', 'Dee', 'Newbie']             # using the bot = in the server


def test_only_server_members_comments_reach_the_thread(going):
    from app import app, db, Message, ShowtimeThread
    g = going
    with app.app_context():
        db.session.add(ShowtimeThread(showtime_id=g['S1'], group_id=1, guild_id='1', channel_id='2', thread_id='77001'))
        db.session.commit()
    for n in ('Ana', 'Bo', 'Cy'):
        c(g, n).post('/api/messages', json={'showtime_id': g['S1'], 'group_id': 1, 'body': f'hi from {n}', 'to_discord': True})
    posts = client().get('/api/internal/discussion/outbox', query_string={'group_id': 1}, headers=H).json['posts']
    assert [p['body'] for p in posts] == ['hi from Ana']
    assert in_app(lambda: sorted(m.to_discord for m in Message.query.filter(
        Message.showtime_id == g['S1'], Message.user_id.in_([g['Bo'], g['Cy']])))) == [False, False]   # off Discord for good


def test_who_is_asked_about_digest_mentions(synced):
    g = synced
    r = c(g, 'Ana').post('/api/watchlist', json={'movie_id': g['M2']}).json
    assert r['watching'] and r['discord_prompt'] is True                               # in the server, choice "ask"
    assert c(g, 'Bo').post('/api/watchlist', json={'movie_id': g['M2']}).json['discord_prompt'] is False
    c(g, 'Dee').put('/api/discord/prefs', json={'watchlist': 'never'})
    assert c(g, 'Dee').post('/api/watchlist', json={'movie_id': g['M2']}).json['discord_prompt'] is False


@pytest.fixture
def watching(going):
    """Ana, Bo, Cy and Dee ("never") watch ZETA TWO; Newbie used /rsvp."""
    g = going
    c(g, 'Dee').put('/api/discord/prefs', json={'watchlist': 'never'})
    for n in ('Ana', 'Bo', 'Cy', 'Dee'):
        c(g, n).post('/api/watchlist', json={'movie_id': g['M2']})
    client().post('/api/internal/rsvp', headers=H, json={'discord_user_id': '7199', 'discord_name': 'Newbie', 'create': '1',
                                                        'group_id': 1, 'showtime_id': g['S1'], 'status': 'going'})
    return g


def digest():
    return client().get('/api/internal/digest', query_string={'group_id': 1, 'days': 7}, headers=H).json


def watch_item(d, sid):
    return next(i for i in d['watchlist'] if i['showtime_id'] == sid)


def test_the_digest_names_only_those_who_said_yes(watching):
    g = watching
    item = watch_item(digest(), g['S2'])
    assert item['watchers'] == [] and item['more'] == 4                              # unanswered: all counted
    r = c(g, 'Ana').put(f"/api/watchlist/{g['M2']}/discord", json={'share': True}).json
    assert r['discord_share'] is True and r['prefs']['watchlist'] == 'ask'
    client().post('/api/internal/watch', json={'discord_user_id': '7104', 'title': 'ZETA ONE', 'action': 'add'}, headers=H)
    d = digest()
    item = watch_item(d, g['S2'])
    assert [w['name'] for w in item['watchers']] == ['Ana'] and item['more'] == 3 and len(item['quiet_ids']) == 3
    one = watch_item(d, g['S1'])
    assert one['watchers'] == [] and one['more'] == 1                                # added with /watch, but "never" wins


def test_whos_going_respects_never_share(watching):
    g = watching
    going = next(x for x in digest()['whos_going'] if x['showtime_id'] == g['S1'])
    assert going['going'] == ['Ana', 'Dee', 'Newbie'] and going['going_more'] == 2
    c(g, 'Dee').put('/api/discord/prefs', json={'rsvp': 'never'})
    going = next(x for x in digest()['whos_going'] if x['showtime_id'] == g['S1'])
    assert going['going'] == ['Ana', 'Newbie'] and going['going_more'] == 3


def test_delivery_emails_only_those_who_chose_email(watching, monkeypatch):
    import app as A
    g = watching
    monkeypatch.setattr(A, 'send_email', lambda *a: None)
    c(g, 'Ana').put(f"/api/watchlist/{g['M2']}/discord", json={'share': True})
    c(g, 'Bo').put('/api/me/notifications', json={'channels': {'email': True}})
    item = watch_item(digest(), g['S2'])
    r = client().post('/api/internal/digest/delivered', headers=H,
                      json={'watchlist_ids': [w['watchlist_id'] for w in item['watchers']] + item['quiet_ids']}).json
    assert r == {'marked': 4, 'emailed': 1}                                            # of the three not named, only Bo


def test_never_ask_again(watching):
    g = watching
    r = c(g, 'Ana').put(f"/api/watchlist/{g['M2']}/discord", json={'share': False, 'remember': True}).json
    assert r['prefs']['watchlist'] == 'never' and r['discord_share'] is False
    assert [i['discord_share'] for i in c(g, 'Ana').get('/api/watchlist').json] == [False]


def test_bot_lookups_only_cover_server_members(going):
    g = going
    lb = client().get('/api/internal/leaderboard', query_string={'group_id': 1}, headers=H).json
    names = [r['user']['name'] for r in lb['rows']]
    assert 'Ana' in names and 'Bo' not in names and 'Cy' not in names and lb['hidden'] >= 3
    assert all('email' not in r['user'] for r in lb['rows']) and all(r['place'] >= 1 for r in lb['rows'])
    picker = [m['name'] for m in client().get('/api/internal/members', query_string={'group_id': 1}, headers=H).json]
    assert 'Ana' in picker and 'Bo' not in picker and 'Cy' not in picker
    assert client().get('/api/internal/watchlist', query_string={'member_id': g['Cy'], 'discord_user_id': '7101'},
                        headers=H).status_code == 404
    for path, q in (('profile', {'member_discord_id': '7102'}), ('history', {'member_discord_id': '7102', 'group_id': 1}),
                    ('compare', {'discord_user_id': '7101', 'member_discord_id': '7102', 'group_id': 1})):
        assert client().get(f'/api/internal/{path}', query_string=q, headers=H).status_code == 404


def test_leaving_the_server(going):
    from app import app, db, DiscordPost, ShowtimeThread
    g = going
    with app.app_context():
        db.session.add(ShowtimeThread(showtime_id=g['S1'], group_id=1, guild_id='1', channel_id='2', thread_id='77001'))
        db.session.commit()
    c(g, 'Ana').post('/api/messages', json={'showtime_id': g['S1'], 'group_id': 1, 'body': 'hi', 'to_discord': True})
    with app.app_context():
        inv = DiscordPost(group_id=1, kind='invite', user_id=g['Ana'], ref_id=g['S1'], post_at=datetime.now(), status='posted', message_id='5')
        db.session.add(inv)
        ShowtimeThread.query.filter_by(thread_id='77001').first().card_dirty = False
        DiscordPost.query.filter_by(user_id=g['Ana'], kind='rsvp', status='pending').update({'post_at': datetime.now()})
        db.session.commit()
        inv_id = inv.id
    assert sync(left=['7101'])['left'] == 1
    assert in_app(lambda: (ShowtimeThread.query.filter_by(thread_id='77001').first().card_dirty,
                           db.session.get(DiscordPost, inv_id).dirty)) == (True, True)      # cards and invites refresh
    items = {x['id']: x for x in due()}
    assert items[inv_id]['action'] == 'edit' and items[inv_id]['data']['by'] is None          # unsigned
    assert 'Ana' not in [p['name'] for p in items[inv_id]['data']['card']['going']]
    assert in_app(lambda: {p.status for p in DiscordPost.query.filter_by(user_id=g['Ana'], kind='rsvp')}) == {'cancelled'}
    assert not any(x['kind'] == 'rsvp' for x in items.values())
    assert client().get('/api/internal/discussion/outbox', query_string={'group_id': 1}, headers=H).json['posts'] == []
    assert sync(joined=['7101'])['joined'] == 1 and c(g, 'Ana').get('/api/discord/prefs').json['available']
    assert sync(full=True, ids=['7104'])['left'] >= 2 and not c(g, 'Ana').get('/api/discord/prefs').json['available']

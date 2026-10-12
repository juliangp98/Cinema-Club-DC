"""Screening discussions mirrored with Discord threads (R3/R3d): a comment
waits for a thread, the thread backfills, messages go both ways, deletes and
edits follow, the starter card refreshes, a deleted thread unlinks."""
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, client, setup_db

THREAD = {'guild_id': '900', 'channel_id': '901', 'thread_id': '5001', 'starter_message_id': '5000'}


@pytest.fixture
def club():
    """Thread Club (the Discord server's club): Ana (1001, Discord picture)
    and Bo (1002, own picture). SIRÂT (70mm) in 2 days with 12 comments from
    before threads existed; Ana's going. HAMNET in 3 days."""
    import app as A
    from app import app, db, User, Group, GroupMembership, Showtime, Movie, Theatre, Message, RSVP
    setup_db()
    now_utc, now = datetime.utcnow(), datetime.now()
    with app.app_context():
        tid = Theatre.query.filter_by(slug='afi').first().id
        s1 = Showtime(movie_id=Movie.query.filter_by(title='SIRÂT').first().id, theatre_id=tid, format_label='70mm',
                      start_time=now + timedelta(days=2), end_time=now + timedelta(days=2, hours=2))
        s2 = Showtime(movie_id=Movie.query.filter_by(title='HAMNET').first().id, theatre_id=tid,
                      start_time=now + timedelta(days=3), end_time=now + timedelta(days=3, hours=2))
        g = Group(name='Thread Club', slug='thread-club', is_public=False)
        db.session.add_all([s1, s2, g])
        db.session.flush()
        ana = User(email='ana10@test.dev', name='Ana', is_active=True, discord_user_id='1001',
                   avatar_url='https://cdn.discordapp.com/avatars/1001/x.png')
        bo = User(email='bo10@test.dev', name='Bo', is_active=True, avatar_url='https://example.com/me.png', discord_user_id='1002')
        db.session.add_all([ana, bo])
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=g.id, status='active'),
                            GroupMembership(user_id=bo.id, group_id=g.id, status='active')])
        for i in range(12):
            db.session.add(Message(user_id=bo.id if i % 2 else ana.id, showtime_id=s1.id, group_id=g.id,
                                   body=f'old {i}', created_at=now_utc - timedelta(days=2) + timedelta(minutes=i)))
        db.session.add(RSVP(user_id=ana.id, showtime_id=s1.id, group_id=g.id, status='going'))
        db.session.commit()
        ids = {'s1': s1.id, 's2': s2.id, 'group': g.id, 'ana': ana.id, 'bo': bo.id, 'now': now_utc}
    A.DISCORD_GROUP_ID = ids['group']
    all_linked_present()
    return ids


def outbox(c):
    return client().get('/api/internal/discussion/outbox', query_string={'group_id': c['group']}, headers=H).json


def thread_info(c):
    return client().get('/api/internal/discussion/thread', query_string={'showtime_id': c['s1'], 'group_id': c['group']}, headers=H).json


def comment(c, who, body):
    return client(c[who]).post('/api/messages', json={'showtime_id': c['s1'], 'group_id': c['group'], 'body': body})


def register(c, **extra):
    return client().post('/api/internal/discussion/threads', json={'showtime_id': c['s1'], 'group_id': c['group'], **THREAD, **extra},
                         headers=H)


def messages(c):
    return client(c['ana']).get('/api/messages', query_string={'showtime_id': c['s1'], 'group_id': c['group']}).json


@pytest.fixture
def threaded(club):
    """Bo commented on the site; the bot made the thread and mirrored his
    comment (→ 7001) and the last 10 old ones (→ 6000…6009)."""
    from app import app, Message
    m1 = comment(club, 'bo', 'Who is in for 70mm?').json
    register(club)
    with app.app_context():
        olds = [m.id for m in Message.query.filter_by(showtime_id=club['s1']).order_by(Message.created_at) if m.body.startswith('old')][2:]
    client().post('/api/internal/discussion/mirrored', headers=H, json={'items': [{'message_id': m1['id'], 'discord_message_id': '7001'}]
                  + [{'message_id': mid, 'discord_message_id': f'60{i:02d}'} for i, mid in enumerate(olds)]})
    return {**club, 'm1': m1}


def from_discord(c, **k):
    return client().post('/api/internal/discussion/messages', headers=H,
                         json={'discord_user_id': '1001', 'create': '0', 'group_id': c['group'], **k})


@pytest.fixture
def discussed(threaded):
    """Ana typed in the thread (8001, later edited) and posted with /discuss (8010)."""
    from_discord(threaded, thread_id='5001', discord_message_id='8001', body='I am in, middle left')
    client().post('/api/internal/discussion/messages/edit', json={'discord_message_id': '8001', 'body': 'I am in, front row'}, headers=H)
    from_discord(threaded, thread_id='5001', discord_message_id='8010', body='Posted with /discuss', source='discord_bot')
    return threaded


def test_old_comments_are_not_sent_to_discord(club):
    assert outbox(club)['posts'] == []


def test_a_site_comment_waits_for_a_thread(club):
    r = comment(club, 'bo', 'Who is in for 70mm?')
    assert r.status_code == 201 and r.json['can_delete'] and not r.json['via_discord']
    assert outbox(club)['posts'] == []                                         # a comment never starts a thread


def test_a_new_thread_starts_with_a_card_and_recent_comments(club):
    comment(club, 'bo', 'Who is in for 70mm?')
    info = thread_info(club)
    assert info['thread'] is None and info['earlier_total'] == 12
    assert [x['body'] for x in info['backfill']] == [f'old {i}' for i in range(2, 12)]        # the last 10, oldest first
    assert info['backfill'][0]['author']['avatar_url'] == 'https://cdn.discordapp.com/avatars/1001/x.png'
    assert info['backfill'][1]['author']['avatar_url'] is None                              # only Discord pictures
    card = info['card']
    assert card['title'] == 'SIRÂT' and card['format_label'] == '70mm' and card['site_path'] == f"/calendar?showtime={club['s1']}"
    assert card['going'] == [{'name': 'Ana', 'discord_user_id': '1001'}]


def test_registering_the_thread_sends_the_waiting_comment(club):
    m1 = comment(club, 'bo', 'Who is in for 70mm?').json
    r = register(club)
    assert r.status_code == 201 and r.json['url'] == 'https://discord.com/channels/900/5001'
    dup = register(club, thread_id='5099', starter_message_id=None)
    assert dup.status_code == 409 and dup.json['thread']['thread_id'] == '5001'              # a racing second thread
    posts = outbox(club)['posts']
    assert [p['message_id'] for p in posts] == [m1['id']]
    assert posts[0]['author']['name'] == 'Bo' and posts[0]['author']['avatar_url'] is None


def test_the_thread_shows_up_across_the_site(threaded):
    c = threaded
    assert outbox(c)['posts'] == []                                                          # mirrored: out of the outbox
    assert client().get('/api/internal/discussion/threads', query_string={'group_id': c['group']}, headers=H).json == ['5001']
    a = client(c['ana'])
    assert a.get(f"/api/showtimes/{c['s1']}", query_string={'group_id': c['group']}).json['discord_thread_url'] == 'https://discord.com/channels/900/5001'
    week = a.get('/api/showtimes', query_string={'group_id': c['group'], 'start': datetime.now().isoformat(),
                                                 'end': (datetime.now() + timedelta(days=5)).isoformat()}).json
    assert {s['id']: s['discord_thread_url'] for s in week if s['id'] in (c['s1'], c['s2'])} == {
        c['s1']: 'https://discord.com/channels/900/5001', c['s2']: None}
    feed = a.get('/api/feed', query_string={'group_id': c['group']}).json
    assert next(x for x in feed['cards'] if x.get('showtime', {}).get('id') == c['s1'])['showtime']['discord_thread_url'].endswith('/5001')


def test_discord_messages_become_comments(threaded):
    c = threaded
    assert from_discord(c, thread_id='5001', discord_message_id='8001', body='I am in, middle left').status_code == 201
    assert from_discord(c, thread_id='5001', discord_message_id='8001', body='I am in, middle left').json.get('duplicate')
    assert from_discord(c, thread_id='9999', discord_message_id='8002', body='x').status_code == 404
    assert from_discord(c, thread_id='5001', discord_message_id='8003', body='  ').status_code == 400
    assert outbox(c)['posts'] == []                                                          # no loop back to Discord
    last = messages(c)[-1]
    assert last['body'] == 'I am in, middle left' and last['via_discord'] and not last['can_delete']
    assert client(c['ana']).delete(f"/api/messages/{last['id']}").status_code == 400         # typed in Discord: delete it there


def test_edits_follow_only_messages_typed_in_discord(discussed):
    assert messages(discussed)[-2]['body'] == 'I am in, front row'
    last = messages(discussed)[-1]
    assert last['via_discord'] and last['can_delete']                                       # /discuss posts: deletable on the site
    client().post('/api/internal/discussion/messages/edit', json={'discord_message_id': '8010', 'body': 'tampered'}, headers=H)
    assert messages(discussed)[-1]['body'] == 'Posted with /discuss'


def test_deleting_a_mirrored_comment_removes_its_discord_copy(threaded):
    c = threaded
    assert client(c['bo']).delete(f"/api/messages/{c['m1']['id']}").status_code == 200
    deletions = outbox(c)['deletions']
    assert [(d['thread_id'], d['discord_message_id']) for d in deletions] == [('5001', '7001')]
    client().post(f"/api/internal/discussion/deletions/{deletions[0]['id']}/done", headers=H)
    assert outbox(c)['deletions'] == []
    r = comment(c, 'bo', 'never mind').json
    client(c['bo']).delete(f"/api/messages/{r['id']}")
    assert outbox(c)['deletions'] == [] and outbox(c)['posts'] == []                        # never reached Discord: nothing to undo


def test_only_your_own_comments_and_discord_deletes(discussed):
    c = discussed
    ms = messages(c)
    bos = next(m for m in ms if m['user']['id'] == c['bo'])
    assert client(c['ana']).delete(f"/api/messages/{bos['id']}").status_code in (400, 403, 404)
    assert client(c['bo']).delete(f"/api/messages/{ms[-1]['id']}").status_code in (400, 403, 404)
    n = client().post('/api/internal/discussion/messages/delete', json={'discord_message_ids': ['8010', '6000']}, headers=H).json['deleted']
    assert n == 2                                                                            # deleted in Discord: gone here


def test_the_starter_card_refreshes_after_a_quiet_spell(threaded):
    from app import app, db, ShowtimeThread
    c = threaded
    assert outbox(c)['cards'] == []
    client(c['bo']).post('/api/rsvp', json={'showtime_id': c['s1'], 'status': 'maybe', 'group_id': c['group']})
    assert outbox(c)['cards'] == []                                                          # waits for the 3-minute window
    with app.app_context():
        ShowtimeThread.query.filter_by(thread_id='5001').first().card_refreshed_at = c['now'] - timedelta(minutes=5)
        db.session.commit()
    [card] = outbox(c)['cards']
    assert card['starter_message_id'] == '5000' and card['card']['maybe'] == [{'name': 'Bo', 'discord_user_id': '1002'}]
    client().post('/api/internal/discussion/cards/5001/refreshed', headers=H)
    assert outbox(c)['cards'] == []
    client(c['bo']).post('/api/rsvp', json={'showtime_id': c['s1'], 'status': None, 'group_id': c['group']})
    with app.app_context():
        assert ShowtimeThread.query.filter_by(thread_id='5001').first().card_dirty           # removing an RSVP too


def test_a_thread_deleted_in_discord_unlinks(discussed):
    from app import app, Message, ShowtimeThread
    c = discussed
    client().post('/api/internal/discussion/threads/5001/unlink', headers=H)
    with app.app_context():
        assert ShowtimeThread.query.count() == 0
        assert Message.query.filter(Message.showtime_id == c['s1'], Message.discord_message_id.isnot(None)).count() == 0
        assert Message.query.filter_by(showtime_id=c['s1']).count() > 10                     # comments kept
    info = thread_info(c)
    assert info['thread'] is None and info['backfill'][-1]['body'] == 'Posted with /discuss'   # the next thread backfills again

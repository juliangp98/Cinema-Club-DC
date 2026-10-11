"""discussion_threads"""
from helpers import H, client, Checks, WORK


def test_discussion_threads():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, Showtime, Movie, Theatre, Message, RSVP,
                     ShowtimeThread, DiscordDeletion, INTERNAL_API_TOKEN)

    H = {'X-Internal-Token': INTERNAL_API_TOKEN}
    NOW = datetime.utcnow()

    with app.app_context():
        db.create_all(); migrate()
        now_local = datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        mid = Movie.query.filter_by(title='SIRÂT').first().id
        mid2 = Movie.query.filter_by(title='HAMNET').first().id
        s1 = Showtime(movie_id=mid, theatre_id=tid, start_time=now_local + timedelta(days=2), end_time=now_local + timedelta(days=2, hours=2), format_label='70mm')
        s2 = Showtime(movie_id=mid2, theatre_id=tid, start_time=now_local + timedelta(days=3), end_time=now_local + timedelta(days=3, hours=2))
        g = Group(name='Thread Club', slug='thread-club', is_public=False)
        db.session.add_all([s1, s2, g]); db.session.flush()
        ana = User(email='ana10@test.dev', name='Ana', is_active=True, discord_user_id='1001',
                   avatar_url='https://cdn.discordapp.com/avatars/1001/x.png')
        bo = User(email='bo10@test.dev', name='Bo', is_active=True, avatar_url='https://example.com/me.png',
                  discord_user_id='1002')   # only server members' comments reach Discord
        db.session.add_all([ana, bo]); db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=g.id, status='active'),
                            GroupMembership(user_id=bo.id, group_id=g.id, status='active')])
        # 12 comments from before threads existed, oldest 2 days ago
        for i in range(12):
            db.session.add(Message(user_id=bo.id if i % 2 else ana.id, showtime_id=s1.id, group_id=g.id,
                                   body=f'old {i}', created_at=NOW - timedelta(days=2) + timedelta(minutes=i)))
        db.session.add(RSVP(user_id=ana.id, showtime_id=s1.id, group_id=g.id, status='going'))
        db.session.commit()
        S1, S2, G, A, B = s1.id, s2.id, g.id, ana.id, bo.id

    def as_user(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, b, bot = as_user(A), as_user(B), app.test_client()
    def outbox(): return bot.get('/api/internal/discussion/outbox', query_string={'group_id': G}, headers=H).get_json()

    import app as _A; _A.DISCORD_GROUP_ID = G   # this test's club is the one tied to the server
    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- migration + legacy ---')
    check('pre-existing comments are not queued for Discord', outbox()['posts'] == [])

    print('--- a site comment waits for a thread (R3d) ---')
    r = b.post('/api/messages', json={'showtime_id': S1, 'group_id': G, 'body': 'Who is in for 70mm?'})
    m1 = r.get_json()
    check('site comment saved as deletable, not via Discord', r.status_code == 201 and m1['can_delete'] and not m1['via_discord'])
    ob = outbox()
    check('…but waits: a comment never starts a thread', ob['posts'] == [], ob['posts'])
    info = bot.get('/api/internal/discussion/thread', query_string={'showtime_id': S1, 'group_id': G}, headers=H).get_json()
    check('no thread yet: card + last 10 earlier comments (oldest first), not the pending one',
          info['thread'] is None and info['earlier_total'] == 12 and [x['body'] for x in info['backfill']] == [f'old {i}' for i in range(2, 12)], info.get('backfill'))
    check('backfill keeps Discord avatars for linked members only', info['backfill'][0]['author']['avatar_url'] == 'https://cdn.discordapp.com/avatars/1001/x.png'
          and info['backfill'][1]['author']['avatar_url'] is None)
    check('card: title, format, who\'s going (with Discord ids)', info['card']['title'] == 'SIRÂT' and info['card']['format_label'] == '70mm'
          and info['card']['going'] == [{'name': 'Ana', 'discord_user_id': '1001'}] and info['card']['site_path'] == f'/calendar?showtime={S1}', info['card'])

    print('--- bot registers the thread, mirrors ---')
    reg = bot.post('/api/internal/discussion/threads', json={'showtime_id': S1, 'group_id': G, 'guild_id': '900', 'channel_id': '901',
                                                            'thread_id': '5001', 'starter_message_id': '5000'}, headers=H)
    check('thread registered', reg.status_code == 201 and reg.get_json()['url'] == 'https://discord.com/channels/900/5001')
    dup = bot.post('/api/internal/discussion/threads', json={'showtime_id': S1, 'group_id': G, 'guild_id': '900', 'channel_id': '901',
                                                            'thread_id': '5099'}, headers=H)
    check('a racing second thread is refused with the existing one', dup.status_code == 409 and dup.get_json()['thread']['thread_id'] == '5001')
    ob = outbox()
    check('…then the waiting comment is in the outbox with its author', [p['message_id'] for p in ob['posts']] == [m1['id']]
          and ob['posts'][0]['author']['name'] == 'Bo' and ob['posts'][0]['author']['avatar_url'] is None, ob['posts'])
    with app.app_context():
        olds = [m.id for m in Message.query.filter_by(showtime_id=S1).order_by(Message.created_at) if m.body.startswith('old')][2:]
    bot.post('/api/internal/discussion/mirrored', json={'items': [{'message_id': m1['id'], 'discord_message_id': '7001'}]
             + [{'message_id': mid_, 'discord_message_id': f'60{i:02d}'} for i, mid_ in enumerate(olds)]}, headers=H)
    check('mirrored comments leave the outbox', outbox()['posts'] == [])
    check('thread list for the bot', bot.get('/api/internal/discussion/threads', query_string={'group_id': G}, headers=H).get_json() == ['5001'])
    st = a.get(f'/api/showtimes/{S1}', query_string={'group_id': G}).get_json()
    check('site drawer gets the "Discuss in Discord" link', st['discord_thread_url'] == 'https://discord.com/channels/900/5001')
    lst = a.get('/api/showtimes', query_string={'group_id': G, 'start': (datetime.now()).isoformat(), 'end': (datetime.now() + timedelta(days=5)).isoformat()}).get_json()
    check('calendar list too (and none for screenings without a thread)', {s['id']: s['discord_thread_url'] for s in lst if s['id'] in (S1, S2)}
          == {S1: 'https://discord.com/channels/900/5001', S2: None})
    fd = a.get('/api/feed', query_string={'group_id': G}).get_json()
    check('feed cards carry it', next(c for c in fd['cards'] if c.get('showtime', {}).get('id') == S1)['showtime']['discord_thread_url'].endswith('/5001'))

    print('--- Discord -> site ---')
    msg = lambda **k: bot.post('/api/internal/discussion/messages', json={'discord_user_id': '1001', 'create': '0', 'group_id': G, **k}, headers=H)
    r = msg(thread_id='5001', discord_message_id='8001', body='I am in, middle left')
    check('thread message becomes the member\'s comment', r.status_code == 201)
    r2 = msg(thread_id='5001', discord_message_id='8001', body='I am in, middle left')
    check('…once (idempotent per Discord message)', r2.get_json().get('duplicate'))
    check('unknown thread -> 404', msg(thread_id='9999', discord_message_id='8002', body='x').status_code == 404)
    check('empty body -> 400', msg(thread_id='5001', discord_message_id='8003', body='  ').status_code == 400)
    check('Discord comments are not queued back to Discord (no loop)', outbox()['posts'] == [])
    ms = a.get('/api/messages', query_string={'showtime_id': S1, 'group_id': G}).get_json()
    last = ms[-1]
    check('site shows it via Discord; its author cannot delete it on the site', last['body'] == 'I am in, middle left' and last['via_discord'] and not last['can_delete'])
    check('site delete of a Discord-typed comment is refused', a.delete(f"/api/messages/{last['id']}").status_code == 400)
    bot.post('/api/internal/discussion/messages/edit', json={'discord_message_id': '8001', 'body': 'I am in, front row'}, headers=H)
    check('Discord edits update the site copy', a.get('/api/messages', query_string={'showtime_id': S1, 'group_id': G}).get_json()[-1]['body'] == 'I am in, front row')
    r = msg(thread_id='5001', discord_message_id='8010', body='Posted with /discuss', source='discord_bot')
    ms = a.get('/api/messages', query_string={'showtime_id': S1, 'group_id': G}).get_json()
    check('/discuss posts (bot-made) are deletable on the site by their author', ms[-1]['via_discord'] and ms[-1]['can_delete'])
    bot.post('/api/internal/discussion/messages/edit', json={'discord_message_id': '8010', 'body': 'tampered'}, headers=H)
    check("edits only apply to messages typed in Discord", a.get('/api/messages', query_string={'showtime_id': S1, 'group_id': G}).get_json()[-1]['body'] == 'Posted with /discuss')

    print('--- deletes ---')
    r = b.delete(f"/api/messages/{m1['id']}")
    ob = outbox()
    check('site delete of a mirrored comment queues removing its Discord copy', r.status_code == 200 and
          [(d['thread_id'], d['discord_message_id']) for d in ob['deletions']] == [('5001', '7001')], ob['deletions'])
    bot.post(f"/api/internal/discussion/deletions/{ob['deletions'][0]['id']}/done", headers=H)
    check('…done once the bot removes it', outbox()['deletions'] == [])
    bos = next(m for m in ms if m['user']['id'] == B)
    check("can't delete someone else's comment", a.delete(f"/api/messages/{bos['id']}").status_code in (400, 403, 404)
          and b.delete(f"/api/messages/{ms[-1]['id']}").status_code in (400, 403, 404))
    r = b.post('/api/messages', json={'showtime_id': S1, 'group_id': G, 'body': 'never mind'}).get_json()
    b.delete(f"/api/messages/{r['id']}")
    check('deleting before it reached Discord needs no Discord cleanup', outbox()['deletions'] == [] and outbox()['posts'] == [])
    n = bot.post('/api/internal/discussion/messages/delete', json={'discord_message_ids': ['8010', '6000']}, headers=H).get_json()['deleted']
    check('deleted in Discord (own message, or a moderator removing a copy) -> gone from the site', n == 2)

    print('--- starter card refresh ---')
    check('no card refresh needed yet', outbox()['cards'] == [])
    b.post('/api/rsvp', json={'showtime_id': S1, 'status': 'maybe', 'group_id': G})
    check('an RSVP waits for the 3-minute card window', outbox()['cards'] == [])
    with app.app_context():
        t = ShowtimeThread.query.filter_by(thread_id='5001').first(); t.card_refreshed_at = NOW - timedelta(minutes=5); db.session.commit()
    cards = outbox()['cards']
    check('…then the card is due, with the new Maybe', len(cards) == 1 and cards[0]['starter_message_id'] == '5000'
          and cards[0]['card']['maybe'] == [{'name': 'Bo', 'discord_user_id': '1002'}], cards)
    bot.post('/api/internal/discussion/cards/5001/refreshed', headers=H)
    check('refreshed -> not due', outbox()['cards'] == [])
    b.post('/api/rsvp', json={'showtime_id': S1, 'status': None, 'group_id': G})
    with app.app_context():
        check('removing an RSVP marks it dirty too', ShowtimeThread.query.filter_by(thread_id='5001').first().card_dirty)

    print('--- thread deleted in Discord ---')
    bot.post('/api/internal/discussion/threads/5001/unlink', headers=H)
    with app.app_context():
        check('unlinked: mapping gone, Discord ids cleared, comments kept', ShowtimeThread.query.count() == 0
              and Message.query.filter(Message.showtime_id == S1, Message.discord_message_id.isnot(None)).count() == 0
              and Message.query.filter_by(showtime_id=S1).count() > 10)
    info = bot.get('/api/internal/discussion/thread', query_string={'showtime_id': S1, 'group_id': G}, headers=H).get_json()
    check('next thread would backfill again (incl. Discord-made comments)', info['thread'] is None and info['backfill'][-1]['body'] == 'I am in, front row', info['backfill'][-1])
    checks.done()

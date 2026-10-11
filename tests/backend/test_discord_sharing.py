"""discord_sharing"""
from helpers import H, client, Checks, WORK


def test_discord_sharing():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta, timezone
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Message, Poll,
                     PollCategory, PollOption, DiscordPost, SharedRsvp, ShowtimeThread, INTERNAL_API_TOKEN)
    import app as A
    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        other = Group(name='No Discord', slug='nodisc-r3d', is_public=False); db.session.add(other); db.session.flush()
        us = [User(email=f'd{i}@r3d.test', name=n, is_active=True, discord_user_id=str(7700 + i)) for i, n in enumerate(['Ana', 'Bo', 'Cy'])]
        db.session.add_all(us); db.session.flush()
        for u, role in zip(us, ('admin', 'member', 'member')):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role=role))
            db.session.add(GroupMembership(user_id=u.id, group_id=other.id, status='active'))
        now = datetime.now()
        def show(title, days, hour=19):
            m = Movie(title=title); db.session.add(m); db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=(now + timedelta(days=days)).replace(hour=hour, minute=30, second=0, microsecond=0))
            db.session.add(s); db.session.flush(); return s.id
        S1, S2, S3, S4 = show('ALPHA', 2), show('BRAVO', 3), show('CHARLIE', 4), show('DELTA', 5)
        db.session.commit()
        ANA, BO, CY = (u.id for u in us)

    def client(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    ana, bo, cy = client(ANA), client(BO), client(CY)
    bot = app.test_client()
    due = lambda: bot.get('/api/internal/discord/posts/due', query_string={'group_id': 1}, headers=H).json
    done = lambda pid, **b: bot.post(f'/api/internal/discord/posts/{pid}/done', json=b, headers=H)
    def fast_forward():
        with app.app_context():
            DiscordPost.query.filter_by(status='pending').filter(DiscordPost.post_at <= datetime.now() + timedelta(days=90)) \
                .filter(DiscordPost.kind == 'rsvp').update({'post_at': datetime.now() - timedelta(seconds=1)})
            db.session.commit()
    rsvp = lambda c, sid, status, g=1: c.post('/api/rsvp', json={'showtime_id': sid, 'status': status, 'group_id': g}).json

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- prefs ---')
    r = ana.get('/api/discord/prefs').json
    check('default: ask for everything; available in the Discord group', r == {'prefs': {'rsvp': 'ask', 'poll': 'ask', 'comment': 'ask', 'watchlist': 'ask'}, 'available': True, 'reason': None}, r)
    r = cy.put('/api/discord/prefs', json={'rsvp': 'never', 'comment': 'bogus'}).json
    check('set a pref; bad values ignored', r['prefs'] == {'rsvp': 'never', 'poll': 'ask', 'comment': 'ask', 'watchlist': 'ask'})

    print('--- RSVP prompt ---')
    d = rsvp(ana, S1, 'going')
    check('ask: going on the site → prompt, nothing queued', d['discord']['prompt'] is True and d['discord']['my_share'] is None and due() == [])
    d = rsvp(ana, S1, 'going')
    check('same status again → no prompt', 'prompt' not in d['discord'])
    d = rsvp(cy, S1, 'going')
    check('never → no prompt', 'prompt' not in d['discord'] and d['discord']['my_share'] is None)
    d = rsvp(ana, S1, 'going', g=None) if False else ana.post('/api/rsvp', json={'showtime_id': S1, 'status': 'maybe', 'group_id': 0}).status_code
    d = rsvp(ana, S1, 'going', g=None) if False else None
    with app.app_context():
        oid = Group.query.filter_by(slug='nodisc-r3d').first().id
    d = rsvp(ana, S2, 'going', g=oid)
    check('other groups: no Discord at all', d['discord'] is None)

    print('--- share + batching ---')
    r = ana.post('/api/discord/shares', json={'kind': 'rsvp', 'group_id': 1, 'showtime_id': S1})
    check('share an RSVP', r.status_code == 201 and r.json['kind'] == 'rsvp' and r.json['status'] == 'pending', r.json)
    P1 = r.json['id']
    check('not due yet (batch window)', due() == [])
    rsvp(ana, S2, 'maybe')
    r2 = ana.post('/api/discord/shares', json={'kind': 'rsvp', 'group_id': 1, 'showtime_id': S2, 'remember': True})
    check('a second RSVP joins the same post; remember → always', r2.json['id'] == P1 and ana.get('/api/discord/prefs').json['prefs']['rsvp'] == 'always')
    d = rsvp(ana, S3, 'going')
    check('always: RSVP shares itself (same batch)', d['discord']['my_share']['id'] == P1 and 'prompt' not in d['discord'])
    r = bo.post('/api/discord/shares', json={'kind': 'rsvp', 'group_id': 1, 'showtime_id': S1})
    check("can't share an RSVP you haven't made", r.status_code == 400)
    st = ana.get(f'/api/showtimes/{S2}', query_string={'group_id': 1}).json
    check('screening shows your share', st['discord']['my_share']['id'] == P1)
    rsvp(ana, S3, 'not_going')
    fast_forward()
    items = due()
    check('due: one post, both remaining screenings, sorted', len(items) == 1 and items[0]['action'] == 'post'
          and [i['title'] for i in items[0]['data']['items']] == ['ALPHA', 'BRAVO'] and items[0]['data']['items'][1]['status'] == 'maybe'
          and items[0]['data']['user'] == 'Ana', items)
    done(P1, action='posted', message_id='555', jump_url='https://discord.com/channels/1/2/555')
    check('posted, nothing else due', due() == [])
    st = ana.get(f'/api/showtimes/{S1}', query_string={'group_id': 1}).json
    check('screening links to the post', st['discord']['my_share']['jump_url'].endswith('/555') and st['discord']['my_share']['status'] == 'posted')

    print('--- stale posts ---')
    rsvp(ana, S2, 'going')
    items = due()
    check('going instead of maybe → edit', len(items) == 1 and items[0]['action'] == 'edit' and items[0]['message_id'] == '555'
          and items[0]['data']['items'][1]['status'] == 'going')
    done(P1, action='edited')
    rsvp(ana, S1, None)
    items = due()
    check('RSVP removed → edited out', items[0]['action'] == 'edit' and [i['title'] for i in items[0]['data']['items']] == ['BRAVO'])
    done(P1, action='edited')
    r = ana.delete(f'/api/discord/shares/{P1}', query_string={'showtime_id': S2})
    items = due()
    check('unshare the last one → delete', items and items[0]['action'] == 'delete' and items[0]['message_id'] == '555', items)
    done(P1, action='deleted')
    check('then gone', due() == [] and ana.get(f'/api/showtimes/{S2}', query_string={'group_id': 1}).json['discord']['my_share'] is None)
    rsvp(ana, S4, 'going')       # always → pending post
    rsvp(ana, S4, 'not_going')
    with app.app_context():
        check('changed mind before it went out → cancelled', DiscordPost.query.order_by(DiscordPost.id.desc()).first().status == 'cancelled')

    print("--- who's in? ---")
    r = bo.post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': S3, 'note': 'Anyone?'})
    INV = r.json['id']
    check('invite created (now)', r.status_code == 201 and r.json['note'] == 'Anyone?')
    check('a second ask returns the same invite', cy.post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': S3}).json['id'] == INV)
    items = due()
    inv = next(i for i in items if i['id'] == INV)
    check('due with card, by, no ids', inv['action'] == 'post' and inv['data']['by'] == 'Bo' and inv['data']['card']['going'] == [])
    done(INV, action='posted', message_id='777', jump_url='u')
    rsvp(cy, S3, 'going')
    inv = next(i for i in due() if i['id'] == INV)
    check('someone RSVPs → invite card edited, names only', inv['action'] == 'edit' and inv['data']['card']['going'] == [{'name': 'Cy'}])
    done(INV, action='edited')
    check("others can't take it down", cy.delete(f'/api/discord/shares/{INV}').status_code == 403)
    check('a group admin can', ana.delete(f'/api/discord/shares/{INV}').status_code == 200)
    inv = next(i for i in due() if i['id'] == INV)
    check('removed → delete', inv['action'] == 'delete')
    done(INV, action='deleted')
    r = bo.post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': S4, 'post_at': (now + timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')})
    check('scheduled invite stays pending', r.status_code == 201 and all(i['id'] != r.json['id'] for i in due()))
    check('post now', bo.post(f"/api/discord/shares/{r.json['id']}/now").json['status'] == 'pending' and any(i['id'] == r.json['id'] for i in due()))
    check('a time past 60 days is refused', bo.post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': S1,
          'post_at': (now + timedelta(days=90)).strftime('%Y-%m-%dT%H:%M')}).status_code == 400)
    check('other groups refused', bo.post('/api/discord/shares', json={'kind': 'invite', 'group_id': oid, 'showtime_id': S1}).status_code == 400)

    print('--- polls ---')
    mk = lambda **kw: ana.post('/api/groups/1/polls', json={'title': kw.pop('title'), 'categories': [{'title': 'C', 'options': [{'text': 'x'}, {'text': 'y'}]}], **kw}).json
    pending_for = lambda pid, kind: [i for i in due() if i['kind'] == kind and i['data'] and i['data'].get('poll_id') == pid]
    p1 = mk(title='Now poll', announce='now')
    it = pending_for(p1['id'], 'poll')
    check('announce now → due post', len(it) == 1 and it[0]['data']['status'] == 'open')
    done(it[0]['id'], action='posted', message_id='900', jump_url='j')
    p2 = mk(title='Later poll', announce='later', announce_at=(now + timedelta(hours=3)).strftime('%Y-%m-%dT%H:%M'))
    p3 = mk(title='Quiet poll', announce='none')
    with app.app_context():
        later = DiscordPost.query.filter_by(kind='poll', ref_id=p2['id']).first()
        check('later → scheduled, none → nothing', later.status == 'pending' and later.post_at > now + timedelta(hours=2)
              and DiscordPost.query.filter_by(kind='poll', ref_id=p3['id']).count() == 0)
    g = ana.get(f"/api/polls/{p2['id']}").json
    check('poll page shows its Discord state', g['discord']['announce']['status'] == 'pending' and g['discord']['results'] is None)
    ana.put(f"/api/polls/{p1['id']}", json={'status': 'closed'})
    it = [i for i in due() if i['message_id'] == '900']
    check('closing the poll edits the announcement', it and it[0]['action'] == 'edit' and it[0]['data']['status'] == 'closed')
    done(it[0]['id'], action='edited')
    check('members cannot share polls', bo.post('/api/discord/shares', json={'kind': 'poll', 'group_id': 1, 'poll_id': p3['id']}).status_code == 403)
    check('results need scoring first', ana.post('/api/discord/shares', json={'kind': 'poll_results', 'group_id': 1, 'poll_id': p1['id']}).status_code == 400)
    cat = p1['categories'][0]
    ana.post(f"/api/polls/{p1['id']}/score", json={'winners': {str(cat['id']): cat['options'][0]['id']}})
    check('ask: scoring alone posts nothing', pending_for(p1['id'], 'poll_results') == [])
    r = ana.post('/api/discord/shares', json={'kind': 'poll_results', 'group_id': 1, 'poll_id': p1['id']})
    it = pending_for(p1['id'], 'poll_results')
    check('post results', r.status_code == 201 and it and it[0]['action'] == 'post' and 'top' in it[0]['data'])
    done(it[0]['id'], action='posted', message_id='901', jump_url='j')
    ana.put(f"/api/polls/{p1['id']}", json={'status': 'closed'})     # undo scoring
    it = [i for i in due() if i['message_id'] == '901']
    check('undo scoring → results post deleted', it and it[0]['action'] == 'delete')
    done(it[0]['id'], action='deleted')
    it = [i for i in due() if i['message_id'] == '900']
    check('...and the announcement refreshed', it and it[0]['action'] == 'edit')
    done(it[0]['id'], action='edited')
    ana.delete(f"/api/polls/{p1['id']}")
    it = [i for i in due() if i['message_id'] == '900']
    check('deleting the poll deletes its announcement', it and it[0]['action'] == 'delete')
    done(it[0]['id'], action='deleted')
    ana.put('/api/discord/prefs', json={'poll': 'always'})
    p4 = mk(title='Always poll')
    check('always + no choice on the form → announced', len(pending_for(p4['id'], 'poll')) == 1)
    ana.delete(f"/api/polls/{p2['id']}")
    with app.app_context():
        check('deleting a poll cancels its scheduled announcement', DiscordPost.query.filter_by(kind='poll', ref_id=p2['id']).first().status == 'cancelled')

    print('--- comments + threads ---')
    c1 = ana.post('/api/messages', json={'showtime_id': S2, 'group_id': 1, 'body': 'public', 'to_discord': True}).json
    c2 = ana.post('/api/messages', json={'showtime_id': S2, 'group_id': 1, 'body': 'site only', 'to_discord': False}).json
    box = lambda: [p['body'] for p in bot.get('/api/internal/discussion/outbox', query_string={'group_id': 1}, headers=H).json['posts']]
    check('no thread → comments wait (never start one)', box() == [])
    info = bot.get('/api/internal/discussion/thread', query_string={'showtime_id': S2, 'group_id': 1}, headers=H).json
    check('backfill skips site-only comments', [b['body'] for b in info['backfill']] == [] or 'site only' not in [b['body'] for b in info['backfill']])
    r = bo.post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': S2})
    st = bo.get(f'/api/showtimes/{S2}', query_string={'group_id': 1}).json
    check('start a thread → pending (shown on the screening)', r.status_code == 201 and st['discord']['thread_pending'])
    it = [i for i in due() if i['kind'] == 'thread']
    check('due: thread request', it and it[0]['data'] == {'showtime_id': S2})
    with app.app_context():
        db.session.add(ShowtimeThread(showtime_id=S2, group_id=1, guild_id='1', channel_id='2', thread_id='3333')); db.session.commit()
    done(it[0]['id'], action='posted', message_id='3333', jump_url='https://discord.com/channels/1/3333')
    check('once threaded, only the public comment goes out', box() == ['public'], box())
    r = bo.post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': S2})
    check('asking again just returns the thread', r.status_code == 200 and 'thread_url' in r.json)
    cy.put('/api/discord/prefs', json={'comment': 'never'})
    cy.post('/api/messages', json={'showtime_id': S2, 'group_id': 1, 'body': 'old client, never'})
    check('no choice sent → preference decides', 'old client, never' not in box())
    checks.done()

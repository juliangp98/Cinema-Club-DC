"""R5c club roles + bringing personal plans into a club."""
from helpers import H, client, Checks, WORK


def test_club_roles():
    checks = Checks()
    check = checks.check
    import sys, time
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, ShowtimeThread,
                     INTERNAL_API_TOKEN)
    import app as A
    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Role Club', slug='role-club', is_public=False); db.session.add(g); db.session.flush()
        us = {n: User(email=f'{n}@r5c.test', name=n.title(), is_active=True, discord_user_id=d)
              for n, d in (('ada', '5101'), ('olly', '5102'), ('mo', '5103'), ('vi', '5104'), ('newbie', '5105'))}
        db.session.add_all(us.values()); db.session.flush()
        for n, role in (('ada', 'admin'), ('olly', 'organizer'), ('mo', 'member'), ('vi', 'viewer')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g.id, status='active', role=role))
        now = datetime.now()
        mk = lambda t, d: Showtime(movie_id=(lambda m: (db.session.add(m), db.session.flush(), m.id)[2])(Movie(title=t)), theatre_id=th.id, start_time=now + timedelta(days=d))
        s1, s2, s3 = mk('ROLE ONE', 2), mk('ROLE TWO', 3), mk('ROLE THREE', 4)
        db.session.add_all([s1, s2, s3]); db.session.flush()
        db.session.add(ShowtimeThread(showtime_id=s1.id, group_id=g.id, guild_id='1', channel_id='2', thread_id='424242'))
        # newbie made personal plans before joining
        for s, st in ((s1, 'going'), (s2, 'maybe'), (s3, 'going')):
            db.session.add(RSVP(user_id=us['newbie'].id, showtime_id=s.id, group_id=None, status=st))
        db.session.commit()
        G = g.id; S1, S2, S3 = s1.id, s2.id, s3.id
        U = {n: u.id for n, u in us.items()}
    A.DISCORD_GROUP_ID = G

    def client(n):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = U[n]; s['seen'] = int(time.time())
        return c
    ada, olly, mo, vi, newbie = (client(n) for n in ('ada', 'olly', 'mo', 'vi', 'newbie'))
    code = lambda r: (r.status_code, (r.get_json(silent=True) or {}).get('code'))

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- read-only (viewer) ---')
    check('sees the club', vi.get(f'/api/showtimes/{S1}', query_string={'group_id': G}).status_code == 200
          and vi.get('/api/feed', query_string={'group_id': G}).status_code == 200 and vi.get(f'/api/groups/{G}/polls').status_code == 200)
    for label, r in (('RSVP', vi.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': G})),
                     ('react', vi.post('/api/reactions', json={'showtime_id': S1, 'emoji': '🔥', 'group_id': G})),
                     ('comment', vi.post('/api/messages', json={'showtime_id': S1, 'group_id': G, 'body': 'hi'})),
                     ("who's in", vi.post('/api/discord/shares', json={'kind': 'invite', 'group_id': G, 'showtime_id': S1}))):
        check(f"can't {label} (read_only)", code(r) == (403, 'read_only'), code(r))
    check('personal plans still fine', vi.post('/api/rsvp', json={'showtime_id': S2, 'status': 'going'}).status_code == 200)

    print('--- polls: organizer and up ---')
    mkpoll = lambda c: c.post(f'/api/groups/{G}/polls', json={'title': 'P', 'announce': 'none', 'categories': [{'title': 'C', 'options': [{'text': 'x'}, {'text': 'y'}]}]})
    check("members can't create polls", code(mkpoll(mo)) == (403, 'role'))
    r = mkpoll(olly); P = r.get_json()['id']; cat = r.get_json()['categories'][0]
    check('organizers can', r.status_code == 201)
    check('…edit, score, and post them to Discord', olly.put(f'/api/polls/{P}', json={'title': 'P2'}).status_code == 200
          and olly.post(f'/api/polls/{P}/score', json={'winners': {str(cat['id']): cat['options'][0]['id']}}).status_code == 200
          and olly.post('/api/discord/shares', json={'kind': 'poll_results', 'group_id': G, 'poll_id': P}).status_code == 201)
    P2 = mkpoll(ada).get_json()['id']
    check("read-only can't vote", code(vi.post(f'/api/polls/{P2}/vote', json={'votes': []})) == (403, 'read_only'))
    check('members can', mo.post(f'/api/polls/{P2}/vote', json={'votes': [{'category_id': mkpoll and cat['id'], 'option_id': cat['options'][0]['id']}]}).status_code in (200, 400))
    check("organizers can't manage members or roles", code(olly.put(f'/api/groups/role-club/members/{U["mo"]}/role', json={'role': 'viewer'}))[0] == 403
          and olly.post('/api/admin/invite', json={'email': 'x@r5c.test', 'group_id': G}).status_code == 403)

    print('--- admins grant and revoke ---')
    r = ada.put(f'/api/groups/role-club/members/{U["vi"]}/role', json={'role': 'member'})
    check('promote read-only → member', r.status_code == 200 and r.get_json()['role'] == 'member')
    check('…who can now RSVP', vi.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': G}).status_code == 200)
    check('unknown roles refused', ada.put(f'/api/groups/role-club/members/{U["vi"]}/role', json={'role': 'owner'}).status_code == 400)
    check("the only admin can't demote themselves", code(ada.put(f'/api/groups/role-club/members/{U["ada"]}/role', json={'role': 'member'})) == (400, 'last_admin'))
    check("…or leave", code(ada.delete(f'/api/groups/role-club/members/{U["ada"]}')) == (400, 'last_admin'))
    ada.put(f'/api/groups/role-club/members/{U["olly"]}/role', json={'role': 'admin'})
    check('with a second admin, they can step down', ada.put(f'/api/groups/role-club/members/{U["ada"]}/role', json={'role': 'organizer'}).status_code == 200)
    check('…and the new admin now manages roles', olly.put(f'/api/groups/role-club/members/{U["vi"]}/role', json={'role': 'viewer'}).status_code == 200)

    print('--- Discord: same rules through the bot ---')
    bot = app.test_client()
    who = lambda d: {'discord_user_id': d, 'create': '0', 'group_id': G}
    check('/rsvp for read-only → read_only', code(bot.post('/api/internal/rsvp', json={**who('5104'), 'showtime_id': S1, 'status': 'going'}, headers=H)) == (403, 'read_only'))
    check('/vote for read-only → read_only', code(bot.post(f'/api/internal/polls/{P2}/vote', json={**who('5104'), 'votes': []}, headers=H)) == (403, 'read_only'))
    check('Discuss button comment → refused', code(bot.post('/api/internal/discussion/messages', json={**who('5104'), 'thread_id': '424242', 'discord_message_id': '9001', 'body': 'x', 'source': 'discord_bot'}, headers=H)) == (403, 'read_only'))
    check('typed in the thread → still mirrors', bot.post('/api/internal/discussion/messages', json={**who('5104'), 'thread_id': '424242', 'discord_message_id': '9002', 'body': 'typed'}, headers=H).status_code == 201)
    check("bot RSVP for someone outside the club → refused", bot.post('/api/internal/rsvp', json={**who('5105'), 'showtime_id': S1, 'status': 'going'}, headers=H).status_code == 403)

    print('--- bringing personal plans along ---')
    with app.app_context():
        db.session.add(GroupMembership(user_id=U['newbie'], group_id=G, status='active', role='member'))
        db.session.add(RSVP(user_id=U['newbie'], showtime_id=S3, group_id=G, status='maybe'))   # already planned S3 with the club
        db.session.commit()
    lst = newbie.get(f'/api/groups/{G}/personal-plans').get_json()['items']
    check('lists your upcoming personal plans', [i['showtime_id'] for i in lst] == [S1, S2, S3], lst)
    check("read-only members aren't asked", vi.get(f'/api/groups/{G}/personal-plans').status_code == 403)
    r = newbie.post(f'/api/groups/{G}/personal-plans', json={'showtime_ids': [S1, S3]})
    check('ticked plans move into the club', r.get_json()['moved'] == 1)
    with app.app_context():
        rows = {(x.showtime_id, x.group_id): x.status for x in RSVP.query.filter_by(user_id=U['newbie'])}
        check('S1 now a club RSVP; S2 stays personal; S3 keeps the club RSVP (no duplicate)',
              rows == {(S1, G): 'going', (S2, None): 'maybe', (S3, G): 'maybe'}, rows)
        check("the screening's Discord card refreshes", ShowtimeThread.query.filter_by(thread_id='424242').first().card_dirty)
    m = mo.get(f'/api/showtimes/{S1}', query_string={'group_id': G}).get_json()
    check('the club now sees them going', 'Newbie' in [a['name'] for a in m['attendees']])
    check("the other personal plan stays invisible to the club", 'Newbie' not in [a['name'] for a in mo.get(f'/api/showtimes/{S2}', query_string={'group_id': G}).get_json()['maybes']])
    checks.done()

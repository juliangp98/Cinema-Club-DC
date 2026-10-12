"""R6a.1: only members who've linked Discord AND are in the club's server ever
appear there (shares, comments, names, pings); everyone else is a count."""
from helpers import H, client, Checks, WORK


def test_discord_membership():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, GroupMembership, RSVP, Showtime, Movie, Theatre, Message, Poll, Watchlist,
                     DiscordPost, ShowtimeThread, DiscordServerMember, Reaction, INTERNAL_API_TOKEN)
    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    # An old database (before the column): one linked and one unlinked member with a watchlist entry.
    import os, sqlite3
    _con = sqlite3.connect(os.environ['DATABASE_URL'].replace('sqlite:///', ''))
    (u1,), (u2,) = _con.execute('select id from user order by id limit 2').fetchall()
    _con.execute("update user set discord_user_id = '7190' where id = ?", (u1,))
    _con.executemany('insert into watchlist (user_id, movie_id) values (?, 1)', [(u1,), (u2,)])
    _con.commit(); _con.close()

    with app.app_context():
        db.create_all(); migrate()
        # The base database predates the column. Digest mentions are opt-in
        # (Oct 2026): everyone's entries start unchosen, linked or not.
        rows = [(w.user.discord_user_id is not None, w.share_discord) for w in Watchlist.query.all() if w.user]
        check('migration: digest mentions start unchosen for everyone (opt-in)',
              rows and all(s is None for _, s in rows), rows[:6])
        th = Theatre.query.filter_by(slug='afi').first()
        names = ['Ana', 'Bo', 'Cy', 'Dee', 'Org']
        did = {'Ana': '7101', 'Bo': '7102', 'Dee': '7104'}            # Cy and Org never linked Discord
        us = {n: User(email=f'{n.lower()}@r6d.test', name=n, is_active=True, discord_user_id=did.get(n)) for n in names}
        db.session.add_all(us.values()); db.session.flush()
        for n, u in us.items():
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active',
                                           role='organizer' if n in ('Ana', 'Org') else 'member'))
        now = datetime.now()
        def show(title, days):
            m = Movie(title=title); db.session.add(m); db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=(now + timedelta(days=days)).replace(hour=19, minute=0, second=0, microsecond=0))
            db.session.add(s); db.session.flush(); return s
        s1, s2 = show('ZETA ONE', 2), show('ZETA TWO', 3)
        db.session.commit()
        ID = {n: u.id for n, u in us.items()}
        S1, S2, M1, M2 = s1.id, s2.id, s1.movie_id, s2.movie_id

    def client(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    c = {n: client(i) for n, i in ID.items()}
    bot = app.test_client()
    due = lambda: bot.get('/api/internal/discord/posts/due', query_string={'group_id': 1}, headers=H).json
    sync = lambda **b: bot.post('/api/internal/discord/members', json=b, headers=H).json
    rsvp = lambda n, sid, status='going': c[n].post('/api/rsvp', json={'showtime_id': sid, 'status': status, 'group_id': 1}).json
    def go(fn):
        with app.app_context():
            return fn()

    print('--- before the bot reports members ---')
    c['Ana'].put('/api/discord/prefs', json={'rsvp': 'always'})
    r = c['Ana'].get('/api/discord/prefs').json
    check("nobody counts as in the server yet", r['available'] is False and r['reason'] == 'not_in_server', r)
    check('nothing is posted until the first sync', due() == [])

    print('--- member sync ---')
    r = sync(full=True, ids=['7101', '7104', '99999', 'junk'])
    check('full list saved (junk ignored)', r == {'members': 3, 'joined': 3, 'left': 0}, r)
    r = sync(full=True, ids=['7101', '7104', '99999'])
    check('same list again: no changes', r == {'members': 3, 'joined': 0, 'left': 0}, r)
    check('on_discord shows on your profile', c['Ana'].get('/api/auth/me').json['user']['on_discord'] is True
          and c['Bo'].get('/api/auth/me').json['user']['on_discord'] is False)
    prefs = {n: c[n].get('/api/discord/prefs').json for n in ('Ana', 'Bo', 'Cy')}
    check('sharing: available in the server; linked-but-not-in-server and unlinked are told why',
          prefs['Ana']['available'] and prefs['Bo']['reason'] == 'not_in_server' and prefs['Cy']['reason'] == 'not_linked', prefs)

    print('--- shares ---')
    for n in ('Bo', 'Cy'):
        c[n].put('/api/discord/prefs', json={'rsvp': 'always', 'poll': 'always', 'comment': 'always'})
    d = rsvp('Ana', S1)
    check('in the server + always: the RSVP is shared', d['discord'] and d['discord']['my_share'])
    for n in ('Bo', 'Cy', 'Dee'):
        rsvp(n, S1)
    d = rsvp('Bo', S2)
    check('not in the server: "always" shares nothing, and no Discord controls', d['discord'] is None)
    d = rsvp('Cy', S2)
    check('not linked: same', d['discord'] is None)
    r = c['Cy'].post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': S1})
    r2 = c['Bo'].post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': S1})
    check('sharing directly is refused for both', r.status_code == 403 and r.json['code'] == 'not_on_discord' and r2.status_code == 403)
    check('only Ana has anything queued', go(lambda: sorted({p.user_id for p in DiscordPost.query.filter(DiscordPost.status != 'cancelled')} )) == [ID['Ana']])

    print('--- polls ---')
    poll = {'title': 'Best ZETA', 'categories': [{'title': 'Pick', 'options': [{'text': 'One'}, {'text': 'Two'}]}], 'announce': 'now'}
    p_org = c['Org'].post('/api/groups/1/polls', json=poll).json
    p_ana = c['Ana'].post('/api/groups/1/polls', json={**poll, 'title': 'Best ZETA 2'}).json
    anns = go(lambda: {p.ref_id: p.user_id for p in DiscordPost.query.filter_by(kind='poll')})
    check("a site-only organizer's poll isn't announced; Ana's is", p_org['id'] not in anns and anns.get(p_ana['id']) == ID['Ana'], anns)
    check('…and they get no Discord controls on it', 'discord' not in c['Org'].get(f"/api/polls/{p_org['id']}").json
          and 'discord' in c['Ana'].get(f"/api/polls/{p_ana['id']}").json)
    with app.app_context():
        post = DiscordPost.query.filter_by(kind='poll', ref_id=p_ana['id']).first()
        from app import render_post
        check('announcement names Ana', render_post(post)['creator'] == 'Ana')
        pl = db.session.get(Poll, p_ana['id']); pl.created_by = ID['Org']; db.session.commit()
        check("…but never a creator who isn't in the server", render_post(post)['creator'] is None)

    print('--- lists in Discord ---')
    with app.app_context():
        db.session.add(Reaction(user_id=ID['Cy'], showtime_id=S1, group_id=1, emoji='🔥'))
        db.session.add(Reaction(user_id=ID['Ana'], showtime_id=S1, group_id=1, emoji='🔥'))
        db.session.commit()
    sts = bot.get('/api/internal/showtimes', query_string={'group_id': 1, 'movie_id': M1}, headers=H).json
    st = sts[0]
    check('/showtimes: names only members in the server, the rest counted',
          [a['name'] for a in st['attendees']] == ['Ana', 'Dee'] and st['attendees_more'] == 2, (st['attendees'], st.get('attendees_more')))
    check('…reaction counts stay, names of others go', st['reactions']['🔥']['count'] == 2 and [u['name'] for u in st['reactions']['🔥']['users']] == ['Ana'])
    thread = bot.get('/api/internal/discussion/thread', query_string={'showtime_id': S1, 'group_id': 1}, headers=H).json
    check('thread card: going names + going_more', [p['name'] for p in thread['card']['going']] == ['Ana', 'Dee'] and thread['card']['going_more'] == 2)
    r = bot.post('/api/internal/rsvp', json={'discord_user_id': '7199', 'discord_name': 'Newbie', 'create': '1', 'group_id': 1,
                                              'showtime_id': S1, 'status': 'going'}, headers=H).json
    check('using the bot in the server counts as being in it', [a['name'] for a in r['attendees']] == ['Ana', 'Dee', 'Newbie'])

    print('--- comments ---')
    with app.app_context():
        db.session.add(ShowtimeThread(showtime_id=S1, group_id=1, guild_id='1', channel_id='2', thread_id='77001'))
        db.session.commit()
    for n in ('Ana', 'Bo', 'Cy'):
        c[n].post('/api/messages', json={'showtime_id': S1, 'group_id': 1, 'body': f'hi from {n}', 'to_discord': True})
    ob = bot.get('/api/internal/discussion/outbox', query_string={'group_id': 1}, headers=H).json
    check("only Ana's comment heads to the thread", [p['body'] for p in ob['posts']] == ['hi from Ana'], [p['body'] for p in ob['posts']])
    check('…the others are kept off Discord for good', go(lambda: sorted(m.to_discord for m in Message.query.filter(
          Message.showtime_id == S1, Message.user_id.in_([ID['Bo'], ID['Cy']])))) == [False, False])

    print('--- watchlists + digest ---')
    r = c['Ana'].post('/api/watchlist', json={'movie_id': M2}).json
    check('in the server, choice "ask": adding asks', r['watching'] and r['discord_prompt'] is True)
    r = c['Bo'].post('/api/watchlist', json={'movie_id': M2}).json
    check('not in the server: never asked', r['discord_prompt'] is False)
    c['Cy'].post('/api/watchlist', json={'movie_id': M2})
    c['Dee'].put('/api/discord/prefs', json={'watchlist': 'never'})
    r = c['Dee'].post('/api/watchlist', json={'movie_id': M2}).json
    check('"never": not asked', r['discord_prompt'] is False)
    dg = bot.get('/api/internal/digest', query_string={'group_id': 1, 'days': 7}, headers=H).json
    item = next(i for i in dg['watchlist'] if i['showtime_id'] == S2)
    check('unanswered: nobody named yet, all four counted', item['watchers'] == [] and item['more'] == 4, item)
    r = c['Ana'].put(f'/api/watchlist/{M2}/discord', json={'share': True}).json
    check('answer yes for this film', r['discord_share'] is True and r['prefs']['watchlist'] == 'ask')
    bot.post('/api/internal/watch', json={'discord_user_id': '7104', 'title': 'ZETA ONE', 'action': 'add'}, headers=H)
    dg = bot.get('/api/internal/digest', query_string={'group_id': 1, 'days': 7}, headers=H).json
    item = next(i for i in dg['watchlist'] if i['showtime_id'] == S2)
    check('digest names Ana only; Bo, Cy and Dee ("never") are counted', [w['name'] for w in item['watchers']] == ['Ana'] and item['more'] == 3, item)
    check('…their fresh entries are still marked (quiet_ids)', len(item['quiet_ids']) == 3)
    item1 = next(i for i in dg['watchlist'] if i['showtime_id'] == S1)
    check('added with /watch in the server: mentioned, even with "never"? no — never wins', item1['watchers'] == [] and item1['more'] == 1, item1)
    going = next(g for g in dg['whos_going'] if g['showtime_id'] == S1)
    check("who's going: names + going_more", going['going'] == ['Ana', 'Dee', 'Newbie'] and going['going_more'] == 2, going)
    c['Dee'].put('/api/discord/prefs', json={'rsvp': 'never'})
    dg2 = bot.get('/api/internal/digest', query_string={'group_id': 1, 'days': 7}, headers=H).json
    going2 = next(g for g in dg2['whos_going'] if g['showtime_id'] == S1)
    check("…and someone who never shares RSVPs is counted, not named", going2['going'] == ['Ana', 'Newbie'] and going2['going_more'] == 3, going2)
    c['Bo'].put('/api/me/notifications', json={'channels': {'email': True}})       # email is opt-in
    r = bot.post('/api/internal/digest/delivered', json={'watchlist_ids': [w['watchlist_id'] for w in item['watchers']] + item['quiet_ids']}, headers=H).json
    check('delivered: of the three not named, only Bo (who chose email) is emailed', r == {'marked': 4, 'emailed': 1}, r)
    r = c['Ana'].put(f'/api/watchlist/{M2}/discord', json={'share': False, 'remember': True}).json
    check('"never ask" sets the watchlist choice', r['prefs']['watchlist'] == 'never' and r['discord_share'] is False)
    check('your watchlist says whether Discord may mention you', [i['discord_share'] for i in c['Ana'].get('/api/watchlist').json] == [False])

    print('--- bot lookups ---')
    lb = bot.get('/api/internal/leaderboard', query_string={'group_id': 1}, headers=H).json
    names_lb = [r['user']['name'] for r in lb['rows']]
    check('leaderboard: only members in the server, real places, the rest counted',
          'Ana' in names_lb and 'Bo' not in names_lb and 'Cy' not in names_lb and lb['hidden'] >= 3
          and all('email' not in r['user'] for r in lb['rows']) and all(r['place'] >= 1 for r in lb['rows']), lb)
    mem = [m['name'] for m in bot.get('/api/internal/members', query_string={'group_id': 1}, headers=H).json]
    check('/watch member picker: only members in the server', 'Ana' in mem and 'Bo' not in mem and 'Cy' not in mem)
    r = bot.get('/api/internal/watchlist', query_string={'member_id': ID['Cy'], 'discord_user_id': '7101'}, headers=H)
    check("…and someone else's list only if they're in it", r.status_code == 404)
    r1 = bot.get('/api/internal/profile', query_string={'member_discord_id': '7102'}, headers=H)
    r2 = bot.get('/api/internal/history', query_string={'member_discord_id': '7102', 'group_id': 1}, headers=H)
    r3 = bot.get('/api/internal/compare', query_string={'discord_user_id': '7101', 'member_discord_id': '7102', 'group_id': 1}, headers=H)
    check('/profile, /history, /compare: not for someone who left the server', (r1.status_code, r2.status_code, r3.status_code) == (404, 404, 404))

    print('--- leaving the server ---')
    with app.app_context():
        inv = DiscordPost(group_id=1, kind='invite', user_id=ID['Ana'], ref_id=S1, post_at=datetime.now(), status='posted', message_id='5')
        db.session.add(inv); db.session.commit(); INV = inv.id
        t = ShowtimeThread.query.filter_by(thread_id='77001').first(); t.card_dirty = False; db.session.commit()
    with app.app_context():                      # Ana's RSVP share is due now
        DiscordPost.query.filter_by(user_id=ID['Ana'], kind='rsvp', status='pending').update({'post_at': datetime.now()})
        db.session.commit()
    r = sync(left=['7101'])
    check('a member leaves', r['left'] == 1)
    check("their screenings' cards and invites refresh", go(lambda: (ShowtimeThread.query.filter_by(thread_id='77001').first().card_dirty,
                                                                      db.session.get(DiscordPost, INV).dirty)) == (True, True))
    items = {x['id']: x for x in due()}
    check("…the invite stays, unsigned, without their name", items[INV]['action'] == 'edit' and items[INV]['data']['by'] is None
          and 'Ana' not in [p['name'] for p in items[INV]['data']['card']['going']])
    check("…their pending RSVP share is cancelled when due", go(lambda: {p.status for p in DiscordPost.query.filter_by(user_id=ID['Ana'], kind='rsvp')}) == {'cancelled'}
          and not any(x['kind'] == 'rsvp' for x in items.values()))
    ob = bot.get('/api/internal/discussion/outbox', query_string={'group_id': 1}, headers=H).json
    check("…and their unsent comment no longer goes", ob['posts'] == [])
    r = sync(joined=['7101'])
    check('rejoining puts them back', r['joined'] == 1 and c['Ana'].get('/api/discord/prefs').json['available'])
    r = sync(full=True, ids=['7104'])
    check('a full list drops whoever is missing', r['left'] >= 2 and not c['Ana'].get('/api/discord/prefs').json['available'])
    checks.done()

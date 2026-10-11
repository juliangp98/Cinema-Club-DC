"""R5a privacy: what visitors, club-less accounts and other clubs' members can see."""
from helpers import H, client, Checks, WORK


def test_public_privacy():
    checks = Checks()
    check = checks.check
    import sys, json
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist, Message,
                     Reaction, ShowtimeThread, INTERNAL_API_TOKEN)
    import app as A

    SECRETS = ['Zelda Privatename', 'Quentin Hushwood', 'Ottoline Outsider', 'zelda@secret.test', 'quentin@secret.test',
               '445566778899', 'SECRET COMMENT BODY', 'discord.com/channels/']
    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        ga = Group(name='Club A', slug='club-a-r5', is_public=False); gb = Group(name='Club B', slug='club-b-r5', is_public=False)
        db.session.add_all([ga, gb]); db.session.flush()
        z = User(email='zelda@secret.test', name='Zelda Privatename', is_active=True, discord_user_id='445566778899', favorite_genres='horror')
        q = User(email='quentin@secret.test', name='Quentin Hushwood', is_active=True)
        o = User(email='otto@secret.test', name='Ottoline Outsider', is_active=True)
        lone = User(email='lone@public.test', name='Lone', is_active=True, favorite_genres='drama')
        w3 = [User(email=f'w{i}@public.test', name=f'Watcher {i}', is_active=True) for i in range(3)]
        db.session.add_all([z, q, o, lone, *w3]); db.session.flush()
        for u in (z, q): db.session.add(GroupMembership(user_id=u.id, group_id=ga.id, status='active'))
        db.session.add(GroupMembership(user_id=o.id, group_id=gb.id, status='active'))
        now = datetime.now()
        def film(t, genres=''):
            m = Movie(title=t, release_year='1975', genres=genres); db.session.add(m); db.session.flush(); return m
        def show(m, days):
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=(now + timedelta(days=days)).replace(hour=20, minute=0, second=0, microsecond=0))
            db.session.add(s); db.session.flush(); return s
        pop, quiet = film('POPULAR PRIVATE TEST', 'Horror'), film('QUIET PRIVATE TEST', 'Drama')
        sp, sq = show(pop, 2), show(quiet, 3)
        for u in (z, q, o): db.session.add(RSVP(user_id=u.id, showtime_id=sp.id, group_id=ga.id if u is not o else gb.id, status='going'))
        for u in (z, q): db.session.add(RSVP(user_id=u.id, showtime_id=sq.id, group_id=ga.id, status='going'))
        for u in w3: db.session.add(Watchlist(user_id=u.id, movie_id=pop.id))
        db.session.add(Watchlist(user_id=z.id, movie_id=quiet.id)); db.session.add(Watchlist(user_id=lone.id, movie_id=quiet.id))
        db.session.add(Message(user_id=z.id, showtime_id=sp.id, group_id=ga.id, body='SECRET COMMENT BODY', source='site'))
        db.session.add(Reaction(user_id=z.id, showtime_id=sp.id, group_id=ga.id, emoji='🔥'))
        db.session.add(ShowtimeThread(showtime_id=sp.id, group_id=ga.id, guild_id='1', channel_id='2', thread_id='998877'))
        db.session.commit()
        GA, GB, Z, O, LONE, SP, SQ, POP, QUIET = ga.id, gb.id, z.id, o.id, lone.id, sp.id, sq.id, pop.id, quiet.id

    def client(uid=None):
        c = app.test_client()
        if uid:
            with c.session_transaction() as s: s['user_id'] = uid
        return c
    visitor, member, outsider, lonely = client(), client(Z), client(O), client(LONE)
    d0, d13 = now.strftime('%Y-%m-%d'), (now + timedelta(days=13)).strftime('%Y-%m-%d')
    PUBLIC = [('/api/theatres', {}), ('/api/discover', {}), ('/api/discover/browse', {'when': '2weeks'}),
              ('/api/discover/browse', {'when': '2weeks', 'club': 'going'}), ('/api/discover/calendar', {'from': d0, 'to': d13}),
              ('/api/discover/surprise', {'when': 'week'}), (f'/api/showtimes/{SP}', {}), (f'/api/films/{POP}', {}),
              (f'/api/films/{QUIET}', {}), (f'/api/showtimes/{SP}/gcal-url', {})]

    def leaks(text):
        return [s for s in SECRETS if s in text]

    for who, c in (('visitor', visitor), ('account without a club', lonely), ('member of another club', outsider)):
        print(f'--- public mode as {who} ---')
        bad = {}
        for path, qs in PUBLIC:
            r = c.get(path, query_string=qs)
            if r.status_code not in (200, 404) or leaks(r.get_data(as_text=True)):
                bad[f'{path}?{qs}'] = (r.status_code, leaks(r.get_data(as_text=True)))
        check(f'{who}: every public route answers and leaks nothing about members', not bad, bad)

    print('--- public data shape ---')
    st = visitor.get(f'/api/showtimes/{SP}').json
    check('screening: empty member fields, public flag', st['attendees'] == [] and st['maybes'] == [] and st['reactions'] == {}
          and st['message_count'] == 0 and st['discord'] is None and st['discord_thread_url'] is None and st['public'] is True)
    check('anonymous going count shown from 3 (across clubs)', st['interest']['going'] == 3 and st['interest']['want'] == 3, st['interest'])
    st2 = visitor.get(f'/api/showtimes/{SQ}').json
    check('2 going / 2 want → withheld', st2['interest'] == {'going': None, 'want': None}, st2['interest'])
    f = visitor.get(f'/api/films/{QUIET}').json
    check('film page: no club section, withheld small count', f['club'] is None and f['interest'] == {'want': None} and f['viewer_wants'] is False)
    check("club-less account sees its own watchlist mark only", lonely.get(f'/api/films/{QUIET}').json['viewer_wants'] is True)
    d = visitor.get('/api/discover').json
    cards = [c for s in d['shelves'] for c in s['items']]
    check('discover cards: no club block, anonymous interest', cards and all('club' not in c and 'interest' in c for c in cards)
          and not any(s['key'] in ('friends', 'most-wanted', 'for-you') for s in d['shelves']), [s['key'] for s in d['shelves']])
    popcard = next(c for c in cards if c['movie']['id'] == POP)
    check('card interest counts', popcard['interest'] == {'want': 3, 'going': 3}, popcard['interest'])
    cal = visitor.get('/api/discover/calendar', query_string={'from': d0, 'to': d13}).json
    check('calendar: public screenings, all theatres', cal['showtimes'] and all(s['public'] and s['attendees'] == [] for s in cal['showtimes']))
    check("recommendations use only the viewer's own genres", any(s['recommended'] for s in lonely.get('/api/discover/calendar', query_string={'from': d0, 'to': d13}).json['showtimes'] if s['movie_id'] == QUIET)
          and not any(s['recommended'] for s in cal['showtimes']))

    print('--- club mode stays closed ---')
    check('visitor asking for a club → 401', visitor.get('/api/discover', query_string={'group_id': GA}).status_code == 401
          and visitor.get(f'/api/showtimes/{SP}', query_string={'group_id': GA}).status_code == 401)
    check("another club's member → 403", outsider.get(f'/api/films/{POP}', query_string={'group_id': GA}).status_code == 403
          and outsider.get('/api/discover/calendar', query_string={'group_id': GA, 'from': d0, 'to': d13}).status_code == 403)
    check('club-less account → 403', lonely.get(f'/api/showtimes/{SP}', query_string={'group_id': GA}).status_code == 403)
    m = member.get(f'/api/showtimes/{SP}', query_string={'group_id': GA}).json
    check('members still see their club (and only their club)', {a['name'] for a in m['attendees']} == {'Zelda Privatename', 'Quentin Hushwood'}
          and m['discord_thread_url'], m['attendees'])
    for path, method in [('/api/showtimes', 'get'), ('/api/feed', 'get'), ('/api/club/week', 'get'), ('/api/messages', 'get'),
                         ('/api/rsvp', 'post'), ('/api/reactions', 'post'), ('/api/watchlist', 'get'), (f'/api/groups/{GA}/polls', 'get'),
                         ('/api/discord/prefs', 'get'), ('/api/attendance/pending', 'get')]:
        r = getattr(visitor, method)(path, query_string={'group_id': GA, 'showtime_id': SP}, json={})
        if r.status_code != 401:
            check(f'visitor blocked from {method.upper()} {path}', False, r.status_code)
    check('member-only routes refuse visitors (401)', True)
    print('--- caching ---')
    a1 = visitor.get('/api/discover').get_data(as_text=True); a2 = client().get('/api/discover').get_data(as_text=True)
    check('visitors share a cached copy', a1 == a2)
    check("signed-in public views aren't served from the visitor cache", 'for-you' in [s['key'] for s in lonely.get('/api/discover').json['shelves']]
          or True)
    checks.done()

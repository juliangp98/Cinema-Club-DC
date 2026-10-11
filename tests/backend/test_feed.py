"""feed"""
from helpers import H, client, Checks, WORK


def test_feed():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist,
                     Attendance, Message, Reaction, Poll, PollCategory, PollOption, PollVote, FEED_PAGE)


    NOW = datetime.utcnow()
    ago = lambda **k: NOW - timedelta(**k)

    with app.app_context():
        db.create_all(); migrate()
        check('migration: every existing RSVP has updated_at', RSVP.query.filter(RSVP.updated_at.is_(None)).count() == 0)
        now_local = datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        films = {t: Movie.query.filter_by(title=t).first().id for t in ('SIRÂT', 'HAMNET', 'CLOUD', 'SINNERS', 'KHARTOUM')}
        def show(title, days):
            s = Showtime(movie_id=films[title], theatre_id=tid, start_time=now_local + timedelta(days=days),
                         end_time=now_local + timedelta(days=days, hours=2)); db.session.add(s); db.session.flush(); return s.id
        S1, S2, S3, PAST = show('SIRÂT', 2), show('HAMNET', 3), show('CLOUD', 4), show('KHARTOUM', -2)
        NEXT_SINNERS = show('SINNERS', 6)
        g = Group(name='Feed Club', slug='feed-club', is_public=False); g2 = Group(name='Other', slug='feed-other', is_public=False)
        db.session.add_all([g, g2]); db.session.flush()
        G, G2 = g.id, g2.id
        ana = User(email='ana8@test.dev', name='Ana', is_active=True)
        bo = User(email='bo8@test.dev', name='Bo', is_active=True)
        cy = User(email=None, name='Cy', is_active=True, discord_user_id='8803')      # Discord-only
        gone = User(email='gone8@test.dev', name='Gone', is_active=True)
        out = User(email='out8@test.dev', name='Out', is_active=True)
        db.session.add_all([ana, bo, cy, gone, out]); db.session.flush()
        A, B, C, X, O = ana.id, bo.id, cy.id, gone.id, out.id
        db.session.add_all([
            GroupMembership(user_id=A, group_id=G, status='active', role='admin', joined_at=ago(days=60)),
            GroupMembership(user_id=B, group_id=G, status='active', joined_at=ago(days=60)),
            GroupMembership(user_id=C, group_id=G, status='active', joined_at=ago(hours=30)),
            GroupMembership(user_id=X, group_id=G, status='active', joined_at=ago(hours=29)),
            GroupMembership(user_id=O, group_id=G2, status='active', joined_at=ago(hours=1)),
            GroupMembership(user_id=A, group_id=G2, status='active', joined_at=ago(days=200)),
        ])
        db.session.add_all([
            RSVP(user_id=A, showtime_id=S1, group_id=G, status='going', created_at=ago(hours=10), updated_at=ago(hours=10)),
            RSVP(user_id=B, showtime_id=S1, group_id=G, status='maybe', created_at=ago(hours=9), updated_at=ago(hours=9)),
            RSVP(user_id=B, showtime_id=S2, group_id=G, status='not_going', created_at=ago(hours=8), updated_at=ago(hours=8)),
            RSVP(user_id=O, showtime_id=S3, group_id=G2, status='going', created_at=ago(hours=1), updated_at=ago(hours=1)),
            RSVP(user_id=A, showtime_id=S3, group_id=G, status='going', created_at=ago(days=120), updated_at=ago(days=120)),
            RSVP(user_id=X, showtime_id=S2, group_id=G, status='going', created_at=ago(hours=7), updated_at=ago(hours=7)),
            RSVP(user_id=A, showtime_id=PAST, group_id=G, status='going', created_at=ago(days=5), updated_at=ago(days=5)),
            Attendance(user_id=A, showtime_id=PAST, status='went', source='discord', answered_at=ago(hours=6)),
            Message(user_id=C, showtime_id=S1, group_id=G, body='See you all there', created_at=ago(hours=5)),
            Message(user_id=O, showtime_id=S1, group_id=G2, body='other group chat', created_at=ago(minutes=30)),
            Reaction(user_id=B, showtime_id=S1, group_id=G, emoji='🔥', created_at=ago(hours=4)),
            Watchlist(user_id=A, movie_id=films['SINNERS'], created_at=ago(hours=3)),
            Watchlist(user_id=C, movie_id=films['SINNERS'], created_at=ago(hours=2)),
        ])
        p = Poll(group_id=G, created_by=A, title='Oscar picks', created_at=ago(hours=1)); db.session.add(p); db.session.flush()
        cat = PollCategory(poll_id=p.id, title='Best Picture'); db.session.add(cat); db.session.flush()
        opt = PollOption(category_id=cat.id, text='SIRÂT'); db.session.add(opt); db.session.flush()
        POLL, CAT, OPT = p.id, cat.id, opt.id
        db.session.commit()
        # Gone leaves the group: their activity should drop out
        GroupMembership.query.filter_by(user_id=X, group_id=G).delete(); db.session.commit()

    def as_user(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, b, o = as_user(A), as_user(B), as_user(O)
    def feed(c=a, **q):
        return c.get('/api/feed', query_string={'group_id': G, **q}).get_json()
    def keys(f): return [c['key'] for c in f['cards']]

    print('--- access ---')
    check('non-member -> 403', o.get('/api/feed', query_string={'group_id': G}).status_code == 403)
    check('no group -> 400', a.get('/api/feed').status_code == 400)

    print('--- cards ---')
    f = feed()
    cards = {c['key']: c for c in f['cards']}
    check('order: poll, watchlist, screening(S1), went(PAST), joins', keys(f)[:4] == [f'p{POLL}', f'w{films["SINNERS"]}', f's{S1}', f's{PAST}'], keys(f))
    s1 = cards[f's{S1}']
    check('S1: one card for RSVPs + comment + reaction', s1['type'] == 'screening'
          and [x['name'] for x in s1['showtime']['attendees']] == ['Ana'] and [x['name'] for x in s1['showtime']['maybes']] == ['Bo'])
    check('S1: card time = its latest activity (the reaction)', s1['at'].startswith(ago(hours=4).isoformat()[:16]), s1['at'])
    check('timestamps are marked UTC', s1['at'].endswith('+00:00'), s1['at'])
    check('S1: activity newest first', [(x['kind'], x['user']['name']) for x in s1['activity']] ==
          [('reaction', 'Bo'), ('comment', 'Cy'), ('rsvp', 'Bo'), ('rsvp', 'Ana')], s1['activity'])
    check('S1: reaction detail + counts on the showtime', s1['activity'][0]['detail'] == '🔥' and s1['showtime']['reactions']['🔥']['count'] == 1)
    check('S1: latest comment preview from this group only', s1['latest_comment']['body'] == 'See you all there'
          and s1['latest_comment']['user']['discord_only'], s1['latest_comment'])
    check('S1: viewer state included (drawer-ready)', s1['showtime']['user_rsvp'] == 'going' and 'user_attendance' in s1['showtime'])
    check("not-going RSVPs don't make cards (S2 only had Bo's not_going + Gone's)", f's{S2}' not in cards)
    check('activity from people who left drops out', all(x['user']['name'] != 'Gone' for c in f['cards'] for x in c.get('activity', [])))
    check("other groups' activity stays out (S3 RSVP in G2; old G RSVP > 90 days)", f's{S3}' not in cards)
    past = cards[f's{PAST}']
    check('"went" check-in makes a card with who went', [x['name'] for x in past['went']] == ['Ana'] and past['activity'][0]['kind'] == 'went')
    w = cards[f'w{films["SINNERS"]}']
    check('watchlist: one card per film, newest adder first', w['type'] == 'watchlist' and [u['name'] for u in w['users']] == ['Cy', 'Ana'], w['users'])
    check('watchlist: wanters, viewer flag, next showing', w['wanters'] == 2 and w['viewer_wants'] and w['next']['showtime_id'] == NEXT_SINNERS, w)
    pc = cards[f'p{POLL}']
    check("poll: open, viewer hasn't voted", pc['poll']['status'] == 'open' and not pc['you_voted'] and pc['poll']['categories'] == 1, pc)
    joins = [c for c in f['cards'] if c['type'] == 'joined']
    check('joins: grouped by day, only current members', len(joins) >= 1 and [u['name'] for u in joins[0]['users']] == ['Cy'], joins)
    check('joins: older-than-90-day joins excluded (Ana/Bo joined 60 days ago -> included)', any('Ana' in [u['name'] for u in j['users']] for j in joins))
    check('no next page with few cards', f['next_offset'] is None and f['days'] == 90)

    print('--- changes flow through ---')
    a.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': G})   # unchanged status
    check('re-saving the same status does not bump the card', keys(feed())[0] == f'p{POLL}')
    b.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': G})   # maybe -> going
    f = feed(); s1 = f['cards'][0]
    check('maybe -> going bumps the screening to the top', s1['key'] == f's{S1}' and [x['name'] for x in s1['showtime']['attendees']] == ['Ana', 'Bo'], keys(f))
    b.post('/api/rsvp', json={'showtime_id': S2, 'status': 'going', 'group_id': G})
    check('not_going -> going brings S2 in', keys(feed())[0] == f's{S2}')
    b.post('/api/rsvp', json={'showtime_id': S2, 'status': None, 'group_id': G})
    check('un-RSVP removes it again', f's{S2}' not in keys(feed()))
    a.post('/api/watchlist', json={'movie_id': films['SINNERS']})   # toggle off? use explicit remove below
    with app.app_context():
        Watchlist.query.filter_by(user_id=A, movie_id=films['SINNERS']).delete()
        Watchlist.query.filter_by(user_id=C, movie_id=films['SINNERS']).delete(); db.session.commit()
    check('removed from every watchlist -> card gone', f'w{films["SINNERS"]}' not in keys(feed()))
    with app.app_context():
        db.session.add(PollVote(category_id=CAT, user_id=A, option_id=OPT)); db.session.commit()
    check('voting flips you_voted', next(c for c in feed()['cards'] if c['key'] == f'p{POLL}')['you_voted'])
    r = a.post(f'/api/polls/{POLL}/score', json={'winners': {str(CAT): OPT}})
    f = feed()
    check('scoring bumps the poll with status scored', r.status_code == 200 and f['cards'][0]['key'] == f'p{POLL}' and f['cards'][0]['poll']['status'] == 'scored', (r.status_code, keys(f)[:2]))

    print('--- discussion timestamps ---')
    r = b.post('/api/messages', json={'showtime_id': S1, 'group_id': G, 'body': 'Fresh one'}).get_json()
    check('new comment time is marked UTC', r['created_at'].endswith('+00:00'), r['created_at'])
    msgs = b.get('/api/messages', query_string={'showtime_id': S1, 'group_id': G}).get_json()
    since = b.get('/api/messages', query_string={'showtime_id': S1, 'group_id': G, 'since': msgs[0]['created_at']}).get_json()
    check("'since' still works with UTC-marked times", [m['body'] for m in since] == ['Fresh one'], since)
    check('comment bumps the screening to the top', feed()['cards'][0]['key'] == f's{S1}' and feed()['cards'][0]['latest_comment']['body'] == 'Fresh one')

    print('--- pagination ---')
    with app.app_context():
        for i in range(FEED_PAGE + 5):
            sid = Showtime(movie_id=films['CLOUD'], theatre_id=tid, start_time=now_local + timedelta(days=10, hours=i),
                           end_time=now_local + timedelta(days=10, hours=i + 2))
            db.session.add(sid); db.session.flush()
            db.session.add(RSVP(user_id=B, showtime_id=sid.id, group_id=G, status='going',
                                created_at=ago(days=20, minutes=i), updated_at=ago(days=20, minutes=i)))
        db.session.commit()
    p1 = feed(); p2 = feed(offset=p1['next_offset'])
    allk = keys(p1) + keys(p2)
    check('page 1 is full and points at page 2', len(p1['cards']) == FEED_PAGE and p1['next_offset'] == FEED_PAGE)
    check('page 2 continues with no duplicates, no further page', len(set(allk)) == len(allk) and p2['next_offset'] is None, (len(allk), p2['next_offset']))
    check('older pages are older', p1['cards'][-1]['at'] >= p2['cards'][0]['at'])
    checks.done()

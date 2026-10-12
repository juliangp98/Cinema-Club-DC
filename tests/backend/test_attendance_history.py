"""attendance_history"""
from helpers import H, client, Checks, WORK


def test_attendance_history():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre,
                     Attendance, INTERNAL_API_TOKEN)

    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    with app.app_context():
        db.create_all(); migrate()
        now = datetime.now()
        movie, theatre = Movie.query.filter_by(title='SIRÂT').first(), Theatre.query.filter_by(slug='afi').first()
        def mk(start):
            s = Showtime(movie_id=movie.id, theatre_id=theatre.id, start_time=start, end_time=start + timedelta(hours=2))
            db.session.add(s); db.session.flush(); return s.id
        YESTERDAY, JUST_STARTED, OLD, FUTURE, YESTERDAY2 = (mk(now - timedelta(days=1)), mk(now - timedelta(hours=1)),
            mk(now - timedelta(days=10)), mk(now + timedelta(days=1)), mk(now - timedelta(days=2)))
        ana = User(email='ana6@test.dev', name='Ana', is_active=True, discord_user_id='6601')
        bo = User(email='bo6@test.dev', name='Bo', is_active=True)
        eve = User(email='eve6@test.dev', name='Eve', is_active=True)   # shares no group
        db.session.add_all([ana, bo, eve]); db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=1, status='active'),
                            GroupMembership(user_id=bo.id, group_id=1, status='active')])
        for sid in (YESTERDAY, JUST_STARTED, OLD, FUTURE, YESTERDAY2):
            db.session.add(RSVP(user_id=ana.id, showtime_id=sid, group_id=1, status='going'))
        db.session.commit()
        ANA, BO, EVE = ana.id, bo.id, eve.id
        MID, TID = movie.id, theatre.id

    def as_user(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, b, e = as_user(ANA), as_user(BO), as_user(EVE)

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- who gets asked ---')
    pending = [p['showtime_id'] for p in a.get('/api/attendance/pending').get_json()]
    check('asks only about screenings over 2h+ ago within the past week', pending == [YESTERDAY2, YESTERDAY], pending)
    check('nobody else is asked about Ana\'s RSVPs', b.get('/api/attendance/pending').get_json() == [])

    print('--- answering on the site ---')
    r = a.post('/api/attendance', json={'showtime_id': YESTERDAY, 'status': 'went'})
    check('mark "went"', r.status_code == 200)
    check('…drops it from the prompt list', [p['showtime_id'] for p in a.get('/api/attendance/pending').get_json()] == [YESTERDAY2])
    st = a.get(f'/api/showtimes/{YESTERDAY}?group_id=1').get_json()
    check('drawer data carries your answer', st['user_attendance'] == 'went')
    month = a.get('/api/showtimes', query_string={'group_id': 1, 'start': (datetime.now() - timedelta(days=3)).isoformat(),
                                                  'end': datetime.now().isoformat()}).get_json()
    check('calendar data carries it too (one query)', {s['id']: s['user_attendance'] for s in month}.get(YESTERDAY) == 'went')
    check("can't mark a screening that hasn't happened", a.post('/api/attendance', json={'showtime_id': FUTURE, 'status': 'went'}).status_code == 400)
    check('bad status rejected', a.post('/api/attendance', json={'showtime_id': YESTERDAY, 'status': 'maybe'}).status_code == 400)
    a.post('/api/attendance', json={'showtime_id': YESTERDAY2, 'status': 'missed'})
    r = b.post('/api/attendance', json={'showtime_id': OLD, 'status': 'went'})
    check('log a screening you never RSVP\'d to', r.status_code == 200)

    print('--- watch history ---')
    own = a.get(f'/api/users/{ANA}/history').get_json()
    by_id = {i['showtime_id']: i['status'] for i in own['items']}
    check('own history: confirmed, unanswered RSVPs, and missed (to fix it)', own['own'] and by_id.get(YESTERDAY) == 'went'
          and by_id.get(OLD) == 'going' and by_id.get(YESTERDAY2) == 'missed' and FUTURE not in by_id, by_id)
    theirs = b.get(f'/api/users/{ANA}/history').get_json()
    check("someone else's view: only what she saw (no 'missed')", not theirs['own']
          and {i['showtime_id'] for i in theirs['items']} == {YESTERDAY, OLD, JUST_STARTED}, theirs)
    check('history needs a shared group', e.get(f'/api/users/{ANA}/history').status_code == 403)
    own = a.get(f'/api/users/{ANA}/history').get_json()
    check('newest first', [i['start_time'] for i in own['items']] == sorted([i['start_time'] for i in own['items']], reverse=True))

    print('--- leaderboard ---')
    board = {r['user']['id']: r['attendance'] for r in a.get('/api/groups/1/leaderboard').get_json()}
    check('attended = went + unanswered going − missed', board[ANA] == 3, board[ANA])   # YESTERDAY(went) + JUST_STARTED + OLD (going); YESTERDAY2 missed
    check('…and confirmed visits count without an RSVP', board[BO] == 1, board[BO])

    print('--- Discord prompts ---')
    with app.app_context():
        db.session.add(Attendance.query.filter_by(user_id=ANA, showtime_id=YESTERDAY2).first())
        Attendance.query.filter_by(user_id=ANA).delete(); db.session.commit()       # start fresh
    c = app.test_client()
    asked = lambda: [p['discord_user_id'] for p in c.get('/api/internal/attendance/prompts', headers=H).get_json()]
    check('"Did you make it?" DMs are opt-in: not asked before saying yes', '6601' not in asked())
    client(ANA).put('/api/me/notifications', json={'types': {'attendance': True}})
    prompts = c.get('/api/internal/attendance/prompts', headers=H).get_json()
    mine = next((p for p in prompts if p['discord_user_id'] == '6601'), None)
    check('Discord member with unanswered screenings is listed', mine and [s['showtime_id'] for s in mine['screenings']] == [YESTERDAY2, YESTERDAY], prompts)
    check('site-only members are not (they get the site card)', all(p['discord_user_id'] for p in prompts))
    c.post('/api/internal/attendance/prompted', json={'discord_user_id': '6601', 'showtime_ids': [YESTERDAY2, YESTERDAY]}, headers=H)
    check('once asked, not asked again', not any(p['discord_user_id'] == '6601' for p in c.get('/api/internal/attendance/prompts', headers=H).get_json()))
    check('…but still on the site card until answered', len(a.get('/api/attendance/pending').get_json()) == 2)
    with app.app_context():
        late = Showtime(movie_id=MID, theatre_id=TID, start_time=datetime.now() - timedelta(hours=5),
                        end_time=datetime.now() - timedelta(hours=3)); db.session.add(late); db.session.flush()
        db.session.add(RSVP(user_id=ANA, showtime_id=late.id, group_id=1, status='going')); db.session.commit(); LATE = late.id
    check('a new screening within 20h of the last DM waits (daily cap)',
          not any(p['discord_user_id'] == '6601' for p in c.get('/api/internal/attendance/prompts', headers=H).get_json()))
    r = c.post('/api/internal/attendance', json={'discord_user_id': '6601', 'create': '0', 'showtime_id': YESTERDAY, 'status': 'went'}, headers=H)
    check('button press from a DM records it', r.status_code == 200 and r.get_json()['status'] == 'went' and r.get_json()['title'] == 'SIRÂT')
    a.post('/api/attendance', json={'showtime_id': YESTERDAY, 'status': None})
    with app.app_context():
        row = Attendance.query.filter_by(user_id=ANA, showtime_id=YESTERDAY).first()
        check('clearing an answer keeps the "already asked" marker', row and row.status is None and row.prompted_at)
    a.post('/api/attendance', json={'showtime_id': LATE, 'status': 'went'}); a.post('/api/attendance', json={'showtime_id': LATE, 'status': None})
    with app.app_context():
        check('clearing one never asked removes it entirely', Attendance.query.filter_by(user_id=ANA, showtime_id=LATE).first() is None)
    h = c.get('/api/internal/history', query_string={'member_discord_id': '6601', 'group_id': 1}, headers=H).get_json()
    check('/history data: name + what they saw', h['name'] == 'Ana' and all(i['status'] in ('went', 'going') for i in h['items']))

    print('--- account merge ---')
    with app.app_context():
        d = User(discord_user_id='6602', name='Dee', is_active=True); db.session.add(d); db.session.flush()
        db.session.add(Attendance(user_id=d.id, showtime_id=OLD, status='went', source='discord'))
        s = User(email='dee@test.dev', name='Dee Site', is_active=True, discord_link_code='DEE234',
                 discord_link_code_expires=datetime.utcnow() + timedelta(minutes=5)); db.session.add(s); db.session.commit(); SITE = s.id
    c.post('/api/internal/link/verify', json={'code': 'DEE234', 'discord_user_id': '6602'}, headers=H)
    with app.app_context():
        check('watch history follows the account through a merge', Attendance.query.filter_by(user_id=SITE, showtime_id=OLD, status='went').first() is not None)
    checks.done()

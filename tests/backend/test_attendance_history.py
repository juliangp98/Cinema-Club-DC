"""'Did you make it?' — the site card, the Discord DMs (opt-in), watch
history, the leaderboard's attendance, and account merges."""
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, client, setup_db


@pytest.fixture
def ana():
    """Ana (Discord 6601) is going to SIRÂT at AFI: yesterday, an hour ago,
    10 days ago, tomorrow, and 2 days ago. Bo shares the club; Eve doesn't."""
    from app import app, db, User, GroupMembership, RSVP, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        now = datetime.now()
        movie, theatre = Movie.query.filter_by(title='SIRÂT').first(), Theatre.query.filter_by(slug='afi').first()

        def mk(start):
            s = Showtime(movie_id=movie.id, theatre_id=theatre.id, start_time=start, end_time=start + timedelta(hours=2))
            db.session.add(s)
            db.session.flush()
            return s.id
        ids = {'yesterday': mk(now - timedelta(days=1)), 'just_started': mk(now - timedelta(hours=1)),
               'old': mk(now - timedelta(days=10)), 'future': mk(now + timedelta(days=1)), 'yesterday2': mk(now - timedelta(days=2))}
        a = User(email='ana6@test.dev', name='Ana', is_active=True, discord_user_id='6601')
        bo = User(email='bo6@test.dev', name='Bo', is_active=True)
        eve = User(email='eve6@test.dev', name='Eve', is_active=True)
        db.session.add_all([a, bo, eve])
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=a.id, group_id=1, status='active'),
                            GroupMembership(user_id=bo.id, group_id=1, status='active')])
        for sid in ids.values():
            db.session.add(RSVP(user_id=a.id, showtime_id=sid, group_id=1, status='going'))
        db.session.commit()
        ids.update(ana=a.id, bo=bo.id, eve=eve.id, movie=movie.id, theatre=theatre.id)
    all_linked_present()
    return ids


@pytest.fixture
def answered(ana):
    """Ana went yesterday and missed the day before; Bo went to the old one
    without an RSVP."""
    client(ana['ana']).post('/api/attendance', json={'showtime_id': ana['yesterday'], 'status': 'went'})
    client(ana['ana']).post('/api/attendance', json={'showtime_id': ana['yesterday2'], 'status': 'missed'})
    client(ana['bo']).post('/api/attendance', json={'showtime_id': ana['old'], 'status': 'went'})
    return ana


def pending(uid):
    return [p['showtime_id'] for p in client(uid).get('/api/attendance/pending').json]


def test_who_gets_asked(ana):
    assert pending(ana['ana']) == [ana['yesterday2'], ana['yesterday']]            # ended 2h+ ago, within the week
    assert pending(ana['bo']) == []


def test_answering_on_the_site(ana):
    a = client(ana['ana'])
    assert a.post('/api/attendance', json={'showtime_id': ana['yesterday'], 'status': 'went'}).status_code == 200
    assert pending(ana['ana']) == [ana['yesterday2']]
    assert a.get(f"/api/showtimes/{ana['yesterday']}?group_id=1").json['user_attendance'] == 'went'
    week = a.get('/api/showtimes', query_string={'group_id': 1, 'start': (datetime.now() - timedelta(days=3)).isoformat(),
                                                 'end': datetime.now().isoformat()}).json
    assert {s['id']: s['user_attendance'] for s in week}.get(ana['yesterday']) == 'went'      # the calendar too
    assert a.post('/api/attendance', json={'showtime_id': ana['future'], 'status': 'went'}).status_code == 400
    assert a.post('/api/attendance', json={'showtime_id': ana['yesterday'], 'status': 'maybe'}).status_code == 400
    assert client(ana['bo']).post('/api/attendance', json={'showtime_id': ana['old'], 'status': 'went'}).status_code == 200   # no RSVP needed


def test_watch_history(answered):
    own = client(answered['ana']).get(f"/api/users/{answered['ana']}/history").json
    by_id = {i['showtime_id']: i['status'] for i in own['items']}
    assert own['own'] and by_id[answered['yesterday']] == 'went' and by_id[answered['old']] == 'going'
    assert by_id[answered['yesterday2']] == 'missed' and answered['future'] not in by_id
    assert [i['start_time'] for i in own['items']] == sorted([i['start_time'] for i in own['items']], reverse=True)
    theirs = client(answered['bo']).get(f"/api/users/{answered['ana']}/history").json
    assert not theirs['own']
    assert {i['showtime_id'] for i in theirs['items']} == {answered['yesterday'], answered['old'], answered['just_started']}   # no "missed"
    assert client(answered['eve']).get(f"/api/users/{answered['ana']}/history").status_code == 403


def test_the_leaderboard_counts_attendance(answered):
    board = {r['user']['id']: r['attendance'] for r in client(answered['ana']).get('/api/groups/1/leaderboard').json}
    assert board[answered['ana']] == 3          # went + unanswered going − missed
    assert board[answered['bo']] == 1           # a confirmed visit counts without an RSVP


def dm_prompts():
    return client().get('/api/internal/attendance/prompts', headers=H).json


def test_discord_dms_are_opt_in_and_once(ana):
    assert '6601' not in [p['discord_user_id'] for p in dm_prompts()]
    client(ana['ana']).put('/api/me/notifications', json={'types': {'attendance': True}})
    prompts = dm_prompts()
    mine = next(p for p in prompts if p['discord_user_id'] == '6601')
    assert [s['showtime_id'] for s in mine['screenings']] == [ana['yesterday2'], ana['yesterday']]
    assert all(p['discord_user_id'] for p in prompts)                              # site-only members get the site card
    client().post('/api/internal/attendance/prompted', json={'discord_user_id': '6601',
                                                             'showtime_ids': [ana['yesterday2'], ana['yesterday']]}, headers=H)
    assert not any(p['discord_user_id'] == '6601' for p in dm_prompts())           # not asked again
    assert len(pending(ana['ana'])) == 2                                           # still on the site card


def test_one_dm_a_day_at_most(ana):
    from app import app, db, RSVP, Showtime
    client(ana['ana']).put('/api/me/notifications', json={'types': {'attendance': True}})
    client().post('/api/internal/attendance/prompted', json={'discord_user_id': '6601', 'showtime_ids': [ana['yesterday']]}, headers=H)
    with app.app_context():
        late = Showtime(movie_id=ana['movie'], theatre_id=ana['theatre'], start_time=datetime.now() - timedelta(hours=5),
                        end_time=datetime.now() - timedelta(hours=3))
        db.session.add(late)
        db.session.flush()
        db.session.add(RSVP(user_id=ana['ana'], showtime_id=late.id, group_id=1, status='going'))
        db.session.commit()
    assert not any(p['discord_user_id'] == '6601' for p in dm_prompts())           # within 20h of the last DM: waits


def test_answering_from_discord_and_clearing(ana):
    from app import app, db, Attendance, RSVP, Showtime
    client().post('/api/internal/attendance/prompted', json={'discord_user_id': '6601', 'showtime_ids': [ana['yesterday']]}, headers=H)
    r = client().post('/api/internal/attendance', json={'discord_user_id': '6601', 'create': '0', 'showtime_id': ana['yesterday'],
                                                        'status': 'went'}, headers=H)
    assert r.status_code == 200 and r.json['status'] == 'went' and r.json['title'] == 'SIRÂT'      # a DM button press
    a = client(ana['ana'])
    a.post('/api/attendance', json={'showtime_id': ana['yesterday'], 'status': None})
    with app.app_context():
        row = Attendance.query.filter_by(user_id=ana['ana'], showtime_id=ana['yesterday']).first()
        assert row.status is None and row.prompted_at                              # keeps the "already asked" marker
    a.post('/api/attendance', json={'showtime_id': ana['old'], 'status': 'went'})
    a.post('/api/attendance', json={'showtime_id': ana['old'], 'status': None})
    with app.app_context():
        assert Attendance.query.filter_by(user_id=ana['ana'], showtime_id=ana['old']).first() is None   # never asked: gone


def test_history_from_discord(answered):
    h = client().get('/api/internal/history', query_string={'member_discord_id': '6601', 'group_id': 1}, headers=H).json
    assert h['name'] == 'Ana' and all(i['status'] in ('went', 'going') for i in h['items'])


def test_history_follows_an_account_merge(ana):
    from app import app, db, Attendance, User
    with app.app_context():
        d = User(discord_user_id='6602', name='Dee', is_active=True)
        db.session.add(d)
        db.session.flush()
        db.session.add(Attendance(user_id=d.id, showtime_id=ana['old'], status='went', source='discord'))
        site = User(email='dee@test.dev', name='Dee Site', is_active=True, discord_link_code='DEE234',
                    discord_link_code_expires=datetime.utcnow() + timedelta(minutes=5))
        db.session.add(site)
        db.session.commit()
        site_id = site.id
    client().post('/api/internal/link/verify', json={'code': 'DEE234', 'discord_user_id': '6602'}, headers=H)
    with app.app_context():
        assert Attendance.query.filter_by(user_id=site_id, showtime_id=ana['old'], status='went').first() is not None

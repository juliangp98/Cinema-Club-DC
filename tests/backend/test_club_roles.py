"""R5c club roles (admin / organizer / member / read-only), the same rules
through the bot, and bringing personal plans into a club."""
import time
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, setup_db

POLL = {'title': 'P', 'announce': 'none', 'categories': [{'title': 'C', 'options': [{'text': 'x'}, {'text': 'y'}]}]}


@pytest.fixture
def club():
    """Role Club (the Discord server's club): Ada admin, Olly organizer, Mo
    member, Vi read-only; Newbie (not in it yet) has personal plans for ROLE
    ONE (going), TWO (maybe) and THREE (going). ROLE ONE has a Discord thread."""
    import app as A
    from app import app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, ShowtimeThread
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Role Club', slug='role-club', is_public=False)
        db.session.add(g)
        db.session.flush()
        us = {n: User(email=f'{n}@r5c.test', name=n.title(), is_active=True, discord_user_id=d)
              for n, d in (('ada', '5101'), ('olly', '5102'), ('mo', '5103'), ('vi', '5104'), ('newbie', '5105'))}
        db.session.add_all(us.values())
        db.session.flush()
        for n, role in (('ada', 'admin'), ('olly', 'organizer'), ('mo', 'member'), ('vi', 'viewer')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g.id, status='active', role=role))
        now = datetime.now()
        shows = []
        for i, t in enumerate(('ROLE ONE', 'ROLE TWO', 'ROLE THREE')):
            m = Movie(title=t)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=2 + i))
            db.session.add(s)
            db.session.flush()
            shows.append(s.id)
        db.session.add(ShowtimeThread(showtime_id=shows[0], group_id=g.id, guild_id='1', channel_id='2', thread_id='424242'))
        for sid, st in zip(shows, ('going', 'maybe', 'going')):
            db.session.add(RSVP(user_id=us['newbie'].id, showtime_id=sid, group_id=None, status=st))
        db.session.commit()
        ids = {n: u.id for n, u in us.items()}
        gid = g.id
    A.DISCORD_GROUP_ID = gid
    all_linked_present()
    return {'group': gid, 's1': shows[0], 's2': shows[1], 's3': shows[2], **ids}


def as_(club, name):
    from app import app
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = club[name]
        s['seen'] = int(time.time())
    return c


def code(r):
    return r.status_code, (r.get_json(silent=True) or {}).get('code')


def test_read_only_members_see_but_dont_act(club):
    vi, G, S1 = as_(club, 'vi'), club['group'], club['s1']
    assert vi.get(f'/api/showtimes/{S1}', query_string={'group_id': G}).status_code == 200
    assert vi.get('/api/feed', query_string={'group_id': G}).status_code == 200
    assert vi.get(f'/api/groups/{G}/polls').status_code == 200
    assert code(vi.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': G})) == (403, 'read_only')
    assert code(vi.post('/api/reactions', json={'showtime_id': S1, 'emoji': '🔥', 'group_id': G})) == (403, 'read_only')
    assert code(vi.post('/api/messages', json={'showtime_id': S1, 'group_id': G, 'body': 'hi'})) == (403, 'read_only')
    assert code(vi.post('/api/discord/shares', json={'kind': 'invite', 'group_id': G, 'showtime_id': S1})) == (403, 'read_only')
    assert vi.post('/api/rsvp', json={'showtime_id': club['s2'], 'status': 'going'}).status_code == 200   # personal plans still fine


def test_polls_are_for_organizers_and_up(club):
    G = club['group']
    assert code(as_(club, 'mo').post(f'/api/groups/{G}/polls', json=POLL)) == (403, 'role')
    olly = as_(club, 'olly')
    r = olly.post(f'/api/groups/{G}/polls', json=POLL)
    assert r.status_code == 201
    pid, cat = r.json['id'], r.json['categories'][0]
    assert olly.put(f'/api/polls/{pid}', json={'title': 'P2'}).status_code == 200
    assert olly.post(f'/api/polls/{pid}/score', json={'winners': {str(cat['id']): cat['options'][0]['id']}}).status_code == 200
    assert olly.post('/api/discord/shares', json={'kind': 'poll_results', 'group_id': G, 'poll_id': pid}).status_code == 201


def test_voting_needs_a_member(club):
    G = club['group']
    poll = as_(club, 'ada').post(f'/api/groups/{G}/polls', json=POLL).json
    cat = poll['categories'][0]
    vote = {'votes': [{'category_id': cat['id'], 'option_id': cat['options'][0]['id']}]}
    assert code(as_(club, 'vi').post(f"/api/polls/{poll['id']}/vote", json=vote)) == (403, 'read_only')
    assert as_(club, 'mo').post(f"/api/polls/{poll['id']}/vote", json=vote).status_code == 200


def test_organizers_dont_manage_members(club):
    olly = as_(club, 'olly')
    assert code(olly.put(f"/api/groups/role-club/members/{club['mo']}/role", json={'role': 'viewer'}))[0] == 403
    assert olly.post('/api/admin/invite', json={'email': 'x@r5c.test', 'group_id': club['group']}).status_code == 403


def test_admins_grant_and_revoke_roles(club):
    ada, role_of = as_(club, 'ada'), lambda who: f"/api/groups/role-club/members/{club[who]}/role"
    r = ada.put(role_of('vi'), json={'role': 'member'})
    assert r.status_code == 200 and r.json['role'] == 'member'
    assert as_(club, 'vi').post('/api/rsvp', json={'showtime_id': club['s1'], 'status': 'going', 'group_id': club['group']}).status_code == 200
    assert ada.put(role_of('vi'), json={'role': 'owner'}).status_code == 400                   # unknown role


def test_the_last_admin_stays_until_theres_another(club):
    ada, role_of = as_(club, 'ada'), lambda who: f"/api/groups/role-club/members/{club[who]}/role"
    assert code(ada.put(role_of('ada'), json={'role': 'member'})) == (400, 'last_admin')
    assert code(ada.delete(f"/api/groups/role-club/members/{club['ada']}")) == (400, 'last_admin')
    ada.put(role_of('olly'), json={'role': 'admin'})
    assert ada.put(role_of('ada'), json={'role': 'organizer'}).status_code == 200
    assert as_(club, 'olly').put(role_of('vi'), json={'role': 'viewer'}).status_code == 200    # the new admin manages roles


def test_the_same_rules_through_the_bot(club):
    from app import app
    G, S1 = club['group'], club['s1']
    poll = as_(club, 'ada').post(f'/api/groups/{G}/polls', json=POLL).json
    bot = app.test_client()
    who = lambda d: {'discord_user_id': d, 'create': '0', 'group_id': G}
    assert code(bot.post('/api/internal/rsvp', json={**who('5104'), 'showtime_id': S1, 'status': 'going'}, headers=H)) == (403, 'read_only')
    assert code(bot.post(f"/api/internal/polls/{poll['id']}/vote", json={**who('5104'), 'votes': []}, headers=H)) == (403, 'read_only')
    msg = {**who('5104'), 'thread_id': '424242', 'body': 'x'}
    assert code(bot.post('/api/internal/discussion/messages', json={**msg, 'discord_message_id': '9001', 'source': 'discord_bot'},
                         headers=H)) == (403, 'read_only')                                    # the Discuss button
    assert bot.post('/api/internal/discussion/messages', json={**msg, 'discord_message_id': '9002', 'body': 'typed'},
                    headers=H).status_code == 201                                             # typed in the thread: mirrored
    assert bot.post('/api/internal/rsvp', json={**who('5105'), 'showtime_id': S1, 'status': 'going'}, headers=H).status_code == 403


def test_bringing_personal_plans_into_the_club(club):
    from app import app, db, GroupMembership, RSVP, ShowtimeThread
    G, S1, S2, S3 = club['group'], club['s1'], club['s2'], club['s3']
    with app.app_context():
        db.session.add(GroupMembership(user_id=club['newbie'], group_id=G, status='active', role='member'))
        db.session.add(RSVP(user_id=club['newbie'], showtime_id=S3, group_id=G, status='maybe'))      # S3 already with the club
        db.session.commit()
    newbie = as_(club, 'newbie')
    assert [i['showtime_id'] for i in newbie.get(f'/api/groups/{G}/personal-plans').json['items']] == [S1, S2, S3]
    assert as_(club, 'vi').get(f'/api/groups/{G}/personal-plans').status_code == 403            # read-only aren't asked
    assert newbie.post(f'/api/groups/{G}/personal-plans', json={'showtime_ids': [S1, S3]}).json['moved'] == 1
    with app.app_context():
        rows = {(x.showtime_id, x.group_id): x.status for x in RSVP.query.filter_by(user_id=club['newbie'])}
        assert rows == {(S1, G): 'going', (S2, None): 'maybe', (S3, G): 'maybe'}               # no duplicate for S3
        assert ShowtimeThread.query.filter_by(thread_id='424242').first().card_dirty           # Discord card refreshes
    mo = as_(club, 'mo')
    assert 'Newbie' in [a['name'] for a in mo.get(f'/api/showtimes/{S1}', query_string={'group_id': G}).json['attendees']]
    assert 'Newbie' not in [a['name'] for a in mo.get(f'/api/showtimes/{S2}', query_string={'group_id': G}).json['maybes']]

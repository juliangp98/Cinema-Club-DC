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


def test_members_can_leave_but_not_remove_others(club):
    mo = as_(club, 'mo')
    assert mo.delete(f"/api/groups/role-club/members/{club['vi']}").status_code == 403          # only admins remove others
    assert mo.delete(f"/api/groups/role-club/members/{club['mo']}").status_code == 200          # leaving
    assert all(g['slug'] != 'role-club' for g in mo.get('/api/groups').json)
    names = [m['user']['name'] for m in as_(club, 'ada').get('/api/groups/role-club/members').json]
    assert names and 'Mo' not in names and 'mo' not in names


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


def test_organizers_choose_which_theatres_announce_new_showtimes(club):
    """7g: the site's switch is the same setting as /announcements in Discord (unknown theatres are ignored)."""
    from helpers import H
    r = as_(club, 'olly').put('/api/groups/role-club', json={'announce_theatres': ['afi', 'nowhere', 'afi']})
    assert r.status_code == 200 and r.json['announce_theatres'] == ['afi']
    bot = as_(club, 'olly').get('/api/internal/alerts', query_string={'group_id': club['group']}, headers=H).json
    assert bot['slugs'] == ['afi']
    assert as_(club, 'mo').put('/api/groups/role-club', json={'announce_theatres': []}).status_code == 403


def test_alerts_come_in_groups_for_settings(club):
    """7g: Settings → Notifications groups the alert types (notify.TYPE_GROUPS) — every type in one group."""
    import notify
    assert set(notify.GROUP_OF) == set(notify.TYPES)
    info = as_(club, 'olly').get('/api/me/notifications').json['types_info']
    groups = [t['group'] for t in info]
    assert groups == sorted(groups, key=['films', 'going', 'games', 'running'].index)   # in order, each group together
    assert {t['group_label'] for t in info} >= {'Your films', 'Going out', 'Games', 'Running a club'}


def test_invite_only_clubs_refuse_join_requests_and_admins_choose(club):
    """SEO: a club that isn't listed on the Clubs page is invite-only — nobody can ask to join it, even
    knowing its address. Only admins switch it; ours starts invite-only (a one-time change on start)."""
    from app import app, db, BotSetting, Group
    with app.app_context():
        db.session.get(Group, club['group']).is_public = False
        db.session.commit()
    stranger = as_(club, 'newbie').post('/api/groups/role-club/join')
    assert stranger.status_code == 403 and 'invite-only' in stranger.json['error']
    assert as_(club, 'olly').put('/api/groups/role-club', json={'is_public': True}).status_code == 403   # organizers can't
    assert as_(club, 'ada').put('/api/groups/role-club', json={'is_public': True}).json['is_public'] is True
    assert as_(club, 'newbie').post('/api/groups/role-club/join').status_code == 202               # listed: requests open
    with app.app_context():
        assert db.session.get(BotSetting, 'discord_club_private_done') is not None             # migrate() ran it once


def test_ai_features_are_for_club_members(club):
    """SEO: ✨ search spends the club's AI allowance — not for strangers who signed up."""
    r = as_(club, 'newbie').post('/api/search/ai', json={'q': 'a scary film tonight'})
    assert r.status_code == 403 and r.json['code'] == 'members'

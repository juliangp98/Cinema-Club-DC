"""Seeing a member's lists and comparing with them (R5): watchlists, RSVPs,
what you both want / are going to / saw — only through a shared club."""
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, client, film_id, setup_db


@pytest.fixture
def pair():
    """Ana and Bo share the club (group 1); Ana is also in a private club Bo
    isn't; Eve shares nothing. Screenings: SIRÂT (Ana going, Bo maybe),
    HAMNET (Ana), VERTIGO (Bo), KHARTOUM (Ana, private club), SINNERS (next
    showing); past: SIRÂT both went, HAMNET Ana only. Watchlists: both want
    SINNERS, Bo wants HAMNET, Ana wants VERTIGO and KHARTOUM."""
    from app import app, db, User, Group, GroupMembership, RSVP, Showtime, Theatre, Watchlist
    setup_db()
    with app.app_context():
        now = datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        films = {t: film_id(t) for t in ('SIRÂT', 'HAMNET', 'VERTIGO', 'SINNERS', 'KHARTOUM')}

        def show(title, days):
            s = Showtime(movie_id=films[title], theatre_id=tid, start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=2))
            db.session.add(s)
            db.session.flush()
            return s.id
        ids = {'both': show('SIRÂT', 1), 'ana_hamnet': show('HAMNET', 2), 'bo_vertigo': show('VERTIGO', 3),
               'private': show('KHARTOUM', 4), 'sinners_next': show('SINNERS', 5),
               'together': show('SIRÂT', -3), 'ana_only': show('HAMNET', -4)}
        g2 = Group(name='Ana Private', slug='ana-private', is_public=False)
        db.session.add(g2)
        db.session.flush()
        ana = User(email='ana7@test.dev', name='Ana', is_active=True, discord_user_id='7701')
        bo = User(email='bo7@test.dev', name='Bo', is_active=True, discord_user_id='7702')
        eve = User(email='eve7@test.dev', name='Eve', is_active=True)
        db.session.add_all([ana, bo, eve])
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=1, status='active'),
                            GroupMembership(user_id=ana.id, group_id=g2.id, status='active'),
                            GroupMembership(user_id=bo.id, group_id=1, status='active')])
        for u, key, gid, st in [(ana, 'both', 1, 'going'), (bo, 'both', 1, 'maybe'), (ana, 'ana_hamnet', 1, 'going'),
                                (bo, 'bo_vertigo', 1, 'going'), (ana, 'private', g2.id, 'going'),
                                (ana, 'together', 1, 'going'), (bo, 'together', 1, 'going'), (ana, 'ana_only', 1, 'going')]:
            db.session.add(RSVP(user_id=u.id, showtime_id=ids[key], group_id=gid, status=st))
        for u, t in [(ana, 'SINNERS'), (bo, 'SINNERS'), (bo, 'HAMNET'), (ana, 'VERTIGO'), (ana, 'KHARTOUM')]:
            db.session.add(Watchlist(user_id=u.id, movie_id=films[t]))
        db.session.commit()
        ids.update(ana=ana.id, bo=bo.id, eve=eve.id)
    all_linked_present()
    return ids


def test_a_members_watchlist_with_next_showings(pair):
    wl = client(pair['bo']).get(f"/api/users/{pair['ana']}/watchlist").json
    titles = {i['movie']['title']: i['next'] for i in wl['items']}
    assert not wl['own'] and set(titles) == {'SINNERS', 'VERTIGO', 'KHARTOUM'}
    assert titles['VERTIGO']['showtime_id'] == pair['bo_vertigo']
    assert client(pair['ana']).get(f"/api/users/{pair['ana']}/watchlist").json['own']
    assert client(pair['eve']).get(f"/api/users/{pair['ana']}/watchlist").status_code == 403    # no shared club


def test_rsvps_only_from_shared_clubs(pair):
    theirs = {i['showtime_id']: i['status'] for i in client(pair['bo']).get(f"/api/users/{pair['ana']}/rsvps").json['items']}
    assert theirs == {pair['both']: 'going', pair['ana_hamnet']: 'going'}          # not the private club's
    mine = client(pair['ana']).get(f"/api/users/{pair['ana']}/rsvps").json['items']
    assert pair['private'] in {i['showtime_id'] for i in mine} and pair['together'] not in {i['showtime_id'] for i in mine}
    order = [i['start_time'] for i in mine]
    assert order == sorted(order) and len(order) == 3                             # soonest first, upcoming only


def test_comparing_two_members(pair):
    cmp = client(pair['bo']).get(f"/api/users/{pair['ana']}/compare").json
    assert [x['movie']['title'] for x in cmp['both_want']] == ['SINNERS']
    assert cmp['both_want'][0]['next']['showtime_id'] == pair['sinners_next']
    assert [(x['showtime_id'], x['status']) for x in cmp['both_going']] == [(pair['both'], 'going')]
    assert [x['showtime_id'] for x in cmp['they_go_you_want']] == [pair['ana_hamnet']]
    assert [x['showtime_id'] for x in cmp['you_go_they_want']] == [pair['bo_vertigo']]
    assert all(x['showtime_id'] != pair['private'] for k in ('both_going', 'they_go_you_want') for x in cmp[k])
    assert [x['showtime_id'] for x in cmp['seen_together']] == [pair['together']]


def test_seen_together_drops_when_one_missed_it(pair):
    from app import app, db, Attendance
    with app.app_context():
        db.session.add(Attendance(user_id=pair['bo'], showtime_id=pair['together'], status='missed', source='site'))
        db.session.commit()
    assert client(pair['bo']).get(f"/api/users/{pair['ana']}/compare").json['seen_together'] == []


def test_compare_refusals(pair):
    assert client(pair['ana']).get(f"/api/users/{pair['ana']}/compare").status_code == 400     # yourself
    assert client(pair['eve']).get(f"/api/users/{pair['ana']}/compare").status_code == 403     # no shared club


def test_compare_from_discord(pair):
    ask = lambda other: client().get('/api/internal/compare', headers=H, query_string={
        'discord_user_id': '7702', 'create': '1', 'group_id': 1, 'member_discord_id': other})
    d = ask('7701').json
    assert d['name'] == 'Ana' and [x['movie']['title'] for x in d['both_want']] == ['SINNERS']
    assert [x['showtime_id'] for x in d['they_go_you_want']] == [pair['ana_hamnet']]
    assert ask('9999').status_code == 404 and ask('7702').status_code == 400

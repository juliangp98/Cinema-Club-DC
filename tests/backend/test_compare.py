"""Seeing a member's lists and comparing with them (R5): watchlists, RSVPs,
what you both want / are going to / saw — only through a shared club."""
import pytest

from helpers import H, client, seed_compare_pair


@pytest.fixture
def pair():
    return seed_compare_pair()


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

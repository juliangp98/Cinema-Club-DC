"""Tournaments (tournaments.py): brackets of 1-v-1 challenges — double
elimination with byes and a losers' bracket, or a round robin and a final —
entries, seeds, no-shows, prizes, backing the champion, and who hears about
it, on the site and in Discord."""
import json
from datetime import datetime, timedelta

import pytest

from helpers import client
from test_challenges import kernels, play


@pytest.fixture
def big(club):
    """The Versus Club, plus Fay and Gus (members, 20 kernels each)."""
    from app import app, db, GroupMembership, KernelGift, Showtime, User
    with app.app_context():
        show = Showtime.query.first()
        for n in ('Fay', 'Gus'):
            u = User(name=n, email=f'{n.lower()}@versus.test', is_active=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=club['G'], status='active', role='member'))
            db.session.add(KernelGift(giver_id=club['Gift'], recipient_id=u.id, group_id=club['G'], showtime_id=show.id,
                                      week=datetime(2026, 1, 5).date(), amount=20))
            club[n] = u.id
        db.session.commit()
    return club


def new(c, who='Ana', players=('Bo', 'Cy'), **body):
    data = {'group_id': c['G'], 'format': 'double', 'kind': 'who_said', 'questions': 1, 'players': [c[n] for n in players],
            'stake': 3, 'payout': 'all', 'deadline': 'tonight', 'match_time': 'day', 'visibility': 'club', **body}
    return client(c[who]).post('/api/tournaments', json=data)


def get(c, who, tid):
    return client(c[who]).get(f'/api/tournaments/{tid}').json


def act(c, who, tid, action, **body):
    return client(c[who]).post(f'/api/tournaments/{tid}/{action}', json=body)


def everyone_in(c, tid, names):
    for n in names:
        assert act(c, n, tid, 'respond', accept=True).status_code == 200


def matches(t):
    return [m for sec in ('winners', 'losers', 'league', 'final') for m in t['bracket'][sec]]


def run(c, tid, order):
    """Play the tournament out: in every open match, whoever comes first in
    `order` gets everything right and the other gets everything wrong."""
    names = {v: k for k, v in c.items() if isinstance(v, int)}
    for _ in range(40):
        t = get(c, 'Ana', tid)
        if t['status'] != 'running':
            return t
        todo = [m for m in matches(t) if m['status'] == 'open']
        assert todo, t
        for m in todo:
            a, b = names[m['a']['user']['id']], names[m['b']['user']['id']]
            win, lose = (a, b) if order.index(a) < order.index(b) else (b, a)
            play(c, win, m['challenge_id'], [True] * 3)
            play(c, lose, m['challenge_id'], [False] * 3)
    raise AssertionError('never finished')


def test_the_brackets():
    import tournaments
    three = tournaments.double_bracket(3)
    assert [(m['key'], m['a_from'], m['b_from']) for m in three] == [
        ('W1-0', 'seed:1', 'seed:4'), ('W1-1', 'seed:2', 'seed:3'), ('W2-0', 'winner:W1-0', 'winner:W1-1'),
        ('L1-0', 'loser:W1-0', 'loser:W1-1'), ('L2-0', 'winner:L1-0', 'loser:W2-0'), ('GF', 'winner:W2-0', 'winner:L2-0')]
    eight = tournaments.double_bracket(5)                         # filled to 8: three byes for the top seeds
    assert [m['key'] for m in eight if m['key'][0] == 'W'] == ['W1-0', 'W1-1', 'W1-2', 'W1-3', 'W2-0', 'W2-1', 'W3-0']
    assert [m['key'] for m in eight if m['key'][0] == 'L'] == ['L1-0', 'L1-1', 'L2-0', 'L2-1', 'L3-0', 'L4-0']
    assert next(m for m in eight if m['key'] == 'L2-0')['b_from'] == 'loser:W2-1'     # dropped in crosswise: no rematch
    assert len(tournaments.double_bracket(16)) == 30 and tournaments._order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    for n in (3, 4, 5, 6):
        games = tournaments.league(n)
        pairs = {frozenset((m['a_from'], m['b_from'])) for m in games if m['key'] != 'F'}
        assert len(pairs) == n * (n - 1) // 2 and games[-1]['a_from'] == 'place:1'


def test_three_players_double_elimination(club):
    r = new(club, stake=3)
    assert r.status_code == 201, r.json
    tid = r.json['id']
    assert r.json['status'] == 'open' and r.json['you']['can_cancel'] and not r.json['you']['can_start']
    assert get(club, 'Bo', tid)['you']['can_accept']
    everyone_in(club, tid, ('Bo', 'Cy'))
    t = get(club, 'Ana', tid)
    assert t['status'] == 'running' and sorted(p['seed'] for p in t['players']) == [1, 2, 3]
    w1 = {m['key']: m for m in t['bracket']['winners']}
    assert w1['W1-0']['status'] == 'bye' and w1['W1-0']['b'] == {'bye': True}           # the top seed waits
    assert w1['W1-1']['status'] == 'open' and w1['W1-1']['challenge_id']
    assert kernels(club, 'Ana')['kernels'] == 20 and client(club['Ana']).get(
        f"/api/challenges?group_id={club['G']}").json['on_the_line'] == 3                  # the entry, held

    done = run(club, tid, ['Cy', 'Bo', 'Ana'])
    assert done['status'] == 'done'
    champ = next(p for p in done['players'] if p['place'] == 1)
    assert champ['user']['name'] == 'Cy' and champ['net'] == 6
    assert sorted(p['net'] for p in done['players']) == [-3, -3, 6]
    assert len([m for m in matches(done) if m['challenge_id']]) == 4                    # 2 × 3 − 2: one grand final
    assert kernels(club, 'Cy')['challenges'] == 6 and kernels(club, 'Cy')['kernels'] == 26
    rec = client(club['Cy']).get(f"/api/challenges/rivals?group_id={club['G']}").json['record']
    assert rec['titles'] == 1 and rec['won'] >= 2                                      # matches count as challenges
    listed = client(club['Cy']).get(f"/api/challenges?group_id={club['G']}").json['challenges']
    assert not any(c['tournament'] for c in listed)                                    # decided ones: on the bracket


def test_byes_and_the_losers_bracket(big):
    r = new(big, players=('Bo', 'Cy', 'Di', 'Fay'), stake=0)
    tid = r.json['id']
    everyone_in(big, tid, ('Bo', 'Cy', 'Di', 'Fay'))
    t = get(big, 'Ana', tid)
    assert sum(1 for m in t['bracket']['winners'] if m['round'] == 1 and m['status'] == 'bye') == 3
    done = run(big, tid, ['Fay', 'Di', 'Cy', 'Bo', 'Ana'])
    assert len([m for m in matches(done) if m['challenge_id']]) == 8                    # 2n − 2 real matches
    gf = done['bracket']['final'][0]
    assert gf['label'] == 'Grand final' and next(p for p in done['players'] if p['place'] == 1)['user']['name'] == 'Fay'
    assert {p['user']['name'] for p in done['players'] if p['place'] in (2, 3)} <= {'Di', 'Cy', 'Bo', 'Ana'}


def test_round_robin_then_a_final_and_60_30_10(club):
    r = new(club, players=('Bo', 'Cy', 'Di'), format='round_robin', stake=4, payout='top3')
    tid = r.json['id']
    everyone_in(club, tid, ('Bo', 'Cy', 'Di'))
    t = get(club, 'Ana', tid)
    assert len(t['bracket']['league']) == 6 and all(m['status'] == 'open' for m in t['bracket']['league'])
    assert t['bracket']['final'][0]['status'] == 'waiting' and t['prizes'] == [11, 4, 1]
    done = run(club, tid, ['Bo', 'Cy', 'Ana', 'Di'])
    table = [r['user']['name'] for r in done['standings']]
    assert table == ['Bo', 'Cy', 'Ana', 'Di'] and done['standings'][0]['won'] == 3
    nets = {p['user']['name']: (p['place'], p['net']) for p in done['players']}
    assert nets == {'Bo': (1, 7), 'Cy': (2, 0), 'Ana': (3, -3), 'Di': (None, -4)}      # pot 16: 11 (9 + what rounding leaves), 4, 1


def test_entries_close_seats_and_no_shows(club):
    import challenges
    import tournaments
    from app import app, db, Tournament
    short = new(club, players=('Bo',), seats=1).json['id']
    full = new(club, players=('Bo', 'Cy'), seats=1).json['id']
    everyone_in(club, full, ('Bo',))
    assert act(club, 'Di', full, 'join').status_code == 200                              # the seat: it starts (Cy still invited)…
    assert get(club, 'Di', full)['status'] == 'open'
    assert act(club, 'Ana', full, 'start').status_code == 200                            # …or the creator starts it with who's in
    assert get(club, 'Cy', full)['you']['status'] == 'expired'
    later = datetime.utcnow() + timedelta(days=2)
    with app.app_context():
        tournaments.start_due(later)                                                      # entries closed with two in: off
        assert db.session.get(Tournament, short).status == 'cancelled'
        challenges.settle_due(later)                                                      # nobody played their match:
    t = get(club, 'Ana', full)
    w = {m['key']: m for m in t['bracket']['winners']}
    seeds = {p['user']['id']: p['seed'] for p in t['players'] if p['seed']}
    assert w['W1-1']['status'] == 'done' and seeds[w['W1-1']['winner_id']] == 2           # the higher seed goes through


def test_backing_the_champion(big):
    tid = new(big, players=('Bo', 'Cy'), stake=0).json['id']
    assert act(big, 'Di', tid, 'back', user_id=big['Bo'], amount=3).status_code == 400   # Bo hasn't said yes yet
    everyone_in(big, tid, ('Bo', 'Cy'))
    assert act(big, 'Bo', tid, 'back', user_id=big['Cy'], amount=3).status_code == 400   # players can't back
    assert act(big, 'Di', tid, 'back', user_id=big['Cy'], amount=4).status_code == 200
    assert act(big, 'Fay', tid, 'back', user_id=big['Bo'], amount=2).status_code == 200
    run(big, tid, ['Cy', 'Bo', 'Ana'])
    assert act(big, 'Gus', tid, 'back', user_id=big['Cy'], amount=1).status_code == 400  # decided: closed
    done = get(big, 'Di', tid)
    assert done['backing']['mine']['net'] == 2 and get(big, 'Fay', tid)['backing']['mine']['net'] == -2
    assert kernels(big, 'Di')['challenges'] == 2


def test_backing_closes_once_a_match_is_decided(big):
    tid = new(big, players=('Bo', 'Cy'), stake=0).json['id']
    everyone_in(big, tid, ('Bo', 'Cy'))
    first = next(m for m in matches(get(big, 'Ana', tid)) if m['status'] == 'open')
    names = {v: k for k, v in big.items() if isinstance(v, int)}
    for side in ('a', 'b'):
        play(big, names[first[side]['user']['id']], first['challenge_id'], [True])
    assert not get(big, 'Di', tid)['you']['can_back']


def test_matches_are_challenges_without_their_own_stakes(club):
    tid = new(club, stake=2).json['id']
    everyone_in(club, tid, ('Bo', 'Cy'))
    m = next(m for m in matches(get(club, 'Ana', tid)) if m['status'] == 'open')
    players = [m['a']['user']['id'], m['b']['user']['id']]
    who = next(n for n in ('Ana', 'Bo', 'Cy') if club[n] in players)
    ch = client(club[who]).get(f"/api/challenges/{m['challenge_id']}").json
    assert ch['tournament'] == {'id': tid, 'title': '🏆 Double elimination', 'match': "Winners' round 1"}
    assert ch['stake'] == 0 and not ch['backing']['open'] and not ch['you']['can_cancel']
    listed = lambda n: [c['id'] for c in client(club[n]).get(f"/api/challenges?group_id={club['G']}").json['challenges']]
    assert m['challenge_id'] in listed(who)                                             # yours to play, on Play
    assert m['challenge_id'] not in listed('Di')                                        # the club sees the bracket instead
    cards = client(club['Di']).get(f"/api/feed?group_id={club['G']}").json['cards']
    assert any(c.get('type') == 'tournament' for c in cards) and not any(c.get('type') == 'challenge' for c in cards)
    assert act(club, who, tid, 'cancel').status_code == 400


def test_who_hears_about_it(club):
    from app import app, db, Notification, User
    with app.app_context():
        cy = db.session.get(User, club['Cy'])
        cy.notify_prefs = json.dumps({'types': {'challenge_invite': False}})
        db.session.get(User, club['Di']).notify_prefs = json.dumps({'types': {'challenge_open': True}})   # opted in
        db.session.commit()
    tid = new(club).json['id']
    bell = lambda n: client(club[n]).get('/api/notifications').json
    bo = [i for i in bell('Bo')['items'] if i['kind'] == 'tournament_invite']
    assert bo and bo[0]['needs_answer'] and bo[0]['link'] == f'/tournaments/{tid}'
    assert not [i for i in bell('Cy')['items'] if i['kind'] == 'tournament_invite']         # Cy turned invites off
    assert [i for i in bell('Di')['items'] if i['kind'] == 'tournament_open']
    assert not [i for i in bell('Bo')['items'] if i['kind'] == 'tournament_open']          # the default: off
    everyone_in(club, tid, ('Bo', 'Cy'))
    ready = [i for i in bell('Bo')['items'] if i['kind'] == 'tournament_match'] + \
        [i for i in bell('Ana')['items'] if i['kind'] == 'tournament_match']
    assert ready and ready[0]['needs_answer'] and ready[0]['link'].startswith('/challenges/')
    run(club, tid, ['Bo', 'Ana', 'Cy'])
    with app.app_context():
        results = Notification.query.filter_by(kind='tournament_result').all()
        assert len(results) == 3
        assert any(json.loads(n.payload_json)['place'] == 1 for n in results)


def test_a_new_tournament_checks(club):
    assert new(club, players=('Bo',)).json['error'].startswith('A tournament needs at least 3')
    assert 'at most 6' in new(club, players=('Bo', 'Cy', 'Di'), format='round_robin', seats=3).json['error']
    assert 'Entry runs' in new(club, stake=99).json['error']
    assert new(club, stake=10, who='Di').status_code == 201
    from app import app, db, Group
    with app.app_context():
        db.session.get(Group, club['G']).challenges_enabled = False
        db.session.commit()
    assert new(club).json['error'] == 'Challenges are off in this club.'


def test_random_games_are_drawn_for_each_match(club):
    t = new(club, kind=None, rounds=[{'kind': 'random', 'questions': 2}, {'kind': 'who_said', 'questions': 1}]).json
    assert [r['kind'] for r in t['rounds']] == ['random', 'who_said'] and t['games_line'] == '🧩 2 games: Random, Who said it'


def test_the_discord_post(club):
    import tournaments
    from app import app, db, DiscordPost, Tournament, render_post
    tid = new(club, announce='now').json['id']
    with app.app_context():
        assert DiscordPost.query.filter_by(kind='tournament', ref_id=tid).count() == 0       # Ana isn't on Discord here
        t = db.session.get(Tournament, tid)
        p = tournaments.post_payload(t)
        assert p['title'] == '🏆 Double elimination' and p['by'] is None
        assert all(x['name'] is None for x in p['players'])                                    # nobody's on Discord: no names
        db.session.add(DiscordPost(group_id=club['G'], kind='tournament', user_id=club['Ana'], ref_id=tid,
                                   post_at=datetime.utcnow()))
        db.session.commit()
        post = DiscordPost.query.filter_by(kind='tournament', ref_id=tid).first()
        assert render_post(post)['tournament_id'] == tid


def test_a_random_game_with_nothing_to_ask_is_drawn_again(club, monkeypatch):
    """The still game has no stills here: a random match draws again instead
    of handing the higher seed a walkover."""
    import challenges
    draws = iter(['still', 'who_said'])
    real = challenges.plan_rounds
    monkeypatch.setattr(challenges, 'plan_rounds', lambda g, d, rng=None: (
        [{'kind': next(draws), 'questions': 1}], None) if d.get('rounds', [{}])[0].get('kind') == 'random' else real(g, d, rng))
    monkeypatch.setattr(__import__('quizzes'), '_backdrops', lambda *a, **k: [])
    tid = new(club, kind='random').json['id']
    everyone_in(club, tid, ('Bo', 'Cy'))
    m = next(m for m in matches(get(club, 'Ana', tid)) if m['key'] == 'W1-1')
    assert m['status'] == 'open' and m['games'] == '🗣️ Who said it'

"""Challenges (challenges.py): members play the same set of a game against
each other with kernels on the line, others back a player; scores sealed or
live, 30 seconds a question, open seats, rematches, records and rivalries —
and who hears about it, on the site and in Discord."""
import json
from datetime import datetime, timedelta

from helpers import client


def make(c, who='Ana', **body):
    data = {'group_id': c['G'], 'kind': 'who_said', 'opponents': [c['Bo'], c['Cy']], 'stake': 3, 'questions': 3,
            'deadline': 'tonight', 'visibility': 'club', 'reveal': 'sealed', **body}
    return client(c[who]).post('/api/challenges', json=data)


def act(c, who, cid, action, **body):
    return client(c[who]).post(f'/api/challenges/{cid}/{action}', json=body)


def truth(cid, r, i):
    """The right answer to question `i` of game `r`."""
    from app import app, db, Challenge
    with app.app_context():
        state = json.loads(db.session.get(Challenge, cid).state_json)
        if state['rounds'][r]['kind'] == 'higher_lower':
            chain = state['chains'][str(r)]
            return 'before' if chain[i + 1]['year'] < chain[i]['year'] else 'after'
        return state['sets'][str(r)][i]['answer']


def play(c, who, cid, rights):
    """Play every question: right where `rights` says so, wrong otherwise."""
    shown = []
    for right in rights:
        q = client(c[who]).get(f'/api/challenges/{cid}/play').json['question']
        if not q:
            break
        shown.append(q)
        good = truth(cid, q['round'], q['q'])
        choice = good if right else ((good + 1) % len(q['options']) if isinstance(good, int)
                                     else ('after' if good == 'before' else 'before'))
        r = client(c[who]).post(f'/api/challenges/{cid}/play', json={'choice': choice})
        assert r.status_code == 200, r.json
    return shown


def kernels(c, who):
    return client(c[who]).get(f"/api/kernels?group_id={c['G']}").json


def test_off_until_the_club_turns_it_on(club):
    from app import app, db, Group
    with app.app_context():
        db.session.get(Group, club['G']).challenges_enabled = False
        db.session.commit()
    r = make(club)
    assert r.status_code == 400 and 'off' in r.json['error']


def test_everyone_gets_the_same_set_and_the_top_score_takes_the_pot(club):
    r = make(club)
    assert r.status_code == 201, r.json
    cid = r.json['id']
    assert r.json['pot'] == 3 and [p['status'] for p in r.json['players']] == ['accepted', 'invited', 'invited']
    for who in ('Bo', 'Cy'):
        assert act(club, who, cid, 'respond', accept=True).status_code == 200
    a = play(club, 'Ana', cid, [True, True, True])
    b = play(club, 'Bo', cid, [True, False, True])
    assert [(q['quote'], q['options']) for q in a] == [(q['quote'], q['options']) for q in b]    # the identical set
    view = client(club['Di']).get(f'/api/challenges/{cid}').json
    assert view['status'] == 'open' and all(p['score'] is None for p in view['players'])        # sealed
    mine = client(club['Ana']).get(f'/api/challenges/{cid}').json
    assert next(p for p in mine['players'] if p['user']['id'] == club['Ana'])['score'] == 3    # but you see yours
    play(club, 'Cy', cid, [False, False, False])
    done = client(club['Di']).get(f'/api/challenges/{cid}').json
    assert done['status'] == 'done' and done['pot'] == 9
    by = {p['user']['name']: p for p in done['players']}
    assert (by['Ana']['score'], by['Bo']['score'], by['Cy']['score']) == (3, 2, 0)
    assert (by['Ana']['net'], by['Bo']['net'], by['Cy']['net']) == (6, -3, -3) and by['Ana']['winner']
    asked = done['results'][0]['questions']
    assert len(done['results']) == 1 and len(asked) == 3 and asked[1]['answers'][str(club['Bo'])]['right'] is False
    k = kernels(club, 'Ana')
    assert k['challenges'] == 6 and k['kernels'] == 26
    row = next(r for r in client(club['Ana']).get(f"/api/groups/{club['G']}/leaderboard").json['rows']
               if r['user']['id'] == club['Ana'])
    assert row['breakdown']['challenges'] == 6 and row['stats']['challenges'] == {'played': 1, 'won': 1, 'lost': 0, 'streak': 1, 'titles': 0}


def test_a_tie_splits_the_pot_and_a_no_show_forfeits(club):
    from app import app, db, Challenge
    cid = make(club, stake=5).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    act(club, 'Cy', cid, 'respond', accept=True)
    play(club, 'Ana', cid, [True, False, False])
    play(club, 'Bo', cid, [False, True, False])
    with app.app_context():                                              # the deadline passes; Cy never played
        db.session.get(Challenge, cid).closes_at = datetime.utcnow() - timedelta(minutes=1)
        db.session.commit()
    done = client(club['Ana']).get(f'/api/challenges/{cid}').json
    by = {p['user']['name']: p for p in done['players']}
    assert by['Cy']['status'] == 'forfeit' and by['Cy']['net'] == -5
    assert sorted((by['Ana']['net'], by['Bo']['net'])) == [2, 3]       # 15 split two ways: the odd one to whoever finished first
    assert by['Ana']['net'] == 3


def test_live_scores_show_as_each_player_finishes(club):
    cid = make(club, reveal='live').json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    play(club, 'Bo', cid, [True, True, False])
    view = client(club['Di']).get(f'/api/challenges/{cid}').json
    assert next(p for p in view['players'] if p['user']['id'] == club['Bo'])['score'] == 2


def test_thirty_seconds_a_question(club):
    from app import app, db, ChallengePlayer
    cid = make(club).json['id']
    q = client(club['Ana']).get(f'/api/challenges/{cid}/play').json['question']
    assert q['q'] == 0 and q['ends_at']
    with app.app_context():                                              # Ana walks away for a minute
        p = ChallengePlayer.query.filter_by(challenge_id=cid, user_id=club['Ana']).one()
        prog = json.loads(p.progress_json)
        prog['shown_at'] = (datetime.utcnow() - timedelta(seconds=60)).isoformat()
        p.progress_json = json.dumps(prog)
        db.session.commit()
    q = client(club['Ana']).get(f'/api/challenges/{cid}/play').json['question']
    assert q['q'] == 1                                                                            # the first ran out: on to the next
    r = client(club['Ana']).post(f'/api/challenges/{cid}/play', json={'choice': truth(cid, 0, 1)}).json
    assert r['answered']['q'] == 1 and r['answered']['last']['right']
    with app.app_context():
        answers = json.loads(ChallengePlayer.query.filter_by(challenge_id=cid, user_id=club['Ana']).one().progress_json)['answers']
    assert answers[0]['timeout'] and answers[0]['points'] == 0


def test_backing_a_player(club):
    cid = make(club, stake=2).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    act(club, 'Cy', cid, 'respond', accept=True)
    assert act(club, 'Bo', cid, 'back', user_id=club['Ana'], amount=3).status_code == 400          # players can't back
    assert act(club, 'Di', cid, 'back', user_id=club['Bo'], amount=11).status_code == 400          # 1–10
    assert act(club, 'Di', cid, 'back', user_id=club['Bo'], amount=4).status_code == 200
    assert act(club, 'Di', cid, 'back', user_id=club['Cy'], amount=1).status_code == 400           # once
    assert client(club['Di']).get(f'/api/challenges/{cid}').json['backing']['total'] == 4
    assert client(club['Di']).get(f"/api/challenges?group_id={club['G']}").json['on_the_line'] == 4
    play(club, 'Bo', cid, [True, True, True])
    assert not client(club['Di']).get(f'/api/challenges/{cid}').json['backing']['open']             # closed once someone finishes
    play(club, 'Ana', cid, [True, False, False])
    play(club, 'Cy', cid, [False, False, False])
    done = client(club['Di']).get(f'/api/challenges/{cid}').json
    assert done['backing']['mine'] == {'backing_id': club['Bo'], 'amount': 4, 'net': 0}            # only backer of the winner: theirs back
    assert kernels(club, 'Di')['challenges'] == 0


def test_the_backing_pot_goes_to_whoever_backed_the_winner(club):
    from app import app, db, GroupMembership, KernelGift, User, Showtime
    with app.app_context():                                              # a second onlooker, with kernels
        fay = User(name='Fay', email='fay@versus.test', is_active=True)
        db.session.add(fay)
        db.session.flush()
        db.session.add(GroupMembership(user_id=fay.id, group_id=club['G'], status='active'))
        db.session.add(KernelGift(giver_id=club['Gift'], recipient_id=fay.id, group_id=club['G'],
                                  showtime_id=Showtime.query.first().id, week=datetime(2026, 1, 5).date(), amount=20))
        db.session.commit()
        club['Fay'] = fay.id
    cid = make(club, opponents=[club['Bo']], stake=0).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    act(club, 'Di', cid, 'back', user_id=club['Bo'], amount=6)
    act(club, 'Fay', cid, 'back', user_id=club['Ana'], amount=3)
    play(club, 'Bo', cid, [True, True, True])
    play(club, 'Ana', cid, [False, False, False])
    assert kernels(club, 'Di')['challenges'] == 3 and kernels(club, 'Fay')['challenges'] == -3
    assert kernels(club, 'Bo')['challenges'] == 0                        # stake 0: bragging rights only


def test_you_can_only_put_in_what_you_have(club):
    from app import app, db, Group
    with app.app_context():
        db.session.get(Group, club['G']).challenge_max_stake = 50
        db.session.commit()
    r = make(club, stake=30)
    assert r.status_code == 400 and 'You have 20 🍿' in r.json['error']
    cid = make(club, stake=15).json['id']
    assert 'You have 5 🍿' in make(club, stake=15, opponents=[club['Di']]).json['error']           # 15 already on the line
    assert act(club, 'Bo', cid, 'respond', accept=True).status_code == 200


def test_fewer_than_two_players_is_called_off(club):
    cid = make(club).json['id']
    act(club, 'Bo', cid, 'respond', accept=False)
    act(club, 'Cy', cid, 'respond', accept=False)
    done = client(club['Ana']).get(f'/api/challenges/{cid}').json
    assert done['status'] == 'cancelled' and kernels(club, 'Ana')['kernels'] == 20


def test_the_creator_can_call_it_off_or_end_it_early(club):
    cid = make(club).json['id']
    assert act(club, 'Bo', cid, 'cancel').status_code == 400                                       # not Bo's to call off
    assert act(club, 'Ana', cid, 'cancel').json['status'] == 'cancelled'
    cid = make(club, seats=2).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    play(club, 'Ana', cid, [True, True, True])
    assert act(club, 'Ana', cid, 'end').status_code == 400                                         # Bo hasn't played
    play(club, 'Bo', cid, [True, False, False])
    r = act(club, 'Ana', cid, 'end').json
    assert r['status'] == 'done' and next(p for p in r['players'] if p['user']['id'] == club['Cy'])['status'] == 'expired'


def test_open_seats(club):
    cid = make(club, opponents=[], seats=1).json['id']
    assert act(club, 'Eve', cid, 'join').status_code == 404                                        # not in the club
    assert act(club, 'Di', cid, 'join').json['seats_left'] == 0
    assert act(club, 'Cy', cid, 'join').status_code == 400                                         # full
    play(club, 'Ana', cid, [True, True, False])
    play(club, 'Di', cid, [True, False, False])
    assert client(club['Di']).get(f'/api/challenges/{cid}').json['status'] == 'done'


def test_rematch_and_double_or_nothing(club):
    cid = make(club, opponents=[club['Bo']], stake=4).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    play(club, 'Ana', cid, [True, True, True])
    play(club, 'Bo', cid, [False, False, False])
    r = act(club, 'Bo', cid, 'rematch', double=True)
    assert r.status_code == 201 and r.json['stake'] == 8 and r.json['rematch_of'] == cid
    assert [(p['user']['name'], p['status']) for p in r.json['players']] == [('Bo', 'accepted'), ('Ana', 'invited')]
    assert client(club['Ana']).get(f'/api/challenges/{cid}').json['rematch'] == r.json['id']


def test_higher_or_lower_is_one_run_on_the_same_films(club):
    cid = make(club, kind='higher_lower', opponents=[club['Bo']]).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    a = play(club, 'Ana', cid, [True, True, False, True])
    b = play(club, 'Bo', cid, [True, False, True])
    assert len(a) == 3 and len(b) == 2                                                             # a miss ends the run
    assert [q['current']['title'] for q in a[:2]] == [q['current']['title'] for q in b[:2]]
    done = client(club['Ana']).get(f'/api/challenges/{cid}').json
    assert {p['user']['name']: p['score'] for p in done['players']} == {'Ana': 2, 'Bo': 1}


def test_records_and_rivals(club):
    for winner in ('Ana', 'Ana', 'Bo'):
        cid = make(club, opponents=[club['Bo']], stake=1).json['id']
        act(club, 'Bo', cid, 'respond', accept=True)
        play(club, 'Ana', cid, [winner == 'Ana'] * 3)
        play(club, 'Bo', cid, [winner == 'Bo'] * 3)
    r = client(club['Bo']).get(f"/api/challenges/rivals?group_id={club['G']}&user_id={club['Ana']}").json
    assert r['record'] == {'played': 3, 'won': 2, 'lost': 1, 'streak': 0, 'titles': 0}
    assert r['rivals'][0]['user']['name'] == 'Bo' and (r['rivals'][0]['won'], r['rivals'][0]['lost']) == (2, 1)
    assert (r['versus_you']['won'], r['versus_you']['lost']) == (2, 1)                            # Ana against Bo, as Bo sees it


def test_who_sees_a_challenge(club):
    hidden = make(club, visibility='players').json['id']
    shown = make(club, opponents=[club['Bo']]).json['id']
    listed = [c['id'] for c in client(club['Di']).get(f"/api/challenges?group_id={club['G']}").json['challenges']]
    assert shown in listed and hidden not in listed
    assert client(club['Di']).get(f'/api/challenges/{hidden}').status_code == 404
    assert client(club['Eve']).get(f'/api/challenges/{shown}').status_code == 404


def test_who_hears_about_it(club):
    """Invites wait in the bell (and go out by DM, email or push only if
    chosen); results reach players and backers; new club challenges only those who asked."""
    import notify
    from app import app, db, Notification, User
    with app.app_context():
        notify.set_prefs(db.session.get(User, club['Cy']), {'types': {'challenge_open': True}})
        notify.set_prefs(db.session.get(User, club['Bo']), {'channels': {'discord': True}})
        db.session.commit()
    cid = make(club, opponents=[club['Bo']]).json['id']
    with app.app_context():
        notes = {(n.user_id, n.kind): n.channels for n in Notification.query.filter(Notification.kind.like('challenge_%'))}
    assert notes == {(club['Bo'], 'challenge_invite'): 'discord', (club['Cy'], 'challenge_open'): ''}
    bell = client(club['Bo']).get('/api/notifications').json['items'][0]
    assert bell['headline'] == 'Ana challenges you: 🗣️ Who said it' and bell['needs_answer'] and bell['link'] == f'/challenges/{cid}'
    act(club, 'Di', cid, 'back', user_id=club['Bo'], amount=2)
    act(club, 'Bo', cid, 'respond', accept=True)
    assert not client(club['Bo']).get('/api/notifications').json['items'][-1]['needs_answer']   # answered
    play(club, 'Ana', cid, [True, True, True])
    play(club, 'Bo', cid, [False, False, False])
    with app.app_context():
        got = sorted((n.user_id, n.kind) for n in Notification.query.filter(Notification.kind.in_(('challenge_result', 'challenge_backed'))))
    assert got == sorted([(club['Bo'], 'challenge_backed'), (club['Ana'], 'challenge_result'),
                          (club['Bo'], 'challenge_result'), (club['Di'], 'challenge_result')])
    di = client(club['Di']).get('/api/notifications').json['items'][0]
    assert di['headline'] == '🗣️ Who said it: Ana won'
    assert di['detail'] == 'You backed Bo · nobody backed Ana, so your 2 🍿 came back'


def test_discord_posts_follow_the_creators_setting_and_never_ping(club):
    import app as A
    from app import app, db, DiscordPost, User, render_post, set_share_pref
    from helpers import all_linked_present
    with app.app_context():
        for n, did in (('Ana', '9910'), ('Cy', '9912')):
            db.session.get(User, club[n]).discord_user_id = did
        set_share_pref(db.session.get(User, club['Cy']), 'challenge', 'never')
        db.session.commit()
    A.HOME_GROUP_ID = club['G']
    all_linked_present()
    cid = make(club, announce='now').json['id']
    with app.app_context():
        post = DiscordPost.query.filter_by(kind='challenge', ref_id=cid).one()
        payload = render_post(post)
    assert payload['game'] == '🗣️ Who said it' and payload['by'] == 'Ana' and payload['pot'] == 3
    assert [p['name'] for p in payload['players']] == ['Ana', 'Bo', None]                         # Cy said Never
    quiet = make(club, visibility='players', announce='now').json['id']
    with app.app_context():
        assert DiscordPost.query.filter_by(kind='challenge', ref_id=quiet).count() == 0              # not the club's to see


def test_posting_in_discord_is_the_creators_call_on_the_spot(club):
    """Whatever "Challenges I start or play" says, the creator can post this
    one (their name shows) or not post it."""
    import app as A
    from app import app, db, DiscordPost, User, render_post, set_share_pref
    from helpers import all_linked_present
    with app.app_context():
        ana = db.session.get(User, club['Ana'])
        ana.discord_user_id = '9910'
        set_share_pref(ana, 'challenge', 'never')
        db.session.commit()
    A.HOME_GROUP_ID = club['G']
    all_linked_present()
    posted = make(club, announce='now').json['id']
    with app.app_context():
        assert render_post(DiscordPost.query.filter_by(kind='challenge', ref_id=posted).one())['by'] == 'Ana'
        set_share_pref(db.session.get(User, club['Ana']), 'challenge', 'always')
        db.session.commit()
    kept = make(club, announce='none').json['id']
    default = make(club).json['id']
    with app.app_context():
        assert DiscordPost.query.filter_by(kind='challenge', ref_id=kept).count() == 0
        assert DiscordPost.query.filter_by(kind='challenge', ref_id=default).count() == 1           # Always, nothing said


def test_a_challenge_still_is_each_players_own(club, monkeypatch):
    import quizzes
    monkeypatch.setattr(quizzes, '_backdrops', lambda tid: ['/still.jpg'])
    monkeypatch.setattr(quizzes, 'crop_still', lambda state, step: b'jpeg-' + str(step).encode())
    cid = make(club, kind='still', opponents=[club['Bo']]).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    a = client(club['Ana']).get(f'/api/challenges/{cid}/play').json['question']
    assert '/api/challenges/still/' in a['image'] and '/0/0/' in a['image']                        # game 0, question 0
    b = client(club['Bo']).get(f'/api/challenges/{cid}/play').json['question']
    assert a['image'] != b['image'] and a['options'] == b['options']
    assert client().get(a['image']).data == b'jpeg-1'
    assert client().get(a['image'].replace('-1.jpg', '-2.jpg')).status_code == 404                 # no peeking ahead
    client(club['Ana']).post(f'/api/challenges/{cid}/play', json={'choice': 'more'})
    assert client().get(a['image'].replace('-1.jpg', '-2.jpg')).data == b'jpeg-2'


def test_the_feed_shows_club_challenges(club):
    cid = make(club, opponents=[club['Bo']]).json['id']
    make(club, visibility='players', opponents=[club['Cy']])
    cards = client(club['Di']).get(f"/api/feed?group_id={club['G']}&type=games").json['cards']
    mine = [c for c in cards if c['type'] == 'challenge']
    assert len(mine) == 1 and mine[0]['challenge']['id'] == cid and mine[0]['challenge']['status'] == 'open'


def test_a_gauntlet_is_won_on_games_then_points(club):
    """Several games: each game's top scorer wins it; most games won takes it
    — here one each, so kernels scored decide."""
    r = make(club, opponents=[club['Bo']], rounds=[{'kind': 'who_said', 'questions': 2}, {'kind': 'higher_lower'}])
    assert r.status_code == 201, r.json
    c = r.json
    assert c['gauntlet'] and [x['kind'] for x in c['rounds']] == ['who_said', 'higher_lower']
    assert c['games_line'] == '🧩 Gauntlet: Who said it, Higher or lower'
    act(club, 'Bo', c['id'], 'respond', accept=True)
    play(club, 'Ana', c['id'], [True, True, False])                 # Who said it 2, then a higher-or-lower miss
    play(club, 'Bo', c['id'], [False, False, True, False])          # Who said it 0, then a run of 1
    done = client(club['Ana']).get(f"/api/challenges/{c['id']}").json
    by = {p['user']['name']: p for p in done['players']}
    assert (by['Ana']['rounds_won'], by['Bo']['rounds_won']) == (1, 1)
    assert by['Ana']['winner'] and by['Ana']['round_scores'] == [2, 0] and by['Bo']['round_scores'] == [0, 1]
    assert [res['winners'] for res in done['results']] == [[club['Ana']], [club['Bo']]]
    assert len(done['results'][1]['questions']) == 2                # Bo's run: one right, then the miss


def test_games_can_be_random_and_any_length(club, monkeypatch):
    import quizzes
    monkeypatch.setattr(quizzes, '_backdrops', lambda tid: ['/still.jpg'])
    c = make(club, kind='gauntlet', games=3, questions=12).json
    kinds = [x['kind'] for x in c['rounds']]
    assert sorted(kinds) == ['higher_lower', 'still', 'who_said']    # random: each of the club's games once
    assert {x['questions'] for x in c['rounds'] if x['kind'] != 'higher_lower'} == {10}       # 1–10 a game
    one = make(club, kind='random', questions=8).json
    assert len(one['rounds']) == 1 and one['rounds'][0]['kind'] in ('who_said', 'higher_lower', 'still')
    assert make(club, rounds=[{'kind': 'emoji'}]).json['error'] == "Pick from the club's games."   # not on here


def test_the_games_can_be_picked_again_until_someone_plays(club, monkeypatch):
    import quizzes
    monkeypatch.setattr(quizzes, '_backdrops', lambda tid: ['/still.jpg'])          # if Guess the still comes up
    cid = make(club, kind='gauntlet', games=2).json['id']
    r = act(club, 'Ana', cid, 'games', rounds=[{'kind': 'who_said', 'questions': 4}])
    assert r.status_code == 200 and [x['kind'] for x in r.json['rounds']] == ['who_said'] and not r.json['gauntlet']
    assert act(club, 'Bo', cid, 'games', rounds=[{'kind': 'higher_lower'}]).status_code == 400    # not Bo's to change
    client(club['Ana']).get(f'/api/challenges/{cid}/play')
    assert act(club, 'Ana', cid, 'games', rounds=[{'kind': 'higher_lower'}]).status_code == 400   # someone's started


def test_who_played_beats_who_didnt(club):
    """Bo got the first one right, then never came back; Ana played them all
    and got none: Ana played, so Ana takes the pot."""
    import challenges
    from app import app
    cid = make(club, opponents=[club['Bo']], questions=3, stake=2).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    play(club, 'Bo', cid, [True])
    play(club, 'Ana', cid, [False] * 3)
    with app.app_context():
        challenges.settle_due(datetime.utcnow() + timedelta(days=4))
    done = client(club['Ana']).get(f'/api/challenges/{cid}').json
    nets = {p['user']['name']: (p['status'], p['net'], p['winner']) for p in done['players']}
    assert nets == {'Ana': ('finished', 2, True), 'Bo': ('forfeit', -2, False)}


def test_decided_the_moment_the_last_player_runs_out_of_time(club):
    """Found in the Play demo: the last player's last question ran out while they were away. Coming
    back finishes them (a miss), and that decides it then, not at the deadline."""
    from app import app, db, ChallengePlayer
    cid = make(club, opponents=[club['Bo']], questions=1, stake=0).json['id']
    act(club, 'Bo', cid, 'respond', accept=True)
    play(club, 'Bo', cid, [True])
    client(club['Ana']).get(f'/api/challenges/{cid}/play')                       # Ana sees her question, then walks away
    with app.app_context():
        p = ChallengePlayer.query.filter_by(challenge_id=cid, user_id=club['Ana']).one()
        prog = json.loads(p.progress_json)
        prog['shown_at'] = (datetime.utcnow() - timedelta(seconds=60)).isoformat()
        p.progress_json = json.dumps(prog)
        db.session.commit()
    r = client(club['Ana']).get(f'/api/challenges/{cid}/play').json
    assert r['question'] is None and r['challenge']['status'] == 'done'
    assert [p['user']['name'] for p in r['challenge']['players'] if p.get('winner')] == ['Bo']


def test_your_turn_says_who_its_against(club):
    """Found in the Play demo: two "Your turn: 🧠 Trivia" lines on Today looked the same. Each names the
    other players (not anyone who declined)."""
    cid = make(club).json['id']
    turn = lambda: client(club['Ana']).get('/api/play', query_string={'group_id': club['G']}).json['challenges']['your_turn']
    assert [(c['id'], c['against']) for c in turn()] == [(cid, 'Bo, Cy')]
    act(club, 'Cy', cid, 'respond', accept=False)
    assert turn()[0]['against'] == 'Bo'

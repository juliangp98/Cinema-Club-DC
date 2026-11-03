"""Challenge scouting (scout.py): the club's challenge stats and yours, who
you should challenge and why, their movie habits next to yours — only what
the club already sees — and the roast (never telling the AI anyone's name)."""
import json
from datetime import date, timedelta

from helpers import client
from test_challenges import act, make, play


def decide(c, winner, loser, stake=2, kind='who_said'):
    cid = make(c, who=winner, kind=kind, opponents=[c[loser]], stake=stake, questions=1).json['id']
    act(c, loser, cid, 'respond', accept=True)
    play(c, winner, cid, [True])
    play(c, loser, cid, [False])
    return cid


def scouting(c, who):
    return client(c[who]).get(f"/api/challenges/scout?group_id={c['G']}").json


def test_the_stats(club):
    decide(club, 'Bo', 'Ana')
    decide(club, 'Bo', 'Ana', stake=5)
    decide(club, 'Ana', 'Cy')
    s = scouting(club, 'Ana')['stats']
    by = {row['key']: row for row in s['club']}
    assert s['decided'] == 3 and s['kernels_moved'] == 9
    assert by['wins']['user']['name'] == 'Bo' and by['wins']['value'] == '2–0 (100%)'
    assert by['kernels']['value'] == '+7 🍿' and by['streak']['value'] == '2 wins in a row'
    assert by['pot']['value'].startswith('10 🍿') and by['pot']['user']['name'] == 'Bo'
    assert {by['rivalry']['user']['name'], by['rivalry']['other']['name']} == {'Ana', 'Bo'}
    assert by['game']['value'] == 'Who said it · 3 played'
    you = s['you']
    assert (you['won'], you['lost'], you['win_rate']) == (1, 2, 33)
    assert you['nemesis']['user']['name'] == 'Bo' and you['nemesis']['lost'] == 2
    assert you['victim']['user']['name'] == 'Cy' and you['biggest_win'] == 2


def test_who_to_challenge(club):
    decide(club, 'Bo', 'Ana')
    decide(club, 'Bo', 'Cy')
    picks = scouting(club, 'Ana')['picks']
    by = {p['user']['name']: p for p in picks}
    assert picks[0]['user']['name'] == 'Bo'                                     # a grudge (and a streak) first
    assert by['Bo']['tag']['label'] == 'Grudge match' and "They're 1–0 up on you. Settle it." in by['Bo']['why']
    assert any('2 in a row' in w for w in by['Bo']['why'])
    assert by['Di']['tag']['label'] == 'Fresh meat' and by['Di']['versus']['played'] == 0
    assert by['Bo']['kernels'] == {'them': 24, 'you': 18} and by['Bo']['record']['win_rate'] == 100
    assert by['Bo']['suggest']['kind'] in ('who_said', 'higher_lower', 'still') and by['Bo']['suggest']['stake'] == 3
    assert 'Eve' not in by and 'Ana' not in by                                  # another club's; yourself


def test_habits_show_only_what_the_club_sees(club):
    import scout
    from app import app, db, Group, LetterboxdEntry, User, Watchlist, Movie
    with app.app_context():
        di = db.session.get(User, club['Di'])
        for m in Movie.query.limit(4):
            db.session.add(Watchlist(user_id=di.id, movie_id=m.id))
        for i in range(5):
            db.session.add(LetterboxdEntry(user_id=di.id, guid=f'g{i}', watched_on=date.today() - timedelta(days=i), title=f'F{i}',
                                           year=1950 + i, rating=5.0, genres='horror'))
        db.session.commit()
        g = db.session.get(Group, club['G'])
        h = scout.habits(di, g)
        assert h['watchlist'] == 4 and h['watchlist_seen'] == 0 and 'diary' not in h          # no diary connected
        di.letterboxd_sync = True
        db.session.commit()
        h = scout.habits(di, g)
        assert h['diary'] == 5 and h['diary_median_year'] == 1952 and h['diary_genre'] == 'horror' and 'avg_rating' not in h
        di.letterboxd_ratings = True                                                      # sharing ratings: now they count
        db.session.commit()
        assert scout.habits(di, g)['avg_rating'] == 5.0 and 'genres' not in h              # taste: only if shown
    rows = {p['user']['name']: p for p in scouting(club, 'Ana')['picks']}['Di']['habits']
    assert {'icon': '📋', 'label': 'On the watchlist', 'you': '0', 'them': '4'} in rows
    assert {'icon': '⭐', 'label': 'Average rating', 'you': None, 'them': '5.0★'} in rows
    client(club['Di']).put('/api/auth/profile', json={'roastable': False})
    di = {p['user']['name']: p for p in scouting(club, 'Ana')['picks']}['Di']
    assert di['habits'] == [] and di['roastable'] is False                              # only the numbers
    r = client(club['Ana']).post(f"/api/challenges/scout/{club['Di']}/roast", json={'group_id': club['G']})
    assert r.status_code == 400 and 'turned off' in r.json['error']


def test_the_roast(club, monkeypatch):
    import ai
    import scout
    scout._roasts.clear()

    def down(messages, **kw):
        raise ai.Unavailable('no AI in the tests')
    monkeypatch.setattr(ai, 'chat', down)
    roast = lambda **b: client(club['Ana']).post(f"/api/challenges/scout/{club['Bo']}/roast",
                                                json={'group_id': club['G'], **b}).json
    got = roast()                                                       # no AI here: a line from the facts
    assert got['by'] == 'facts' and 'Bo' in got['roast'] and 'THEM' not in got['roast']
    assert roast()['roast'] == got['roast']                            # the same one, until you ask for another
    asked = []

    def chat(messages, **kw):
        asked.append(json.dumps(messages))
        return '"THEM has a watchlist longer than YOUR attention span 🍿"'
    monkeypatch.setattr(ai, 'chat', chat)
    again = roast(again=True)
    assert again == {'roast': 'Bo has a watchlist longer than your attention span 🍿', 'by': 'ai', 'more': True}
    assert 'Bo' not in asked[0] and 'Ana' not in asked[0]                # the AI never hears a name
    roast(again=True)
    assert roast(again=True)['more'] is False and len(asked) == 2        # a few a day
    assert scout._named('YOU and THEM tied. YOUR move.', 'Bo') == 'You and Bo tied. Your move.'

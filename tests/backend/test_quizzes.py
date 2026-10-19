"""Quiz games (R15, quizzes.py): each its own switch, off to start; a round
per member, private; higher or lower runs until a miss, who said it is one
question; +1 a right call, at most 5 kernels a day from each game — and it
all shows in the kernels and the leaderboard."""
import json

import pytest

from helpers import H, client, setup_db

FILMS = [('ALPHA', 1950), ('BRAVO', 1962), ('CHARLIE', 1971), ('DELTA', 1984), ('ECHO', 1990), ('FOXTROT', 1999),
         ('GOLF', 2004), ('HOTEL', 2011), ('INDIA', 2018), ('JULIET', 1977)]


@pytest.fixture
def club():
    """Quiz Club (our films only): Ana (organizer), Bo (member, Discord 9901);
    CASABLANCA with its characters, and a quote of Rick's."""
    from app import app, db, Group, GroupMembership, Movie, Quote, User
    setup_db()
    with app.app_context():
        g = Group(name='Quiz Club', slug='quiz-club', is_public=False, trivia_source='local')
        ana = User(name='Ana', email='ana@quiz.test', is_active=True)
        bo = User(name='Bo', email='bo@quiz.test', is_active=True, discord_user_id='9901')
        db.session.add_all([g, ana, bo])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=g.id, status='active', role='organizer'))
        db.session.add(GroupMembership(user_id=bo.id, group_id=g.id, status='active', role='member'))
        for i, (t, y) in enumerate(FILMS):
            db.session.add(Movie(title=t, release_year=str(y), tmdb_id=970000 + i, genres='drama'))
        cast = [{'name': n, 'character': c} for n, c in (('Humphrey Bogart', 'Rick Blaine'), ('Ingrid Bergman', 'Ilsa Lund'),
                                                        ('Paul Henreid', 'Victor Laszlo'), ('Claude Rains', 'Captain Renault'),
                                                        ('Conrad Veidt', 'Major Strasser'))]
        db.session.add(Movie(title='CASABLANCA', release_year='1942', tmdb_id=979999, genres='drama,romance',
                             cast_json=json.dumps(cast)))
        db.session.add(Quote(text='Here’s looking at you, kid.', movie='Casablanca', character='Rick'))
        db.session.commit()
        return {'G': g.id, 'slug': g.slug, 'ana': ana.id, 'bo': bo.id}


def turn_on(c, **games):
    r = client(c['ana']).put(f"/api/groups/{c['slug']}", json={'quizzes': games})
    assert r.status_code == 200, r.json
    return r.json['quizzes']


def start(c, kind, who='bo'):
    return client(c[who]).post('/api/quizzes/start', json={'group_id': c['G'], 'kind': kind})


def answer(c, rid, choice, who='bo'):
    return client(c[who]).post('/api/quizzes/answer', json={'group_id': c['G'], 'round_id': rid, 'choice': choice})


def truth(rid):
    """The right call for a higher-or-lower round as it stands."""
    from app import app, db, QuizRound
    with app.app_context():
        chain = json.loads(db.session.get(QuizRound, rid).state_json)['chain']
    return 'before' if chain[-1]['year'] < chain[-2]['year'] else 'after'


def test_off_until_an_organizer_turns_one_on(club):
    assert client(club['bo']).get('/api/quizzes', query_string={'group_id': club['G']}).json == {'games': []}
    assert 'off' in start(club, 'higher_lower').json['error']
    assert client(club['bo']).put(f"/api/groups/{club['slug']}", json={'quizzes': {'who_said': True}}).status_code == 403
    assert turn_on(club, higher_lower=True, bogus=True) == {'higher_lower': True, 'who_said': False, 'still': False, 'reviews': False, 'emoji': False}
    games = client(club['bo']).get('/api/quizzes', query_string={'group_id': club['G']}).json['games']
    assert [g['kind'] for g in games] == ['higher_lower'] and games[0]['round'] is None


def test_higher_or_lower_runs_until_a_miss(club):
    turn_on(club, higher_lower=True)
    r = start(club, 'higher_lower').json
    assert r['current']['year'] and r['next']['year'] is None and not r['done']        # the next year is the question
    assert start(club, 'higher_lower').json['id'] == r['id']                          # one run at a time
    r = answer(club, r['id'], truth(r['id'])).json
    assert r['last'] == {'right': True, 'paid': 1} and r['score'] == 1 and not r['done']
    wrong = 'after' if truth(r['id']) == 'before' else 'before'
    r = answer(club, r['id'], wrong).json
    assert r['done'] and r['last']['right'] is False and r['score'] == 1 and r['next']['year']   # the year, now
    assert 'over' in answer(club, r['id'], 'before').json['error']
    assert "isn't yours" in answer(club, r['id'], 'before', who='ana').json['error']


def test_five_kernels_a_day_from_each_game(club):
    import kernels
    from app import app
    turn_on(club, higher_lower=True)
    paid = []
    rid = start(club, 'higher_lower').json['id']
    for _ in range(8):
        r = answer(club, rid, truth(rid)).json
        paid.append(r['last']['paid'])
        if r['done']:
            rid = start(club, 'higher_lower').json['id']
    assert paid == [1, 1, 1, 1, 1, 0, 0, 0]
    with app.app_context():
        k = kernels.breakdown(club['bo'], club['G'])
        assert k['games'] == 5 and k['kernels'] >= 5


def test_who_said_it(club):
    turn_on(club, who_said=True)
    r = start(club, 'who_said').json
    assert r['quote'] == 'Here’s looking at you, kid.' and r['film']['title'] == 'Casablanca'
    assert len(r['options']) == 4 and 'Rick Blaine' in r['options'] and 'Rick' not in r['options']   # the film's name for him
    assert 'answer' not in r
    r = answer(club, r['id'], r['options'].index('Rick Blaine')).json
    assert r['done'] and r['last'] == {'right': True, 'paid': 1} and r['options'][r['answer']] == 'Rick Blaine'


def test_in_the_leaderboard_and_the_kernel_rules(club):
    turn_on(club, higher_lower=True)
    rid = start(club, 'higher_lower').json['id']
    answer(club, rid, truth(rid))
    answer(club, rid, 'after' if truth(rid) == 'before' else 'before')
    rows = {r['user']['name']: r for r in client(club['ana']).get(f"/api/groups/{club['G']}/leaderboard",
                                                                   query_string={'period': 'month'}).json['rows']}
    assert rows['Bo']['breakdown']['games'] == 1 and rows['Bo']['stats']['quizzes'] == {'rounds': 1, 'best_streak': 1, 'right': 0}
    rules = client(club['bo']).get('/api/kernels', query_string={'group_id': club['G']}).json['rules']
    assert rules['games'] == [{'label': 'Higher or lower', 'each': 1, 'per_day': 5, 'by_step': False}]


def test_from_discord(club):
    turn_on(club, who_said=True)
    ident = {'discord_user_id': '9901', 'group_id': club['G']}
    games = client().get('/api/internal/quizzes', query_string=ident, headers=H).json['games']
    assert [g['kind'] for g in games] == ['who_said']
    r = client().post('/api/internal/quizzes', json={**ident, 'action': 'start', 'kind': 'who_said'}, headers=H).json
    r = client().post('/api/internal/quizzes', json={**ident, 'action': 'answer', 'round_id': r['id'],
                                                     'choice': r['options'].index('Rick Blaine')}, headers=H).json
    assert r['done'] and r['earned'] == 1

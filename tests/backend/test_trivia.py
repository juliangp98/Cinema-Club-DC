"""Daily trivia (R10d): off until a club admin turns it on (and the Discord
post is a second yes); one question a day per club, made from our films and
quotes, the same for everyone; the answer stays hidden until you've
answered; one try each; +2 kernels for a right one."""
import json
import random
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db

FILMS = [  # title, year, director, cast, tagline
    ('VERTIGO', 1958, 'Alfred Hitchcock', ['James Stewart', 'Kim Novak', 'Barbara Bel Geddes'], 'A double-edged thriller'),
    ('STALKER', 1979, 'Andrei Tarkovsky', ['Alisa Freyndlikh', 'Aleksandr Kaydanovskiy', 'Anatoliy Solonitsyn'], None),
    ('HEAT', 1995, 'Michael Mann', ['Al Pacino', 'Robert De Niro', 'Val Kilmer'], 'A Los Angeles crime saga'),
    ('CLUELESS', 1995, 'Amy Heckerling', ['Alicia Silverstone', 'Stacey Dash', 'Brittany Murphy'], 'Sex. Clothes. Popularity.'),
    ('PARASITE', 2019, 'Bong Joon Ho', ['Song Kang-ho', 'Lee Sun-kyun', 'Cho Yeo-jeong'], 'Act like you own the place.'),
    ('ALIEN', 1979, 'Ridley Scott', ['Sigourney Weaver', 'Tom Skerritt', 'John Hurt'], 'In space no one can hear you scream.'),
    ('TAMPOPO', 1985, 'Juzo Itami', ['Tsutomu Yamazaki', 'Nobuko Miyamoto', 'Koji Yakusho'], None),
    ('MOONLIGHT', 2016, 'Barry Jenkins', ['Mahershala Ali', 'Naomie Harris', 'Trevante Rhodes'], 'This is the story of a lifetime'),
]
QUOTES = [('Here’s looking at you, kid.', 'Casablanca'), ('I’ll be back.', 'The Terminator'),
          ('You talking to me?', 'Taxi Driver'), ('Fasten your seatbelts.', 'All About Eve'),
          ('I’m walking here!', 'Midnight Cowboy')]


@pytest.fixture
def club():
    """Trivia Club (AFI): Ana (admin), Bo (member), Vi (read-only), Out (not
    in it). HEAT is on the calendar."""
    from app import app, db, Group, GroupMembership, Movie, Quote, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        g = Group(name='Trivia Club', slug='trivia-club', is_public=False, theatres='afi')
        us = {n: User(name=n, email=f'{n.lower()}@q.test', is_active=True) for n in ('Ana', 'Bo', 'Vi', 'Out')}
        db.session.add_all([g, *us.values()])
        db.session.flush()
        for n, role in (('Ana', 'admin'), ('Bo', 'member'), ('Vi', 'viewer')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g.id, status='active', role=role))
        for i, (title, year, director, cast, tagline) in enumerate(FILMS):
            m = Movie(title=title, release_year=str(year), director=director, tagline=tagline, tmdb_id=900000 + i,
                      cast_json=json.dumps([{'name': c} for c in cast]))
            db.session.add(m)
            db.session.flush()
            if title == 'HEAT':
                db.session.add(Showtime(movie_id=m.id, theatre_id=Theatre.query.filter_by(slug='afi').first().id,
                                        start_time=datetime.now() + timedelta(days=3)))
        for text, movie in QUOTES:
            db.session.add(Quote(text=text, movie=movie))
        db.session.commit()
        return {**{n: u.id for n, u in us.items()}, 'G': g.id, 'slug': g.slug}


def turn_on(c, post='never'):
    r = client(c['Ana']).put(f"/api/groups/{c['slug']}", json={'trivia_enabled': True, 'trivia_post': post})
    assert r.status_code == 200
    return r.json


def today(c, who='Bo'):
    return client(c[who]).get('/api/trivia/today', query_string={'group_id': c['G']}).json


def answer(c, who, q, choice):
    return client(c[who]).post('/api/trivia/answer', json={'group_id': c['G'], 'question_id': q['id'], 'choice': choice})


# ── switching it on ──

def test_trivia_starts_off(club):
    assert today(club) == {'enabled': False}
    assert client(club['Bo']).get(f"/api/groups/{club['slug']}").json['trivia'] == {'enabled': False, 'anytime': False,
                                                                                   'post': 'never'}
    r = client(club['Bo']).post('/api/trivia/answer', json={'group_id': club['G'], 'question_id': 1, 'choice': 0})
    assert r.status_code == 400 and 'off' in r.json['error']


def test_only_club_admins_switch_it(club):
    assert client(club['Bo']).put(f"/api/groups/{club['slug']}", json={'trivia_enabled': True}).status_code == 403
    assert turn_on(club, post='ask')['trivia'] == {'enabled': True, 'anytime': False, 'post': 'ask'}
    bad = client(club['Ana']).put(f"/api/groups/{club['slug']}", json={'trivia_post': 'sometimes'}).json
    assert bad['trivia']['post'] == 'ask'                                         # only never / ask / always


# ── the question of the day ──

def test_one_question_a_day_the_same_for_everyone(club):
    turn_on(club)
    bo, ana = today(club, 'Bo'), today(club, 'Ana')
    q = bo['question']
    assert bo['enabled'] and q['id'] == ana['question']['id'] and len(q['options']) == 4 and len(set(q['options'])) == 4
    assert not {'answer', 'stats', 'movie', 'mine'} & set(q)                    # nothing given away before you answer
    assert q['kernels'] == 2 and bo['yesterday'] is None


def test_answering_once(club):
    import trivia
    from app import app, db, TriviaQuestion
    turn_on(club)
    q = today(club)['question']
    with app.app_context():
        right = db.session.get(TriviaQuestion, q['id']).answer
    r = answer(club, 'Bo', q, right)
    assert r.status_code == 200 and r.json['mine'] == {'choice': right, 'correct': True}
    assert r.json['answer'] == right and r.json['stats'] == {'answered': 1, 'correct': 1}
    assert 'already answered' in answer(club, 'Bo', q, right).json['error']
    wrong = (right + 1) % 4
    assert answer(club, 'Ana', q, wrong).json['mine'] == {'choice': wrong, 'correct': False}
    with app.app_context():
        import kernels
        assert kernels.breakdown(club['Bo'], club['G'])['trivia'] == trivia.TRIVIA_KERNELS
        assert kernels.breakdown(club['Ana'], club['G'])['trivia'] == 0
    assert today(club)['question']['stats'] == {'answered': 2, 'correct': 1}


def test_who_can_answer(club):
    turn_on(club)
    q = today(club)['question']
    assert 'members' in answer(club, 'Vi', q, 0).json['error']                 # read-only
    assert answer(club, 'Out', q, 0).status_code == 403
    assert 'Pick one' in answer(club, 'Bo', q, 7).json['error']


def test_yesterdays_question_is_revealed_and_closed(club):
    import trivia
    from app import app, db, Group, TriviaAnswer
    turn_on(club)
    with app.app_context():
        q = trivia.question_for(db.session.get(Group, club['G']), trivia.today() - timedelta(days=1))
        db.session.add(TriviaAnswer(question_id=q.id, user_id=club['Ana'], choice=q.answer, correct=True))
        db.session.commit()
        qid, right = q.id, q.answer
    y = today(club)['yesterday']
    assert y['id'] == qid and y['answer'] == right and y['stats'] == {'answered': 1, 'correct': 1}
    assert 'earlier day' in answer(club, 'Bo', {'id': qid}, right).json['error']
    assert today(club)['question']['id'] != qid


def test_every_kind_asks_something_true(club):
    import trivia
    from app import app, Movie, Quote
    with app.app_context():
        films, quotes = Movie.query.filter(Movie.tmdb_id >= 900000).all(), Quote.query.all()
        directors = {f.title: f.director for f in films}
        for build in trivia.BUILDERS:
            for seed in range(25):
                q = build(random.Random(seed), films, set(), set(), quotes)
                assert q, build.__name__
                right = q['options'][q['answer']]
                assert len(set(q['options'])) == 4
                if q['kind'] == 'director':
                    title = q['prompt'].removeprefix('Who directed ').rsplit(' (', 1)[0]
                    assert right == directors[title]
                elif q['kind'] == 'first':
                    years = {f.title: int(f.release_year) for f in films}
                    assert years[right] == min(years[o] for o in q['options'])
                elif q['kind'] == 'quote':
                    text = q['prompt'].split('“', 1)[1].rstrip('”')
                    assert dict(QUOTES)[text] == right
                elif q['kind'] == 'tagline':
                    assert all(w not in q['prompt'].lower() for w in right.lower().split() if len(w) > 3 and not w.startswith('('))


def test_no_film_or_quote_twice_in_a_while(club):
    import trivia
    from app import app, db, Group
    turn_on(club)
    with app.app_context():
        g = db.session.get(Group, club['G'])
        refs = [trivia.question_for(g, trivia.today() - timedelta(days=d)).ref for d in range(10, 0, -1)]
    assert len(refs) == len(set(refs))


# ── Discord ──

def test_answering_from_discord(club):
    from app import app, db, User
    with app.app_context():
        db.session.get(User, club['Bo']).discord_user_id = '9501'
        db.session.commit()
    ident = {'discord_user_id': '9501', 'group_id': club['G']}
    assert client().get('/api/internal/trivia/today', query_string=ident, headers=H).json == {'enabled': False}
    turn_on(club)
    q = client().get('/api/internal/trivia/today', query_string=ident, headers=H).json['question']
    r = client().post('/api/internal/trivia/answer', json={**ident, 'question_id': q['id'], 'choice': 0}, headers=H)
    assert r.status_code == 200 and 'mine' in r.json


def test_kernel_rules_mention_trivia_only_when_on(club):
    rules = lambda: client(club['Bo']).get('/api/kernels', query_string={'group_id': club['G']}).json['rules']
    assert rules()['trivia'] is None
    turn_on(club)
    assert rules()['trivia'] == 2


# ── anytime questions ──

def another(c, who):
    return client(c[who]).post('/api/trivia/another', json={'group_id': c['G']})


def right_answer(qid):
    from app import app, db, TriviaQuestion
    with app.app_context():
        return db.session.get(TriviaQuestion, qid).answer


def anytime_on(c, on=True):
    assert client(c['Ana']).put(f"/api/groups/{c['slug']}", json={'trivia_anytime': on}).json['trivia']['anytime'] is on


def test_anytime_is_its_own_switch(club):
    turn_on(club)
    assert 'off' in another(club, 'Bo').json['error']                           # the daily alone doesn't allow extras
    client(club['Ana']).put(f"/api/groups/{club['slug']}", json={'trivia_enabled': False})
    assert client(club['Bo']).put(f"/api/groups/{club['slug']}", json={'trivia_anytime': True}).status_code == 403
    anytime_on(club)
    t = today(club)
    assert t['enabled'] and t['anytime'] and not t['daily'] and t['question'] is None
    q = another(club, 'Bo').json
    assert q['anytime'] and q['kernels'] == 1 and q['kernels_left_today'] == 5 and 'answer' not in q


def test_anytime_questions_are_private_and_one_at_a_time(club):
    turn_on(club)
    anytime_on(club)
    daily = today(club)['question']
    q1 = another(club, 'Bo').json
    assert another(club, 'Bo').json['id'] == q1['id']                           # no skipping to an easier one
    assert today(club)['waiting']['id'] == q1['id']
    assert "isn't yours" in answer(club, 'Ana', q1, 0).json['error']
    r = answer(club, 'Bo', q1, right_answer(q1['id'])).json
    assert r['mine']['correct'] and r['earned'] == 1 and r['anytime_on'] is True and r['kernels_left_today'] == 4
    q2 = another(club, 'Bo').json
    assert q2['id'] not in (q1['id'], daily['id']) and q2['prompt'] not in (q1['prompt'], daily['prompt'])
    assert another(club, 'Vi').status_code == 400                               # read-only members don't play


def test_anytime_kernels_stop_at_five_a_day(club):
    import kernels
    from app import app
    turn_on(club)
    anytime_on(club)
    earned = []
    for _ in range(7):
        q = another(club, 'Bo').json
        earned.append(answer(club, 'Bo', q, right_answer(q['id'])).json['earned'])
    assert earned == [1, 1, 1, 1, 1, 0, 0]                                      # then just for fun
    daily = today(club)['question']
    answer(club, 'Bo', daily, right_answer(daily['id']))
    with app.app_context():
        assert kernels.breakdown(club['Bo'], club['G'])['trivia'] == 5 + 2


def test_trivia_tables_from_before_anytime_are_rebuilt():
    from app import app, db, migrate, TriviaQuestion
    setup_db()
    with app.app_context():
        db.session.execute(db.text("DROP TABLE trivia_question"))
        db.session.execute(db.text("""CREATE TABLE trivia_question (id INTEGER PRIMARY KEY, group_id INTEGER NOT NULL,
            day DATE NOT NULL, kind VARCHAR(20) NOT NULL, prompt TEXT NOT NULL, options_json TEXT NOT NULL,
            answer INTEGER NOT NULL, movie_id INTEGER, ref VARCHAR(200), discord_message_id VARCHAR(30),
            created_at DATETIME, UNIQUE (group_id, day))"""))
        db.session.execute(db.text("""INSERT INTO trivia_question (id, group_id, day, kind, prompt, options_json, answer)
            VALUES (7, 1, '2026-10-12', 'quote', 'Q?', '["a","b","c","d"]', 2)"""))
        db.session.commit()
        migrate()
        old = db.session.get(TriviaQuestion, 7)
        assert old.slot == 'daily' and old.answer == 2 and old.asked_by is None
        db.session.add(TriviaQuestion(group_id=1, day=old.day, slot='5:1', asked_by=5, kind='quote', prompt='Q2?',
                                      options_json='["a","b","c","d"]', answer=0))
        db.session.commit()                                                      # a second question the same day fits now

"""Trivia that's actually hard (R15, film_pool.py): wrong answers that look
like the right one (same era, genre, fame — not a 1926 swashbuckler against
a 2026 cartoon), TMDB's titles instead of the theatre's capitals, a
difficulty that pays, and a club's choice of films — ours, TMDB's best
known, or both."""
import json
import random
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db

POOL = [  # tmdb id, title, year, genres, votes
    (1, 'The Black Pirate', 1926, 'adventure,action', 900),
    (2, 'The Thief of Bagdad', 1924, 'adventure,fantasy', 1200),
    (3, 'The Mark of Zorro', 1920, 'adventure,action', 700),
    (4, 'Captain Blood', 1935, 'adventure,action', 1600),
    (5, 'The Sea Hawk', 1940, 'adventure,action', 1100),
    (6, 'Paw Patrol: The Dino Movie', 2026, 'animation,family', 300),
    (7, 'Basic Instinct', 1992, 'thriller,mystery', 4500),
    (8, 'Wild Zero', 1999, 'horror,comedy', 200),
    (9, 'The Dark Knight', 2008, 'action,crime,drama', 33000),
    (10, 'Inception', 2010, 'action,science fiction', 36000),
    (11, 'Interstellar', 2014, 'adventure,science fiction,drama', 35000),
    (12, 'The Matrix', 1999, 'action,science fiction', 26000),
]


@pytest.fixture
def pool():
    from app import app, db, PoolFilm
    setup_db()
    with app.app_context():
        for tid, title, year, genres, votes in POOL:
            db.session.add(PoolFilm(tmdb_id=tid, title=title, year=year, genres=genres, vote_count=votes))
        db.session.commit()


def film(title):
    import film_pool
    from app import PoolFilm
    return film_pool.from_pool(PoolFilm.query.filter_by(title=title).first())


def test_wrong_answers_look_like_the_right_one(pool):
    import film_pool
    from app import app
    with app.app_context():
        _, everyone = film_pool.films('tmdb')
        pirate = film('The Black Pirate')
        for seed in range(10):
            picks = {f.title for f in film_pool.lookalikes(pirate, everyone, random.Random(seed), top=4)}
            assert picks <= {'The Thief of Bagdad', 'The Mark of Zorro', 'Captain Blood', 'The Sea Hawk'}
            assert not picks & {'Paw Patrol: The Dino Movie', 'Basic Instinct', 'Wild Zero'}


def test_theatre_titles_read_like_titles():
    import film_pool
    assert film_pool.nice_title('THE BLACK PIRATE') == 'The Black Pirate'
    assert film_pool.nice_title('NIGHT OF THE LIVING DEAD') == 'Night of the Living Dead'
    assert film_pool.nice_title('Paris, Texas') == 'Paris, Texas'                   # already fine: left alone


def test_difficulty_follows_fame_and_how_close_the_others_are(pool):
    import film_pool
    from app import app
    with app.app_context():
        famous = film('The Dark Knight')
        loose = [film('Paw Patrol: The Dino Movie'), film('The Mark of Zorro'), film('Wild Zero')]
        assert film_pool.difficulty(famous, loose) == film_pool.EASY
        close = [film('The Thief of Bagdad'), film('The Mark of Zorro'), film('Captain Blood')]
        assert film_pool.difficulty(film('The Black Pirate'), close) == film_pool.HARD


def test_the_pool_comes_from_tmdbs_most_voted(monkeypatch):
    import enrich
    import film_pool
    from app import app, db, BotSetting, PoolFilm
    setup_db()
    pages = {1: [{'id': 101, 'title': 'Inception', 'release_date': '2010-07-15', 'genre_ids': [28, 878],
                  'vote_count': 36000, 'popularity': 80, 'poster_path': '/i.jpg'}],
             2: []}

    class R:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data
    calls = []

    def get(url, params=None, **k):
        calls.append(url)
        if url.endswith('/genre/movie/list'):
            return R({'genres': [{'id': 28, 'name': 'Action'}, {'id': 878, 'name': 'Science Fiction'}]})
        return R({'results': pages.get(params['page'], [])})
    monkeypatch.setattr(enrich._http, 'get', get)
    with app.app_context():
        assert film_pool.refresh_if_due() == 1
        p = PoolFilm.query.filter_by(tmdb_id=101).first()
        assert (p.title, p.year, p.vote_count) == ('Inception', 2010, 36000) and 'action' in p.genres
        assert p.poster_url.endswith('/i.jpg')
        n = len(calls)
        assert film_pool.refresh_if_due() is None and len(calls) == n                 # a week before the next
        db.session.get(BotSetting, 'film_pool_at').value = (datetime.utcnow() - timedelta(days=8)).isoformat()
        db.session.commit()
        assert film_pool.refresh_if_due() == 1


def test_a_pool_films_people_are_looked_up_once(pool, monkeypatch):
    import enrich
    import film_pool
    from app import app
    seen = []
    monkeypatch.setattr(enrich, 'tmdb_details', lambda tid: seen.append(tid) or {
        'director': 'Albert Parker', 'tagline': 'Adventure on the high seas', 'cast_json': json.dumps([{'name': 'Douglas Fairbanks'}])})
    with app.app_context():
        f = film_pool.ensure_details(film('The Black Pirate'))
        assert (f.director, f.cast) == ('Albert Parker', ['Douglas Fairbanks'])
        film_pool.ensure_details(film('The Black Pirate'))
        assert seen == [1]


@pytest.fixture
def club(pool):
    from app import app, db, Group, GroupMembership, Movie, User
    with app.app_context():
        g = Group(name='Pool Club', slug='pool-club', is_public=False, theatres='afi', trivia_enabled=True,
                  trivia_anytime=True, trivia_source='tmdb')
        bo = User(name='Bo', email='bo@pool.test', is_active=True)
        db.session.add_all([g, bo])
        db.session.flush()
        db.session.add(GroupMembership(user_id=bo.id, group_id=g.id, status='active', role='member'))
        db.session.add(Movie(title='OUR FILM', release_year='1970', tmdb_id=950001, director='Someone', genres='drama'))
        db.session.commit()
        return {'G': g.id, 'Bo': bo.id, 'slug': g.slug}


def test_a_club_on_tmdb_asks_about_well_known_films(club, monkeypatch):
    import enrich
    import trivia
    from app import app, db, Group
    monkeypatch.setattr(enrich, 'tmdb_details', lambda tid: None)          # no people: "which came first" / taglines
    with app.app_context():
        g = db.session.get(Group, club['G'])
        for d in range(6):
            made = trivia.make_question(g, trivia.today() - timedelta(days=d), rng=random.Random(d), recent=set())
            assert made and (made['ref'].startswith('tmdb:') or made['kind'] == 'quote')   # about a pool film
            assert made['difficulty'] in ('easy', 'medium', 'hard')
            assert not any(o.isupper() for o in made['options'])                  # TMDB's titles


def test_an_empty_pool_falls_back_to_our_films(monkeypatch):
    import trivia
    from app import app, db, Group, Movie
    setup_db()
    with app.app_context():
        g = Group(name='New Club', slug='new-club', is_public=False, trivia_enabled=True, trivia_source='tmdb')
        db.session.add(g)
        for i, (t, y) in enumerate((('ALPHA', 1950), ('BETA', 1960), ('GAMMA', 1970), ('DELTA', 1980))):
            db.session.add(Movie(title=t, release_year=str(y), tmdb_id=960000 + i, director=f'D{i}', genres='drama'))
        db.session.commit()
        made = trivia.make_question(g, trivia.today(), rng=random.Random(1), recent=set())
        assert made and (made['movie_id'] or made['kind'] == 'quote')


def test_harder_questions_pay_more(club):
    import trivia
    from app import app, db, TriviaQuestion
    with app.app_context():
        q = trivia.question_for(db.session.get(__import__('app').Group, club['G']))
        q.difficulty = 'hard'
        db.session.commit()
        qid, right = q.id, q.answer
    r = client(club['Bo']).post('/api/trivia/answer', json={'group_id': club['G'], 'question_id': qid, 'choice': right}).json
    assert r['earned'] == 3 and r['difficulty'] == 'hard' and r['kernels'] == 3
    with app.app_context():
        assert trivia.worth('anytime', 'hard') == 2 and trivia.worth('daily', None) == 2      # older questions: medium

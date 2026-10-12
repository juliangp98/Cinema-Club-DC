"""R6c: search suggestions as you type, and ✨ AI search."""
import json
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def library():
    """A club at AFI: THE THING (1982, Carpenter, Kurt Russell), IN THE MOUTH
    OF MADNESS (1994, Carpenter), PADDINGTON 2 playing; THE THIN MAN in the
    database, not playing. A member and a guest."""
    from app import app, db, User, Group, GroupMembership, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Search Club', slug='search-r6c', is_public=False, theatres='afi')
        db.session.add(g)
        db.session.flush()
        u = User(email='u@r6c.test', name='U', is_active=True)
        guest = User(name='Guest', is_active=True, is_guest=True)
        db.session.add_all([u, guest])
        db.session.flush()
        db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        now = datetime.now()
        cast = json.dumps([{'name': 'Kurt Russell'}, {'name': 'Wilford Brimley'}])
        for i, (t, y, gen, d) in enumerate([('THE THING', 1982, 'Horror, Science Fiction', 'John Carpenter'),
                                            ('IN THE MOUTH OF MADNESS', 1994, 'Horror', 'John Carpenter'),
                                            ('PADDINGTON 2', 2017, 'Family, Comedy', 'Paul King')]):
            m = Movie(title=t, release_year=str(y), genres=gen, director=d, cast_json=cast if i == 0 else None, tmdb_id=9000 + i)
            db.session.add(m)
            db.session.flush()
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=2 + i)))
        db.session.add(Movie(title='THE THIN MAN', release_year='1934', tmdb_id=9100))
        db.session.commit()
        return {'group': g.id, 'user': u.id, 'guest': guest.id}


def suggest(lib, q, anonymous=False):
    who = client() if anonymous else client(lib['user'])
    params = {'q': q} if anonymous else {'q': q, 'group_id': lib['group']}
    return who.get('/api/search/suggest', query_string=params).json


def labels(r):
    return [f['label'] for f in r['filters']]


def test_films_playing_first_then_the_rest(library):
    r = suggest(library, 'thin')
    assert [f['title'] for f in r['films']] == ['THE THING', 'THE THIN MAN']
    assert r['films'][0]['playing'] and r['films'][0]['theatre'] and not r['films'][1]['playing']


def test_people_directors_and_actors(library):
    assert suggest(library, 'carp')['people'][0] == {'name': 'John Carpenter', 'role': 'director', 'count': 2,
                                                     'params': {'q': 'John Carpenter'}}
    kurt = suggest(library, 'kurt')['people'][0]
    assert kurt['name'] == 'Kurt Russell' and kurt['role'] == 'actor'
    assert suggest(library, 'urt')['people'] == []                      # names match at word starts only


def test_filters_moods_genres_formats_shelves(library):
    assert 'Scare me' in labels(suggest(library, 'spooky'))
    assert any(f['params'] == {'genres': 'horror'} and '2 films' in f['hint'] for f in suggest(library, 'horr')['filters'])
    assert {'On film (35/16/70mm)', 'Big screen (IMAX, 70mm, Dolby)'} <= set(labels(suggest(library, '70mm')))
    assert 'Rare gems' in labels(suggest(library, 'rare'))
    assert 'This weekend' in labels(suggest(library, 'week')) and 'Virginia' in labels(suggest(library, 'virg'))
    assert suggest(library, '80s')['filters'][0]['params'] == {'decade': '1980'}
    assert suggest(library, '1990s')['filters'][0]['params'] == {'decade': '1990'}


def test_theatres_and_club_filters_follow_the_club(library):
    assert any(f['params'] == {'theatres': 'afi'} for f in suggest(library, 'afi')['filters'])
    assert not any(f['params'].get('theatres') == 'suns' for f in suggest(library, 'suns')['filters'])   # not the club's
    assert 'Friends going' in labels(suggest(library, 'friends'))
    visitor = labels(suggest(library, 'friends', anonymous=True))
    assert 'Friends going' not in visitor and 'Friends are going' not in visitor


def test_ordering_and_edges(library):
    assert suggest(library, 't')['films'] == [] and suggest(library, 't')['filters'] == []      # one letter: nothing yet
    assert suggest(library, 'carp')['order'][0] == 'people'
    assert suggest(library, 'horr')['order'][0] == 'filters' and suggest(library, 'thin')['order'][0] == 'films'
    assert suggest(library, 'thin', anonymous=True)['films'][0]['title'] == 'THE THING'           # visitors: all theatres
    assert client(library['user']).get('/api/search/suggest', query_string={'q': 'thin', 'group_id': 999999}).status_code in (403, 404)


@pytest.fixture
def ai_search(library):
    import ai
    from fake_groq import Fake
    ai._client = Fake(['qwen/qwen3-32b', 'llama-3.3-70b-versatile'])
    return library, ai._client


def ask(lib, q, who=None, **k):
    return client(lib['user'] if who is None else who).post('/api/search/ai', json={'q': q, 'group_id': lib['group'], **k})


def test_a_fully_understood_request_needs_no_ai(ai_search):
    lib, fake = ai_search
    r = ask(lib, 'anything rare in virginia this weekend').json
    assert r['ai'] is False and not [x for x in fake.calls if 'Request' in x[1]]
    assert r['params'] == {'shelf': 'rare', 'regions': 'virginia', 'when': 'weekend'} and r['path'].startswith('/browse?')


def test_leftover_words_go_to_the_ai_and_only_real_values_survive(ai_search):
    lib, fake = ai_search
    fake.reply = lambda m, msgs, kw: json.dumps({'params': {'mood': 'scare-me', 'runtime': 'short', 'regions': 'dc',
                                                           'theatres': 'afi,made-up', 'genres': 'horror,nonsense', 'decade': '1985',
                                                           'club': 'going', 'sort': 'chaos'}, 'search': ''})
    r = ask(lib, 'something to make me jump that is not too long near downtown').json
    assert r['ai'] is True
    assert r['params'] == {'shelf': 'short', 'mood': 'scare-me', 'runtime': 'short', 'regions': 'dc', 'theatres': 'afi',
                           'genres': 'horror', 'club': 'going', 'when': 'month'}
    assert r['explain'] == 'Short & sweet · Scare me · Next 30 days · DC · AFI'


def test_a_person_or_title_becomes_a_search(ai_search):
    lib, fake = ai_search
    fake.reply = lambda m, msgs, kw: json.dumps({'params': {}, 'search': 'John Carpenter'})
    assert ask(lib, 'that guy who made the thing with kurt russell').json['params'].get('q') == 'John Carpenter'


def test_when_the_ai_fails_the_plain_reading_is_used(ai_search):
    lib, fake = ai_search
    fake.reply = lambda m, msgs, kw: 'not json at all'
    r = ask(lib, 'vibes for a rainy sunday with wine').json
    assert r['ai'] is False and r['note'] and r['params']['when'] == 'weekend'
    fake.limited = {'qwen/qwen3-32b', 'llama-3.3-70b-versatile'}
    r = ask(lib, 'zombie musicals with puppets').json
    assert r['ai'] is False and 'busy' in r['note'] and r['params']['q'] == 'zombie musicals puppets'


def test_who_may_use_ai_search(ai_search):
    lib, _ = ai_search
    assert ask(lib, 'something scary', who=lib['guest']).status_code == 403
    assert client().post('/api/search/ai', json={'q': 'something scary'}).status_code == 401
    assert ask(lib, 'ok').status_code == 400                                              # too short
    assert ask(lib, 'something scary', group_id=999999).status_code == 403


def test_ai_searches_are_limited_per_hour(ai_search):
    lib, fake = ai_search
    fake.reply = lambda m, msgs, kw: json.dumps({'params': {'mood': 'laugh'}, 'search': ''})
    codes = [ask(lib, f'something silly number {i} please').status_code for i in range(16)]
    assert 429 in codes

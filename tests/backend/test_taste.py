"""Your taste (R13): one list of genres for the whole site (TMDB's, plus the
ones only OMDb names), ways to watch, favorite theatres, films and people,
genres you're not into — shown on your profile only if you say so."""
import pytest

from helpers import H, client, setup_db


@pytest.fixture
def club(monkeypatch):
    """Ana and Bo in club 1; Out in no club. Films with credits to search."""
    import enrich
    from app import app, db, GroupMembership, Movie, User
    setup_db()
    monkeypatch.setattr(enrich, 'tmdb_people', lambda q, limit=8: [{'name': 'Agnès Varda', 'kind': 'director'}]
                        if 'varda' in q.lower() else [])
    with app.app_context():
        us = {n: User(name=n, email=f'{n.lower()}@taste.test', is_active=True) for n in ('Ana', 'Bo', 'Out')}
        db.session.add_all(us.values())
        db.session.flush()
        for n in ('Ana', 'Bo'):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=1, status='active'))
        m = Movie(title='CHUNGKING EXPRESS', release_year='1994', director='Wong Kar-wai', genres='drama,romance',
                  cast_json='[{"name": "Faye Wong"}, {"name": "Tony Leung Chiu-wai"}]',
                  crew_json='[{"name": "Wong Kar-wai", "job": "Director"}, {"name": "Wong Kar-wai", "job": "Screenplay"}]')
        db.session.add(m)
        db.session.commit()
        return {**{n: u.id for n, u in us.items()}, 'film': m.id}


def taste(c, who='Ana'):
    return client(c[who]).get('/api/me/taste').json


def put(c, who='Ana', **data):
    return client(c[who]).put('/api/me/taste', json=data)


def test_one_genre_list_from_tmdb_and_omdb():
    import taste
    assert taste.merge_genres(['Science Fiction', 'Drama'], ['Sci-Fi', 'Film-Noir', 'Biography', 'Short']) == \
        'science fiction,drama,film-noir,biography'
    assert taste.merge_genres(['TV Movie', 'nonsense']) == ''
    assert taste.genre_key('  Film   Noir ') == 'film-noir' and taste.genre_key('sci-fi') == 'science fiction'
    assert len(taste.GENRES) == 22 and taste.GENRE_LABELS['science fiction'] == 'Sci-fi'


def test_enrichment_adds_omdbs_genres_and_the_language(monkeypatch):
    import enrich
    monkeypatch.setattr(enrich, 'tmdb_details', lambda tid: {'tmdb_title': 'The Third Man', 'genres': 'thriller,mystery',
                                                             'original_language': 'en', 'release_year': '1949'})
    monkeypatch.setattr(enrich, 'enrich_from_omdb', lambda *a, **k: {'awards': None, 'omdb_genres': ['Film-Noir', 'Mystery']})
    r = enrich.enrich_by_tmdb_id(1092)
    assert r['genres'] == 'thriller,mystery,film-noir' and r['original_language'] == 'en' and 'omdb_genres' not in r


def test_old_profiles_move_over_once():
    import taste
    from app import app, db, User
    setup_db()
    with app.app_context():
        u = User(name='Old', email='old@taste.test', is_active=True, favorite_genres='sci-fi,classic,indie,noir,horror,experimental')
        db.session.add(u)
        db.session.commit()
        taste.migrate_legacy_genres()
        taste.migrate_legacy_genres()                                   # safe to re-run
        u = db.session.get(User, u.id)
        v = taste.view(u)
        assert v['genres'] == ['film-noir', 'horror', 'science fiction'] and v['ways'] == ['classics', 'arthouse']
        assert u.favorite_genres == '' and v['set']


def test_picking_genres_ways_and_theatres(club):
    t = taste(club)
    assert not t['set'] and not t['public'] and len(t['options']['genres']) == 22
    assert {o['key'] for o in t['options']['ways']} >= {'film', 'big', 'events', 'foreign'}
    assert 'afi' in {o['slug'] for o in t['options']['theatres']}
    t = put(club, genres=['Horror', 'sci-fi', 'nope'], avoid=['romance', 'horror'], ways=['film', 'late'], theatres=['afi']).json
    assert t['genres'] == ['horror', 'science fiction'] and t['avoid'] == ['romance']      # a favorite can't be avoided too
    assert t['ways'] == ['film', 'late'] and t['theatres'] == ['afi'] and t['set']
    assert put(club, genres=['romance', 'horror']).json['avoid'] == []                      # picking it stops avoiding it
    assert put(club, ways=['flying']).status_code == 400 and put(club, theatres=['nowhere']).status_code == 400
    assert taste(club)['ways'] == ['film', 'late']                                         # nothing saved on an error


def test_favorite_films_and_people(club, monkeypatch):
    import enrich
    monkeypatch.setattr(enrich, 'enrich_by_tmdb_id', lambda tid, title='': {'tmdb_id': tid, 'tmdb_title': 'Cléo from 5 to 7',
                                                                            'release_year': '1962', 'genres': 'drama'})
    c = client(club['Ana'])
    add = lambda **d: c.post('/api/me/taste/items', json=d)
    add(kind='movie', movie_id=club['film'])
    t = add(kind='movie', tmdb_id=499).json                                 # any film on TMDB
    assert [m['label'] for m in t['movies']] == ['CHUNGKING EXPRESS', 'Cléo from 5 to 7']
    add(kind='director', name='  Wong  Kar-wai ')
    t = add(kind='director', name='wong kar-wai').json                      # once
    assert t['people'] == [{'kind': 'director', 'key': 'wong kar-wai', 'label': 'Wong Kar-wai'}]
    assert add(kind='enemy', name='x').status_code == 400 and add(kind='movie', movie_id=999999).status_code == 400
    t = c.delete('/api/me/taste/items', json={'kind': 'movie', 'key': str(club['film'])}).json
    assert [m['label'] for m in t['movies']] == ['Cléo from 5 to 7']


def test_people_search_uses_our_credits_then_tmdb(club):
    c = client(club['Ana'])
    found = c.get('/api/taste/people', query_string={'q': 'wong'}).json
    assert {'name': 'Wong Kar-wai', 'kind': 'director'} in found and {'name': 'Wong Kar-wai', 'kind': 'writer'} in found
    assert {'name': 'Faye Wong', 'kind': 'actor'} in found
    assert c.get('/api/taste/people', query_string={'q': 'wong', 'kind': 'actor'}).json == [{'name': 'Faye Wong', 'kind': 'actor'}]
    assert c.get('/api/taste/people', query_string={'q': 'varda'}).json == [{'name': 'Agnès Varda', 'kind': 'director'}]
    assert c.get('/api/taste/people', query_string={'q': 'w'}).json == []


def test_your_taste_is_yours_unless_you_show_it(club):
    put(club, genres=['horror'], ways=['film'])
    client(club['Ana']).post('/api/me/taste/items', json={'kind': 'actor', 'name': 'Faye Wong'})
    theirs = client(club['Bo']).get(f"/api/users/{club['Ana']}/profile").json
    assert 'taste' not in theirs and 'taste_public' not in theirs
    assert client(club['Ana']).get(f"/api/users/{club['Ana']}/profile").json['taste']['genres'] == ['Horror']   # your own
    put(club, public=True)
    shown = client(club['Bo']).get(f"/api/users/{club['Ana']}/profile").json['taste']
    assert shown['genres'] == ['Horror'] and shown['ways'] == ['🎞️ On film prints']
    assert shown['people'] == [{'kind': 'actor', 'label': 'Faye Wong'}]


def test_discord_profiles_follow_the_same_switch(club):
    from app import app, db, User
    with app.app_context():
        for n, did in (('Ana', '7001'), ('Bo', '7002')):
            db.session.get(User, club[n]).discord_user_id = did
        db.session.commit()
    import helpers
    helpers.all_linked_present()
    put(club, genres=['horror'])
    other = client().get('/api/internal/profile', query_string={'member_discord_id': '7001'}, headers=H).json
    assert other['genres'] == [] and other['taste_hidden']
    put(club, public=True)
    other = client().get('/api/internal/profile', query_string={'member_discord_id': '7001'}, headers=H).json
    assert other['genres'] == [{'key': 'horror', 'label': 'Horror'}] and not other['taste_hidden']

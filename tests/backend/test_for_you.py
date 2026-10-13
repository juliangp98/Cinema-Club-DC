"""For you (R13): films playing soon scored from your taste and what you've
done, each with its reasons — on Discover, theatre pages, Browse and the
Theatres page's counts."""
from datetime import date, datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def world():
    """Club 1: Ana (a full taste) and Bo (none, but loved PSYCHO on Letterboxd).
    Playing in the next two weeks at AFI and Suns: VERTIGO (Hitchcock, 35mm,
    a romance), HORROR NIGHT (late at Suns), ROMCOM, SEEN IT (Ana went to an
    earlier showing), WANTED (on Ana's watchlist) and LA JETÉE (French, Suns)."""
    import taste
    from app import (app, db, Attendance, GroupMembership, LetterboxdEntry, Movie, Showtime, Theatre, User,
                     Watchlist)
    setup_db()
    with app.app_context():
        afi, suns = (Theatre.query.filter_by(slug=s).first() for s in ('afi', 'suns'))
        ana, bo = User(name='Ana', email='ana@fy.test', is_active=True), User(name='Bo', email='bo@fy.test', is_active=True)
        db.session.add_all([ana, bo])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        day = datetime.now().replace(hour=19, minute=0, second=0, microsecond=0) + timedelta(days=2)
        ids = {}

        def film(title, year, genres, theatre, hour=19, fmt=None, director=None, lang='en', tmdb=None, playing=True):
            m = Movie(title=title, release_year=str(year), genres=genres, director=director, original_language=lang, tmdb_id=tmdb)
            db.session.add(m)
            db.session.flush()
            if playing:
                db.session.add(Showtime(movie_id=m.id, theatre_id=theatre.id, start_time=day.replace(hour=hour), format_label=fmt))
            ids[title] = m.id
            return m
        film('VERTIGO', 1958, 'thriller,mystery,romance', afi, fmt='35mm', director='Alfred Hitchcock')
        film('HORROR NIGHT', 2024, 'horror', suns, hour=22)
        film('ROMCOM', 2025, 'romance,comedy', afi)
        seen = film('SEEN IT', 2023, 'horror,drama', suns)
        film('WANTED', 2025, 'documentary', afi)
        film('LA JETÉE', 1962, 'drama,science fiction', suns, lang='fr')
        film('PSYCHO', 1960, 'horror,thriller', afi, director='Alfred Hitchcock', tmdb=539, playing=False)
        old = Showtime(movie_id=seen.id, theatre_id=suns.id, start_time=datetime.now() - timedelta(days=20))
        db.session.add(old)
        db.session.flush()
        db.session.add(Attendance(user_id=ana.id, showtime_id=old.id, status='went', source='site', answered_at=datetime.utcnow()))
        db.session.add(Watchlist(user_id=ana.id, movie_id=ids['WANTED']))
        db.session.add(LetterboxdEntry(user_id=bo.id, guid='lb-1', watched_on=date.today(), title='Psycho', year=1960,
                                       tmdb_id=539, rating=4.5))
        db.session.commit()
        taste.update(ana, {'genres': ['horror'], 'avoid': ['romance'], 'ways': ['film', 'foreign'], 'theatres': ['suns']})
        taste.add(ana, {'kind': 'director', 'name': 'Alfred Hitchcock'})
        taste.add(ana, {'kind': 'hide', 'movie_id': ids['ROMCOM']})
        return {**ids, 'ana': ana.id, 'bo': bo.id}


def for_you(w, who='ana', **q):
    d = client(w[who]).get('/api/discover', query_string={'group_id': 1, **q}).json
    shelf = next((s for s in d['shelves'] if s['key'] == 'for-you'), None)
    return d, {c['movie']['title']: c['reasons'] for c in shelf['items']} if shelf else {}


def test_your_taste_picks_and_explains(world):
    d, picks = for_you(world)
    assert d['taste_set'] is True
    assert picks == {
        'WANTED': ['on your watchlist'],                                   # the strongest first
        'HORROR NIGHT': ['Horror', 'at SUNS'],
        'LA JETÉE': ['in French', 'at SUNS'],
        'VERTIGO': ['Alfred Hitchcock', 'on 35mm'],                        # a romance, but a favorite's
    }
    assert list(picks)[0] == 'WANTED'


def test_left_out_seen_hidden_and_not_into(world):
    _, picks = for_you(world)
    assert 'SEEN IT' not in picks and 'ROMCOM' not in picks              # went to it; said not for me
    client(world['ana']).delete('/api/me/taste/items', json={'kind': 'director', 'key': 'alfred hitchcock'})
    assert 'VERTIGO' not in for_you(world)[1]                            # without Hitchcock, the romance outweighs 35mm


def test_learning_from_what_you_loved(world):
    d, picks = for_you(world, who='bo')
    assert d['taste_set'] is False
    assert picks == {'VERTIGO': ['more from Alfred Hitchcock']}          # loved PSYCHO on Letterboxd


def test_theatre_pages_and_the_theatres_list(world):
    d, picks = for_you(world, theatres='suns')
    assert next(s for s in d['shelves'] if s['key'] == 'for-you')['title'] == 'For you here'
    assert set(picks) == {'HORROR NIGHT', 'LA JETÉE'}
    counts = client(world['ana']).get('/api/for-you/theatres', query_string={'group_id': 1}).json
    assert counts == {'suns': 2, 'afi': 2}
    assert client().get('/api/for-you/theatres').status_code == 401


def test_browse_shows_them_all(world):
    r = client(world['ana']).get('/api/discover/browse', query_string={'group_id': 1, 'shelf': 'for-you', 'when': '2weeks'}).json
    assert {c['movie']['title'] for c in r['films']} == {'WANTED', 'HORROR NIGHT', 'LA JETÉE', 'VERTIGO'}

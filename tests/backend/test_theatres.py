"""Theatre pages on the Discover engine (R7b): one theatre's shelves, the
Theatres page previews."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def two_theatres():
    """Suns with a rare 35mm one-off and four back-to-back double bills;
    AFI with one ordinary film."""
    from app import app, db, Movie, Showtime, Theatre
    setup_db()
    with app.app_context():
        suns, afi = (Theatre.query.filter_by(slug=s).first() for s in ('suns', 'afi'))
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        def film(title, year=2000):
            m = Movie(title=title, release_year=str(year), runtime_minutes=90, genres='drama', poster_url=f'https://img/{title}.jpg')
            db.session.add(m)
            db.session.flush()
            return m
        def show(m, th, start, fmt=None):
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=start,
                                    end_time=start + timedelta(minutes=105), format_label=fmt))
        rare = film('RARE PRINT', 1971)
        show(rare, suns, day + timedelta(hours=19), fmt='35mm')
        for d in range(4):                                 # a double bill each night: 7:00 then 9:00
            a, b = film(f'FIRST {d}'), film(f'SECOND {d}')
            show(a, suns, day + timedelta(days=d + 1, hours=19))
            show(b, suns, day + timedelta(days=d + 1, hours=21))
        show(film('AFI FILM'), afi, day + timedelta(hours=20))
        db.session.commit()


def test_a_theatres_discover_page_only_has_its_films(two_theatres):
    d = client().get('/api/discover', query_string={'theatres': 'suns'}).json
    titles = {c['movie']['title'] for s in d['shelves'] for c in s['items']}
    assert 'RARE PRINT' in titles and 'AFI FILM' not in titles
    rare = next(s for s in d['shelves'] if s['key'] == 'rare')
    assert rare['items'][0]['movie']['title'] == 'RARE PRINT'


def test_one_theatre_shows_all_its_double_bills(two_theatres):
    # Discover caps doubles at three per theatre (variety); a theatre's own page doesn't.
    assert len(client().get('/api/discover', query_string={'theatres': 'suns'}).json['double_features']) == 4
    assert len(client().get('/api/discover').json['double_features']) <= 3


def test_unknown_theatre(two_theatres):
    assert client().get('/api/discover', query_string={'theatres': 'nope'}).status_code == 404


def test_theatres_page_previews(two_theatres):
    rows = {t['slug']: t for t in client().get('/api/theatres-overview').json}
    suns = rows['suns']['preview']
    assert suns['film_count'] == 9 and suns['rare'] >= 1 and suns['formats'] == ['35mm']
    assert suns['posters'][0]['title'] == 'RARE PRINT' and len(suns['posters']) == 5
    assert suns['next']['title'] == 'RARE PRINT'
    assert rows['avalon']['preview'] == {'posters': [], 'rare': 0, 'formats': [], 'tonight': 0, 'film_count': 0}

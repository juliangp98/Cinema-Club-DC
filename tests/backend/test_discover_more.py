"""Discover's See-all pages (R7b): every Spotlight, every double bill in the
next six weeks, and Browse's person filter that a Spotlight opens."""
import json
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def world():
    """At Suns: the same double bill on three nights five weeks apart-ish, by
    one director; at AFI: three films with one star; one far-off double."""
    from app import app, db, Movie, Showtime, Theatre
    setup_db()
    with app.app_context():
        suns, afi = (Theatre.query.filter_by(slug=s).first() for s in ('suns', 'afi'))
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        def film(title, director=None, cast=()):
            m = Movie(title=title, release_year='1990', runtime_minutes=90, genres='drama', director=director,
                      cast_json=json.dumps([{'name': c} for c in cast]))
            db.session.add(m)
            db.session.flush()
            return m
        def show(m, th, start):
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=start, end_time=start + timedelta(minutes=105)))
        a, b = film('BILL ONE', 'Agnès Varda'), film('BILL TWO', 'Agnès Varda')
        for d in (0, 7, 14):                                   # the same bill, three Saturdays
            show(a, suns, day + timedelta(days=d, hours=19))
            show(b, suns, day + timedelta(days=d, hours=21))
        late_a, late_b = film('LATE ONE'), film('LATE TWO')    # five weeks out: past a month, inside six weeks
        show(late_a, afi, day + timedelta(days=35, hours=18))
        show(late_b, afi, day + timedelta(days=35, hours=20))
        for i in range(3):
            show(film(f'STAR {i}', cast=['Tony Leung', f'Someone {i}']), afi, day + timedelta(days=i + 1, hours=13))
        show(film('STAR BIT PART', cast=['A', 'B', 'C', 'Tony Leung']), afi, day + timedelta(days=2, hours=10))
        db.session.commit()


def test_every_double_bill_six_weeks_out(world):
    doubles = client().get('/api/discover/doubles').json['doubles']
    bill = next(d for d in doubles if d['first']['movie']['title'] == 'BILL ONE')
    assert bill['second']['movie']['title'] == 'BILL TWO' and len(bill['also']) == 2   # listed once, other nights noted
    assert sum(d['first']['movie']['title'] == 'BILL ONE' for d in doubles) == 1
    assert any(d['first']['movie']['title'] == 'LATE ONE' for d in doubles)
    starts = [d['first']['next']['start_time'] for d in doubles]
    assert starts == sorted(starts)


def test_doubles_narrowed_to_a_theatre_or_region(world):
    at_afi = client().get('/api/discover/doubles', query_string={'theatres': 'afi'}).json['doubles']
    assert {d['theatre_slug'] for d in at_afi} == {'afi'}
    in_md = client().get('/api/discover/doubles', query_string={'regions': 'maryland'}).json['doubles']
    assert {d['theatre_slug'] for d in in_md} <= {'afi', 'avalon', 'regal-majestic'} and in_md


def test_every_spotlight(world):
    sp = {s['name']: s for s in client().get('/api/discover/spotlights').json['spotlights']}
    assert sp['Agnès Varda']['role'] == 'director' and sp['Agnès Varda']['count'] == 2
    assert sp['Tony Leung']['count'] == 3                      # top-billed three only, like Discover's
    only_suns = client().get('/api/discover/spotlights', query_string={'theatres': 'suns'}).json['spotlights']
    assert [s['name'] for s in only_suns] == ['Agnès Varda']


def test_a_spotlight_opens_its_films_in_browse(world):
    r = client().get('/api/discover/browse', query_string={'person': 'tony leung', 'when': 'month'}).json
    assert sorted(c['movie']['title'] for c in r['films']) == ['STAR 0', 'STAR 1', 'STAR 2']
    assert r['title'] == 'Tony Leung'                         # as the credits spell it
    assert client().get('/api/discover/browse', query_string={'person': 'Agnès Varda', 'when': 'month'}).json['total'] == 2

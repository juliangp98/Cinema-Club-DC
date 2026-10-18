"""Tickets (R15): Browse and the Calendar by ticket status — all (with the
films a theatre has announced, on their expected day), available, sold out,
or coming soon (only the announced films) — and suggestions (Discover's
shelves, Surprise me) that skip sold-out showings."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def box_office():
    """At Suns this week: OPEN NIGHT (one sold-out showing, one open), PACKED
    HOUSE (sold out both nights); NEXT WEEK announced for three days out
    (tickets not on sale yet), and FAR OFF announced for next month."""
    import app as A
    from app import app, db, Announcement, Movie, Showtime, Theatre
    setup_db()
    A._public_cache.clear()
    with app.app_context():
        suns = Theatre.query.filter_by(slug='suns').first()
        day = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)

        def film(title, genres='drama'):
            m = Movie(title=title, release_year='1985', runtime_minutes=100, genres=genres)
            db.session.add(m)
            db.session.flush()
            return m
        open_night, packed = film('OPEN NIGHT'), film('PACKED HOUSE')
        for m, h, sold in ((open_night, 19, True), (open_night, 21, False), (packed, 19, True), (packed, 21, True)):
            db.session.add(Showtime(movie_id=m.id, theatre_id=suns.id, start_time=day + timedelta(hours=h), is_sold_out=sold))
        soon, far = film('NEXT WEEK', 'horror'), film('FAR OFF')
        db.session.add(Announcement(theatre_id=suns.id, movie_id=soon.id, expected_on=(day + timedelta(days=2)).date()))
        db.session.add(Announcement(theatre_id=suns.id, movie_id=far.id, expected_on=(day + timedelta(days=40)).date()))
        db.session.commit()
        return {'soon_date': (day + timedelta(days=2)).date().isoformat()}


def browse(**params):
    return client().get('/api/discover/browse', query_string={'theatres': 'suns', 'when': 'week', **params}).json


def titles(d):
    return sorted(c['movie']['title'] for c in d['films'])


def test_all_shows_everything_and_whats_announced(box_office):
    d = browse()
    assert titles(d) == ['OPEN NIGHT', 'PACKED HOUSE']
    assert [a['movie']['title'] for a in d['announced']] == ['NEXT WEEK']               # this week's window only
    assert d['announced'][0]['date'] == box_office['soon_date']


def test_available_sold_out_and_coming_soon(box_office):
    d = browse(tickets='available')
    assert titles(d) == ['OPEN NIGHT'] and d['announced'] == []
    assert titles(browse(tickets='soldout')) == ['OPEN NIGHT', 'PACKED HOUSE']
    d = browse(tickets='soon')
    assert d['films'] == [] and [a['movie']['title'] for a in d['announced']] == ['NEXT WEEK']


def test_announced_films_follow_the_film_filters_they_can(box_office):
    assert [a['movie']['title'] for a in browse(genres='horror')['announced']] == ['NEXT WEEK']
    assert browse(genres='comedy')['announced'] == []
    assert browse(format='film')['announced'] == []                                     # only showings can answer that


def test_the_calendar_shows_the_status_and_announced_days(box_office):
    cal = client().get('/api/discover/calendar', query_string={'theatres': 'suns', 'when': 'week'}).json
    assert [a['movie']['title'] for a in cal['announced']] == ['NEXT WEEK']
    avail = client().get('/api/discover/calendar', query_string={'theatres': 'suns', 'when': 'week', 'tickets': 'available'}).json
    assert avail['announced'] == [] and all(not s['is_sold_out'] for s in avail['showtimes'])
    assert len(avail['showtimes']) == 1


def test_suggestions_skip_sold_out_showings(box_office):
    import discover
    from app import app
    with app.app_context():
        shelves = discover.discover(None, None)
        on_shelves = {c['movie']['title'] for s in shelves['shelves'] for c in s['items']}
        assert 'PACKED HOUSE' not in on_shelves                                         # nothing left to get into
        picks = {discover.surprise(None, None, when='week')['movie']['title'] for _ in range(20)}
        assert 'PACKED HOUSE' not in picks


def test_a_saved_search_label_says_it(box_office):
    import discover
    assert discover.describe({'tickets': 'available', 'when': 'week'}) == 'Tickets available · Next 7 days'

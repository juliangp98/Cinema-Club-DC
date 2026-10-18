"""Home bingo (R15): with the club's switch on, the month's Letterboxd diary
entries fill the squares the film alone decides (era, genre, length) and "Off
your watchlist" — after anything seen in person — and a line or full card
that needs one is worth less."""
import json
from datetime import date, datetime, timedelta

import pytest

from helpers import client, setup_db

# The grid reads keys[:4] + FREE + keys[4:]: 0 film · 1 pre1960 · 2 horror · 3 long · 4 FREE ·
# 5 late · 6 watchlist · 7 documentary · 8 comedy.
KEYS = ['film', 'pre1960', 'horror', 'long', 'late', 'watchlist', 'documentary', 'comedy']
TODAY = date.today()


@pytest.fixture
def card():
    """Club 1 with bingo on (home off) and this month's card; Ana (member,
    Letterboxd connected) wants WANTED (TMDB 77)."""
    import bingo
    from app import app, db, BingoCard, Group, GroupMembership, Movie, User, Watchlist
    setup_db()
    with app.app_context():
        g = db.session.get(Group, 1)
        g.bingo_enabled = True
        ana = User(name='Ana', email='ana@home.test', is_active=True, letterboxd_username='ana')
        db.session.add(ana)
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active', role='member'))
        wanted = Movie(title='WANTED', tmdb_id=77, release_year='2001', genres='drama')
        db.session.add(wanted)
        db.session.flush()
        db.session.add(Watchlist(user_id=ana.id, movie_id=wanted.id))
        BingoCard.query.filter_by(group_id=1, month=bingo.month_of()).delete()
        db.session.add(BingoCard(group_id=1, month=bingo.month_of(), squares_json=json.dumps(KEYS)))
        db.session.commit()
        return {'ana': ana.id}


def diary(uid, title, year=None, genres='', runtime=None, tmdb_id=None, showtime_id=None, n=[0]):
    from app import db, LetterboxdEntry
    n[0] += 1
    db.session.add(LetterboxdEntry(user_id=uid, guid=f'g{n[0]}', watched_on=TODAY, title=title, year=year,
                                   genres=genres, runtime=runtime, tmdb_id=tmdb_id, showtime_id=showtime_id,
                                   details_at=datetime.utcnow()))
    db.session.commit()


def went(uid, title, year, genres='', fmt=None, hour=19):
    from app import db, Attendance, Movie, Showtime, Theatre
    m = Movie(title=title, release_year=str(year), genres=genres)
    db.session.add(m)
    db.session.flush()
    start = datetime.combine(TODAY, datetime.min.time()).replace(hour=hour) - timedelta(days=0 if TODAY.day == 1 else 1)
    s = Showtime(movie_id=m.id, theatre_id=Theatre.query.first().id, start_time=start, format_label=fmt)
    db.session.add(s)
    db.session.flush()
    db.session.add(Attendance(user_id=uid, showtime_id=s.id, status='went', answered_at=start))
    db.session.commit()
    return s.id


def progress(uid, home=None):
    import bingo
    from app import BingoCard
    return bingo.progress(BingoCard.query.filter_by(group_id=1, month=bingo.month_of()).first(), uid, home)


def test_off_until_the_club_turns_it_on(card):
    from app import app
    with app.app_context():
        diary(card['ana'], 'OLD DOC', 1950, 'documentary')
        p = progress(card['ana'])
        assert p['filled'] == 0 and p['home'] == 0


def test_a_diary_entry_fills_every_film_square_it_fits(card):
    from app import app, db, Group
    with app.app_context():
        db.session.get(Group, 1).bingo_home = True
        db.session.commit()
        diary(card['ana'], 'OLD DOC', 1950, 'documentary')
        p = progress(card['ana'])
        assert p['home'] == 2 and p['filled'] == 2                         # before 1960 + documentary
        assert p['line_at'] and p['kernels'] == 3                          # a line that needed home squares


def test_in_person_wins_and_an_in_person_line_pays_full(card):
    from app import app
    with app.app_context():
        went(card['ana'], 'OLD PRINT', 1948, 'drama')                      # before 1960, in person
        diary(card['ana'], 'OLD DOC', 1950, 'documentary')
        p = progress(card['ana'], home=True)
        cells = {sq[0]: sq for sq in p['squares'] if sq}
        assert cells['pre1960'][1] is not None and cells['pre1960'][3] is None      # the screening, not the diary
        assert cells['documentary'][3] is not None
        assert p['kernels'] == 3                                           # its only line used a home square
        went(card['ana'], 'FUNNY 35', 1990, 'comedy', fmt='35mm')          # film + comedy: the 0-4-8 line, in person
        assert progress(card['ana'], home=True)['kernels'] == 5


def test_entries_that_matched_a_screening_count_once(card):
    from app import app
    with app.app_context():
        sid = went(card['ana'], 'MATCHED', 1955, 'drama')
        diary(card['ana'], 'MATCHED', 1955, 'documentary', showtime_id=sid)   # the same night, logged
        p = progress(card['ana'], home=True)
        assert p['home'] == 0 and p['filled'] == 1


def test_a_watchlisted_film_logged_at_home(card):
    from app import app
    with app.app_context():
        diary(card['ana'], 'Wanted', 2001, 'drama', tmdb_id=77)
        cells = {sq[0]: sq for sq in progress(card['ana'], home=True)['squares'] if sq}
        assert cells['watchlist'][3] is not None


def test_a_full_card_with_home_squares(card):
    import bingo
    from app import app, db, BingoCard
    with app.app_context():
        c = BingoCard.query.filter_by(group_id=1, month=bingo.month_of()).first()
        c.squares_json = json.dumps(['pre1960', 'seventies', 'new', 'documentary', 'horror', 'comedy', 'long', 'watchlist'])
        db.session.commit()
        for args in (('A', 1950, 'documentary,horror'), ('B', 1975, 'comedy', 160), ('C', TODAY.year, 'drama')):
            diary(card['ana'], *args)
        diary(card['ana'], 'Wanted', 2001, 'drama', tmdb_id=77)
        p = progress(card['ana'], home=True)
        assert p['full_at'] and p['kernels'] == bingo.HOME_LINE_KERNELS + bingo.HOME_FULL_KERNELS


def test_diary_films_get_their_details(card, monkeypatch):
    import enrich
    import letterboxd
    from app import app, db, LetterboxdEntry, Movie, User
    looked = []
    monkeypatch.setattr(enrich, 'tmdb_details', lambda tid: looked.append(tid) or
                        ({'genres': 'horror', 'runtime_minutes': 95} if tid == 501 else None))
    with app.app_context():
        db.session.add(Movie(title='OURS', tmdb_id=500, genres='comedy', runtime_minutes=170))
        for i, tid in enumerate((500, 501, 502)):
            db.session.add(LetterboxdEntry(user_id=card['ana'], guid=f'd{i}', watched_on=TODAY, title=f'T{i}', tmdb_id=tid))
        db.session.commit()
        letterboxd.fill_details(db.session.get(User, card['ana']))
        db.session.commit()
        got = {e.tmdb_id: (e.genres, e.runtime, e.details_at is not None) for e in LetterboxdEntry.query.filter_by(user_id=card['ana'])}
    assert got[500] == ('comedy', 170, True)                                # ours: no TMDB call
    assert got[501] == ('horror', 95, True)
    assert got[502] == (None, None, False)                                  # TMDB didn't answer: next sync
    assert looked == [501, 502]


def test_the_switch_is_a_club_setting(card):
    from app import app, db, GroupMembership, Group
    with app.app_context():
        GroupMembership.query.filter_by(user_id=card['ana'], group_id=1).first().role = 'organizer'
        slug = db.session.get(Group, 1).slug
        db.session.commit()
    r = client(card['ana']).put(f'/api/groups/{slug}', json={'bingo_home': True})
    assert r.status_code == 200 and r.json['bingo']['home'] is True

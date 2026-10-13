"""Repertory bingo (R10e): off until a club admin turns it on; one 3×3 card a
month for the whole club (free middle), made only from squares this month's
calendar makes possible and kept once made; filled in from check-ins; a
first line +5, the full card +15 more."""
import json
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    """Bingo Club (AFI): Ana (admin), Bo, Cy (members), Out (not in it)."""
    from app import app, db, Group, GroupMembership, User
    setup_db()
    with app.app_context():
        g = Group(name='Bingo Club', slug='bingo-club', is_public=False, theatres='afi')
        us = {n: User(name=n, email=f'{n.lower()}@b.test', is_active=True) for n in ('Ana', 'Bo', 'Cy', 'Out')}
        db.session.add_all([g, *us.values()])
        db.session.flush()
        for n in ('Ana', 'Bo', 'Cy'):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g.id, status='active',
                                           role='admin' if n == 'Ana' else 'member'))
        db.session.commit()
        return {**{n: u.id for n, u in us.items()}, 'G': g.id, 'slug': g.slug}


def show(title, when, fmt=None, year='1950', genres='horror', runtime=160, theatre='afi'):
    from app import app, db, Movie, Showtime, Theatre
    with app.app_context():
        m = Movie(title=title, release_year=year, genres=genres, runtime_minutes=runtime)
        db.session.add(m)
        db.session.flush()
        s = Showtime(movie_id=m.id, theatre_id=Theatre.query.filter_by(slug=theatre).first().id, start_time=when,
                     format_label=fmt)
        db.session.add(s)
        db.session.commit()
        return s.id, m.id


def went(uid, sid, minutes=0):
    from app import app, db, Attendance
    with app.app_context():
        db.session.add(Attendance(user_id=uid, showtime_id=sid, status='went', source='site',
                                  answered_at=datetime.utcnow() + timedelta(minutes=minutes)))
        db.session.commit()


def turn_on(c):
    assert client(c['Ana']).put(f"/api/groups/{c['slug']}", json={'bingo_enabled': True}).json['bingo'] == {'enabled': True}


def this_month(day, hour):
    return datetime.now().replace(day=1, hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=day)


def set_card(c, keys):
    """This month's card, with these squares (grid order, the middle free)."""
    import bingo
    from app import app, db, BingoCard
    with app.app_context():
        db.session.add(BingoCard(group_id=c['G'], month=bingo.month_of(), squares_json=json.dumps(keys)))
        db.session.commit()


def card(c, who):
    return client(c[who]).get('/api/bingo', query_string={'group_id': c['G']}).json


def test_bingo_starts_off_and_only_admins_switch_it(club):
    assert card(club, 'Bo') == {'enabled': False}
    assert client(club['Bo']).put(f"/api/groups/{club['slug']}", json={'bingo_enabled': True}).status_code == 403
    turn_on(club)
    assert card(club, 'Bo')['enabled'] is True
    assert client(club['Out']).get('/api/bingo', query_string={'group_id': club['G']}).status_code == 403


def test_a_card_only_has_squares_this_month_can_fill_and_stays_put(club):
    import bingo
    from app import app, db, Group
    for i in range(3):
        show(f'OLD HORROR {i}', datetime(2099, 1, 10 + i, 14), fmt='35mm')    # on film, matinee, pre-1960, horror, long
    with app.app_context():
        g = db.session.get(Group, club['G'])
        keys = json.loads(bingo.card_for(g, '2099-01').squares_json)
        assert len(keys) == len(set(keys)) == 8
        possible = {'film', 'matinee', 'pre1960', 'horror', 'long'} | {k for k in bingo.SQUARES if k not in bingo.SHOW_SQUARES}
        assert set(keys) <= possible
        show('LATE NEW COMEDY', datetime(2099, 1, 20, 22), year='2099', genres='comedy', runtime=90)
        show('LATE NEW COMEDY 2', datetime(2099, 1, 21, 22), year='2099', genres='comedy', runtime=90)
        assert json.loads(bingo.card_for(g, '2099-01').squares_json) == keys       # kept, even as the calendar changes


def test_one_screening_fills_every_square_it_fits(club):
    from app import app, db, Watchlist
    turn_on(club)
    set_card(club, ['film', 'pre1960', 'horror', 'matinee', 'long', 'double', 'watchlist', 'new_theatre'])
    sid, _ = show('NOSFERATU', this_month(2, 14), fmt='35mm')
    went(club['Bo'], sid)
    c = card(club, 'Bo')
    done = {s['key'] for s in c['squares'] if s['done']}
    assert done == {'free', 'film', 'pre1960', 'horror', 'matinee', 'long', 'new_theatre'}
    assert c['line'] and c['lines'] >= 1 and c['kernels'] == 5 and not c['full']
    by = next(s for s in c['squares'] if s['key'] == 'film')['by']
    assert by['title'] == 'NOSFERATU'
    sid2, mid2 = show('THE THING', this_month(2, 20), year='1982', genres='horror,science fiction', runtime=109)
    with app.app_context():
        db.session.add(Watchlist(user_id=club['Bo'], movie_id=mid2))
        db.session.commit()
    went(club['Bo'], sid2, minutes=5)                                        # same day, on the watchlist
    c = card(club, 'Bo')
    assert c['full'] and c['filled'] == 8 and c['kernels'] == 5 + 15
    import kernels
    with app.app_context():
        assert kernels.breakdown(club['Bo'], club['G'])['bingo'] == 20


def test_only_this_months_screenings_count(club):
    turn_on(club)
    set_card(club, ['film', 'pre1960', 'horror', 'matinee', 'long', 'double', 'watchlist', 'new_theatre'])
    sid, _ = show('LAST MONTH', datetime.now().replace(day=1) - timedelta(days=3), fmt='35mm')
    went(club['Bo'], sid)
    assert card(club, 'Bo')['filled'] == 0


def test_crew_nights_and_trailblazers(club):
    from app import app, db, RSVP
    turn_on(club)
    set_card(club, ['crew', 'trailblazer', 'comedy', 'documentary', 'seventies', 'late', 'event', 'big'])
    sid, _ = show('TOGETHER', this_month(3, 19), genres='drama', year='2001', runtime=100)
    with app.app_context():
        for i, who in enumerate(('Ana', 'Bo')):                              # Ana first
            db.session.add(RSVP(user_id=club[who], showtime_id=sid, group_id=club['G'], status='going',
                                created_at=datetime.utcnow() + timedelta(seconds=i)))
        db.session.commit()
    for who in ('Ana', 'Bo'):
        went(club[who], sid)
    assert not any(s['done'] for s in card(club, 'Ana')['squares'] if s['key'] == 'crew')   # two isn't a crew
    went(club['Cy'], sid)
    squares = {s['key']: s['done'] for s in card(club, 'Ana')['squares']}
    assert squares['crew'] and squares['trailblazer']                        # Ana said she was going first
    bo = {s['key']: s['done'] for s in card(club, 'Bo')['squares']}
    assert bo['crew'] and not bo['trailblazer']
    club_rows = {r['user']['name']: r['filled'] for r in card(club, 'Ana')['club']}
    assert club_rows == {'Bo': 1, 'Cy': 1}                                   # how the club is doing (not you)


def test_bingo_shows_in_the_feed(club):
    turn_on(club)
    set_card(club, ['film', 'pre1960', 'horror', 'matinee', 'long', 'double', 'watchlist', 'new_theatre'])
    sid, _ = show('NOSFERATU', this_month(2, 14), fmt='35mm')
    went(club['Bo'], sid)
    feed = client(club['Ana']).get('/api/feed', query_string={'group_id': club['G'], 'type': 'games'}).json
    [b] = feed['cards']
    assert b['type'] == 'bingo' and [(w['user']['name'], w['kind']) for w in b['winners']] == [('Bo', 'line')]


def test_an_empty_calendar_still_makes_a_full_card(club):
    turn_on(club)
    c = card(club, 'Bo')
    assert len(c['squares']) == 9 and c['squares'][4]['key'] == 'free' and len({s['key'] for s in c['squares']}) == 9

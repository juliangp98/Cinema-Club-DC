"""How far a theatre has published its full schedule (the horizon "last
chance" is judged against): steady at every hour of the day, not stretched by
a lone event later on or by empty days, bridging a theatre's closed days."""
from datetime import datetime, timedelta

import pytest

from helpers import setup_db

TODAY = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
EVERY_HOUR = pytest.mark.parametrize('hour', range(24))


def horizon(schedule, hour):
    """The horizon (days from today) of a theatre showing `schedule`
    ({day: number of showings, spread 11:00–23:00}) when it's `hour`:30."""
    from app import app, db, Group, Movie, Showtime, Theatre, schedule_horizons
    setup_db()
    with app.app_context():
        th = Theatre(name='Horizon Test', slug='horizon-test')
        g = Group(name='Horizon Club', slug='horizon-club', is_public=False, theatres='horizon-test')
        m = Movie(title='HORIZON FILM')
        db.session.add_all([th, g, m])
        db.session.flush()
        for day, n in schedule.items():
            for i in range(n):
                db.session.add(Showtime(movie_id=m.id, theatre_id=th.id,
                                        start_time=TODAY + timedelta(days=day, hours=11 + i * 12 / max(n, 1))))
        db.session.commit()
        h = schedule_horizons(g, TODAY + timedelta(hours=hour, minutes=30))[th.id]
        return (h.date() - TODAY.date()).days


@EVERY_HOUR
def test_a_lone_event_later_doesnt_stretch_a_small_theatres_schedule(hour):
    small = {d: 2 for d in range(7)} | {20: 1}                      # two a day for a week; an event in three weeks
    assert horizon(small, hour) == 6


@EVERY_HOUR
def test_empty_days_dont_lower_the_bar(hour):
    week = {0: 2, 1: 7, 2: 3, 3: 2, 4: 7, 7: 1}                     # the bar is half a typical day *with* showings
    assert horizon(week, hour) == 4


def test_closed_days_inside_the_schedule_are_bridged():
    closed_two_days = {d: 4 for d in (0, 1, 2, 5, 6, 7, 8)}
    assert horizon(closed_two_days, 9) == 8


def test_three_days_without_a_full_schedule_end_it():
    festival_later = {d: 4 for d in (0, 1, 2, 3, 7, 8, 9)}
    assert horizon(festival_later, 9) == 3


def test_last_chance_needs_the_schedule_to_run_three_days_past_the_final_showing():
    from app import is_last_chance
    h = TODAY + timedelta(days=horizon({d: 2 for d in range(7)}, 9), hours=23, minutes=59)
    assert is_last_chance(TODAY + timedelta(days=3, hours=19), {1}, {1: h})
    assert not is_last_chance(TODAY + timedelta(days=4, hours=19), {1}, {1: h})

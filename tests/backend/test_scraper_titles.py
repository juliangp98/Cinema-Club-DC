"""Cleaning scraped titles: event-code prefixes ("SOS26: THE THING") come off
the film's title, and the catalog cleanup repairs films saved with one."""
from datetime import datetime, timedelta

import pytest

from helpers import setup_db
from scrapers.base import event_label, normalize_title, parse_movie_title


@pytest.mark.parametrize('raw, title', [
    ('SOS26: In the Mouth of Madness', 'In the Mouth of Madness'),
    ('SOS26: The Thing (1982)', 'The Thing'),
    ('SOS 26: Halloween', 'Halloween'),
    ("SOS'26 – HALLOWEEN (35mm)", 'HALLOWEEN'),
    ('AFI50: Casablanca', 'Casablanca'),
    # Real titles and program names stay as they are.
    ('2001: A Space Odyssey', '2001: A Space Odyssey'),
    ('M3GAN 2.0', 'M3GAN 2.0'),
    ('THX 1138: A Story', 'THX 1138: A Story'),
    ('Friday the 13th Part VII: The New Blood', 'Friday the 13th Part VII: The New Blood'),
    ('EPIC SUNDAY: BATMAN BEGINS', 'EPIC SUNDAY: BATMAN BEGINS'),
    ('Star Wars: Episode IV - A New Hope', 'Star Wars: Episode IV - A New Hope'),
])
def test_code_prefixes_come_off(raw, title):
    assert parse_movie_title(raw)[0] == title


def test_same_film_across_venues_and_billing_kept():
    assert normalize_title('SOS26: The Thing') == normalize_title('THE THING')
    assert event_label('SOS26: The Thing', 'The Thing') == 'SOS26: The Thing'
    assert parse_movie_title('SOS26: The Thing (1982)')[1] == '1982'


def test_cleanup_repairs_films_already_saved_with_a_code():
    from app import app, db, Movie, MovieAlias, Showtime, Theatre
    from scrapers.sync import consolidate_catalog
    setup_db()
    with app.app_context():
        th = Theatre.query.first()
        good = Movie(title='The Thing', release_year='1982', tmdb_id=1091)
        bad = Movie(title='SOS26: The Thing', release_year='1982')
        lonely = Movie(title='SOS26: In the Mouth of Madness')
        db.session.add_all([good, bad, lonely])
        db.session.flush()
        st = Showtime(movie_id=bad.id, theatre_id=th.id, start_time=datetime.now() + timedelta(days=3))
        db.session.add(st)
        db.session.commit()
        good_id, bad_id, lonely_id, st_id = good.id, bad.id, lonely.id, st.id
    consolidate_catalog()                     # as backfill_enrichment.py runs it
    with app.app_context():
        st = db.session.get(Showtime, st_id)
        assert st.movie_id == good_id and db.session.get(Movie, bad_id) is None        # merged into The Thing
        assert st.event_label == 'SOS26: The Thing'                                    # the venue's billing stays
        assert MovieAlias.query.filter_by(title='SOS26: The Thing').first().movie_id == good_id
        assert db.session.get(Movie, lonely_id).title == 'In the Mouth of Madness'     # so its TMDB lookup can work

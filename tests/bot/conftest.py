"""Shared fixtures for the bot tests: the home club with challenges on."""
import json

import pytest

from helpers import patch_bot_api, setup_db


@pytest.fixture
def bot():
    """The home club, with challenges on, Who said it and Higher or lower."""
    from app import app, db, Group, Movie, Quote
    setup_db()
    with app.app_context():
        g = db.session.get(Group, 1)
        g.challenges_enabled = True
        g.trivia_source = 'local'
        g.quizzes_json = json.dumps({'who_said': True, 'higher_lower': True})
        cast = [{'name': n, 'character': c} for n, c in (('Humphrey Bogart', 'Rick Blaine'), ('Ingrid Bergman', 'Ilsa Lund'),
                                                        ('Paul Henreid', 'Victor Laszlo'), ('Claude Rains', 'Captain Renault'))]
        db.session.add(Movie(title='CASABLANCA', release_year='1942', tmdb_id=979999, cast_json=json.dumps(cast)))
        db.session.add(Quote(text='Here’s looking at you, kid.', movie='Casablanca', character='Rick'))
        db.session.commit()
    return patch_bot_api()

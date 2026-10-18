"""/find and /surprise in Discord (R3b): the real commands against the real
backend (through the Flask test client), with fake interactions."""
import asyncio
import re
from datetime import datetime, timedelta

import pytest

from helpers import FakeInteraction, items_of, patch_bot_api, setup_db


@pytest.fixture
def bot_with_films():
    """Three films playing this week at the club's theatres (the bot's club is group 1)."""
    from app import app, db, Movie, Showtime, Theatre
    setup_db()
    with app.app_context():
        afi = Theatre.query.filter_by(slug='afi').first()
        base = datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        ids = {}
        for i, (title, year, fmt) in enumerate([('THE CONVERSATION', 1974, '35mm'), ('PSYCHO', 1960, None), ('NEW ONE', 2026, None)]):
            m = Movie(title=title, release_year=str(year), genres='drama', runtime_minutes=100, tmdb_id=5000 + i)
            db.session.add(m)
            db.session.flush()
            db.session.add(Showtime(movie_id=m.id, theatre_id=afi.id, start_time=base + timedelta(hours=3 * i), format_label=fmt))
            ids[title] = m.id
        db.session.commit()
    return patch_bot_api(), ids


def run(coro):
    return asyncio.run(coro)


def test_find_posts_a_list_with_a_film_picker(bot_with_films):
    bot, ids = bot_with_films
    it = FakeInteraction()
    run(bot.find.callback(it, type='shelf:rare', when=None, where=None, search=None, private=False))
    assert it.sent[0] == ('defer', None, {'ephemeral': False})
    kind, _, kw = it.last
    assert kind == 'followup' and kw['embed'].title.startswith('🔎 Rare gems')
    picker = next(i for i in items_of(kw['view']) if getattr(i, 'custom_id', None) == 'find:pick')
    assert str(ids['THE CONVERSATION']) in [o.value for o in picker.options]
    assert any(getattr(i, 'url', '') and '/browse?' in i.url for i in items_of(kw['view']))


def test_find_privately(bot_with_films):
    bot, _ = bot_with_films
    it = FakeInteraction()
    run(bot.find.callback(it, type=None, when=None, where=None, search='psycho', private=True))
    assert it.sent[0] == ('defer', None, {'ephemeral': True})
    assert 'PSYCHO' in it.last[2]['embed'].description


def test_picking_a_film_shows_its_showtimes_privately(bot_with_films):
    bot, ids = bot_with_films
    it = FakeInteraction(data={'values': [str(ids['PSYCHO'])]})
    run(bot.FindPickSelect().callback(it))
    kind, _, kw = it.last
    assert kind == 'followup' and kw.get('ephemeral') and 'PSYCHO' in kw['embed'].title


def test_find_type_suggestions(bot_with_films):
    bot, _ = bot_with_films
    choices = run(bot.find_type_autocomplete(FakeInteraction(), 'rare'))
    assert any(c.name.startswith('Rare gems') and c.value == 'shelf:rare' for c in choices)


def test_surprise_and_spin_again_until_none_are_left(bot_with_films):
    bot, ids = bot_with_films
    week = type('Choice', (), {'value': 'week'})()
    it = FakeInteraction()
    run(bot.surprise.callback(it, when=week, where=None, private=False))
    kw = it.last[2]
    assert kw['embed'].title.startswith('🎲 ')
    spin = next(i for i in items_of(kw['view']) if (getattr(i, 'custom_id', '') or '').startswith('sur:'))
    shown = {kw['embed'].title}
    for _ in range(2):                                       # two more films to show, then none
        button = run(bot.SpinButton.from_custom_id(None, None, re.fullmatch(bot.SURPRISE_ID, spin.custom_id)))
        it2 = FakeInteraction()
        run(button.callback(it2))
        kind, _, kw2 = it2.last
        assert kind == 'edit' and kw2['embed'].title not in shown
        shown.add(kw2['embed'].title)
        spin = next(i for i in items_of(kw2['view']) if (getattr(i, 'custom_id', '') or '').startswith('sur:'))
    button = run(bot.SpinButton.from_custom_id(None, None, re.fullmatch(bot.SURPRISE_ID, spin.custom_id)))
    it3 = FakeInteraction()
    run(button.callback(it3))
    assert it3.last[0] == 'followup' and 'no more spins' in it3.last[1] and it3.last[2]['ephemeral']


def test_surprise_with_nothing_playing(bot_with_films):
    bot, _ = bot_with_films
    it = FakeInteraction()
    run(bot.surprise.callback(it, when=None, where='region:virginia', private=False))
    assert it.last[0] == 'followup' and "Nothing's playing" in it.last[1]

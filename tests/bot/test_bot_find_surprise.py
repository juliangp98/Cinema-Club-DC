"""/find and /surprise in Discord (R3b): the real commands against the real
backend (through the Flask test client), with fake interactions — and
🔔 Alert me under /find (a saved search, opt-in), and /showtimes' ticket filter."""
import asyncio
import re
from datetime import datetime, timedelta

import pytest

from helpers import press, FakeInteraction, items_of, patch_bot_api, setup_db


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


def test_alert_me_saves_the_search_and_asks_how_once(bot_with_films):
    """🔔 Alert me reads the search back from the card's link; the first time, it asks about DMs (opt-in)."""
    from types import SimpleNamespace
    from app import app, db, SavedSearch, User
    bot, _ = bot_with_films
    with app.app_context():
        db.session.add(User(name='Ana', discord_user_id='9301', is_active=True))
        db.session.commit()
    it = FakeInteraction(uid=9301, name='ana')
    run(bot.find.callback(it, type='genre:drama', when=None, where='theatre:afi', search=None, private=True))
    kw = it.last[2]
    [alert] = [i for i in items_of(kw['view']) if getattr(i, 'custom_id', None) == 'find:alert']
    tap = FakeInteraction(uid=9301, name='ana')
    tap.message = SimpleNamespace(embeds=[kw['embed']])
    press(bot.FindAlertButton, alert.custom_id, tap)
    saved, ask = tap.sent[-2], tap.sent[-1]
    assert saved[1].startswith('🔔 Saved **') and '3 films fit already' in saved[1] and 'bell' in saved[1]
    assert ask[1] == bot.ASK_SEARCH and [b.label for b in ask[2]['view'].children] == ['DM me', 'No thanks']
    with app.app_context():
        [s] = SavedSearch.query.all()
        assert __import__('json').loads(s.params_json) == {'genres': 'drama', 'theatres': 'afi'}
    again = FakeInteraction(uid=9301, name='ana')
    again.message = tap.message
    press(bot.FindAlertButton, alert.custom_id, again)
    assert again.last[1].startswith('🔔 Saved') and len([x for x in again.sent if x[0] == 'followup']) == 1   # asked once
    with app.app_context():
        assert SavedSearch.query.count() == 1                                    # the same search is one


def test_foryou_has_no_alert_button(bot_with_films):
    bot, _ = bot_with_films

    async def ids(alert):                                                       # views need a running loop
        return [getattr(i, 'custom_id', None) for i in items_of(bot.find_view(
            {'films': [], 'total': 0, 'browse_path': '/browse?shelf=for-you', 'params': {'shelf': 'for-you'}}, alert=alert))]
    assert 'find:alert' not in run(ids(False)) and 'find:alert' in run(ids(True))


def test_showtimes_by_tickets(bot_with_films):
    """tickets:Sold out keeps only sold-out showings; Coming soon lists announced films (no showings yet)."""
    from app import app, db, Announcement, Movie, Showtime, Theatre
    bot, ids = bot_with_films
    with app.app_context():
        Showtime.query.filter_by(movie_id=ids['PSYCHO']).first().is_sold_out = True
        afi = Theatre.query.filter_by(slug='afi').first()
        m = Movie(title='COMING THING', release_year='2026')
        db.session.add(m)
        db.session.flush()
        db.session.add(Announcement(movie_id=m.id, theatre_id=afi.id, expected_on=(datetime.now() + timedelta(days=3)).date(),
                                    last_seen_at=datetime.utcnow(), url='https://afi.test/coming'))
        db.session.commit()
    choice = {c.value: c for c in bot.TICKET_CHOICES}
    it = FakeInteraction()
    run(bot.showtimes.callback(it, days=7, tickets=choice['soldout']))
    e = it.last[2]['embed']
    text = ' '.join(f.value for f in e.fields)
    assert 'PSYCHO' in text and '(sold out)' in text and 'THE CONVERSATION' not in text and e.title.endswith('· Sold out')
    it = FakeInteraction()
    run(bot.showtimes.callback(it, days=7, tickets=choice['available']))
    assert 'PSYCHO' not in ' '.join(f.value for f in it.last[2]['embed'].fields)
    it = FakeInteraction()
    run(bot.showtimes.callback(it, days=7, tickets=choice['soon']))
    e = it.last[2]['embed']
    assert e.title.startswith('🔜 Coming soon') and 'COMING THING (2026)' in e.description and 'PSYCHO' not in e.description

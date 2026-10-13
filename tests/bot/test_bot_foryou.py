"""/foryou (R13): your For you picks privately in Discord, with why; and the
taste match on /compare."""
import asyncio
from datetime import datetime, timedelta

import pytest

from helpers import FakeInteraction, all_linked_present, patch_bot_api, setup_db


@pytest.fixture
def bot():
    """Ana (9501) loves horror; Bo (9502) has no taste yet. NIGHT SHIFT (a
    horror film) plays at AFI in three days."""
    import taste
    from app import app, db, GroupMembership, Movie, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        ana, bo = User(name='Ana', discord_user_id='9501', is_active=True), User(name='Bo', discord_user_id='9502', is_active=True)
        m = Movie(title='NIGHT SHIFT', genres='horror', release_year='2025')
        db.session.add_all([ana, bo, m])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        db.session.add(Showtime(movie_id=m.id, theatre_id=Theatre.query.filter_by(slug='afi').first().id,
                                start_time=datetime.now() + timedelta(days=3)))
        db.session.commit()
        taste.update(ana, {'genres': ['horror'], 'public': True})
        taste.update(bo, {'genres': ['horror', 'comedy']})
    all_linked_present()
    return patch_bot_api()


def run(bot, uid, cmd='foryou_cmd', **kw):
    it = FakeInteraction(uid=uid, name='x')
    asyncio.run(getattr(bot, cmd).callback(it, **kw))
    return it.last


def test_your_picks_with_why(bot):
    _, _, kw = run(bot, 9501)
    e = kw['embed']
    assert kw['ephemeral'] is True and e.title == '✨ For you' and 'NIGHT SHIFT' in e.description and '*Horror*' in e.description
    assert kw['view'] is not None and '1 for you' in e.footer.text


def test_nothing_yet_says_how_to_set_your_taste(bot):
    from app import app, db, TasteItem, User
    with app.app_context():
        TasteItem.query.filter_by(user_id=User.query.filter_by(discord_user_id='9502').first().id).delete()
        db.session.commit()
    e = run(bot, 9502)[2]['embed']
    assert '/profile' in e.description and 'Your taste' in e.description


def test_compare_shows_the_taste_match(bot):
    import types
    other = types.SimpleNamespace(id=9501, display_name='Ana', name='ana', bot=False)
    e = run(bot, 9502, cmd='compare', member=other)[2]['embed']
    match = next(f for f in e.fields if f.name.startswith('🎨 Taste match'))
    assert match.name == '🎨 Taste match: 50%' and match.value == 'You both love Horror'

"""Game posts in #movies from the bot (R14): it posts what the club approved
(once), and an admin who takes DMs reviews Ask-first posts with buttons."""
import asyncio
import types
from datetime import datetime

import pytest

from helpers import all_linked_present, client, items_of, patch_bot_api, setup_db

NOON = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture
def bot(monkeypatch):
    """Adm (9801, admin, takes DMs) and Ana (9802) in the Discord club; quotes to ask about."""
    import game_posts
    import notify
    from app import app, db, GroupMembership, Quote, User
    monkeypatch.setattr(game_posts, '_local_now', lambda: NOON)
    setup_db()
    with app.app_context():
        adm = User(name='Adm', email='adm@b.test', discord_user_id='9801', is_active=True)
        ana = User(name='Ana', discord_user_id='9802', is_active=True)
        db.session.add_all([adm, ana])
        db.session.flush()
        db.session.add(GroupMembership(user_id=adm.id, group_id=1, status='active', role='admin'))
        db.session.add(GroupMembership(user_id=ana.id, group_id=1, status='active'))
        for text, movie in (('Rosebud.', 'Citizen Kane'), ('Stella!', 'A Streetcar Named Desire'),
                            ('I’ll be back.', 'The Terminator'), ('You talking to me?', 'Taxi Driver'),
                            ('Fasten your seatbelts.', 'All About Eve')):
            db.session.add(Quote(text=text, movie=movie))
        notify.set_prefs(adm, {'channels': {'discord': True}})
        db.session.commit()
        b = patch_bot_api()
        b.test_admin = adm.id
    all_linked_present()
    b.sent = []

    class Channel:
        async def send(self, content=None, embed=None, view=None, **k):
            b.sent.append((embed, view, k))
            return types.SimpleNamespace(id=4242 + len(b.sent))
    monkeypatch.setattr(b, 'movies_channel', lambda: Channel())
    return b


def switch(bot, **on):
    from app import app, db, Group
    with app.app_context():
        slug = db.session.get(Group, 1).slug
    assert client(bot.test_admin).put(f'/api/groups/{slug}', json=on).status_code == 200


def run(coro):
    return asyncio.run(coro)


def test_an_approved_question_goes_up_once_without_pinging(bot):
    switch(bot, trivia_enabled=True)
    run(bot.games_loop.coro())
    assert bot.sent == []                                                     # on, but the club didn't say post
    switch(bot, trivia_post='always')
    from app import BotSetting, app, db
    with app.app_context():
        db.session.query(BotSetting).filter_by(key='games_tick_at').delete()
        db.session.commit()
    run(bot.games_loop.coro())
    run(bot.games_loop.coro())
    [(embed, view, kw)] = bot.sent
    assert embed.title == '🧠 Question of the day' and len(items_of(view)) == 4
    assert kw['allowed_mentions'].everyone is False and kw['allowed_mentions'].roles is False


def test_an_admin_reviews_by_dm(bot, monkeypatch):
    switch(bot, trivia_enabled=True, trivia_post='ask')
    run(bot.games_loop.coro())
    assert bot.sent == []                                                     # waiting for an OK
    dms = []

    class DMUser:
        async def send(self, content=None, embed=None, view=None, **k):
            dms.append((content, embed, view))

    async def fetch_user(uid):
        return DMUser()
    bot.client.fetch_user = fetch_user

    class Day(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz).replace(hour=12)
    bot.datetime = Day
    run(bot.notify_loop.coro())
    review = next(d for d in dms if d[2] is not None)
    assert review[0].startswith('👀 Waiting for your OK') and 'The answer:' in review[0]
    labels = [i.label for i in items_of(review[2])]
    assert labels == ['Post it', 'Try another', 'Skip']
    edits, order = [], []

    class Response:                                                   # answered first (a defer), then edited
        async def defer(self, **k):
            order.append('defer')

        def is_done(self):
            return 'defer' in order

    class Followup:
        async def send(self, content=None, **k):                      # a failure would land here
            edits.append((f'FAILED: {content}', None, None))

    async def edit_original_response(content=None, embed=None, view=None, **k):
        edits.append((content, embed, view))
    real_post = bot.api.post

    async def post(path, *a, **k):
        order.append('backend')
        return await real_post(path, *a, **k)
    monkeypatch.setattr(bot.api, 'post', post)
    it = types.SimpleNamespace(user=types.SimpleNamespace(id=9801, name='adm', display_name='Adm', display_avatar=None),
                               guild_id=None, channel_id=1, response=Response(), followup=Followup(),
                               edit_original_response=edit_original_response)
    button = lambda view, label: next(c for c in view.children if getattr(c, 'item', c).label == label)
    another = button(review[2], 'Try another')
    run(another.callback(it))
    assert order == ['defer', 'backend']                                      # Discord hears back within its 3 s
    assert edits[-1][1].description != review[1].description                 # a different question
    post = button(edits[-1][2], 'Post it')
    run(post.callback(it))
    assert edits[-1][0].startswith('✅ Approved')
    run(bot.games_loop.coro())
    assert len(bot.sent) == 1 and bot.sent[0][0].description == edits[-2][1].description

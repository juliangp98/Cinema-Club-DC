"""The bot's side of alerts (R8a): bundled DMs (not at night, never twice),
and /notifications to change the setting from Discord."""
import asyncio
import types
from datetime import datetime, timedelta

import pytest

from helpers import FakeInteraction, client, items_of, patch_bot_api, setup_db


@pytest.fixture
def bot_with_alerts():
    """Ana (Discord 7101) has two alerts ready to send; Bo (7102) has one
    and DMs closed."""
    import discord
    from app import app, db, Movie, Notification, User
    setup_db()
    with app.app_context():
        m = Movie(title='STALKER', release_year='1979', poster_url='https://img/stalker.jpg')
        db.session.add(m)
        ana = User(name='Ana', discord_user_id='7101', is_active=True)
        bo = User(name='Bo', discord_user_id='7102', is_active=True)
        db.session.add_all([ana, bo])
        db.session.flush()
        ready = datetime.utcnow()
        for u, title in ((ana, 'STALKER'), (ana, 'MIRROR'), (bo, 'SOLARIS')):
            db.session.add(Notification(user_id=u.id, kind='showings', movie_id=m.id, channels='discord', ready_at=ready,
                                        payload_json=f'{{"title": "{title}", "theatre": "Suns Cinema", '
                                                     f'"first": "{(datetime.now() + timedelta(days=2)).isoformat()}", "count": 1}}'))
        db.session.commit()
    bot = patch_bot_api()

    class DMUser:
        def __init__(self, closed=False):
            self.sent, self.closed = [], closed

        async def send(self, content=None, embed=None, **k):
            if self.closed:
                raise discord.Forbidden(types.SimpleNamespace(status=403, reason='Forbidden'), 'DMs closed')
            self.sent.append(embed)
    users = {7101: DMUser(), 7102: DMUser(closed=True)}

    async def fetch_user(uid):
        return users[uid]
    bot.client.fetch_user = fetch_user
    return bot, users


def at_hour(bot, h):
    from datetime import datetime as real

    class Fake(real):
        @classmethod
        def now(cls, tz=None):
            return real.now(tz).replace(hour=h)
    bot.datetime = Fake


def test_alerts_go_out_bundled_once_and_not_at_night(bot_with_alerts):
    import bot as B
    bot, users = bot_with_alerts
    try:
        at_hour(bot, 2)
        asyncio.run(bot.notify_loop.coro())
        assert users[7101].sent == []                                  # 2 AM: waits for the morning
        at_hour(bot, 9)
        asyncio.run(bot.notify_loop.coro())
        [embed] = users[7101].sent
        assert embed.title == '🔔 2 updates on your watchlist'
        assert 'STALKER is playing' in embed.description and 'MIRROR is playing' in embed.description
        assert embed.footer.text.endswith('/notifications')
        asyncio.run(bot.notify_loop.coro())
        assert len(users[7101].sent) == 1                              # never twice
        from helpers import H
        assert client().get('/api/internal/notifications/dm', headers=H).json == []   # Bo: DMs closed, not retried
    finally:
        B.datetime = datetime


def test_notifications_command_toggles_the_setting(bot_with_alerts):
    bot, _ = bot_with_alerts
    it = FakeInteraction(uid=7101, name='ana')
    asyncio.run(bot.notifications_cmd.callback(it))
    kind, _, kw = it.last
    assert kw['ephemeral'] is True and kw['embed'].title == '🔔 Your notifications'
    assert '⬜ Discord DMs' in kw['embed'].fields[0].value and 'add an address' in kw['embed'].fields[0].value   # opt-in
    dm_button = next(i for i in items_of(kw['view']) if getattr(i, 'label', '').startswith('Discord DMs'))
    assert dm_button.label == 'Discord DMs: off'
    asyncio.run(dm_button.callback(it))
    _, _, kw = it.last
    assert '✅ Discord DMs' in kw['embed'].fields[0].value
    select = next(i for i in items_of(kw['view']) if isinstance(i, __import__('discord').ui.Select))
    select._values = ['showings']                                   # what Discord fills in on a pick
    asyncio.run(select.callback(it))
    _, _, kw = it.last
    assert '✅ A film on your watchlist is booked or announced' in kw['embed'].fields[1].value
    assert '⬜ Tickets go on sale' in kw['embed'].fields[1].value

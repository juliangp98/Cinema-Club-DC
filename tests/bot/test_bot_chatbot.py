"""The bot's chatbot and /llm, through the shared AI."""
import asyncio
import types

import pytest

from helpers import patch_bot_api, setup_db, patch_bot


@pytest.fixture
def bot_ai():
    import ai
    from fake_groq import Fake
    setup_db()
    ai._client = Fake(['llama-3.3-70b-versatile', 'qwen/qwen3-32b'])
    bot = patch_bot_api()
    bot.llm.configure(bot.api)
    return bot, ai._client


def test_the_chatbot_replies_through_the_backend(bot_ai):
    bot, _ = bot_ai
    text = asyncio.run(bot.llm.chat([{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': 'what should i see?'}],
                                    max_tokens=150))
    assert text == 'reply from qwen/qwen3-32b'


def test_a_rate_limit_reaches_the_bot_with_a_wait(bot_ai):
    bot, fake = bot_ai
    asyncio.run(bot.llm.chat([{'role': 'user', 'content': 'hi'}]))        # models chosen
    fake.limited = {'qwen/qwen3-32b', 'llama-3.3-70b-versatile'}
    with pytest.raises(bot.llm.RateLimited) as e:
        asyncio.run(bot.llm.chat([{'role': 'user', 'content': 'hi'}]))
    assert abs((e.value.retry_after_sec or 0) - 672.5) < 0.01


def test_llm_show_reads_the_shared_status(bot_ai):
    bot, _ = bot_ai
    asyncio.run(bot.llm.chat([{'role': 'user', 'content': 'hi'}]))
    sent = []

    class R:
        async def defer(self, **k):
            pass

    class F:
        async def send(self, content=None, **k):
            sent.append(content)
    asyncio.run(bot.llm_cmd.callback(types.SimpleNamespace(response=R(), followup=F(), guild_id=900,
                                                             user=types.SimpleNamespace(display_name='Admin'))))
    assert '`qwen/qwen3-32b`' in sent[-1] and 'poll drafts' in sent[-1]

    class Elsewhere:                                     # another club's server: the AI isn't theirs to change
        async def send_message(self, content=None, **k):
            sent.append(content)
    asyncio.run(bot.llm_cmd.callback(types.SimpleNamespace(response=Elsewhere(), followup=F(), guild_id=4321,
                                                             user=types.SimpleNamespace(display_name='Admin'))))
    assert sent[-1] == bot.HOME_ONLY_MSG


def test_model_changes_reach_the_owner_by_dm_not_the_channel(bot_ai):
    bot, _ = bot_ai
    asyncio.run(bot.llm.chat([{'role': 'user', 'content': 'hi'}]))       # the first choice is a change
    dms, posts = [], []

    async def dm(msg):
        dms.append(msg)

    class Ch:
        async def send(self, *a, **k):
            posts.append((a, k))
    patch_bot(dm_owner=dm, movies_channel=lambda: Ch())
    bot.client.get_channel = lambda _id: Ch()
    asyncio.run(bot.announce_loop.coro())
    assert any('AI models' in m for m in dms) and not posts


def test_a_key_that_starts_working_reaches_the_owner_by_dm(bot_ai):
    """The scraper's "AMC accepted the API key" note: the owner's DMs, never the channel."""
    bot, _ = bot_ai
    from app import app
    from scrapers.sync import set_service_ready
    with app.app_context():
        set_service_ready('amc', True)
    dms, posts = [], []

    async def dm(msg):
        dms.append(msg)

    class Ch:
        async def send(self, *a, **k):
            posts.append((a, k))
    patch_bot(dm_owner=dm, movies_channel=lambda: Ch())
    bot.client.get_channel = lambda _id: Ch()
    asyncio.run(bot.announce_loop.coro())
    assert any(m.startswith('✅ AMC accepted the API key') for m in dms) and not posts

"""The bot's chatbot and /llm through the shared AI (run via run_bot_inprocess.py with seed_bot_r6.py)."""
from helpers import H, client, Checks, WORK


def test_bot_chatbot():
    checks = Checks()
    check = checks.check
    # ── seed ──
    import sys
    from app import app, db, migrate
    import ai
    from fake_groq import Fake
    with app.app_context():
        db.create_all(); migrate()
    ai._client = Fake(['llama-3.3-70b-versatile', 'qwen/qwen3-32b'])
    from helpers import patch_bot_api
    patch_bot_api()
    import asyncio, types
    import bot, ai

    async def main():
        bot.llm.configure(bot.api)
        text = await bot.llm.chat([{'role': 'system', 'content': 'x'}, {'role': 'user', 'content': 'what should i see?'}], max_tokens=150)
        check('chatbot replies through the backend', text == 'reply from qwen/qwen3-32b', text)
        ai._client.limited = {'qwen/qwen3-32b', 'llama-3.3-70b-versatile'}
        try:
            await bot.llm.chat([{'role': 'user', 'content': 'hi'}]); check('rate limit surfaces', False)
        except bot.llm.RateLimited as e:
            check('rate limit surfaces as RateLimited with a wait', abs((e.retry_after_sec or 0) - 672.5) < 0.01, e.retry_after_sec)
        ai._client.limited = set()
        sent = []
        class R:
            async def defer(self, **k): pass
        class F:
            async def send(self, content=None, **k): sent.append(content)
        it = types.SimpleNamespace(response=R(), followup=F(), user=types.SimpleNamespace(display_name='Admin'))
        await bot.llm_show.callback(it)
        check('/llm show reads the shared status', sent and '`qwen/qwen3-32b`' in sent[-1] and 'poll drafts' in sent[-1], sent[-1:])
        dms, posts = [], []
        async def dm(msg): dms.append(msg)
        bot.dm_owner = dm
        class Ch:
            async def send(self, *a, **k): posts.append((a, k))
        bot.movies_channel = lambda: Ch()
        bot.client.get_channel = lambda _id: Ch()
        await bot.announce_loop.coro()
        check('model changes reach the owner by DM, not the channel', any('AI models' in m for m in dms) and not posts, (dms, posts))
    asyncio.run(main())
    checks.done()

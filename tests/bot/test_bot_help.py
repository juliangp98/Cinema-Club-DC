"""/help lists every member command that exists, privately."""
from helpers import H, client, Checks, WORK


def test_bot_help():
    checks = Checks()
    check = checks.check
    import asyncio, types
    import bot, embeds
    async def main():
        sent = {}
        class R:
            async def send_message(self, *a, **k): sent.update(k)
        it = types.SimpleNamespace(response=R())
        await bot.help_cmd.callback(it)
        e = sent.get('embed')
        check('private reply with the guide', sent.get('ephemeral') is True and e.title.startswith('🍿 CinemaBot'))
        listed = {cmd for _, rows in embeds.HELP_SECTIONS for cmd, _ in rows if cmd.startswith('/')}
        real = set()
        for c in bot.client.tree.get_commands():
            if hasattr(c, 'commands'):
                real |= {f'/{c.name} {s.name}' for s in c.commands} | {f'/{c.name}'}
            else:
                real.add(f'/{c.name}')
        check('every command listed exists', listed <= real, listed - real)
        hidden = {'/llm', '/llm show', '/llm set', '/help', '/poll', '/quote add', '/quote edit', '/quote remove', '/quote find'}
        check('every member command is listed (admin /llm left out)', real - listed <= hidden, real - listed - hidden)
        check('fits Discord limits', len(e) <= 6000 and all(len(f.value) <= 1024 for f in e.fields))
    asyncio.run(main())
    checks.done()

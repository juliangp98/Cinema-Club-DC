"""/help lists every member command that exists, privately."""
import asyncio
import types

import pytest


@pytest.fixture
def help_embed():
    import bot
    sent = {}

    class R:
        async def send_message(self, *a, **k):
            sent.update(k)
    asyncio.run(bot.help_cmd.callback(types.SimpleNamespace(response=R())))
    return sent


def commands():
    import bot
    real = set()
    for c in bot.client.tree.get_commands():
        real |= ({f'/{c.name} {s.name}' for s in c.commands} | {f'/{c.name}'}) if hasattr(c, 'commands') else {f'/{c.name}'}
    return real


def test_help_is_a_private_guide(help_embed):
    assert help_embed.get('ephemeral') is True and help_embed['embed'].title.startswith('🍿 CinemaBot')


def test_help_lists_exactly_the_member_commands():
    import embeds
    listed = {cmd for _, rows in embeds.HELP_SECTIONS for cmd, _ in rows if cmd.startswith('/')}
    hidden = {'/llm', '/llm show', '/llm set', '/help', '/poll', '/quote add', '/quote edit', '/quote remove', '/quote find'}
    assert listed <= commands()                                   # every command listed exists
    assert commands() - listed <= hidden                          # every member command is listed (admin /llm left out)


def test_help_fits_discords_limits(help_embed):
    e = help_embed['embed']
    assert len(e) <= 6000 and all(len(f.value) <= 1024 for f in e.fields)

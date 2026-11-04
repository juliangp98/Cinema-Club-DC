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
    """Every command as members type it: /showtimes, /play challenge start…"""
    import bot
    from discord import app_commands

    def paths(c, at='/'):
        here = f'{at}{c.name}'
        return set().union(*(paths(s, here + ' ') for s in c.commands)) if isinstance(c, app_commands.Group) else {here}
    return set().union(*(paths(c) for c in bot.client.tree.get_commands()))


def test_help_is_a_private_guide(help_embed):
    assert help_embed.get('ephemeral') is True and help_embed['embed'].title.startswith('🍿 CinemaBot')
    assert help_embed['embed'].url.endswith('/help') and 'Full guide' in help_embed['embed'].description   # the site's guide


def test_help_lists_exactly_the_member_commands():
    import embeds
    listed = {cmd for _, rows in embeds.HELP_SECTIONS for cmd, _ in rows if cmd.startswith('/')}
    hidden = {'/llm', '/help'}
    assert listed <= commands()                                   # every command listed exists
    assert commands() - listed <= hidden                          # every member command is listed (admin /llm left out)


def test_help_fits_discords_limits(help_embed):
    e = help_embed['embed']
    assert len(e) <= 6000 and all(len(f.value) <= 1024 for f in e.fields)


def test_a_big_drop_says_how_many_more_films():
    import embeds
    films = [{'movie_id': i, 'title': f'FILM {i}', 'first_showtime': '2026-11-01T19:00:00', 'showtime_count': 2}
             for i in range(10)]
    event = {'payload': {'theatre_name': 'AFI Silver', 'new_showtime_count': 40, 'new_movie_count': 3,
                         'date_min': '2026-11-01T19:00:00', 'date_max': '2026-11-30T19:00:00',
                         'movie_summaries': films, 'movie_ids': list(range(23))}}
    assert '…and 15 more films' in embeds.drop_embed(event).description       # all 23, not the 10 summarized
    event['payload'].update(movie_summaries=films[:9], movie_ids=list(range(9)))
    assert '…and 1 more film' in embeds.drop_embed(event).description

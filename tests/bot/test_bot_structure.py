"""The bot is split by feature (bot/features/*); each module registers its
persistent buttons and background loops for setup_hook to start. Nothing may
be left out — an unregistered button stops working after a restart, an
unregistered loop never runs."""
import inspect

from discord.ext import tasks
from discord.ui import DynamicItem

import bot  # noqa: F401 — loads every feature
from features import shared, chat, alerts, schedule, threads, profile, polls, admin, games, challenges, tournaments, club, servers

FEATURES = (shared, chat, alerts, schedule, threads, profile, polls, admin, games, challenges, tournaments, club, servers)


def test_every_button_and_loop_is_registered():
    items = {obj for m in FEATURES for obj in vars(m).values()
             if inspect.isclass(obj) and issubclass(obj, DynamicItem) and obj is not DynamicItem and obj.__module__ == m.__name__}
    loops = {obj for m in FEATURES for name, obj in vars(m).items() if isinstance(obj, tasks.Loop)}
    assert items and set(shared._registry['items']) == items
    assert loops and set(shared._registry['loops']) == loops
    assert len(shared._registry['items']) == len(items)            # each once


def test_every_command_is_on_the_tree():
    names = {c.name for c in shared.client.tree.get_commands()}
    assert {'showtimes', 'rsvp', 'discuss', 'profile', 'poll', 'play', 'llm', 'help', 'quote', 'setup'} <= names
    assert len(names) == 22


def tree(c):
    """{subcommand: its options as members see them}, nested for a group: /play's shape."""
    from discord import app_commands
    if isinstance(c, app_commands.Group):
        return {s.name: tree(s) for s in c.commands}
    return {p.display_name for p in c.parameters}


def test_commands_with_options_and_the_two_trees():
    """Most commands are one command, its choices as options Discord shows
    (action:, period:…), like /showtimes. /play and /poll do many different
    things, so they're trees: each subcommand carries only its own options."""
    from discord import app_commands
    by_name = {c.name: c for c in shared.client.tree.get_commands()}
    assert sorted(n for n, c in by_name.items() if isinstance(c, app_commands.Group)) == ['play', 'poll']
    for name, option in (('quote', 'action'), ('llm', 'action'), ('leaderboard', 'period'), ('watch', 'action'),
                         ('announcements', 'action')):
        params = {p.name: p for p in by_name[name].parameters}
        assert params[option].choices and not params[option].required, (name, option)
    play = tree(by_name['play'])
    assert set(play) == {'today', 'solo', 'kernels', 'challenge', 'tournament'}
    assert play['today'] == play['kernels'] == set() and play['solo'] == {'game'}
    assert set(play['challenge']) == {'start', 'list', 'scout'} and set(play['tournament']) == {'start', 'list'}
    start, cup = play['challenge']['start'], play['tournament']['start']
    assert {'game', 'opponent', 'stake', 'closes', 'club'} <= start and not {'format', 'prizes', 'player'} & start
    assert {'format', 'game', 'player', 'player5', 'entry', 'prizes', 'match_time', 'club'} <= cup and 'opponent' not in cup
    assert play['challenge']['scout'] == set() and play['challenge']['list'] == play['tournament']['list'] == {'which'}
    poll = tree(by_name['poll'])
    assert poll == {'list': set(), 'vote': {'poll'}, 'answers': {'poll'},
                    'make': {'request', 'based_on', 'scoring', 'answers', 'in_discord'}}


def test_play_offers_every_quiz_game():
    """/play solo lists the backend's quiz games (quizzes.GAMES), each once,
    and /play challenge start the same, plus trivia."""
    import quizzes
    assert [k for k, _ in games.QUIZ_GAMES] == list(quizzes.GAMES)
    assert [c.value for c in challenges.VERSUS_GAMES] == ['random', 'gauntlet', *quizzes.GAMES, 'trivia']


def test_every_command_fits_discords_limits():
    """Discord refuses the whole tree at sync if one description, option or
    choice is too long (100 characters), so a restart would leave every
    command stale."""
    from discord import app_commands

    def walk(c):                                  # (name, its most, description) for each piece
        yield c.name, 32, c.description
        if isinstance(c, app_commands.Group):
            for s in c.commands:
                yield from walk(s)
            return
        for p in c.parameters:
            yield p.display_name, 32, p.description
            yield from ((ch.name, 100, ch.name) for ch in p.choices)
    too_long = [(n, d) for c in shared.client.tree.get_commands() for n, most, d in walk(c)
                if len(n) > most or not 1 <= len(d) <= 100]
    assert too_long == []

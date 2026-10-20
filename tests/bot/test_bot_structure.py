"""The bot is split by feature (bot/features/*); each module registers its
persistent buttons and background loops for setup_hook to start. Nothing may
be left out — an unregistered button stops working after a restart, an
unregistered loop never runs."""
import inspect

from discord.ext import tasks
from discord.ui import DynamicItem

import bot  # noqa: F401 — loads every feature
from features import shared, chat, alerts, schedule, threads, profile, polls, admin, games, club, servers

FEATURES = (shared, chat, alerts, schedule, threads, profile, polls, admin, games, club, servers)


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


def test_every_command_is_one_command_with_options():
    """Like /showtimes: one command, its choices as options Discord shows
    (action:, game:, period:…) — never sub-commands ("/quote add") listed apart."""
    from discord import app_commands
    groups = [c.name for c in shared.client.tree.get_commands() if isinstance(c, app_commands.Group)]
    assert groups == []
    by_name = {c.name: c for c in shared.client.tree.get_commands()}
    for name, option in (('quote', 'action'), ('poll', 'action'), ('llm', 'action'), ('play', 'game'),
                         ('leaderboard', 'period'), ('watch', 'action'), ('announcements', 'action')):
        params = {p.name: p for p in by_name[name].parameters}
        assert params[option].choices and not params[option].required, (name, option)


def test_play_offers_every_quiz_game():
    """/play game: lists the backend's quiz games (quizzes.GAMES), each once."""
    import quizzes
    assert [k for k, _ in games.QUIZ_GAMES] == list(quizzes.GAMES)

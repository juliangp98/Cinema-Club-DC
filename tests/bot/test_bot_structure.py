"""The bot is split by feature (bot/features/*); each module registers its
persistent buttons and background loops for setup_hook to start. Nothing may
be left out — an unregistered button stops working after a restart, an
unregistered loop never runs."""
import inspect

from discord.ext import tasks
from discord.ui import DynamicItem

import bot  # noqa: F401 — loads every feature
from features import shared, chat, alerts, schedule, threads, profile, polls, admin, games, club

FEATURES = (shared, chat, alerts, schedule, threads, profile, polls, admin, games, club)


def test_every_button_and_loop_is_registered():
    items = {obj for m in FEATURES for obj in vars(m).values()
             if inspect.isclass(obj) and issubclass(obj, DynamicItem) and obj is not DynamicItem and obj.__module__ == m.__name__}
    loops = {obj for m in FEATURES for name, obj in vars(m).items() if isinstance(obj, tasks.Loop)}
    assert items and set(shared._registry['items']) == items
    assert loops and set(shared._registry['loops']) == loops
    assert len(shared._registry['items']) == len(items)            # each once


def test_every_command_is_on_the_tree():
    names = {c.name for c in shared.client.tree.get_commands()}
    assert {'showtimes', 'rsvp', 'discuss', 'profile', 'poll', 'play', 'llm', 'help', 'quote'} <= names
    assert len(names) == 21

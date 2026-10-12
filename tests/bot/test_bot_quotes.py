"""/quote add · edit · find · remove and /wisdom, over the seeded list of
built-in quotes."""
import asyncio
import types

import pytest

from helpers import patch_bot_api, setup_db

HOME = 1000
ALIEN = 'In space, no one can hear you scream.'


def member(uid, name, admin=False):
    return types.SimpleNamespace(id=uid, name=name, display_name=name, mention=f'<@{uid}>',
                                 display_avatar=types.SimpleNamespace(url=f'https://cdn/{uid}.png'),
                                 guild_permissions=types.SimpleNamespace(manage_guild=admin))


ANA, BEN, MOD = member(9201, 'Ana'), member(9202, 'Ben'), member(9203, 'Mod', admin=True)


class Interaction:
    """Records (kind, ephemeral, content, embed-or-modal)."""
    def __init__(self, u, guild_id=HOME):
        self.log, self.user, self.guild_id, self.channel_id = [], u, guild_id, 42
        self.namespace = types.SimpleNamespace()
        outer = self

        class R:
            async def defer(self, ephemeral=False, **k):
                outer.log.append(('defer', ephemeral, None, None))

            async def send_message(self, content=None, ephemeral=False, embed=None, **k):
                outer.log.append(('reply', ephemeral, content, embed))

            async def send_modal(self, modal):
                outer.log.append(('modal', None, None, modal))

            def is_done(self):
                return False

        class F:
            async def send(self, content=None, ephemeral=False, embed=None, **k):
                outer.log.append(('followup', ephemeral, content, embed))
        self.response, self.followup = R(), F()

    def last(self):
        return self.log[-1]


def run(coro):
    return asyncio.run(coro)


def submit(modal, user, text=None, movie=None, character=None, guild_id=HOME):
    for field, value in (('text', text), ('movie', movie), ('character', character)):
        if value is not None:
            getattr(modal, field)._value = value
    it = Interaction(user, guild_id)
    run(modal.on_submit(it))
    return it.last()


def new_modal(bot, user, guild_id=HOME):
    """A /quote form, made where discord.py needs it: inside an event loop."""
    async def make():
        return bot.QuoteModal(bot.discord_identity(Interaction(user, guild_id)))
    return run(make())


def call(command, user, **kw):
    it = Interaction(user)
    run(command.callback(it, **kw))
    return it.last()


@pytest.fixture
def bot():
    setup_db()
    b = patch_bot_api()
    b._quote_cache.update(texts=[], fetched=-1e9)
    b.movies_channel = lambda: types.SimpleNamespace(guild=types.SimpleNamespace(id=HOME))
    return b


@pytest.fixture
def seeded(bot):
    run(bot.seed_quotes())
    return bot


def add_quote(bot):
    """Ana adds "Mein Führer! I can walk!" (Dr. Strangelove); returns its #."""
    it = Interaction(ANA)
    run(bot.quote_add.callback(it))
    content = submit(it.last()[3], ANA, text='  Mein Führer! I can walk!  ', movie='Dr. Strangelove', character='Dr. Strangelove')[2]
    return int(content.split('**#')[1].split('**')[0]), content


def test_seeding_the_built_in_quotes(bot):
    assert run(bot.random_quote()) in bot.quotes.QUOTES                       # before seeding: the built-in list
    run(bot.seed_quotes())
    rows = run(bot.api.get('/api/internal/quotes'))
    assert len(rows) == 302
    alien = next(r for r in rows if r['text'] == ALIEN)
    assert alien['movie'] == 'Alien' and alien['character'] == 'tagline'      # sources kept
    run(bot.seed_quotes())
    assert len(run(bot.api.get('/api/internal/quotes'))) == 302                # again: no-op


def test_adding_a_quote(seeded):
    it = Interaction(ANA)
    run(seeded.quote_add.callback(it))
    modal = it.last()[3]
    assert it.last()[0] == 'modal' and modal.movie.required and modal.character.required is False
    kind, ephemeral, content, _ = submit(modal, ANA, text='  Mein Führer! I can walk!  ', movie='Dr. Strangelove',
                                         character='Dr. Strangelove')
    assert ephemeral and content.startswith('Added ✓') and 'Mein Führer! I can walk!' in content    # trimmed
    assert '*Dr. Strangelove (Dr. Strangelove)*' in content
    picks = {run(seeded.random_quote()) for _ in range(400)}
    assert 'Mein Führer! I can walk!' in picks or len(seeded._quote_cache['texts']) == 303          # /wisdom can draw it


def test_duplicates_and_strangers_are_refused(seeded):
    new_id, _ = add_quote(seeded)
    content = submit(new_modal(seeded, BEN), BEN, text='mein führer! I CAN WALK!', movie='x')[2]
    assert f'already in the list (#{new_id})' in content                     # any capitalization
    stranger = member(9300, 'Stranger')
    content = submit(new_modal(seeded, stranger, None), stranger, text='A brand new line', movie='Some Film', guild_id=None)[2]
    assert content == seeded.NO_ACCOUNT_MSG


def test_the_quote_picker(seeded):
    new_id, _ = add_quote(seeded)
    ac = run(seeded.quote_autocomplete(Interaction(BEN), ''))
    assert ac[0].value == str(new_id)                                        # newest first
    ac = run(seeded.quote_autocomplete(Interaction(BEN), 'gin joints'))
    assert 'gin joints' in ac[0].name and len(ac[0].name) <= 100              # searches the text
    assert any(c.value == str(new_id) for c in run(seeded.quote_autocomplete(Interaction(BEN), 'Strangelove')))   # and the movie


def test_anyone_can_correct_a_source(seeded):
    new_id, _ = add_quote(seeded)
    it = Interaction(BEN)
    run(seeded.quote_edit.callback(it, quote=str(new_id)))
    modal = it.last()[3]
    assert modal.text.default == 'Mein Führer! I can walk!' and modal.movie.default == 'Dr. Strangelove'    # prefilled
    content = submit(modal, BEN, text='Mein Führer! I can walk!',
                     movie='Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb', character='Dr. Strangelove')[2]
    assert content.startswith('Updated ✓') and 'Learned to Stop Worrying' in content
    assert call(seeded.quote_edit, BEN, quote='not-a-number')[2] == 'Pick a quote from the list.'


def test_finding_quotes(seeded):
    add_quote(seeded)
    _, ephemeral, _, emb = call(seeded.quote_find, BEN, search='Jaws')
    assert ephemeral and 'Jaws' in emb.description and "You're gonna need a bigger boat." in emb.description
    assert 'added by Ana' in call(seeded.quote_find, BEN, search='Strangelove')[3].description
    assert 'No quotes match' in call(seeded.quote_find, BEN, search='zzzz-nothing')[2]


def test_who_can_remove_a_quote(seeded):
    new_id, _ = add_quote(seeded)
    alien = next(r for r in run(seeded.api.get('/api/internal/quotes')) if r['text'] == ALIEN)
    assert call(seeded.quote_remove, BEN, quote=str(new_id))[2] == 'Only Ana or a server admin can remove that one.'
    assert 'the original list or a server admin' in call(seeded.quote_remove, BEN, quote=str(alien['id']))[2]
    assert call(seeded.quote_remove, ANA, quote=str(new_id))[2] == f'Removed quote #{new_id}.'          # your own
    assert call(seeded.quote_remove, MOD, quote=str(alien['id']))[2] == f"Removed quote #{alien['id']}."  # admins: any
    assert "isn't in the list anymore" in call(seeded.quote_remove, MOD, quote=str(alien['id']))[2]
    rows = run(seeded.api.get('/api/internal/quotes'))
    assert len(rows) == 301 and all(r['id'] not in (new_id, alien['id']) for r in rows)
    seeded._quote_cache.update(texts=[], fetched=-1e9)
    assert ALIEN not in {run(seeded.random_quote()) for _ in range(400)}       # /wisdom stops drawing it

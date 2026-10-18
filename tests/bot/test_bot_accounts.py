"""Discord members need no site account: /rsvp, /watch and /profile make
one on first use (in the club's server), and its name follows Discord."""
import asyncio
import types

import pytest
from discord import app_commands

from helpers import patch_bot_api, setup_db

HOME = 1000
Choice = app_commands.Choice


class Channel:
    id = 42
    guild = types.SimpleNamespace(id=HOME)

    def __init__(self):
        self.sent = []

    async def send(self, content=None, embed=None, **kw):
        self.sent.append((content, embed))


def user(uid, name, nick=None):
    return types.SimpleNamespace(id=uid, name=name, display_name=nick or name, mention=f'<@{uid}>',
                                 display_avatar=types.SimpleNamespace(url=f'https://cdn.discordapp.com/{uid}.png'))


class Interaction:
    """Records (kind, ephemeral, content, embed, view-or-modal)."""
    def __init__(self, u, guild_id=HOME, **ns):
        self.log, self.user, self.guild_id = [], u, guild_id
        self.channel, self.channel_id = Channel(), 42
        self.namespace = types.SimpleNamespace(**ns)
        outer = self

        class R:
            async def defer(self, ephemeral=False, **k):
                outer.log.append(('defer', ephemeral, None, None, None))

            async def send_message(self, content=None, ephemeral=False, embed=None, **k):
                outer.log.append(('reply', ephemeral, content, embed, None))

            async def edit_message(self, embed=None, view=None, **k):
                outer.log.append(('edit', None, None, embed, view))

            async def send_modal(self, modal):
                outer.log.append(('modal', None, None, None, modal))

            def is_done(self):
                return any(e[0] in ('defer', 'reply', 'edit', 'modal') for e in outer.log)

        class F:
            async def send(self, content=None, ephemeral=False, embed=None, view=None, **k):
                outer.log.append(('followup', ephemeral, content, embed, view))
        self.response, self.followup = R(), F()

    async def edit_original_response(self, embed=None, view=None, **k):     # the edit after a defer
        self.log.append(('edit', None, None, embed, view))

    def last(self):
        return self.log[-1]


ZOE = user(9101, 'zoe_k', 'Zoe')


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def bot():
    """The bot against the backend; a screening to RSVP to."""
    import sqlite3
    import os
    setup_db()
    b = patch_bot_api()
    b.movies_channel = lambda: Channel()
    shows = run(b.api.get('/api/internal/showtimes', group_id=1, limit=1))
    sid = str(shows[0]['id']) if shows else str(sqlite3.connect(os.environ['DATABASE_URL'].replace('sqlite:///', ''))
                                                 .execute('select id from showtime limit 1').fetchone()[0])
    b.test_showtime = sid
    b.test_title = shows[0]['movie']['title'] if shows else 'SIRÂT'
    return b


@pytest.fixture
def zoe(bot):
    """Zoe has used /rsvp and added a film with /watch (so she has an account)."""
    run(bot.rsvp.callback(Interaction(ZOE), showtime=bot.test_showtime))
    run(bot.watch.callback(Interaction(ZOE), action=Choice(name='Add', value='add'), title=bot.test_title))
    return bot


def test_from_a_dm_without_an_account(bot):
    it = Interaction(user(9999, 'stranger'), guild_id=None)
    run(bot.rsvp.callback(it, showtime=bot.test_showtime))
    assert it.last()[2] == bot.NO_ACCOUNT_MSG


def test_rsvp_in_the_server_needs_no_account(bot):
    it = Interaction(ZOE)
    run(bot.rsvp.callback(it, showtime=bot.test_showtime))
    post = next(x for x in it.log if x[0] == 'followup' and x[1] is False)
    assert '<@9101> is going to' in post[2]                                   # public, no linking needed
    assert it.last()[1] is True and 'log whether you made it' in it.last()[2]  # first Going: asked privately


def test_watch_add_and_show(bot):
    run(bot.rsvp.callback(Interaction(ZOE), showtime=bot.test_showtime))
    it = Interaction(ZOE)
    run(bot.watch.callback(it, action=Choice(name='Add', value='add'), title=bot.test_title))
    assert any('is watching for' in (x[2] or '') for x in it.log)
    assert it.last()[1] is True and 'books (or announces)' in it.last()[2]     # first add: asked privately
    it = Interaction(ZOE)
    run(bot.watch.callback(it, action=Choice(name='Show', value='show')))
    assert 'Zoe' in (it.last()[3].title or '')                                # under her Discord name


def test_own_profile_card(zoe):
    it = Interaction(ZOE)
    run(zoe.profile.callback(it))
    _, ephemeral, _, emb, view = it.last()
    assert ephemeral and emb.title == '🎬 Zoe' and isinstance(view, zoe.ProfileView)
    assert any(f.name == 'Watchlist' and f.value == '1 films' for f in emb.fields)
    assert 'sign in' in (emb.footer.text or '').lower()                       # Discord-only: the site is optional
    assert len(view.genres.options) == 22 and view.genres.max_values == 22


def test_choosing_genres(zoe):
    it = Interaction(ZOE)
    run(zoe.profile.callback(it))
    view = it.last()[4]
    view.genres._values = ['horror', 'science fiction']
    view.genres._selected_values = ['horror', 'science fiction']
    comp = Interaction(ZOE)
    run(view.on_genres(comp))
    kind, _, _, emb, view2 = comp.last()
    assert kind == 'edit' and 'Horror, Sci-fi' in emb.fields[0].value
    assert {o.value for o in view2.genres.options if o.default} == {'horror', 'science fiction'}


def test_editing_bio_and_letterboxd(zoe):
    it = Interaction(ZOE)
    run(zoe.profile.callback(it))
    btn = Interaction(ZOE)
    run(it.last()[4].edit_text.callback(btn))
    modal = btn.last()[4]
    assert btn.last()[0] == 'modal' and isinstance(modal, zoe.ProfileModal)
    modal.bio._value, modal.letterboxd._value = 'midnight movie goblin', 'zoe_k'
    sub = Interaction(ZOE)
    run(modal.on_submit(sub))
    emb = sub.last()[3]
    assert emb.description == 'midnight movie goblin' and any(f.name == 'Letterboxd' and 'zoe_k' in f.value for f in emb.fields)


def test_other_peoples_profiles(zoe):
    it = Interaction(user(1, 'admin'))
    run(zoe.profile.callback(it, member=ZOE))
    _, ephemeral, _, emb, view = it.last()
    assert emb.title == '🎬 Zoe' and ephemeral and emb.url.endswith('/people/' + str(emb.url.rsplit('/', 1)[1]))
    labels = [getattr(getattr(i, 'item', i), 'label', None) for i in view.children]   # no editing someone else's:
    assert labels == ['🎞️ History', '📋 Watchlist', '🤝 Compare', '🍿 Give kernels', 'Profile on the site']
    it = Interaction(ZOE)
    run(zoe.profile.callback(it, member=user(7777, 'nobody', 'Nobody')))
    assert it.last()[2] == "Nobody hasn't used Cinema Club yet."


def test_the_name_follows_the_server_nickname(zoe):
    it = Interaction(user(9101, 'zoe_k', 'Zoe K.'))
    run(zoe.profile.callback(it))
    assert it.last()[3].title == '🎬 Zoe K.'

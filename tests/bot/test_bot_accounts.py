"""bot_accounts"""
from helpers import H, client, Checks, WORK


def test_bot_accounts():
    checks = Checks()
    check = checks.check
    import asyncio, os, sys, types
    import bot                          # never calls client.run — no Discord connection
    from helpers import patch_bot_api, setup_db
    setup_db()
    patch_bot_api()
    from discord import app_commands
    Choice = app_commands.Choice
    HOME = 1000

    class Channel:
        id = 42
        guild = types.SimpleNamespace(id=HOME)
        def __init__(self): self.sent = []
        async def send(self, content=None, embed=None, **kw): self.sent.append((content, embed))
    bot.movies_channel = lambda: Channel()

    def user(uid, name, nick=None):
        return types.SimpleNamespace(id=uid, name=name, display_name=nick or name, mention=f'<@{uid}>',
                                     display_avatar=types.SimpleNamespace(url=f'https://cdn.discordapp.com/{uid}.png'))

    class Interaction:
        def __init__(self, u, guild_id=HOME, **ns):
            self.log, self.user, self.guild_id = [], u, guild_id
            self.channel = Channel(); self.channel_id = 42
            self.namespace = types.SimpleNamespace(**ns); outer = self
            class R:
                async def defer(self, ephemeral=False, **k): outer.log.append(('defer', ephemeral, None, None, None))
                async def send_message(self, content=None, ephemeral=False, embed=None, **k): outer.log.append(('reply', ephemeral, content, embed, None))
                async def edit_message(self, embed=None, view=None, **k): outer.log.append(('edit', None, None, embed, view))
                async def send_modal(self, modal): outer.log.append(('modal', None, None, None, modal))
                def is_done(self): return False
            class F:
                async def send(self, content=None, ephemeral=False, embed=None, view=None, **k): outer.log.append(('followup', ephemeral, content, embed, view))
            self.response, self.followup = R(), F()
        def last(self): return self.log[-1]


    async def main():
        zoe = user(9101, 'zoe_k', 'Zoe')
        shows = await bot.api.get('/api/internal/showtimes', group_id=1, limit=1)
        sid = str(shows[0]['id']) if shows else None
        if not sid:   # no future showings in this copy: use any showtime id via search
            import sqlite3; sid = str(sqlite3.connect(os.environ['DATABASE_URL'].replace('sqlite:///', '')).execute('select id from showtime limit 1').fetchone()[0])

        print('--- /rsvp + /watch with no site account ---')
        it = Interaction(user(9999, 'stranger'), guild_id=None)
        await bot.rsvp.callback(it, showtime=sid)
        check('from a DM with no account: told to use the server first', it.last()[2] == bot.NO_ACCOUNT_MSG, it.last())
        it = Interaction(zoe)
        await bot.rsvp.callback(it, showtime=sid)
        post = next((x for x in it.log if x[0] == 'followup' and x[1] is False), None)
        check('in the server: RSVP posts publicly, no linking needed', post and '<@9101> is going to' in post[2], it.log)
        check('first Going: asked privately about "Did you make it?" DMs', it.last()[1] is True
              and 'log whether you made it' in it.last()[2], it.last())
        it = Interaction(zoe)
        await bot.watch.callback(it, action=Choice(name='Add', value='add'), title=shows[0]['movie']['title'] if shows else 'SIRÂT')
        check('/watch add works', any('is watching for' in (x[2] or '') for x in it.log), it.log)
        check('first watchlist add: asked privately how to hear about it', it.last()[1] is True
              and 'books (or announces)' in it.last()[2], it.last())
        it = Interaction(zoe)
        await bot.watch.callback(it, action=Choice(name='Show', value='show'))
        emb = it.last()[3]
        check('/watch show lists it under her Discord name', emb is not None and 'Zoe' in (emb.title or ''), emb and emb.title)

        print('--- /profile ---')
        it = Interaction(zoe)
        await bot.profile.callback(it)
        kind, eph, _, emb, view = it.last()
        check('own profile: private card with edit controls', eph and emb.title == '🎬 Zoe' and isinstance(view, bot.ProfileView))
        check('card shows watchlist + upcoming counts', any(f.name == 'Watchlist' and f.value == '1 films' for f in emb.fields), [(f.name, f.value) for f in emb.fields])
        check('Discord-only card suggests signing in on the site (optional)', 'sign in' in (emb.footer.text or '').lower())
        check('genre picker offers all genres', len(view.genres.options) == 20 and view.genres.max_values == 20)
        comp = Interaction(zoe)
        view.genres._values = ['horror', 'sci-fi']
        view.genres._selected_values = ['horror', 'sci-fi']
        try:
            type(view.genres).values = property(lambda s: s._values)
        except Exception:
            pass
        await view.on_genres(comp)
        kind, _, _, emb2, view2 = comp.last()
        check('choosing genres saves and refreshes the card', kind == 'edit' and 'Horror, Sci-Fi' in emb2.fields[0].value, emb2 and emb2.fields[0].value)
        check('…and the picker remembers them', {o.value for o in view2.genres.options if o.default} == {'horror', 'sci-fi'})
        btn = Interaction(zoe)
        await view2.edit_text.callback(btn)
        modal = btn.last()[4]
        check('edit button opens the bio/Letterboxd form', btn.last()[0] == 'modal' and isinstance(modal, bot.ProfileModal))
        modal.bio._value = 'midnight movie goblin'; modal.letterboxd._value = 'zoe_k'
        sub = Interaction(zoe)
        await modal.on_submit(sub)
        emb3 = sub.last()[3]
        check('form submit saves bio + Letterboxd', emb3.description == 'midnight movie goblin'
              and any(f.name == 'Letterboxd' and 'zoe_k' in f.value for f in emb3.fields), emb3 and emb3.description)
        it = Interaction(user(1, 'admin'))
        await bot.profile.callback(it, member=zoe)
        kind, eph, _, emb, view = it.last()
        check("someone else's profile: read-only card", emb.title == '🎬 Zoe' and view is None and eph)
        it = Interaction(zoe)
        await bot.profile.callback(it, member=user(7777, 'nobody', 'Nobody'))
        check("profile of someone who never used it", "Nobody hasn't used Cinema Club yet." == it.last()[2], it.last())

        print('--- nickname changes follow Discord ---')
        it = Interaction(user(9101, 'zoe_k', 'Zoe K.'))
        await bot.profile.callback(it)
        check('Discord-only name updates to the new server nickname', it.last()[3].title == '🎬 Zoe K.')
        await bot.api.close()
    asyncio.run(main())
    checks.done()

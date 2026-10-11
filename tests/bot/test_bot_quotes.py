"""bot_quotes"""
from helpers import H, client, Checks, WORK


def test_bot_quotes():
    checks = Checks()
    check = checks.check
    import asyncio, os, sys, types
    import bot                          # never calls client.run — no Discord connection
    from helpers import patch_bot_api, setup_db
    setup_db()
    patch_bot_api()
    HOME = 1000

    class Channel:
        guild = types.SimpleNamespace(id=HOME)
    bot.movies_channel = lambda: Channel()

    def member(uid, name, admin=False):
        return types.SimpleNamespace(id=uid, name=name, display_name=name, mention=f'<@{uid}>',
                                     display_avatar=types.SimpleNamespace(url=f'https://cdn/{uid}.png'),
                                     guild_permissions=types.SimpleNamespace(manage_guild=admin))

    class Interaction:
        def __init__(self, u, guild_id=HOME):
            self.log, self.user, self.guild_id, self.channel_id = [], u, guild_id, 42
            self.namespace = types.SimpleNamespace(); outer = self
            class R:
                async def defer(self, ephemeral=False, **k): outer.log.append(('defer', ephemeral, None, None))
                async def send_message(self, content=None, ephemeral=False, embed=None, **k): outer.log.append(('reply', ephemeral, content, embed))
                async def send_modal(self, modal): outer.log.append(('modal', None, None, modal))
                def is_done(self): return False
            class F:
                async def send(self, content=None, ephemeral=False, embed=None, **k): outer.log.append(('followup', ephemeral, content, embed))
            self.response, self.followup = R(), F()
        def last(self): return self.log[-1]


    async def submit(modal, user, text=None, movie=None, character=None, guild_id=HOME):
        if text is not None: modal.text._value = text
        if movie is not None: modal.movie._value = movie
        if character is not None: modal.character._value = character
        it = Interaction(user, guild_id)
        await modal.on_submit(it)
        return it.last()

    async def main():
        ana, ben, mod = member(9201, 'Ana'), member(9202, 'Ben'), member(9203, 'Mod', admin=True)
        print('--- seeding ---')
        before = await bot.random_quote()
        check('before seeding: falls back to the built-in list', before in bot.quotes.QUOTES)
        await bot.seed_quotes()
        rows = await bot.api.get('/api/internal/quotes')
        check('seeds all 302 built-in quotes', len(rows) == 302, len(rows))
        alien = next(r for r in rows if r['text'] == 'In space, no one can hear you scream.')
        check('silent sources kept (movie + character from the comments)', alien['movie'] == 'Alien' and alien['character'] == 'tagline', alien)
        await bot.seed_quotes()
        check('seeding again is a no-op', len(await bot.api.get('/api/internal/quotes')) == 302)

        print('--- /quote add ---')
        it = Interaction(ana); await bot.quote_add.callback(it)
        modal = it.last()[3]
        check('add opens the form (quote, movie, optional character)', it.last()[0] == 'modal' and modal.character.required is False and modal.movie.required)
        kind, eph, content, _ = await submit(modal, ana, text='  Mein Führer! I can walk!  ', movie='Dr. Strangelove', character='Dr. Strangelove')
        check('saves, trimmed, privately confirmed with its source', eph and content.startswith('Added ✓') and 'Mein Führer! I can walk!' in content
              and '*Dr. Strangelove (Dr. Strangelove)*' in content, content)
        new_id = int(content.split('**#')[1].split('**')[0])
        picks = {await bot.random_quote() for _ in range(400)}
        check('cache refreshed: new line can be drawn by /wisdom', 'Mein Führer! I can walk!' in picks or len(bot._quote_cache['texts']) == 303)
        kind, eph, content, _ = await submit(bot.QuoteModal(bot.discord_identity(Interaction(ben))), ben, text='mein führer! I CAN WALK!', movie='x')
        check('duplicate (any capitalization) is refused, naming the existing #', f'already in the list (#{new_id})' in content, content)
        kind, eph, content, _ = await submit(bot.QuoteModal(bot.discord_identity(Interaction(member(9300, 'Stranger'), None))), member(9300, 'Stranger'),
                                             text='A brand new line', movie='Some Film', guild_id=None)
        check('from a DM with no account: told to use the server first', content == bot.NO_ACCOUNT_MSG, content)

        print('--- /quote edit ---')
        ac = await bot.quote_autocomplete(Interaction(ben), '')
        check('autocomplete (nothing typed) lists newest first', ac and ac[0].value == str(new_id), [c.name for c in ac[:2]])
        ac = await bot.quote_autocomplete(Interaction(ben), 'gin joints')
        check('autocomplete searches the text', ac and 'gin joints' in ac[0].name and len(ac[0].name) <= 100, [c.name for c in ac])
        ac = await bot.quote_autocomplete(Interaction(ben), 'Strangelove')
        check('…and the movie', any(c.value == str(new_id) for c in ac))
        it = Interaction(ben); await bot.quote_edit.callback(it, quote=str(new_id))
        modal = it.last()[3]
        check('edit form is prefilled', modal.text.default == 'Mein Führer! I can walk!' and modal.movie.default == 'Dr. Strangelove')
        kind, eph, content, _ = await submit(modal, ben, text='Mein Führer! I can walk!', movie='Dr. Strangelove or: How I Learned to Stop Worrying and Love the Bomb', character='Dr. Strangelove')
        check('anyone can correct the source', content.startswith('Updated ✓') and 'Learned to Stop Worrying' in content, content)
        it = Interaction(ben); await bot.quote_edit.callback(it, quote='not-a-number')
        check('edit with a typed (non-picked) value: asks to pick from the list', it.last()[2] == 'Pick a quote from the list.')

        print('--- /quote find ---')
        it = Interaction(ben); await bot.quote_find.callback(it, search='Jaws')
        emb = it.last()[3]
        check('find: private results with sources', it.last()[1] and 'Jaws' in emb.description and "You're gonna need a bigger boat." in emb.description)
        it = Interaction(ben); await bot.quote_find.callback(it, search='Strangelove')
        check('find shows who added it', 'added by Ana' in it.last()[3].description)
        it = Interaction(ben); await bot.quote_find.callback(it, search='zzzz-nothing')
        check('find with no matches', 'No quotes match' in it.last()[2])

        print('--- /quote remove ---')
        it = Interaction(ben); await bot.quote_remove.callback(it, quote=str(new_id))
        check("someone else's quote: refused, says who can remove it", it.last()[2] == 'Only Ana or a server admin can remove that one.', it.last())
        it = Interaction(ben); await bot.quote_remove.callback(it, quote=str(alien['id']))
        check('original-list quote: only admins', 'the original list or a server admin' in it.last()[2], it.last())
        it = Interaction(ana); await bot.quote_remove.callback(it, quote=str(new_id))
        check('author can remove their own', it.last()[2] == f'Removed quote #{new_id}.')
        it = Interaction(mod); await bot.quote_remove.callback(it, quote=str(alien['id']))
        check('server admin can remove any quote', it.last()[2] == f"Removed quote #{alien['id']}.")
        it = Interaction(mod); await bot.quote_remove.callback(it, quote=str(alien['id']))
        check('removing twice: already gone', "isn't in the list anymore" in it.last()[2])
        rows = await bot.api.get('/api/internal/quotes')
        check('removed quotes leave the live list', len(rows) == 301 and all(r['id'] not in (new_id, alien['id']) for r in rows), len(rows))
        picks = {await bot.random_quote() for _ in range(400)}
        check('…and /wisdom stops drawing them', 'In space, no one can hear you scream.' not in picks)
        await bot.api.close()
    asyncio.run(main())
    checks.done()

"""/poll make end to end (run via run_bot_inprocess.py with seed_bot_r6b.py)."""
from helpers import H, client, Checks, WORK


def test_bot_poll_make():
    checks = Checks()
    check = checks.check
    # ── seed ──
    import sys, json
    from app import app, db, migrate, User, GroupMembership
    import ai
    from fake_groq import Fake
    with app.app_context():
        db.create_all(); migrate()
        for did, name, role in (('6201', 'Orga', 'organizer'), ('6202', 'Memb', 'member')):
            u = User(discord_user_id=did, name=name, is_active=True); db.session.add(u); db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role=role))
        db.session.commit()
    fake = Fake(['qwen/qwen3-32b']); ai._client = fake
    fake.reply = lambda m, msgs, kw: 'ok' if msgs[-1]['content'].endswith('weekend?') else json.dumps(
        {'title': 'Spookiest picks', 'poll_type': 'standard', 'scoring_mode': 'ranked',
         'categories': [{'title': 'Scariest', 'options': ['Hausu', 'Suspiria', 'The Thing']}], 'notes': ''})
    from helpers import patch_bot_api, all_linked_present
    patch_bot_api()
    all_linked_present()   # R6a.1: they're all in the club's server
    import asyncio, re, types
    import bot, discord
    from app import app, Poll, DiscordPost
    class Interaction:
        def __init__(self, uid):
            self.log, self.guild_id, self.channel_id = [], None, 1
            self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', display_avatar=None)
            outer = self
            class R:
                async def defer(self, **k): outer.log.append(('defer', k))
            class F:
                async def send(self, content=None, embed=None, view=None, ephemeral=False, **k): outer.log.append(('send', content, embed, view, ephemeral))
            self.response, self.followup = R(), F()
        @property
        def last(self): return self.log[-1]
    async def main():
        it = Interaction(6201); await bot.poll_make.callback(it, request='spookiest Halloween movies')
        _, content, embed, view, eph = it.last
        items = [getattr(c, 'item', c) for c in view.children]
        check('organizer gets a private draft preview', eph and embed.title == '📝 Draft: Spookiest picks'
              and embed.fields[0].name == 'Scariest' and 'Hausu' in embed.fields[0].value and 'not posted yet' in embed.footer.text)
        check('Create now + Open in editor', items[0].custom_id.startswith('polldraft:create:') and items[1].url.endswith(
              '/polls/new?draft=' + items[0].custom_id.split(':')[-1]))
        btn = await bot.DraftCreateButton.from_custom_id(None, None, re.fullmatch(r'polldraft:create:(?P<id>[0-9]+)', items[0].custom_id))
        it2 = Interaction(6201); await btn.callback(it2)
        with app.app_context():
            p = Poll.query.filter_by(title='Spookiest picks').first()
            ann = DiscordPost.query.filter_by(kind='poll', ref_id=p.id).first() if p else None
        check('Create now opens the poll and queues its announcement', p and p.status == 'open' and ann and 'is open' in it2.last[1])
        it3 = Interaction(6201); await btn.callback(it3)
        check('…only once', 'Already created' in it3.last[1])
        it4 = Interaction(6202); await bot.poll_make.callback(it4, request='comfort movies')
        check("members are told it's for organizers", 'organizers and admins' in it4.last[1], it4.last[1])
    asyncio.run(main())
    checks.done()

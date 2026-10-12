"""R6a.1 in the bot: it reports who's in the server, and members who aren't are
only ever counted (run via run_bot_inprocess.py with seed_bot_r6_discord.py)."""
from helpers import H, client, Checks, WORK


def test_bot_membership():
    checks = Checks()
    check = checks.check
    # ── seed ──
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, GroupMembership, Showtime, Movie, Theatre, RSVP, Poll, PollCategory,
                     PollOption, PollVote)
    S = WORK
    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        ana = User(email='ana@b6d.test', name='Ana', is_active=True, discord_user_id='8801')
        bo = User(email='bo@b6d.test', name='Bo', is_active=True)                       # site only
        cy = User(email='cy@b6d.test', name='Cy', is_active=True, discord_user_id='8803')  # linked, not in the server
        db.session.add_all([ana, bo, cy]); db.session.flush()
        for u in (ana, bo, cy):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        m = Movie(title='OMEGA FILM'); db.session.add(m); db.session.flush()
        s = Showtime(movie_id=m.id, theatre_id=th.id,
                     start_time=(datetime.now() + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0))
        db.session.add(s); db.session.flush()
        for u in (ana, bo, cy):
            db.session.add(RSVP(user_id=u.id, showtime_id=s.id, group_id=1, status='going'))
        # A scored poll Bo won: he's first on the leaderboard, Ana second.
        p = Poll(group_id=1, created_by=ana.id, title='Omega poll', poll_type='prediction', scoring_mode='single', status='scored')
        db.session.add(p); db.session.flush()
        cat = PollCategory(poll_id=p.id, title='Winner'); db.session.add(cat); db.session.flush()
        right, wrong = PollOption(category_id=cat.id, text='Right'), PollOption(category_id=cat.id, text='Wrong')
        db.session.add_all([right, wrong]); db.session.flush()
        cat.correct_option_id = right.id
        db.session.add_all([PollVote(category_id=cat.id, user_id=bo.id, option_id=right.id, confidence=1),
                            PollVote(category_id=cat.id, user_id=ana.id, option_id=wrong.id, confidence=1)])
        db.session.commit()
        open(f'{S}/r6dids.txt', 'w').write(f'{s.id} {ana.id} {bo.id}')
    from helpers import patch_bot_api
    patch_bot_api()
    import asyncio, types
    import bot, embeds
    from app import app, db, DiscordServerMember
    S = WORK
    SID, ANA, BO = map(int, open(f'{S}/r6dids.txt').read().split())

    class Interaction:
        def __init__(self, uid, guild_id=None):
            self.log, self.guild_id, self.channel_id = [], guild_id, 1
            self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', display_avatar=None,
                                              mention=f'<@{uid}>')
            outer = self
            class R:
                async def defer(self, **k): outer.log.append(('defer', k))
            class F:
                async def send(self, content=None, embed=None, view=None, ephemeral=False, **k): outer.log.append(('send', content, embed, view, ephemeral))
            self.response, self.followup = R(), F()
        @property
        def last(self): return self.log[-1]

    member = lambda i, is_bot=False, gid=900: types.SimpleNamespace(id=i, bot=is_bot, guild=types.SimpleNamespace(id=gid))
    class Guild:
        def __init__(self, members, chunked=True, fail=False):
            self.id, self.members, self.chunked, self.fail, self.chunk_calls = 900, members, chunked, fail, 0
        async def chunk(self):
            self.chunk_calls += 1
            if self.fail:
                raise RuntimeError('gateway hiccup')
            self.chunked = True
    guild = Guild([member(8801), member(4242, is_bot=True), member(5555)])
    bot.movies_channel = lambda: types.SimpleNamespace(guild=guild)
    def present():
        with app.app_context():
            return sorted(r.discord_user_id for r in DiscordServerMember.query)

    async def main():
        print('--- member sync ---')
        check('the bot asks for the members intent', bot.intents.members is True)
        await bot.sync_members()
        check('whole list sent (bots left out)', present() == ['5555', '8801'], present())
        await bot.member_changed(member(8803), 'joined')
        check('a join is reported right away', '8803' in present())
        await bot.member_changed(member(8803), 'left')
        await bot.member_changed(member(7777, gid=123), 'joined')
        check('a leave too; other servers are ignored', present() == ['5555', '8801'], present())
        nonlocal guild
        guild = Guild([member(8801)], chunked=False, fail=True)
        await bot.sync_members()
        check("member list not loaded and can't be fetched: no partial list is sent", guild.chunk_calls == 1 and present() == ['5555', '8801'])
        guild = Guild([member(8801)], chunked=False)
        await bot.sync_members()
        check('…fetched first when it can be', guild.chunk_calls == 1 and present() == ['8801'])

        print("--- who's going ---")
        it = Interaction(8801); await bot.whosgoing.callback(it, days=7)
        text = ' '.join(f.value for f in it.last[2].fields)
        check("/whosgoing: Ana by name, Bo and Cy only counted", 'Ana' in text and '+2 on the site' in text
              and 'Bo' not in text and 'Cy' not in text, text)
        it = Interaction(8801, guild_id=900)
        await bot.rsvp.callback(it, showtime=str(SID), status=None)
        reply = next((x[1] for x in it.log if x[0] == 'send' and 'Going (' in (x[1] or '')), '')
        check('/rsvp reply: same', 'Going (3): Ana · +2 on the site' in reply, it.log)

        print('--- leaderboard ---')
        it = Interaction(8801); await bot.leaderboard.callback(it)
        e = it.last[2]
        check('Bo (first, site only) is left out; Ana keeps her real place', 'Bo' not in e.description and '🥇' not in e.description
              and 'Ana' in e.description and 'on the site' in e.footer.text, (e.description, e.footer.text))

        print('--- rendering ---')
        card = {'title': 'X', 'start_time': '2026-10-10T20:00:00', 'theatre': 'AFI', 'site_path': '/x',
                'going': [{'name': 'Ana', 'discord_user_id': '8801'}], 'going_more': 2, 'maybe': [], 'maybe_more': 1}
        d = embeds.thread_card_embed(card).description
        check('thread card: names + counts', '**Going:** <@8801> · +2 on the site' in d and '**Maybe:** 1 on the site' in d, d)
        inv = {'by': None, 'note': None, 'card': {**card, 'going': [{'name': 'Ana'}]}, 'started': False}
        check('invite from someone who left: unsigned', embeds.invite_message(inv) == "🍿 Who's in?"
              and '**Going:** Ana · +2 on the site' in embeds.invite_embed(inv).description)
        res = embeds.poll_results_embed({'poll_id': 1, 'title': 'P', 'voters': 2,
                                         'top': [{'name': None, 'kernels': 3, 'correct': 3}, {'name': 'Ana', 'kernels': 1, 'correct': 1}]})
        check('poll results: unnamed winner, real medals', res.description.startswith('🥇 *a member on the site*') and '🥈 **Ana**' in res.description,
              res.description)
        digest = {'group_name': 'C', 'whos_going': [{'title': 'X', 'start_time': '2026-10-10T20:00:00', 'theatre': 'AFI',
                                                      'going': ['Ana'], 'going_more': 2}],
                  'plans': [], 'rare': [], 'opening': [], 'last_chance': [], 'open_polls': [], 'recap': {'poll': {'title': 'P', 'winner': None, 'kernels': 4}},
                  'watchlist': [{'title': 'Y', 'start_time': '2026-10-10T20:00:00', 'theatre': 'AFI', 'planned': False,
                                 'watchers': [{'watchlist_id': 1, 'name': 'Ana', 'discord_user_id': '8801', 'fresh': True}],
                                 'more': 2, 'quiet_ids': [5, 6]}]}
        content, embed, tagged, _ = embeds.digest_message(digest, tag_watchers=True)
        fields = {f.name: f.value for f in embed.fields}
        check("digest: who's going + watchlists count the rest", 'Ana · +2 on the site' in fields["🎟️ Who's going"]
              and '<@8801> · +2 on the site' in fields['👀 On your watchlists'], fields)
        check('…pings only Ana; the quiet ones are still marked (for the email)', content.count('<@') == 1 and sorted(tagged) == [1, 5, 6], (content, tagged))
        check("…last week's winner unnamed", 'P: a member on the site (4 🍿)' in fields['📊 Last week'])
        _, _, tagged, _ = embeds.digest_message(digest)
        check('a manual digest marks nobody', tagged == [])

    asyncio.run(main())
    checks.done()

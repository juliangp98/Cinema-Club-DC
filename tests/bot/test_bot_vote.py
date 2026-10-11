"""/vote ballots end to end (run via run_bot_inprocess.py with seed_bot_phase9.py)."""
from helpers import H, client, Checks, WORK


def test_bot_vote():
    checks = Checks()
    check = checks.check
    # ── seed ──
    from app import app, db, migrate, User, GroupMembership, Poll, PollCategory, PollOption, PollVote, ActivityEvent, Group
    with app.app_context():
        db.create_all(); migrate()
        Poll.query.filter_by(group_id=1).delete()        # a clean slate in the server's group
        db.session.commit()
        for did, name in (('9101', 'Vee'), ('9102', 'Wes')):
            u = User(discord_user_id=did, name=name, is_active=True); db.session.add(u); db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        lone = User(discord_user_id='9109', name='Lone', is_active=True); db.session.add(lone); db.session.flush()
        other = Group(name='Elsewhere', slug='elsewhere-9', is_public=False); db.session.add(other); db.session.flush()
        db.session.add(GroupMembership(user_id=lone.id, group_id=other.id, status='active'))
        creator = User.query.filter_by(discord_user_id='9101').first()

        def poll(title, mode, cats, status='open', group_id=1):
            p = Poll(group_id=group_id, created_by=creator.id, title=title, scoring_mode=mode, status=status)
            db.session.add(p); db.session.flush()
            for i, (ct, opts) in enumerate(cats):
                c = PollCategory(poll_id=p.id, title=ct, sort_order=i); db.session.add(c); db.session.flush()
                for j, t in enumerate(opts):
                    db.session.add(PollOption(category_id=c.id, text=t, sort_order=j))
            db.session.flush()
            return p
        poll('Quick picks', 'single', [('Best Picture', ['SIRÂT', 'HAMNET', 'SINNERS']),
                                       ('Best Score', ['A', 'B']), ('Best Short', ['X', 'Y'])])
        poll('Oscar stakes', 'confidence', [('Best Actress', ['Rose', 'Jessie']),
                                            ('Everything', [f'Nominee {n}' for n in range(1, 31)])])
        poll('Top 3 of the year', 'ranked', [('Films', ['One', 'Two', 'Three', 'Four'])])
        done = poll('Last year', 'single', [('Best Picture', ['Anora', 'Brutalist'])], status='scored')
        cat = done.categories[0]
        cat.correct_option_id = cat.options[0].id
        db.session.add(PollVote(category_id=cat.id, user_id=creator.id, option_id=cat.options[1].id))
        db.session.commit()
    from helpers import patch_bot_api
    patch_bot_api()
    import asyncio, re, types
    import bot, discord
    from app import app, db, Poll, ActivityEvent


    with app.app_context():
        PID = {p.title: p.id for p in Poll.query.filter_by(group_id=1)}

    class Interaction:
        def __init__(self, uid, values=None):
            self.log, self.guild_id, self.channel_id = [], None, 1
            self.data = {'values': values} if values is not None else {}
            self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', mention=f'<@{uid}>',
                                              display_avatar=types.SimpleNamespace(url='https://cdn/x.png'))
            outer = self
            class R:
                async def defer(self, ephemeral=False, thinking=False, **k): outer.log.append(('defer', ephemeral))
                async def send_message(self, content=None, ephemeral=False, view=None, embed=None, **k):
                    outer.log.append(('reply', ephemeral, content, embed, view))
            class F:
                async def send(self, content=None, ephemeral=False, embed=None, view=None, **k):
                    outer.log.append(('followup', ephemeral, content, embed, view))
            self.response, self.followup = R(), F()
        async def edit_original_response(self, embed=None, view=None, **k):
            self.log.append(('edit', None, None, embed, view))
        @property
        def last(self): return self.log[-1]

    state = {}   # the ballot message as Discord would show it: (embed, view)
    def items(view): return [getattr(c, 'item', c) for c in view.children]
    def find(view, act, **want):
        for it in items(view):
            m = re.fullmatch(bot.VOTE_ID, it.custom_id or '')
            if m and m['act'] == act and all(int(m[k]) == v for k, v in want.items()):
                return it
        return None

    async def click(uid, item, values=None):
        """Rebuild the component from its custom id (as after a restart) and fire it."""
        m = re.fullmatch(bot.VOTE_ID, item.custom_id)
        cls = bot.VoteSelect if m['kind'] == 's' else bot.VoteButton
        comp = await cls.from_custom_id(None, None, m)
        it = Interaction(uid, values)
        await comp.callback(it)
        kind, eph, content, embed, view = it.last
        if embed is not None:
            state[uid] = (embed, view)
        return it

    def desc(uid): return state[uid][0].description
    def view(uid): return state[uid][1]

    def limits_ok(v):
        rows = {}
        for it in items(v):
            rows.setdefault(it.row, []).append(it)
            if len(it.custom_id) > 100: return False
            if isinstance(it, discord.ui.Select):
                if not 1 <= len(it.options) <= 25 or any(len(o.label) > 100 for o in it.options): return False
                if len(rows[it.row]) > 1: return False
            elif len(it.label) > 80: return False
        return len(rows) <= 5 and all(len(r) <= 5 for r in rows.values())

    async def main():
        VEE, WES, LONE = 9101, 9102, 9109
        print('--- /vote and /polls ---')
        it = Interaction(VEE); await bot.vote.callback(it)
        kind, eph, content, _, v = it.last
        check('/vote with several open polls: private "which poll?" with one Vote button each', eph and content == 'Which poll?'
              and sorted(c.item.custom_id for c in v.children) == sorted(f'vote:b:open:{PID[t]}:0:0:0' for t in ('Quick picks', 'Oscar stakes', 'Top 3 of the year')))
        it = Interaction(VEE); await bot.polls.callback(it)
        check('/polls lists open polls with Vote buttons', len(it.last[4].children) == 3 and 'Tap **Vote**' in it.last[2])
        choices = await bot.vote_poll_autocomplete(Interaction(VEE), '')
        check('autocomplete: open polls first, then results', choices[-1].name.startswith('🏆') and len(choices) == 4, [c.name for c in choices])

        print('--- single-pick ballot ---')
        it = Interaction(VEE); await bot.vote.callback(it, poll=str(PID['Quick picks']))
        kind, eph, _, emb, v = it.last
        state[VEE] = (emb, v)
        check('opens privately on the first category', kind == 'followup' and eph and '### Best Picture' in emb.description
              and '0/3 answered' in emb.description and 'Pick yours to see how everyone voted' in emb.description, emb.description)
        pick = find(v, 'pick')
        check('nominee dropdown + jump + Prev/Next/Next unanswered', [o.label for o in pick.options] == ['SIRÂT', 'HAMNET', 'SINNERS']
              and find(v, 'jump') and find(v, 'nav', arg=0) and find(v, 'nav', arg=1) and find(v, 'nav', arg=2), [i.custom_id for i in items(v)])
        check('component limits respected', limits_ok(v))
        await click(VEE, pick, [pick.options[1].value])
        check('pick saves and auto-advances to the next category', '### Best Score' in desc(VEE) and '1/3 answered' in desc(VEE)
              and 'Saved **HAMNET** for Best Picture' in desc(VEE), desc(VEE))
        await click(VEE, find(view(VEE), 'pick'), [find(view(VEE), 'pick').options[0].value])
        await click(VEE, find(view(VEE), 'pick'), [find(view(VEE), 'pick').options[1].value])
        check('last pick: all answered', 'All 3 categories answered' in desc(VEE) and '3/3 answered' in desc(VEE), desc(VEE))
        jump = find(view(VEE), 'jump')
        check('jump list marks answered categories', all(str(o.emoji) == '✅' for o in jump.options), [str(o.emoji) for o in jump.options])
        await click(VEE, jump, ['0'])
        check('after picking, the split shows (with your pick marked)', 'How everyone voted' in desc(VEE) and '👉 HAMNET — 100%' in desc(VEE), desc(VEE))
        await click(VEE, find(view(VEE), 'clear'))
        check('Clear pick clears it', 'No pick yet' in desc(VEE) and 'Pick cleared' in desc(VEE) and '2/3 answered' in desc(VEE), desc(VEE))
        it = Interaction(WES); await bot.vote.callback(it, poll=str(PID['Quick picks']))
        check("another member's ballot is their own (no split before they pick)", '0/3 answered' in it.last[3].description
              and 'How everyone voted' not in it.last[3].description)

        print('--- confidence ballot ---')
        it = Interaction(VEE); await bot.vote.callback(it, poll=str(PID['Oscar stakes'])); state[VEE] = it.last[3:5]
        conf = find(view(VEE), 'conf')
        check('stake dropdown waits for a pick', conf is not None and conf.disabled)
        await click(VEE, find(view(VEE), 'pick'), [find(view(VEE), 'pick').options[0].value])
        check('pick stays on the page and asks for the stake', '### Best Actress' in desc(VEE) and 'now set how sure' in desc(VEE)
              and not find(view(VEE), 'conf').disabled, desc(VEE))
        await click(VEE, find(view(VEE), 'conf'), ['8'])
        check('stake saved', '**Rose** · 8 🍿' in desc(VEE), desc(VEE))
        await click(VEE, find(view(VEE), 'pick'), [find(view(VEE), 'pick').options[1].value])
        check('changing the pick keeps the stake', '**Jessie** · 8 🍿' in desc(VEE) and 'same stake' in desc(VEE), desc(VEE))
        await click(VEE, find(view(VEE), 'nav', arg=1))
        p1 = find(view(VEE), 'pick')
        more = find(view(VEE), 'page')
        check('30 nominees: first 25 in the dropdown + a "More nominees" button', len(p1.options) == 25 and more and '26–30' in more.label
              and limits_ok(view(VEE)), more and more.label)
        await click(VEE, more)
        p2 = find(view(VEE), 'pick')
        check('next page shows the rest', [o.label for o in p2.options] == [f'Nominee {n}' for n in range(26, 31)])
        await click(VEE, p2, [p2.options[2].value])
        check('picking from page 2 saves it', '**Nominee 28** · 1 🍿' in desc(VEE) and 'All 2 categories answered' not in desc(VEE)
              and '2/2 answered' in desc(VEE), desc(VEE))

        print('--- ranked ballot ---')
        it = Interaction(VEE); await bot.vote.callback(it, poll=str(PID['Top 3 of the year'])); state[VEE] = it.last[3:5]
        r1, r2, r3 = (find(view(VEE), 'rank', arg=r) for r in (1, 2, 3))
        check('three rank dropdowns with a "— none —" choice', r1 and r2 and r3 and r1.options[0].label == '— none —' and len(r1.options) == 5
              and limits_ok(view(VEE)))
        val = {o.label: o.value for o in r1.options}
        await click(VEE, r1, [val['One']]); await click(VEE, find(view(VEE), 'rank', arg=2), [val['Two']])
        check('ranks saved', '**1.** One  **2.** Two' in desc(VEE), desc(VEE))
        await click(VEE, find(view(VEE), 'rank', arg=2), [val['One']])
        check('moving a film to another rank moves it (no duplicates)', '**2.** One' in desc(VEE) and 'Two' not in desc(VEE).split('Your pick:')[1].split('\n')[0], desc(VEE))
        await click(VEE, find(view(VEE), 'rank', arg=2), ['0'])
        check('"— none —" on the last rank clears the category', 'No pick yet' in desc(VEE), desc(VEE))

        print('--- results, closing, access ---')
        it = Interaction(VEE); await bot.vote.callback(it, poll=str(PID['Last year']))
        emb, v = it.last[3], it.last[4]
        check('scored poll: winner, ❌ on your pick, kernels, your place; no dropdowns',
              '🏆 Anora' in emb.description and '❌ Brutalist' in emb.description and emb.fields and '#1 of 1' in emb.fields[0].value
              and not find(v, 'pick'), (emb.description, [f.value for f in emb.fields]))
        it = Interaction(VEE); await bot.vote.callback(it, poll=str(PID['Quick picks'])); state[VEE] = it.last[3:5]
        with app.app_context():
            p = db.session.get(Poll, PID['Quick picks']); p.status = 'closed'; db.session.commit()
        await click(VEE, find(view(VEE), 'pick'), [find(view(VEE), 'pick').options[0].value])
        check('voting closed mid-ballot: shown read-only with a note', 'Voting just closed' in desc(VEE) and not find(view(VEE), 'pick'), desc(VEE))
        it = Interaction(LONE); await bot.vote.callback(it, poll=str(PID['Oscar stakes']))
        check("someone outside the poll's group is told so", "group you're not in" in (it.last[2] or ''), it.last)
        it = Interaction(5555); await bot.vote.callback(it, poll=str(PID['Oscar stakes']))
        check('no account (outside the server) -> the usual hint', it.last[2] == bot.NO_ACCOUNT_MSG, it.last)

        print('--- #movies posts ---')
        sent = []
        class Channel:
            async def send(self, content=None, embed=None, view=None, **k): sent.append((content, embed, view))
        bot.movies_channel = lambda: Channel()
        with app.app_context():
            for kind, gid in (('poll_opened', 1), ('poll_scored', 1), ('poll_opened', 999)):
                db.session.add(ActivityEvent(kind=kind, payload_json=__import__('json').dumps(
                    {'poll_id': PID['Oscar stakes'], 'group_id': gid, 'title': 'Oscar stakes', 'scoring_mode': 'confidence',
                     'categories': 2, 'creator': 'Vee', 'voters': 2,
                     'top': [{'name': 'Vee', 'discord_user_id': '9101', 'kernels': 9, 'correct': 2}, {'name': 'Ann', 'discord_user_id': None, 'kernels': 3, 'correct': 1}]})))
            db.session.commit()
        await bot.announce_loop.coro()
        check('only this server\'s polls are posted (2 of 3 events)', len(sent) == 2, sent)
        check('new poll: embed + one Vote button', 'New poll: Oscar stakes' in sent[0][1].title and sent[0][2]
              and items(sent[0][2])[0].custom_id == f"vote:b:open:{PID['Oscar stakes']}:0:0:0")
        check('results: medals, mention for linked members, name otherwise', '🥇 <@9101> — **9 🍿**' in sent[1][1].description
              and '🥈 **Ann**' in sent[1][1].description, sent[1][1].description)
        with app.app_context():
            check('events marked announced', ActivityEvent.query.filter(ActivityEvent.kind.like('poll_%'), ActivityEvent.announced_at.is_(None)).count() == 0)
        await bot.api.close()
    asyncio.run(main())
    checks.done()

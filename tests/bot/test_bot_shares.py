"""The bot's share loop against a fake #movies channel (run via run_bot_inprocess.py with seed_bot_r3d.py)."""
from helpers import H, client, Checks, WORK


def test_bot_shares():
    checks = Checks()
    check = checks.check
    # ── seed ──
    from datetime import datetime, timedelta
    from app import app, db, migrate, User, GroupMembership, Showtime, Movie, Theatre
    S = WORK
    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='suns').first()
        us = [User(email=f'b{i}@r3d.test', name=n, is_active=True, discord_user_id=str(8800 + i)) for i, n in enumerate(['Ana', 'Bo'])]
        db.session.add_all(us); db.session.flush()
        for u, role in zip(us, ('admin', 'member')):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role=role))
        ids = []
        for i, t in enumerate(['PSYCHO', 'THE BIRDS']):
            m = Movie(title=t, poster_url='https://img.test/p.jpg'); db.session.add(m); db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=(datetime.now() + timedelta(days=2 + i)).replace(hour=21, minute=30, second=0, microsecond=0),
                         format_label='35mm' if i == 0 else None)
            db.session.add(s); db.session.flush(); ids.append(s.id)
        db.session.commit()
        open(f'{S}/r3dids.txt', 'w').write(' '.join(map(str, [us[0].id, us[1].id, *ids])))
    from helpers import patch_bot_api, all_linked_present
    patch_bot_api()
    all_linked_present()   # R6a.1: they're all in the club's server
    import asyncio, itertools, types
    from datetime import datetime, timedelta
    import bot, discord
    from app import app, db, DiscordPost

    S = WORK
    ANA, BO, S1, S2 = map(int, open(f'{S}/r3dids.txt').read().split())

    ids = itertools.count(91000)
    class NotFoundResp:
        status, reason = 404, 'Not Found'
    class Msg:
        def __init__(self, ch, content, embed, view):
            self.id, self.channel = next(ids), ch
            self.content, self.embed, self.view, self.deleted = content, embed, view, False
            self.jump_url = f'https://discord.com/channels/900/{ch.id}/{self.id}'
    class Partial:
        def __init__(self, ch, mid): self.ch, self.mid = ch, mid
        async def edit(self, content=None, embed=None, view=None, allowed_mentions=None):
            m = self.ch.msgs.get(self.mid)
            if not m or m.deleted: raise discord.NotFound(NotFoundResp(), 'gone')
            m.content, m.embed, m.view = content, embed, view
            self.ch.log.append(('edit', self.mid, allowed_mentions))
        async def delete(self):
            m = self.ch.msgs.get(self.mid)
            if not m or m.deleted: raise discord.NotFound(NotFoundResp(), 'gone')
            m.deleted = True; self.ch.log.append(('delete', self.mid))
    class Channel:
        id = 901
        def __init__(self): self.msgs, self.log = {}, []
        async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
            m = Msg(self, content, embed, view if view is not discord.utils.MISSING else None)
            self.msgs[m.id] = m; self.log.append(('send', m.id, allowed_mentions)); return m
        def get_partial_message(self, mid): return Partial(self, mid)
    CH = Channel()
    bot.movies_channel = lambda: CH

    def client(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    ana, bo = client(ANA), client(BO)
    def due_now():
        with app.app_context():
            DiscordPost.query.filter_by(status='pending').filter(DiscordPost.kind == 'rsvp') \
                .update({'post_at': datetime.now() - timedelta(seconds=1)}); db.session.commit()
    def ids_of(view): return [getattr(c, 'item', c).custom_id for c in (view.children if view else [])]
    def last_msg(): return CH.msgs[max(CH.msgs)]

    async def main():
        tick = bot.share_loop.coro
        print('--- RSVPs ---')
        ana.put('/api/discord/prefs', json={'rsvp': 'always'})
        ana.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': 1})
        ana.post('/api/rsvp', json={'showtime_id': S2, 'status': 'maybe', 'group_id': 1})
        await tick()
        check('nothing posts during the batch window', CH.log == [])
        due_now(); await tick()
        m = last_msg()
        check('one post for both RSVPs, no pings', len(CH.msgs) == 1 and 'Ana' in m.content and 'has plans for 2 screenings' in m.content
              and 'PSYCHO' in m.content and '*(maybe)*' in m.content and '<@' not in m.content
              and CH.log[-1][2] is not None and CH.log[-1][2].users is False, m.content)
        check('a Going button per screening', ids_of(m.view) == [f'disc:rsvp:going:{S1}', f'disc:rsvp:going:{S2}'])
        st = ana.get(f'/api/showtimes/{S1}', query_string={'group_id': 1}).json
        check('the site links to it', st['discord']['my_share']['jump_url'] == m.jump_url)
        ana.post('/api/rsvp', json={'showtime_id': S2, 'status': 'not_going', 'group_id': 1})
        await tick()
        check('cancelled one → post edited to the other', CH.log[-1][0] == 'edit' and 'is going to **PSYCHO**' in m.content
              and 'BIRDS' not in m.content and ids_of(m.view) == [f'disc:rsvp:going:{S1}', f'disc:open:{S1}'], m.content)
        ana.post('/api/rsvp', json={'showtime_id': S1, 'status': None, 'group_id': 1})
        await tick()
        check('cancelled the last → post deleted', m.deleted and CH.log[-1][0] == 'delete')
        await tick()
        check('and left alone after', CH.log[-1][0] == 'delete' and sum(1 for x in CH.log if x[0] == 'delete') == 1)

        print("--- who's in? ---")
        r = bo.post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': S1, 'note': 'Drinks after?'}).json
        await tick()
        m = last_msg()
        check('invite card with Going / Maybe / Discuss / site link', "**Bo** is asking: who's in?" in m.content and m.embed.title == 'PSYCHO'
              and '> Drinks after?' in m.embed.description and ids_of(m.view)[:3] == [f'disc:rsvp:going:{S1}', f'disc:rsvp:maybe:{S1}', f'disc:open:{S1}'])
        ana.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going', 'group_id': 1})
        await tick()
        check('the card lists who answered (names, no mentions)', '**Going:** Ana' in m.embed.description and '<@' not in m.embed.description)
        CH.msgs[m.id].deleted = True          # someone deleted it in Discord
        bo.post('/api/rsvp', json={'showtime_id': S1, 'status': 'maybe', 'group_id': 1})
        await tick()
        st = bo.get(f'/api/showtimes/{S1}', query_string={'group_id': 1}).json
        check('deleted in Discord → stops tracking it', st['discord']['invite'] is None)

        print('--- polls ---')
        p = ana.post('/api/groups/1/polls', json={'title': 'Best of fall', 'announce': 'now',
                     'categories': [{'title': 'C', 'options': [{'text': 'x'}, {'text': 'y'}]}]}).json
        await tick()
        m = last_msg()
        check('announcement with a Vote button', m.embed.title == '🗳️ New poll: Best of fall' and ids_of(m.view) and ids_of(m.view)[0].startswith('vote:b:open:'))
        ana.put(f"/api/polls/{p['id']}", json={'status': 'closed'})
        await tick()
        check('closed → edited, no Vote button', m.embed.title.startswith('🔒 Voting closed') and m.view is None)
        cat = p['categories'][0]
        ana.post(f"/api/polls/{p['id']}/score", json={'winners': {str(cat['id']): cat['options'][0]['id']}, 'post_results': True})
        await tick()
        res = last_msg()
        check('results posted alongside', res.embed.title == '🏆 Results: Best of fall' and m.embed.description.startswith('Results are in'))
        ana.delete(f"/api/polls/{p['id']}")
        await tick()
        check('poll deleted → both posts deleted', m.deleted and res.deleted)

        print('--- start a thread ---')
        made = []
        async def fake_ensure(sid):
            made.append(sid); return types.SimpleNamespace(id=4444, jump_url='https://discord.com/channels/900/4444'), {}, True
        bot.ensure_thread = fake_ensure
        bo.post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': S2})
        await tick()
        check('the bot starts the thread', made == [S2])

    asyncio.run(main())
    checks.done()

"""Screening threads end to end against fake Discord objects (run via run_bot_inprocess.py)."""
from helpers import H, client, Checks, WORK


def test_bot_threads():
    checks = Checks()
    check = checks.check
    # ── seed ──
    from datetime import datetime, timedelta
    from app import app, db, migrate, User, GroupMembership, Showtime, Movie, Theatre, Message, RSVP
    with app.app_context():
        db.create_all(); migrate()
        now, utc = datetime.now(), datetime.utcnow()
        tid = Theatre.query.filter_by(slug='afi').first().id
        films = {t: Movie.query.filter_by(title=t).first().id for t in ('SIRÂT', 'HAMNET', 'CLOUD')}
        def show(t, days, fmt=None):
            s = Showtime(movie_id=films[t], theatre_id=tid, start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=2), format_label=fmt)
            db.session.add(s); db.session.flush(); return s
        s1, s2, past = show('SIRÂT', 2, '70mm'), show('HAMNET', 3), show('CLOUD', -1)
        ana = User(email='ana-t@test.dev', name='Ana', is_active=True, discord_user_id='1101',
                   avatar_url='https://cdn.discordapp.com/avatars/1101/a.png')
        bo = User(email='bo-t@test.dev', name='Discord Bo', is_active=True, discord_user_id='1102')   # only server members post
        db.session.add_all([ana, bo]); db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        for i in range(12):
            db.session.add(Message(user_id=(bo if i % 2 else ana).id, showtime_id=s1.id, group_id=1, body=f'old {i}',
                                   created_at=utc - timedelta(days=3) + timedelta(minutes=i)))
        db.session.add(RSVP(user_id=ana.id, showtime_id=past.id, group_id=1, status='going'))
        db.session.commit()
        open(f'{WORK}/p10ids.txt', 'w').write(
            f'{s1.id} {s2.id} {past.id} {ana.id} {bo.id}')
    from helpers import patch_bot_api, all_linked_present
    patch_bot_api()
    all_linked_present()   # R6a.1: they're all in the club's server
    import asyncio, itertools, types
    from datetime import timedelta
    import bot, discord
    from app import app, db, Message, ShowtimeThread, RSVP, User

    S = WORK
    S1, S2, PAST, ANA, BO = map(int, open(f'{S}/p10ids.txt').read().split())

    ids = itertools.count(70000)
    class Msg:
        def __init__(self, channel, content=None, embed=None, view=None, **k):
            self.id, self.channel, self.content, self.embed, self.view = next(ids), channel, content, embed, view
            self.edits, self.deleted = [], False
        async def create_thread(self, name, auto_archive_duration=None, **k):
            t = Thread(name, self, auto_archive_duration); THREADS[t.id] = t; return t
        async def edit(self, embed=None, view=None, **k): self.edits.append((embed, view))
        async def delete(self): self.deleted = True

    class Thread:
        def __init__(self, name, starter, archive):
            self.id, self.name, self.starter, self.archive = next(ids), name, starter, archive
            self.archived, self.sent, self.jump_url = False, [], f'https://discord.com/channels/900/{starter.id}'
            self.jump_url = f'https://discord.com/channels/900/{self.id}'
        async def send(self, content=None, **k): m = Msg(self, content); self.sent.append(('bot', content)); return m
        async def edit(self, archived=None, **k): self.archived = archived
        async def delete(self): THREADS.pop(self.id, None)

    class Webhook:
        def __init__(self): self.name, self.user, self.deleted = bot.WEBHOOK_NAME, types.SimpleNamespace(id=4242), []
        async def send(self, content, username=None, avatar_url=None, thread=None, wait=False, allowed_mentions=None):
            m = Msg(thread, content); thread.sent.append(('hook', username, avatar_url, content, m.id)); return m
        async def delete_message(self, mid, thread=None): self.deleted.append((mid, thread.id))

    class Channel:
        def __init__(self):
            self.id, self.guild, self.posts, self.hooks, self.forbid = 901, types.SimpleNamespace(id=900), [], [], False
            self.partials = {}
        async def send(self, content=None, embed=None, view=None, **k):
            m = Msg(self, content, embed, view); self.posts.append(m); return m
        async def webhooks(self):
            if self.forbid: raise discord.Forbidden(types.SimpleNamespace(status=403, reason='Forbidden'), 'Missing Permissions')
            return self.hooks
        async def create_webhook(self, name, reason=None):
            wh = Webhook(); self.hooks.append(wh); return wh
        def get_partial_message(self, mid):
            return next(p for p in self.posts if p.id == mid)

    THREADS, CH, OWNER_DMS = {}, Channel(), []
    bot.movies_channel = lambda: CH
    bot.client._connection.user = types.SimpleNamespace(id=4242)
    bot.client.get_channel = lambda i: THREADS.get(i)
    async def fetch_channel(i):
        if i in THREADS: return THREADS[i]
        raise discord.NotFound(types.SimpleNamespace(status=404, reason='Not Found'), 'Unknown Channel')
    bot.client.fetch_channel = fetch_channel
    async def dm_owner(text): OWNER_DMS.append(text)
    bot.dm_owner = dm_owner

    def member(uid, name):
        return types.SimpleNamespace(id=uid, name=name.lower(), display_name=name, mention=f'<@{uid}>', bot=False,
                                     display_avatar=types.SimpleNamespace(url=f'https://cdn.discordapp.com/avatars/{uid}/x.png'))
    class Interaction:
        def __init__(self, user, guild_id=900):
            self.user, self.guild_id, self.channel_id, self.log, self.modal = user, guild_id, 901, [], None
            outer = self
            class R:
                async def defer(self, ephemeral=False, thinking=False, **k): outer.log.append(('defer', ephemeral))
                async def send_modal(self, modal): outer.modal = modal
                async def send_message(self, content=None, ephemeral=False, **k): outer.log.append(('reply', ephemeral, content))
            class F:
                async def send(self, content=None, ephemeral=False, embed=None, view=None, **k):
                    outer.log.append(('followup', ephemeral, content, view))
            self.response, self.followup = R(), F()

    def site_comments(sid):
        with app.app_context():
            return [(m.body, m.source, m.discord_message_id) for m in Message.query.filter_by(showtime_id=sid, group_id=1).order_by(Message.created_at, Message.id)]
    def thread_for(sid):
        with app.app_context():
            t = ShowtimeThread.query.filter_by(showtime_id=sid, group_id=1).first()
            return THREADS.get(int(t.thread_id)) if t else None
    site = app.test_client()
    with site.session_transaction() as s: s['user_id'] = BO
    ana_site = app.test_client()
    with ana_site.session_transaction() as s: s['user_id'] = ANA

    async def main():
        print('--- "Start a Discord thread" on the site creates it ---')
        r = site.post('/api/messages', json={'showtime_id': S1, 'group_id': 1, 'body': 'Who is in for 70mm?'})
        await bot.discussion_loop.coro()
        check('a site comment alone never starts a thread (R3d)', CH.posts == [])
        site.post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': S1})
        await bot.share_loop.coro()
        await bot.discussion_loop.coro()
        card = CH.posts[0]
        t = thread_for(S1)
        check('one card post in #movies, with Going / Maybe / Open on the site', len(CH.posts) == 1 and card.embed.title == 'SIRÂT'
              and [getattr(c, 'item', c).label for c in card.view.children] == ['Going', 'Maybe', 'Open on the site'])
        check('thread under it, named for the screening, archives after a week', t and t.starter is card and t.name.startswith('SIRÂT · ')
              and t.name.endswith(' · AFI') and t.archive == 10080, t and t.name)
        hooks = [x for x in t.sent if x[0] == 'hook']
        check('intro line, then the last 10 site comments under their authors, then the new one', t.sent[0][0] == 'bot'
              and '12 comments, the last 10 below' in t.sent[0][1] and len(hooks) == 11
              and [h[3].split('\n')[0] for h in hooks[:10]] == [f'old {i}' for i in range(2, 12)]
              and hooks[-1][3] == 'Who is in for 70mm?' and ('bot', '-# ── new ──') in t.sent, t.sent[:2])
        check('copied comments show when they were written', hooks[0][3].endswith('· on the site') and '\n-# ' in hooks[0][3])
        check("Discord-linked members keep their avatar; names can't contain 'Discord'", hooks[0][1] == 'Ana'
              and hooks[0][2].startswith('https://cdn.discordapp.com/') and hooks[1][1] == 'Bo', (hooks[0][:3], hooks[1][:3]))
        check('every copy is linked to its site comment (no re-posting)', all(c[2] for c in site_comments(S1)[2:]) and
              bot.api is not None)
        n_before = len(t.sent)
        await bot.discussion_loop.coro()
        check('nothing posted twice', len(t.sent) == n_before)
        site.post('/api/messages', json={'showtime_id': S1, 'group_id': 1, 'body': 'Second thought'})
        await bot.discussion_loop.coro()
        check('later site comments go to the same thread, no new card', len(CH.posts) == 1 and t.sent[-1][3] == 'Second thought')

        print('--- Discord -> site ---')
        cy = member(1103, 'Cy')
        def dmsg(content, author=cy, webhook_id=None, mtype=discord.MessageType.default, atts=()):
            return types.SimpleNamespace(id=next(ids), author=author, webhook_id=webhook_id, channel=t, guild=CH.guild,
                                         type=mtype, content=content, clean_content=content, attachments=list(atts), mentions=[])
        m = dmsg("Count me in — I'll save seats", atts=[types.SimpleNamespace(url='https://cdn.discordapp.com/att/pic.png')])
        await bot.on_message(m)
        last = site_comments(S1)[-1]
        check('a message typed in the thread becomes a site comment (attachments as links)', last[0] == "Count me in — I'll save seats\nhttps://cdn.discordapp.com/att/pic.png"
              and last[1] == 'discord' and last[2] == str(m.id), last)
        with app.app_context():
            u = User.query.filter_by(discord_user_id='1103').first()
        check('…from a member with no site account (created on the spot)', u is not None and u.email is None)
        before = len(site_comments(S1))
        await bot.on_message(dmsg('echo', author=types.SimpleNamespace(id=4242, bot=True, name='bot')))
        await bot.on_message(dmsg('webhook copy', webhook_id=123))
        await bot.on_message(dmsg('', mtype=discord.MessageType.thread_created))
        check("the bot's own posts, webhooks and system messages are ignored", len(site_comments(S1)) == before)
        replies = []
        async def reply(*a, **k): replies.append(a)
        trig = dmsg('That 70mm IMAX print is gorgeous'); trig.reply = reply
        real_random = bot.random.random; bot.random.random = lambda: 0.0
        bot._trigger_cooldown.clear()
        await bot.on_message(trig)
        bot.random.random = real_random
        check('no ambient quotes inside screening threads', replies == [])
        edited = dmsg('Count me in — I will save four seats'); edited.id = m.id
        await bot.on_raw_message_edit(types.SimpleNamespace(channel_id=t.id, message=edited))
        check('editing in Discord updates the site copy', ('Count me in — I will save four seats', 'discord', str(m.id)) in site_comments(S1), site_comments(S1)[-3:])
        await bot.on_raw_message_delete(types.SimpleNamespace(channel_id=t.id, message_id=m.id))
        check('deleting in Discord removes it from the site', all(c[2] != str(m.id) for c in site_comments(S1)))
        await bot.on_raw_message_delete(types.SimpleNamespace(channel_id=555, message_id=999))
        check('deletes elsewhere are ignored', True)

        print('--- site delete -> Discord ---')
        with app.app_context():
            mine = Message.query.filter_by(showtime_id=S1, body='Second thought').first()
            mid_, did = mine.id, mine.discord_message_id
        site.delete(f'/api/messages/{mid_}')
        await bot.discussion_loop.coro()
        check('deleting your site comment removes its Discord copy', CH.hooks[0].deleted == [(int(did), t.id)], CH.hooks[0].deleted)

        print('--- card buttons ---')
        btn = await bot.ThreadRsvpButton.from_custom_id(None, None, {'status': 'going', 'sid': str(S1)})
        it = Interaction(member(1101, 'Ana')); await btn.callback(it)
        reply = next((x for x in it.log if len(x) > 2 and "You're going to" in (x[2] or '')), None)
        check('Going on the card RSVPs privately', reply and reply[1] and "You're going to **SIRÂT**" in reply[2], it.log)
        with app.app_context():
            t_row = ShowtimeThread.query.filter_by(showtime_id=S1).first(); t_row.card_refreshed_at -= timedelta(minutes=5); db.session.commit()
        await bot.discussion_loop.coro()
        check('the card refreshes with the new Going list', card.edits and '<@1101>' in card.edits[-1][0].description, card.edits)

        print('--- /discuss and the Discuss buttons ---')
        dee = member(1104, 'Dee')
        it = Interaction(dee); await bot.discuss.callback(it, showtime=str(S2), comment='First!')
        t2 = thread_for(S2)
        check('/discuss with a comment creates the thread and posts it under your name', t2 and t2.sent[-1][1] == 'Dee'
              and t2.sent[-1][2] == 'https://cdn.discordapp.com/avatars/1104/x.png' and t2.sent[-1][3] == 'First!'
              and 'Posted in the **HAMNET** thread' in it.log[-1][2], it.log[-1])
        check('no backfill intro when the site had no comments', not any(x[0] == 'bot' for x in t2.sent))
        c2 = site_comments(S2)
        check('…and it is on the site as your comment (deletable there)', c2 == [('First!', 'discord_bot', str(t2.sent[-1][4]))], c2)
        await bot.discussion_loop.coro()
        check('not echoed back into Discord', len(t2.sent) == 1)
        t2.archived = True
        it = Interaction(dee); await bot.discuss.callback(it, showtime=str(S2))
        check('/discuss without a comment on an archived thread reopens it and links it', not t2.archived
              and it.log[-1][2].startswith('💬 **HAMNET** discussion → https://discord.com/channels/900/'), it.log[-1])
        check('still one thread per screening', len(CH.posts) == 2)
        dbtn = await bot.DiscussButton.from_custom_id(None, None, {'sid': str(S2)})
        it = Interaction(dee, guild_id=None); await dbtn.callback(it)
        check('Discuss button opens a comment box', isinstance(it.modal, bot.DiscussModal))
        it.modal.comment._value = 'From the button'
        await it.modal.on_submit(it)
        check('…whose comment lands in the thread and on the site', t2.sent[-1][3] == 'From the button' and site_comments(S2)[-1][0] == 'From the button')
        it.modal.comment._value = ''
        it2 = Interaction(dee); it2.modal = None
        await bot.DiscussModal(S2).on_submit(it2)
        check('an empty comment just links the thread', 'discussion →' in it2.log[-1][2] and len(t2.sent) == 2)
        it = Interaction(member(1101, 'Ana')); await bot.rsvp.callback(it, showtime=str(S2))
        v = it.log[-1][3]
        check('/rsvp confirmation carries a Discuss button', v and getattr(v.children[0], 'item', v.children[0]).custom_id == f'disc:open:{S2}')
        att = await bot.AttendanceButton.from_custom_id(None, None, bot.ATTENDANCE_ID_RE.fullmatch(f'att:went:{PAST}'))
        class AttInteraction(Interaction):
            def __init__(self, user):
                super().__init__(user, guild_id=None); self.message = None
                outer = self
                async def edit_message(view=None, **k): outer.log.append(('edit', view))
                self.response.edit_message = edit_message
        it = AttInteraction(member(1101, 'Ana')); await att.callback(it)
        check('"Went" follow-up carries a Discuss button too', it.log[-1][3] and getattr(it.log[-1][3].children[0], 'item', None).custom_id == f'disc:open:{PAST}', it.log[-1])

        print('--- deleted threads, permissions ---')
        await bot.on_raw_thread_delete(types.SimpleNamespace(thread_id=t.id))
        THREADS.pop(t.id, None)
        site.post('/api/messages', json={'showtime_id': S1, 'group_id': 1, 'body': 'Anyone still going?'})
        await bot.discussion_loop.coro()
        check('a thread deleted in Discord: a comment alone does not restart it (R3d)', thread_for(S1) is None)
        site.post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': S1})
        await bot.share_loop.coro()
        await bot.discussion_loop.coro()
        t3 = thread_for(S1)
        check('…"Start a thread" makes a new one, with a fresh backfill incl. that comment', t3 and t3 is not t
              and t3.sent[0][0] == 'bot' and any(x[0] == 'hook' and x[3].startswith('Anyone still going?') for x in t3.sent),
              t3 and t3.sent[-3:])
        bot._webhook = None; CH.forbid = True
        site.post('/api/messages', json={'showtime_id': S1, 'group_id': 1, 'body': 'perm test'})
        await bot.discussion_loop.coro(); await bot.discussion_loop.coro()
        check('missing permissions: the owner is told once', len(OWNER_DMS) == 1 and 'Manage Webhooks' in OWNER_DMS[0], OWNER_DMS)
        it = Interaction(dee); await bot.discuss.callback(it, showtime=str(S1), comment='hello')
        check('…and members get a clear message', "aren't set up yet" in it.log[-1][2], it.log[-1])
        CH.forbid = False
        await bot.discussion_loop.coro()
        check('once fixed, the waiting comment goes through', t3.sent[-1][3] == 'perm test')
        await bot.api.close()
    asyncio.run(main())
    checks.done()

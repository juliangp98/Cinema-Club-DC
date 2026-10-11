"""bot_attendance"""
from helpers import H, client, Checks, WORK


def test_bot_attendance():
    checks = Checks()
    check = checks.check
    # ── seed ──
    from datetime import datetime, timedelta
    from app import app, db, migrate, User, GroupMembership, RSVP, Showtime, Movie, Theatre
    with app.app_context():
        db.create_all(); migrate()
        now = datetime.now()
        mid, tid = Movie.query.filter_by(title='SIRÂT').first().id, Theatre.query.filter_by(slug='afi').first().id
        mid2 = Movie.query.filter_by(title='HAMNET').first().id
        ids = []
        for m, days in ((mid, 2), (mid2, 1)):
            s = Showtime(movie_id=m, theatre_id=tid, start_time=now - timedelta(days=days),
                         end_time=now - timedelta(days=days) + timedelta(hours=2), format_label='70mm' if m == mid else None)
            db.session.add(s); db.session.flush(); ids.append(s.id)
        for uid, name in (('6601', 'Ana'), ('6603', 'Cal')):
            u = User(discord_user_id=uid, name=name, is_active=True); db.session.add(u); db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
            for sid in ids: db.session.add(RSVP(user_id=u.id, showtime_id=sid, group_id=1, status='going'))
        db.session.commit()
    from helpers import patch_bot_api, all_linked_present
    patch_bot_api()
    all_linked_present()   # R6a.1: they're all in the club's server
    import asyncio, os, sys, types
    from datetime import datetime as real_datetime
    import bot, discord                 # never calls client.run — no Discord connection

    HOUR = {'h': 12}
    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime.now(tz).replace(hour=HOUR['h'])
    bot.datetime = FakeDatetime

    class DMUser:
        def __init__(self, closed=False): self.sent, self.closed = [], closed
        async def send(self, content=None, view=None, **k):
            if self.closed:
                raise discord.Forbidden(types.SimpleNamespace(status=403, reason='Forbidden'), 'Cannot send messages to this user')
            self.sent.append((content, view))
    USERS = {6601: DMUser(), 6603: DMUser(closed=True)}
    async def fake_fetch_user(uid): return USERS[uid]
    bot.client.fetch_user = fake_fetch_user

    def as_message(view):
        """What Discord hands back for a sent view: rows of components."""
        rows = {}
        for item in view.children:
            rows.setdefault(item.row, []).append(types.SimpleNamespace(custom_id=item.custom_id, label=getattr(item, 'item', item).label, style=getattr(item, 'item', item).style))
        return types.SimpleNamespace(components=[types.SimpleNamespace(children=rows[r]) for r in sorted(rows)])

    class Interaction:
        def __init__(self, uid, message=None):
            self.log, self.guild_id, self.channel_id, self.message = [], None, 1, message
            self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', mention=f'<@{uid}>',
                                              display_avatar=types.SimpleNamespace(url='https://cdn/x.png'))
            outer = self
            class R:
                async def defer(self, ephemeral=False, **k): outer.log.append(('defer', ephemeral, None, None, None))
                async def send_message(self, content=None, ephemeral=False, **k): outer.log.append(('reply', ephemeral, content, None, None))
                async def edit_message(self, view=None, **k): outer.log.append(('edit', None, None, None, view))
                def is_done(self): return True
            class F:
                async def send(self, content=None, ephemeral=False, embed=None, view=None, **k): outer.log.append(('followup', ephemeral, content, embed, view))
            self.response, self.followup = R(), F()


    async def main():
        print('--- DM prompts ---')
        HOUR['h'] = 23
        await bot.attendance_loop.coro()
        check('no DMs at night (11 PM ET)', not USERS[6601].sent)
        HOUR['h'] = 12
        await bot.attendance_loop.coro()
        content, view = USERS[6601].sent[-1]
        check('daytime: one private DM listing both screenings', len(USERS[6601].sent) == 1 and 'Did you make it?' in content
              and 'SIRÂT' in content and 'HAMNET' in content and '70mm' in content, content)
        ids = [c.custom_id for c in view.children]
        check('a Went / Didn\'t-go pair per screening, one row each', len(view.children) == 4
              and all(bot.ATTENDANCE_ID_RE.fullmatch(i) for i in ids) and {c.row for c in view.children} == {0, 1}, ids)
        check('button labels within Discord\'s 80-char limit', all(len(getattr(c, 'item', c).label) <= 80 for c in view.children))
        check('persistent: no timeout', view.timeout is None)
        await bot.attendance_loop.coro()
        check('never asked twice', len(USERS[6601].sent) == 1)

        print('--- answering in the DM ---')
        went_sid = int(ids[0].split(':')[2])
        button = await bot.AttendanceButton.from_custom_id(None, None, bot.ATTENDANCE_ID_RE.fullmatch(f'att:went:{went_sid}'))
        it = Interaction(6601, as_message(view))
        await button.callback(it)
        edit, follow = it.log[0], it.log[1]
        new_view = edit[4]
        labels = [getattr(c, 'item', c).label for c in new_view.children]
        check('answered screening becomes one disabled ✅ result, the other stays clickable',
              len(new_view.children) == 3 and labels[0].startswith('✅ Went · SIRÂT') and getattr(new_view.children[0], 'item', new_view.children[0]).disabled
              and all(not getattr(c, 'item', c).disabled for c in new_view.children[1:]), labels)
        check('"went" offers a link into that screening\'s discussion', follow[1] and f'showtime={went_sid}' in follow[2], follow)
        missed_sid = int(ids[2].split(':')[2])
        button2 = await bot.AttendanceButton.from_custom_id(None, None, bot.ATTENDANCE_ID_RE.fullmatch(f'att:missed:{missed_sid}'))
        it2 = Interaction(6601, as_message(new_view))
        await button2.callback(it2)
        final = [(getattr(c, 'item', c).label, getattr(c, 'item', c).disabled) for c in it2.log[0][4].children]
        check('second answer: both rows now show their result', final == [(labels[0], True), ("❌ Didn't go · HAMNET", True)], final)
        check('"didn\'t go" sends no extra message', len(it2.log) == 1)

        print('--- DMs closed ---')
        check('closed DMs: queued for their next command', '6603' in bot._dm_fallback)
        it = Interaction(6603)
        await bot.on_app_command_completion(it, None)
        kind, eph, content, _, v = it.log[-1]
        check('…asked privately right after it, with the same buttons', kind == 'followup' and eph and 'Did you make it?' in content and len(v.children) == 4)
        check('…only once', '6603' not in bot._dm_fallback)
        await bot.attendance_loop.coro()
        check('closed-DM members are marked asked too (no hourly retries)', '6603' not in bot._dm_fallback)

        print('--- /history ---')
        it = Interaction(6601)
        await bot.history.callback(it)
        emb = it.log[-1][3]
        check("own history: ✅ confirmed, missed one left out", emb and '✅ **SIRÂT**' in emb.description and 'HAMNET' not in emb.description,
              emb and emb.description)
        it = Interaction(6601)
        await bot.history.callback(it, member=types.SimpleNamespace(id=6603, display_name='Cal'))
        emb = it.log[-1][3]
        check("a member's history: unanswered RSVPs show as 🎟️", emb and emb.title == "🎞️ Cal's watch history" and '🎟️' in emb.description)
        it = Interaction(6601)
        await bot.history.callback(it, member=types.SimpleNamespace(id=7777, display_name='Nobody'))
        check('someone with no account', it.log[-1][2] == "Nobody hasn't been to anything with the club yet.", it.log[-1])
        await bot.api.close()
    asyncio.run(main())
    checks.done()

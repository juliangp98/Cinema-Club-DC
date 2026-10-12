"""The bot's "Did you make it?" DMs (for members who said yes): daytime
only, once, buttons that turn into results; members with DMs closed are
asked after their next command; /history."""
import asyncio
import types
from datetime import datetime as real_datetime, timedelta

import discord
import pytest

from helpers import all_linked_present, patch_bot_api, setup_db

OPTED_IN = '{"types": {"attendance": true}}'


class DMUser:
    def __init__(self, closed=False):
        self.sent, self.closed = [], closed

    async def send(self, content=None, view=None, **k):
        if self.closed:
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason='Forbidden'), 'Cannot send messages to this user')
        self.sent.append((content, view))


def as_message(view):
    """What Discord hands back for a sent view: rows of components."""
    rows = {}
    for item in view.children:
        it = getattr(item, 'item', item)
        rows.setdefault(item.row, []).append(types.SimpleNamespace(custom_id=item.custom_id, label=it.label, style=it.style))
    return types.SimpleNamespace(components=[types.SimpleNamespace(children=rows[r]) for r in sorted(rows)])


class Interaction:
    """Records (kind, ephemeral, content, embed, view)."""
    def __init__(self, uid, message=None):
        self.log, self.guild_id, self.channel_id, self.message = [], None, 1, message
        self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', mention=f'<@{uid}>',
                                          display_avatar=types.SimpleNamespace(url='https://cdn/x.png'))
        outer = self

        class R:
            async def defer(self, ephemeral=False, **k):
                outer.log.append(('defer', ephemeral, None, None, None))

            async def send_message(self, content=None, ephemeral=False, **k):
                outer.log.append(('reply', ephemeral, content, None, None))

            async def edit_message(self, view=None, **k):
                outer.log.append(('edit', None, None, None, view))

            def is_done(self):
                return True

        class F:
            async def send(self, content=None, ephemeral=False, embed=None, view=None, **k):
                outer.log.append(('followup', ephemeral, content, embed, view))
        self.response, self.followup = R(), F()


def label(c):
    return getattr(c, 'item', c).label


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def bot(monkeypatch):
    """Ana (DMs open) and Cal (DMs closed) both said yes to the DMs and were
    going to SIRÂT (70mm, 2 days ago) and HAMNET (yesterday)."""
    from app import app, db, User, GroupMembership, RSVP, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        now = real_datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        shows = []
        for title, days, fmt in (('SIRÂT', 2, '70mm'), ('HAMNET', 1, None)):
            s = Showtime(movie_id=Movie.query.filter_by(title=title).first().id, theatre_id=tid,
                         start_time=now - timedelta(days=days), end_time=now - timedelta(days=days) + timedelta(hours=2),
                         format_label=fmt)
            db.session.add(s)
            db.session.flush()
            shows.append(s.id)
        for uid, name in (('6601', 'Ana'), ('6603', 'Cal')):
            u = User(discord_user_id=uid, name=name, is_active=True, notify_prefs=OPTED_IN)
            db.session.add(u)
            db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
            for sid in shows:
                db.session.add(RSVP(user_id=u.id, showtime_id=sid, group_id=1, status='going'))
        db.session.commit()
    b = patch_bot_api()
    all_linked_present()
    b.users = {6601: DMUser(), 6603: DMUser(closed=True)}

    async def fetch_user(uid):
        return b.users[uid]
    b.client.fetch_user = fetch_user
    b._dm_fallback.clear()
    b.at_hour = lambda h: monkeypatch.setattr(b, 'datetime', type('Clock', (real_datetime,), {
        'now': classmethod(lambda cls, tz=None: real_datetime.now(tz).replace(hour=h))}))
    return b


@pytest.fixture
def asked(bot):
    """The loop ran at noon: Ana got her DM, Cal's DMs were closed."""
    bot.at_hour(12)
    run(bot.attendance_loop.coro())
    return bot


def test_no_dms_at_night(bot):
    bot.at_hour(23)
    run(bot.attendance_loop.coro())
    assert not bot.users[6601].sent


def test_one_private_dm_listing_both_screenings(asked):
    [(content, view)] = asked.users[6601].sent
    assert 'Did you make it?' in content and 'SIRÂT' in content and 'HAMNET' in content and '70mm' in content
    ids = [c.custom_id for c in view.children]
    assert len(view.children) == 4 and all(asked.ATTENDANCE_ID_RE.fullmatch(i) for i in ids)   # a pair per screening
    assert {c.row for c in view.children} == {0, 1}
    assert all(len(label(c)) <= 80 for c in view.children) and view.timeout is None              # persistent
    run(asked.attendance_loop.coro())
    assert len(asked.users[6601].sent) == 1                                                     # never asked twice


def answer(bot, status, sid, view):
    button = run(bot.AttendanceButton.from_custom_id(None, None, bot.ATTENDANCE_ID_RE.fullmatch(f'att:{status}:{sid}')))
    it = Interaction(6601, as_message(view))
    run(button.callback(it))
    return it


def test_answering_in_the_dm(asked):
    view = asked.users[6601].sent[0][1]
    ids = [c.custom_id for c in view.children]
    went_sid, missed_sid = int(ids[0].split(':')[2]), int(ids[2].split(':')[2])
    it = answer(asked, 'went', went_sid, view)
    edit, follow = it.log[0], it.log[1]
    new_view = edit[4]
    labels = [label(c) for c in new_view.children]
    first = getattr(new_view.children[0], 'item', new_view.children[0])
    assert len(new_view.children) == 3 and labels[0].startswith('✅ Went · SIRÂT') and first.disabled
    assert all(not getattr(c, 'item', c).disabled for c in new_view.children[1:])           # the other stays clickable
    assert follow[1] and f'showtime={went_sid}' in follow[2]                                 # "went": a link to discuss it
    it2 = answer(asked, 'missed', missed_sid, new_view)
    final = [(label(c), getattr(c, 'item', c).disabled) for c in it2.log[0][4].children]
    assert final == [(labels[0], True), ("❌ Didn't go · HAMNET", True)]
    assert len(it2.log) == 1                                                                 # "didn't go": nothing extra


def test_closed_dms_ask_after_the_next_command(asked):
    assert '6603' in asked._dm_fallback
    it = Interaction(6603)
    run(asked.on_app_command_completion(it, None))
    kind, ephemeral, content, _, view = it.log[-1]
    assert kind == 'followup' and ephemeral and 'Did you make it?' in content and len(view.children) == 4
    assert '6603' not in asked._dm_fallback                                                 # once
    run(asked.attendance_loop.coro())
    assert '6603' not in asked._dm_fallback                                                 # marked asked: no retries


def history(bot, member=None):
    it = Interaction(6601)
    run(bot.history.callback(it, member=member) if member else bot.history.callback(it))
    return it.log[-1]


def test_history(asked):
    view = asked.users[6601].sent[0][1]
    ids = [c.custom_id for c in view.children]
    answer(asked, 'went', int(ids[0].split(':')[2]), view)
    answer(asked, 'missed', int(ids[2].split(':')[2]), view)
    emb = history(asked)[3]
    assert '✅ **SIRÂT**' in emb.description and 'HAMNET' not in emb.description          # the missed one left out
    emb = history(asked, types.SimpleNamespace(id=6603, display_name='Cal'))[3]
    assert emb.title == "🎞️ Cal's watch history" and '🎟️' in emb.description            # unanswered RSVPs
    assert history(asked, types.SimpleNamespace(id=7777, display_name='Nobody'))[2] == "Nobody hasn't been to anything with the club yet."

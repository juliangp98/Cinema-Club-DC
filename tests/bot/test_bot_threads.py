"""Screening threads end to end against fake Discord objects: a thread made
on request with a card and a backfill of site comments, messages both ways,
edits and deletes, the card's buttons, /discuss, and recovering from a
deleted thread or missing permissions."""
import asyncio
import itertools
import types
from datetime import datetime, timedelta

import discord
import pytest

from helpers import all_linked_present, client, patch_bot_api, setup_db

_ids = itertools.count(70000)
THREADS = {}


class Msg:
    def __init__(self, channel, content=None, embed=None, view=None, **k):
        self.id, self.channel, self.content, self.embed, self.view = next(_ids), channel, content, embed, view
        self.edits, self.deleted = [], False

    async def create_thread(self, name, auto_archive_duration=None, **k):
        t = Thread(name, self, auto_archive_duration)
        THREADS[t.id] = t
        return t

    async def edit(self, embed=None, view=None, **k):
        self.edits.append((embed, view))

    async def delete(self):
        self.deleted = True


class Thread:
    def __init__(self, name, starter, archive):
        self.id, self.name, self.starter, self.archive = next(_ids), name, starter, archive
        self.archived, self.sent = False, []
        self.jump_url = f'https://discord.com/channels/900/{self.id}'

    async def send(self, content=None, **k):
        self.sent.append(('bot', content))
        return Msg(self, content)

    async def edit(self, archived=None, **k):
        self.archived = archived

    async def delete(self):
        THREADS.pop(self.id, None)


class Webhook:
    def __init__(self, name):
        self.name, self.user, self.deleted = name, types.SimpleNamespace(id=4242), []

    async def send(self, content, username=None, avatar_url=None, thread=None, wait=False, allowed_mentions=None):
        m = Msg(thread, content)
        thread.sent.append(('hook', username, avatar_url, content, m.id))
        return m

    async def delete_message(self, mid, thread=None):
        self.deleted.append((mid, thread.id))


class Channel:
    """#movies: its posts and webhooks; `forbid` takes away Manage Webhooks."""
    def __init__(self, hook_name):
        self.id, self.guild, self.posts, self.hooks, self.forbid, self.hook_name = 901, types.SimpleNamespace(id=900), [], [], False, hook_name

    async def send(self, content=None, embed=None, view=None, **k):
        m = Msg(self, content, embed, view)
        self.posts.append(m)
        return m

    async def webhooks(self):
        if self.forbid:
            raise discord.Forbidden(types.SimpleNamespace(status=403, reason='Forbidden'), 'Missing Permissions')
        return self.hooks

    async def create_webhook(self, name, reason=None):
        wh = Webhook(name)
        self.hooks.append(wh)
        return wh

    def get_partial_message(self, mid):
        return next(p for p in self.posts if p.id == mid)


def member(uid, name):
    return types.SimpleNamespace(id=uid, name=name.lower(), display_name=name, mention=f'<@{uid}>', bot=False,
                                 display_avatar=types.SimpleNamespace(url=f'https://cdn.discordapp.com/avatars/{uid}/x.png'))


class Interaction:
    """`log` items: ('defer', ephemeral), ('reply', ephemeral, content), ('followup', ephemeral, content, view)."""
    def __init__(self, user, guild_id=900):
        self.user, self.guild_id, self.channel_id, self.log, self.modal, self.message = user, guild_id, 901, [], None, None
        outer = self

        class R:
            async def defer(self, ephemeral=False, thinking=False, **k):
                outer.log.append(('defer', ephemeral))

            async def send_modal(self, modal):
                outer.modal = modal

            async def send_message(self, content=None, ephemeral=False, **k):
                outer.log.append(('reply', ephemeral, content))

            async def edit_message(self, view=None, **k):
                outer.log.append(('edit', view))

        class F:
            async def send(self, content=None, ephemeral=False, embed=None, view=None, **k):
                outer.log.append(('followup', ephemeral, content, view))
        self.response, self.followup = R(), F()


@pytest.fixture
def world(monkeypatch):
    """Ana (1101, Discord picture) and Bo ("Discord Bo", 1102) in the club.
    SIRÂT (70mm) in 2 days with 12 comments from before threads existed,
    HAMNET in 3 days, CLOUD yesterday (Ana went)."""
    from app import app, db, User, GroupMembership, Showtime, Movie, Theatre, Message, RSVP
    setup_db()
    with app.app_context():
        now, utc = datetime.now(), datetime.utcnow()
        tid = Theatre.query.filter_by(slug='afi').first().id
        films = {t: Movie.query.filter_by(title=t).first().id for t in ('SIRÂT', 'HAMNET', 'CLOUD')}

        def show(t, days, fmt=None):
            s = Showtime(movie_id=films[t], theatre_id=tid, start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=2), format_label=fmt)
            db.session.add(s)
            db.session.flush()
            return s
        s1, s2, past = show('SIRÂT', 2, '70mm'), show('HAMNET', 3), show('CLOUD', -1)
        ana = User(email='ana-t@test.dev', name='Ana', is_active=True, discord_user_id='1101',
                   avatar_url='https://cdn.discordapp.com/avatars/1101/a.png')
        bo = User(email='bo-t@test.dev', name='Discord Bo', is_active=True, discord_user_id='1102')
        db.session.add_all([ana, bo])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        for i in range(12):
            db.session.add(Message(user_id=(bo if i % 2 else ana).id, showtime_id=s1.id, group_id=1, body=f'old {i}',
                                   created_at=utc - timedelta(days=3) + timedelta(minutes=i)))
        db.session.add(RSVP(user_id=ana.id, showtime_id=past.id, group_id=1, status='going'))
        db.session.commit()
        ids = {'s1': s1.id, 's2': s2.id, 'past': past.id, 'ana': ana.id, 'bo': bo.id}
    bot = patch_bot_api()
    all_linked_present()
    THREADS.clear()
    ch, owner_dms = Channel(bot.WEBHOOK_NAME), []

    async def fetch_channel(i):
        if i in THREADS:
            return THREADS[i]
        raise discord.NotFound(types.SimpleNamespace(status=404, reason='Not Found'), 'Unknown Channel')

    async def dm_owner(text):
        owner_dms.append(text)
    monkeypatch.setattr(bot, 'movies_channel', lambda: ch)
    monkeypatch.setattr(bot, 'dm_owner', dm_owner)
    monkeypatch.setattr(bot.client._connection, 'user', types.SimpleNamespace(id=4242))
    monkeypatch.setattr(bot.client, 'get_channel', lambda i: THREADS.get(i))
    monkeypatch.setattr(bot.client, 'fetch_channel', fetch_channel)
    return types.SimpleNamespace(bot=bot, ch=ch, owner_dms=owner_dms, **ids)


def discussion(w):
    asyncio.run(w.bot.discussion_loop.coro())


def comment(w, body, sid=None):
    return client(w.bo).post('/api/messages', json={'showtime_id': sid or w.s1, 'group_id': 1, 'body': body})


def start_thread(w, sid):
    """"Start a Discord thread" on the site, then the bot's loops run."""
    client(w.bo).post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': sid})
    asyncio.run(w.bot.share_loop.coro())
    discussion(w)


def site_comments(sid):
    from app import app, Message
    with app.app_context():
        return [(m.body, m.source, m.discord_message_id)
                for m in Message.query.filter_by(showtime_id=sid, group_id=1).order_by(Message.created_at, Message.id)]


def thread_for(sid):
    from app import app, ShowtimeThread
    with app.app_context():
        t = ShowtimeThread.query.filter_by(showtime_id=sid, group_id=1).first()
        return THREADS.get(int(t.thread_id)) if t else None


def test_a_site_comment_alone_never_starts_a_thread(world):
    comment(world, 'Who is in for 70mm?')
    discussion(world)
    assert world.ch.posts == []


@pytest.fixture
def started(world):
    """Bo commented on SIRÂT and asked for a thread; the bot made it."""
    comment(world, 'Who is in for 70mm?')
    start_thread(world, world.s1)
    world.card, world.t = world.ch.posts[0], thread_for(world.s1)
    return world


def hooks(t):
    return [x for x in t.sent if x[0] == 'hook']


def test_one_card_in_movies_with_its_thread(started):
    card, t = started.card, started.t
    assert len(started.ch.posts) == 1 and card.embed.title == 'SIRÂT'
    assert [getattr(c, 'item', c).label for c in card.view.children] == ['Going', 'Maybe', 'Open on the site']
    assert t and t.starter is card and t.archive == 10080                                   # archives after a week
    assert t.name.startswith('SIRÂT · ') and t.name.endswith(' · AFI')


def test_the_thread_starts_with_the_last_ten_site_comments(started):
    t, hs = started.t, hooks(started.t)
    assert t.sent[0][0] == 'bot' and '12 comments, the last 10 below' in t.sent[0][1] and len(hs) == 11
    assert [h[3].split('\n')[0] for h in hs[:10]] == [f'old {i}' for i in range(2, 12)]
    assert hs[-1][3] == 'Who is in for 70mm?' and ('bot', '-# ── new ──') in t.sent
    assert hs[0][3].endswith('· on the site') and '\n-# ' in hs[0][3]                        # when they were written
    assert hs[0][1] == 'Ana' and hs[0][2].startswith('https://cdn.discordapp.com/')           # Discord pictures kept
    assert hs[1][1] == 'Bo'                                                                  # names can't contain "Discord"


def test_copies_are_linked_and_never_posted_twice(started):
    assert all(c[2] for c in site_comments(started.s1)[2:])
    n = len(started.t.sent)
    discussion(started)
    assert len(started.t.sent) == n
    comment(started, 'Second thought')
    discussion(started)
    assert len(started.ch.posts) == 1 and started.t.sent[-1][3] == 'Second thought'         # same thread, no new card


def dmsg(w, content, author=None, webhook_id=None, mtype=discord.MessageType.default, atts=()):
    return types.SimpleNamespace(id=next(_ids), author=author or member(1103, 'Cy'), webhook_id=webhook_id, channel=w.t,
                                 guild=w.ch.guild, type=mtype, content=content, clean_content=content,
                                 attachments=list(atts), mentions=[])


def test_a_message_typed_in_the_thread_becomes_a_site_comment(started):
    from app import app, User
    m = dmsg(started, "Count me in — I'll save seats", atts=[types.SimpleNamespace(url='https://cdn.discordapp.com/att/pic.png')])
    asyncio.run(started.bot.on_message(m))
    assert site_comments(started.s1)[-1] == ("Count me in — I'll save seats\nhttps://cdn.discordapp.com/att/pic.png", 'discord', str(m.id))
    with app.app_context():
        u = User.query.filter_by(discord_user_id='1103').first()
        assert u is not None and u.email is None                                             # an account made on the spot


def test_the_bots_own_posts_webhooks_and_system_messages_are_ignored(started):
    before = len(site_comments(started.s1))
    for m in (dmsg(started, 'echo', author=types.SimpleNamespace(id=4242, bot=True, name='bot')),
              dmsg(started, 'webhook copy', webhook_id=123), dmsg(started, '', mtype=discord.MessageType.thread_created)):
        asyncio.run(started.bot.on_message(m))
    assert len(site_comments(started.s1)) == before


def test_no_ambient_quotes_inside_screening_threads(started, monkeypatch):
    replies = []

    async def reply(*a, **k):
        replies.append(a)
    trig = dmsg(started, 'That 70mm IMAX print is gorgeous')
    trig.reply = reply
    monkeypatch.setattr(started.bot.random, 'random', lambda: 0.0)
    started.bot._trigger_cooldown.clear()
    asyncio.run(started.bot.on_message(trig))
    assert replies == []


def test_edits_and_deletes_in_discord_follow_on_the_site(started):
    b = started.bot
    m = dmsg(started, 'Count me in')
    asyncio.run(b.on_message(m))
    edited = dmsg(started, 'Count me in — I will save four seats')
    edited.id = m.id
    asyncio.run(b.on_raw_message_edit(types.SimpleNamespace(channel_id=started.t.id, message=edited)))
    assert ('Count me in — I will save four seats', 'discord', str(m.id)) in site_comments(started.s1)
    asyncio.run(b.on_raw_message_delete(types.SimpleNamespace(channel_id=started.t.id, message_id=m.id)))
    assert all(c[2] != str(m.id) for c in site_comments(started.s1))
    asyncio.run(b.on_raw_message_delete(types.SimpleNamespace(channel_id=555, message_id=999)))   # elsewhere: ignored


def test_deleting_a_site_comment_removes_its_discord_copy(started):
    from app import app, Message
    comment(started, 'Second thought')
    discussion(started)
    with app.app_context():
        mine = Message.query.filter_by(showtime_id=started.s1, body='Second thought').first()
        mid, did = mine.id, mine.discord_message_id
    client(started.bo).delete(f'/api/messages/{mid}')
    discussion(started)
    assert started.ch.hooks[0].deleted == [(int(did), started.t.id)]


def test_the_cards_going_button(started):
    from app import app, db, ShowtimeThread
    b = started.bot
    it = Interaction(member(1101, 'Ana'))

    async def press():
        btn = await b.ThreadRsvpButton.from_custom_id(None, None, {'status': 'going', 'sid': str(started.s1)})
        await btn.callback(it)
    asyncio.run(press())
    reply = next((x for x in it.log if len(x) > 2 and "You're going to" in (x[2] or '')), None)
    assert reply and reply[1] and "You're going to **SIRÂT**" in reply[2]                    # privately
    with app.app_context():
        ShowtimeThread.query.filter_by(showtime_id=started.s1).first().card_refreshed_at -= timedelta(minutes=5)
        db.session.commit()
    discussion(started)
    assert started.card.edits and '<@1101>' in started.card.edits[-1][0].description         # the card's Going list


# ── /discuss and the Discuss buttons ──

DEE = member(1104, 'Dee')


def discuss(w, sid, comment=None, user=DEE):
    it = Interaction(user)
    kw = {'comment': comment} if comment else {}
    asyncio.run(w.bot.discuss.callback(it, showtime=str(sid), **kw))
    return it


def test_discuss_with_a_comment_starts_the_thread(world):
    it = discuss(world, world.s2, 'First!')
    t2 = thread_for(world.s2)
    assert t2 and t2.sent[-1][1:4] == ('Dee', 'https://cdn.discordapp.com/avatars/1104/x.png', 'First!')   # under your name
    assert 'Posted in the **HAMNET** thread' in it.log[-1][2]
    assert not any(x[0] == 'bot' for x in t2.sent)                                           # no site comments to backfill
    assert site_comments(world.s2) == [('First!', 'discord_bot', str(t2.sent[-1][4]))]       # yours on the site
    discussion(world)
    assert len(t2.sent) == 1                                                                 # not echoed back


@pytest.fixture
def discussed(world):
    """Dee started the HAMNET thread with /discuss."""
    discuss(world, world.s2, 'First!')
    world.t2 = thread_for(world.s2)
    return world


def test_discuss_reopens_an_archived_thread(discussed):
    discussed.t2.archived = True
    it = discuss(discussed, discussed.s2)
    assert not discussed.t2.archived and it.log[-1][2].startswith('💬 **HAMNET** discussion → https://discord.com/channels/900/')
    assert len(discussed.ch.posts) == 1                                                      # still one thread per screening


def test_the_discuss_button_opens_a_comment_box(discussed):
    b, t2 = discussed.bot, discussed.t2
    it = Interaction(DEE, guild_id=None)

    async def flow():
        btn = await b.DiscussButton.from_custom_id(None, None, {'sid': str(discussed.s2)})
        await btn.callback(it)
        assert isinstance(it.modal, b.DiscussModal)
        it.modal.comment._value = 'From the button'
        await it.modal.on_submit(it)
        assert t2.sent[-1][3] == 'From the button' and site_comments(discussed.s2)[-1][0] == 'From the button'
        it2 = Interaction(DEE)
        await b.DiscussModal(discussed.s2).on_submit(it2)                                    # an empty comment
        assert 'discussion →' in it2.log[-1][2] and len(t2.sent) == 2                        # just links the thread
    asyncio.run(flow())


def view_ids(it):
    """Custom ids of the components on everything the bot sent back."""
    return [getattr(c, 'item', c).custom_id for x in it.log if len(x) > 3 and x[3] for c in x[3].children]


def test_rsvp_and_went_carry_a_discuss_button(discussed):
    b, w = discussed.bot, discussed
    it = Interaction(member(1101, 'Ana'))
    asyncio.run(b.rsvp.callback(it, showtime=str(w.s2)))
    assert f'disc:open:{w.s2}' in view_ids(it)                                               # beside a first-Going prompt
    it = Interaction(member(1101, 'Ana'), guild_id=None)

    async def went():
        att = await b.AttendanceButton.from_custom_id(None, None, b.ATTENDANCE_ID_RE.fullmatch(f'att:went:{w.past}'))
        await att.callback(it)
    asyncio.run(went())
    assert f'disc:open:{w.past}' in view_ids(it)


# ── deleted threads, permissions ──

def test_a_thread_deleted_in_discord_restarts_only_on_request(started):
    t = started.t
    asyncio.run(started.bot.on_raw_thread_delete(types.SimpleNamespace(thread_id=t.id)))
    THREADS.pop(t.id, None)
    comment(started, 'Anyone still going?')
    discussion(started)
    assert thread_for(started.s1) is None                                                    # a comment alone doesn't restart it
    start_thread(started, started.s1)
    t3 = thread_for(started.s1)
    assert t3 and t3 is not t and t3.sent[0][0] == 'bot'                                     # a fresh backfill…
    assert any(x[0] == 'hook' and x[3].startswith('Anyone still going?') for x in t3.sent)   # …with that comment


def test_missing_permissions(started, monkeypatch):
    monkeypatch.setattr(started.bot, '_webhook', None)
    started.ch.forbid = True
    comment(started, 'perm test')
    discussion(started)
    discussion(started)
    assert len(started.owner_dms) == 1 and 'Manage Webhooks' in started.owner_dms[0]         # the owner is told once
    assert "aren't set up yet" in discuss(started, started.s1, 'hello').log[-1][2]          # members get a clear message
    started.ch.forbid = False
    discussion(started)
    assert started.t.sent[-1][3] == 'perm test'                                              # the waiting comment goes through

"""The bot's share loop against a fake #movies channel: batched RSVP posts
(no pings) that follow later changes, "Who's in?" invite cards, poll
announcements through to results, and starting a thread."""
import asyncio
import itertools
import types
from datetime import datetime, timedelta

import discord
import pytest

from helpers import all_linked_present, client, patch_bot_api, setup_db

_ids = itertools.count(91000)


class NotFoundResp:
    status, reason = 404, 'Not Found'


class Msg:
    def __init__(self, ch, content, embed, view):
        self.id, self.channel = next(_ids), ch
        self.content, self.embed, self.view, self.deleted = content, embed, view, False
        self.jump_url = f'https://discord.com/channels/900/{ch.id}/{self.id}'


class Partial:
    def __init__(self, ch, mid):
        self.ch, self.mid = ch, mid

    async def edit(self, content=None, embed=None, view=None, allowed_mentions=None):
        m = self.ch.msgs.get(self.mid)
        if not m or m.deleted:
            raise discord.NotFound(NotFoundResp(), 'gone')
        m.content, m.embed, m.view = content, embed, view
        self.ch.log.append(('edit', self.mid, allowed_mentions))

    async def delete(self):
        m = self.ch.msgs.get(self.mid)
        if not m or m.deleted:
            raise discord.NotFound(NotFoundResp(), 'gone')
        m.deleted = True
        self.ch.log.append(('delete', self.mid))


class Channel:
    """#movies: what was sent, edited and deleted."""
    id = 901

    def __init__(self):
        self.msgs, self.log = {}, []

    async def send(self, content=None, embed=None, view=None, allowed_mentions=None):
        m = Msg(self, content, embed, view if view is not discord.utils.MISSING else None)
        self.msgs[m.id] = m
        self.log.append(('send', m.id, allowed_mentions))
        return m

    def get_partial_message(self, mid):
        return Partial(self, mid)

    def last(self):
        return self.msgs[max(self.msgs)]


def ids_of(view):
    return [getattr(c, 'item', c).custom_id for c in (view.children if view else [])]


@pytest.fixture
def world():
    """Ana (admin) and Bo in the club; PSYCHO (35mm) and THE BIRDS at Suns."""
    from app import app, db, User, GroupMembership, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='suns').first()
        us = [User(email=f'b{i}@r3d.test', name=n, is_active=True, discord_user_id=str(8800 + i)) for i, n in enumerate(['Ana', 'Bo'])]
        db.session.add_all(us)
        db.session.flush()
        for u, role in zip(us, ('admin', 'member')):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role=role))
        shows = []
        for i, t in enumerate(['PSYCHO', 'THE BIRDS']):
            m = Movie(title=t, poster_url='https://img.test/p.jpg')
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, format_label='35mm' if i == 0 else None,
                         start_time=(datetime.now() + timedelta(days=2 + i)).replace(hour=21, minute=30, second=0, microsecond=0))
            db.session.add(s)
            db.session.flush()
            shows.append(s.id)
        db.session.commit()
        ids = {'ana': us[0].id, 'bo': us[1].id, 's1': shows[0], 's2': shows[1]}
    bot = patch_bot_api()
    all_linked_present()
    ch = Channel()
    bot.movies_channel = lambda: ch
    return types.SimpleNamespace(bot=bot, ch=ch, tick=lambda: asyncio.run(bot.share_loop.coro()), **ids)


def batch_due():
    """The 60-second RSVP batch window is over."""
    from app import app, db, DiscordPost
    with app.app_context():
        DiscordPost.query.filter_by(status='pending').filter(DiscordPost.kind == 'rsvp') \
            .update({'post_at': datetime.now() - timedelta(seconds=1)})
        db.session.commit()


def rsvp(w, who, sid, status):
    return client(w[who] if isinstance(w, dict) else getattr(w, who)).post('/api/rsvp', json={'showtime_id': sid, 'status': status, 'group_id': 1})


@pytest.fixture
def posted(world):
    """Ana always shares her RSVPs: going to PSYCHO, maybe THE BIRDS — posted."""
    client(world.ana).put('/api/discord/prefs', json={'rsvp': 'always'})
    rsvp(world, 'ana', world.s1, 'going')
    rsvp(world, 'ana', world.s2, 'maybe')
    world.tick()
    world.quiet_window = list(world.ch.log)
    batch_due()
    world.tick()
    return world


def test_rsvps_are_batched_into_one_post_without_pings(posted):
    assert posted.quiet_window == []                                         # nothing during the batch window
    m = posted.ch.last()
    assert len(posted.ch.msgs) == 1 and 'Ana' in m.content and 'has plans for 2 screenings' in m.content
    assert 'PSYCHO' in m.content and '*(maybe)*' in m.content and '<@' not in m.content
    assert posted.ch.log[-1][2] is not None and posted.ch.log[-1][2].users is False
    assert ids_of(m.view) == [f'disc:rsvp:going:{posted.s1}', f'disc:rsvp:going:{posted.s2}']   # a Going button each
    st = client(posted.ana).get(f'/api/showtimes/{posted.s1}', query_string={'group_id': 1}).json
    assert st['discord']['my_share']['jump_url'] == m.jump_url                                # the site links to it


def test_the_post_follows_later_changes(posted):
    m = posted.ch.last()
    rsvp(posted, 'ana', posted.s2, 'not_going')
    posted.tick()
    assert posted.ch.log[-1][0] == 'edit' and 'is going to **PSYCHO**' in m.content and 'BIRDS' not in m.content
    assert ids_of(m.view) == [f'disc:rsvp:going:{posted.s1}', f'disc:open:{posted.s1}']
    rsvp(posted, 'ana', posted.s1, None)
    posted.tick()
    assert m.deleted and posted.ch.log[-1][0] == 'delete'                                    # the last one cancelled
    posted.tick()
    assert sum(1 for x in posted.ch.log if x[0] == 'delete') == 1                            # and left alone after


def test_whos_in_invite_cards(world):
    client(world.bo).post('/api/discord/shares', json={'kind': 'invite', 'group_id': 1, 'showtime_id': world.s1, 'note': 'Drinks after?'})
    world.tick()
    m = world.ch.last()
    assert "**Bo** is asking: who's in?" in m.content and m.embed.title == 'PSYCHO' and '> Drinks after?' in m.embed.description
    assert ids_of(m.view)[:3] == [f'disc:rsvp:going:{world.s1}', f'disc:rsvp:maybe:{world.s1}', f'disc:open:{world.s1}']
    rsvp(world, 'ana', world.s1, 'going')
    world.tick()
    assert '**Going:** Ana' in m.embed.description and '<@' not in m.embed.description         # names, no mentions
    world.ch.msgs[m.id].deleted = True                                                          # deleted in Discord
    rsvp(world, 'bo', world.s1, 'maybe')
    world.tick()
    assert client(world.bo).get(f'/api/showtimes/{world.s1}', query_string={'group_id': 1}).json['discord']['invite'] is None


def test_a_polls_posts_from_announcement_to_results(world):
    a = client(world.ana)
    p = a.post('/api/groups/1/polls', json={'title': 'Best of fall', 'announce': 'now',
                                            'categories': [{'title': 'C', 'options': [{'text': 'x'}, {'text': 'y'}]}]}).json
    world.tick()
    m = world.ch.last()
    assert m.embed.title == '🗳️ New poll: Best of fall' and ids_of(m.view)[0].startswith('vote:b:open:')
    a.put(f"/api/polls/{p['id']}", json={'status': 'closed'})
    world.tick()
    assert m.embed.title.startswith('🔒 Voting closed') and m.view is None
    cat = p['categories'][0]
    a.post(f"/api/polls/{p['id']}/score", json={'winners': {str(cat['id']): cat['options'][0]['id']}, 'post_results': True})
    world.tick()
    res = world.ch.last()
    assert res.embed.title == '🏆 Results: Best of fall' and m.embed.description.startswith('Results are in')
    a.delete(f"/api/polls/{p['id']}")
    world.tick()
    assert m.deleted and res.deleted


def test_starting_a_thread(world):
    made = []

    async def fake_ensure(sid):
        made.append(sid)
        return types.SimpleNamespace(id=4444, jump_url='https://discord.com/channels/900/4444'), {}, True
    world.bot.ensure_thread = fake_ensure
    client(world.bo).post('/api/discord/shares', json={'kind': 'thread', 'group_id': 1, 'showtime_id': world.s2})
    world.tick()
    assert made == [world.s2]

"""Screening discussions (threads mirrored with the site, /discuss) and what
members share from the site.
"""

import asyncio
import json
import re
import time
import types
from datetime import datetime
import discord
from discord import app_commands
from discord.ext import tasks
from api import ApiError
import embeds
from .shared import (DEFAULT_GROUP_ID, GONE_MSG, SITE_URL, api, api_failure, channel_for, client, club, club_of, club_zone,
                     connected_clubs, discord_identity, dm_owner, register, reply_failure, rsvp_date_autocomplete,
                     rsvp_end_autocomplete, rsvp_showtime_autocomplete, rsvp_theatre_autocomplete, use_club)
from . import alerts, polls, servers      # used at call time, so the order they load in doesn't matter


# ─── Screening discussion threads ─────────────────────────────────────────────
# Each screening's discussion can live in a thread in #movies, mirrored with
# the site. The thread hangs off a card post (with Going / Maybe buttons) and is
# created on the first comment from either side. Site comments are posted
# through a #movies webhook under the commenter's name; thread messages are
# saved as comments. The bot ignores its own webhook posts (no loops), and no
# ambient quotes are dropped into screening threads.

THREAD_ARCHIVE_MINUTES = 10080        # a week of quiet before Discord archives it
WEBHOOK_NAME = 'Cinema Club'
NEEDED_PERMS = ('Manage Webhooks, Create Public Threads, Send Messages in Threads, '
                'Read Message History')
_webhooks = {}                        # channel id → the bot's webhook there (one per club's channel)
_thread_ids = set()                   # linked thread ids in every connected server, as strings
_thread_ids_loaded = 0.0
_thread_locks = {}
_failed_posts = {}                    # site comment id -> failed attempts
_perm_warned = set()                  # clubs whose missing permissions were reported this run


class DiscussionUnavailable(Exception):
    pass


async def warn_permissions(err, group_id=None):
    """Say once (per run) that threads need permissions in a club's channel:
    the home server's to the bot's owner; another club's to whoever connected
    that server (servers.report_club, once per change)."""
    group_id = group_id or club()
    print(f'discussion threads (club {group_id}): missing permission: {err}')
    if group_id in _perm_warned:
        return
    _perm_warned.add(group_id)
    if group_id == DEFAULT_GROUP_ID:
        await dm_owner(f"⚠️ Screening threads can't work in #movies yet — the bot needs: {NEEDED_PERMS}. "
                       "Grant them in the channel's permissions; I'll pick up where I left off.")
    else:
        await servers.report_club(group_id)


async def get_webhook(channel):
    """The bot's webhook in this channel (made the first time)."""
    if channel is None:
        raise DiscussionUnavailable('no channel')
    wh = _webhooks.get(channel.id)
    if wh is None:
        for found in await channel.webhooks():
            if found.name == WEBHOOK_NAME and found.user and found.user.id == client.user.id:
                wh = found
                break
        else:
            wh = await channel.create_webhook(name=WEBHOOK_NAME, reason='Mirror site discussions into screening threads')
        _webhooks[channel.id] = wh
    return wh


def _hook_name(name):
    """Webhook display names: 1–80 chars, and Discord rejects some words."""
    clean = re.sub(r'(?i)discord|clyde', '', name or '').strip()[:80]
    return clean or 'Cinema Club member'


async def refresh_thread_ids(force=False):
    global _thread_ids, _thread_ids_loaded
    if force or time.monotonic() - _thread_ids_loaded > 600:
        ids = set()
        for group_id, _ in connected_clubs():
            ids |= set(await api.get('/api/internal/discussion/threads', group_id=group_id))
        _thread_ids, _thread_ids_loaded = ids, time.monotonic()


def plans_view(plans):
    """Going buttons for the digest's "make plans" picks (private RSVPs)."""
    if not plans:
        return discord.utils.MISSING
    view = discord.ui.View(timeout=None)
    for p in plans[:5]:
        when = datetime.fromisoformat(p['start_time']).strftime('%a %-I:%M %p').replace(':00 ', ' ')
        view.add_item(ThreadRsvpButton('going', p['showtime_id'], label=f"Going · {p['title']} {when}"))
    return view


def thread_card_view(card):
    view = discord.ui.View(timeout=None)
    view.add_item(ThreadRsvpButton('going', card['showtime_id']))
    view.add_item(ThreadRsvpButton('maybe', card['showtime_id']))
    view.add_item(discord.ui.Button(label='Open on the site', url=f"{SITE_URL}{card['site_path']}"))
    return view


async def _fetch_thread(thread_id):
    thread = client.get_channel(int(thread_id))
    return thread if thread is not None else await client.fetch_channel(int(thread_id))


async def ensure_thread(showtime_id, group_id=None):
    """(thread, info, created) for a screening in a club's server (the current
    club's by default), creating the card post + thread (and copying in the
    last site comments) if it has none yet."""
    group_id = group_id or club()
    lock = _thread_locks.setdefault((group_id, showtime_id), asyncio.Lock())
    async with lock:
        info = await api.get('/api/internal/discussion/thread', showtime_id=showtime_id, group_id=group_id)
        if info['thread']:
            try:
                return await _fetch_thread(info['thread']['thread_id']), info, False
            except discord.NotFound:          # deleted in Discord: forget it and start over
                await api.post(f"/api/internal/discussion/threads/{info['thread']['thread_id']}/unlink")
                _thread_ids.discard(info['thread']['thread_id'])
                info = await api.get('/api/internal/discussion/thread', showtime_id=showtime_id,
                                     group_id=group_id)
        channel = channel_for(group_id)
        if channel is None:
            raise DiscussionUnavailable('no channel for this club')
        card = info['card']
        starter = await channel.send(embed=embeds.thread_card_embed(card), view=thread_card_view(card))
        thread = await starter.create_thread(name=embeds.thread_name(card),
                                             auto_archive_duration=THREAD_ARCHIVE_MINUTES)
        try:
            await api.post('/api/internal/discussion/threads', {
                'showtime_id': showtime_id, 'group_id': group_id, 'guild_id': str(channel.guild.id),
                'channel_id': str(channel.id), 'thread_id': str(thread.id), 'starter_message_id': str(starter.id)})
        except ApiError as e:
            if e.status != 409:
                raise
            existing = json.loads(e.body)['thread']   # lost a race: use the other one, drop ours
            for item in (thread, starter):
                try:
                    await item.delete()
                except discord.HTTPException:
                    pass
            return await _fetch_thread(existing['thread_id']), info, False
        _thread_ids.add(str(thread.id))
        await backfill_thread(thread, info)
        return thread, info, True


async def backfill_thread(thread, info):
    """Copy the last site comments into a brand-new thread, oldest first."""
    items = info.get('backfill') or []
    if not items:
        return
    await thread.send(embeds.backfill_intro(info['earlier_total'], len(items), info['card']['site_path']),
                      allowed_mentions=discord.AllowedMentions.none())
    mirrored = []
    for item in items:
        sent = await post_comment(thread, item['author'], embeds.backfilled_comment(item, club_zone()))
        mirrored.append({'message_id': item['message_id'], 'discord_message_id': str(sent.id)})
    await api.post('/api/internal/discussion/mirrored', {'items': mirrored})
    await thread.send('-# ── new ──', allowed_mentions=discord.AllowedMentions.none())


def _channel_of(thread):
    """The channel a screening thread hangs off (its club's)."""
    return getattr(thread, 'parent', None) or channel_for(club())


async def post_comment(thread, author, content):
    """Post into a thread under someone's name (webhook messages also reopen
    an archived thread)."""
    wh = await get_webhook(_channel_of(thread))
    return await wh.send(content[:2000], username=_hook_name(author.get('name')),
                         avatar_url=author.get('avatar_url') or discord.utils.MISSING,
                         thread=thread, wait=True, allowed_mentions=discord.AllowedMentions.none())


@tasks.loop(seconds=5)
async def discussion_loop():
    """Carry site activity into each connected club's Discord: new comments,
    deletions, card updates."""
    try:
        await refresh_thread_ids()
    except Exception as e:
        print(f'discussion_loop: thread list failed: {e}')
        return
    for group_id, _ in connected_clubs():
        channel = channel_for(group_id)
        if channel is None:
            continue
        use_club(group_id)
        try:
            await _discussion_pass(group_id, channel)
        except discord.Forbidden as e:
            await warn_permissions(e, group_id)


async def _discussion_pass(group_id, channel):
    try:
        box = await api.get('/api/internal/discussion/outbox', group_id=group_id)
    except Exception as e:
        print(f'discussion_loop (club {group_id}): fetch failed: {e}')
        return
    for p in box.get('posts', []):
        if _failed_posts.get(p['message_id'], 0) >= 3:
            continue                           # give up on a comment that keeps failing
        try:
            thread, _, _ = await ensure_thread(p['showtime_id'], group_id)
            sent = await post_comment(thread, p['author'], p['body'])
            await api.post('/api/internal/discussion/mirrored',
                           {'items': [{'message_id': p['message_id'], 'discord_message_id': str(sent.id)}]})
        except discord.Forbidden:
            raise
        except Exception as e:
            _failed_posts[p['message_id']] = _failed_posts.get(p['message_id'], 0) + 1
            print(f"discussion_loop: comment {p['message_id']} failed: {e}")
    for d in box.get('deletions', []):
        try:
            await (await get_webhook(channel)).delete_message(int(d['discord_message_id']),
                                                              thread=discord.Object(int(d['thread_id'])))
        except discord.NotFound:
            pass                               # already gone
        await api.post(f"/api/internal/discussion/deletions/{d['id']}/done")
    for c in box.get('cards', []):
        try:
            await channel.get_partial_message(int(c['starter_message_id'])).edit(
                embed=embeds.thread_card_embed(c['card']), view=thread_card_view(c['card']))
        except discord.NotFound:
            pass                               # card deleted; the thread lives on
        await api.post(f"/api/internal/discussion/cards/{c['thread_id']}/refreshed")


@discussion_loop.before_loop
async def before_discussion():
    await client.wait_until_ready()


def _identity_for(member, guild_id):
    return discord_identity(types.SimpleNamespace(user=member, guild_id=guild_id))


async def mirror_to_site(message):
    """A message typed in a screening thread becomes that member's comment."""
    if message.type not in (discord.MessageType.default, discord.MessageType.reply):
        return
    parts = [message.clean_content.strip()] + [a.url for a in message.attachments]
    body = '\n'.join(p for p in parts if p)[:2000]
    if not body:
        return
    try:
        await api.post('/api/internal/discussion/messages', {
            **_identity_for(message.author, message.guild.id if message.guild else None),
            'thread_id': str(message.channel.id), 'discord_message_id': str(message.id), 'body': body})
    except Exception as e:
        print(f'mirror_to_site failed for {message.id}: {e}')


@client.event
async def on_raw_message_edit(payload):
    if str(payload.channel_id) not in _thread_ids:
        return
    msg = getattr(payload, 'message', None)
    if msg is None or msg.author.bot or msg.webhook_id:
        return
    body = '\n'.join(p for p in [msg.clean_content.strip()] + [a.url for a in msg.attachments] if p)[:2000]
    if body:
        try:
            await api.post('/api/internal/discussion/messages/edit',
                           {'discord_message_id': str(msg.id), 'body': body})
        except Exception as e:
            print(f'mirror edit failed for {msg.id}: {e}')


async def _mirror_deletes(channel_id, message_ids):
    if str(channel_id) in _thread_ids and message_ids:
        try:
            await api.post('/api/internal/discussion/messages/delete',
                           {'discord_message_ids': [str(i) for i in message_ids]})
        except Exception as e:
            print(f'mirror delete failed: {e}')


@client.event
async def on_raw_message_delete(payload):
    await _mirror_deletes(payload.channel_id, [payload.message_id])


@client.event
async def on_raw_bulk_message_delete(payload):
    await _mirror_deletes(payload.channel_id, list(payload.message_ids))


@client.event
async def on_raw_thread_delete(payload):
    if str(payload.thread_id) in _thread_ids:
        _thread_ids.discard(str(payload.thread_id))
        try:
            await api.post(f'/api/internal/discussion/threads/{payload.thread_id}/unlink')
        except Exception as e:
            print(f'thread unlink failed: {e}')


async def open_discussion(interaction, showtime_id, comment=None):
    """Open (creating if needed) a screening's thread and optionally post the
    member's comment there — for /discuss and the Discuss buttons. The
    interaction must already be deferred (ephemeral)."""
    comment = (comment or '').strip()
    try:
        thread, info, created = await ensure_thread(showtime_id, club_of(interaction))
        if getattr(thread, 'archived', False) and not comment:
            await thread.edit(archived=False)
        if comment:
            member = interaction.user
            sent = await post_comment(thread, {'name': getattr(member, 'display_name', None) or member.name,
                                               'avatar_url': str(member.display_avatar.url)}, comment)
            try:
                await api.post('/api/internal/discussion/messages', {
                    **discord_identity(interaction), 'thread_id': str(thread.id),
                    'discord_message_id': str(sent.id), 'body': comment, 'source': 'discord_bot'})
            except ApiError as e:
                await (await get_webhook(_channel_of(thread))).delete_message(sent.id, thread=thread)
                await interaction.followup.send(api_failure(e, "Couldn't save your comment ({status})."), ephemeral=True)
                return
    except ApiError as e:
        msg = GONE_MSG if e.status == 404 else f"Couldn't open the discussion ({e.status})."
        await interaction.followup.send(msg, ephemeral=True)
        return
    except discord.Forbidden as e:
        await warn_permissions(e, club_of(interaction))
        await interaction.followup.send("Screening threads aren't set up yet — the bot is missing permissions "
                                        "(whoever connected this server has been told).", ephemeral=True)
        return
    except Exception as e:
        print(f'open_discussion failed: {e}')
        await interaction.followup.send("Couldn't open the discussion — try again in a bit.", ephemeral=True)
        return
    title = info['card']['title']
    if comment:
        text = f"💬 Posted in the **{title}** thread → {thread.jump_url}"
    elif created:
        text = f"💬 Started the **{title}** thread → {thread.jump_url}\nComments there show up on the site too."
    else:
        text = f"💬 **{title}** discussion → {thread.jump_url}"
    await interaction.followup.send(text, ephemeral=True)


class DiscussModal(discord.ui.Modal, title='Discuss this screening'):
    comment = discord.ui.TextInput(label='Your comment (optional)', style=discord.TextStyle.paragraph,
                                   required=False, max_length=2000,
                                   placeholder='Leave empty to just open the thread')

    def __init__(self, showtime_id):
        super().__init__()
        self.showtime_id = showtime_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await open_discussion(interaction, self.showtime_id, self.comment.value)


class DiscussButton(discord.ui.DynamicItem[discord.ui.Button], template=r'disc:open:(?P<sid>[0-9]+)'):
    """💬 Discuss — on /rsvp confirmations and the "did you go?" follow-up."""
    def __init__(self, showtime_id, row=None):
        super().__init__(discord.ui.Button(label='💬 Discuss', style=discord.ButtonStyle.secondary,
                                           custom_id=f'disc:open:{showtime_id}', row=row))
        self.showtime_id = showtime_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match['sid']))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DiscussModal(self.showtime_id))


def discuss_view(showtime_id):
    view = discord.ui.View(timeout=None)
    view.add_item(DiscussButton(showtime_id))
    return view


class ThreadRsvpButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r'disc:rsvp:(?P<status>going|maybe):(?P<sid>[0-9]+)'):
    """Going / Maybe on a thread's card: RSVPs privately (the card's list
    refreshes within a few minutes)."""
    def __init__(self, status, showtime_id, label=None):
        super().__init__(discord.ui.Button(
            label=(label or ('Going' if status == 'going' else 'Maybe'))[:80],
            style=discord.ButtonStyle.success if status == 'going' else discord.ButtonStyle.secondary,
            custom_id=f'disc:rsvp:{status}:{showtime_id}'))
        self.status, self.showtime_id = status, showtime_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['status'], int(match['sid']))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await api.post('/api/internal/rsvp', {
                **discord_identity(interaction), 'showtime_id': self.showtime_id, 'status': self.status})
        except Exception as e:
            await reply_failure(interaction, e, 'thread RSVP', 'RSVP failed ({status}).', GONE_MSG)
            return
        dt = datetime.fromisoformat(result['start_time'])
        verb = "You're going to" if self.status == 'going' else 'You might go to'
        await interaction.followup.send(
            f"🎟️ {verb} **{result['movie']['title']}** — {dt.strftime('%a %-m/%-d %-I:%M %p')}. "
            "Change it any time here or with `/rsvp`.", ephemeral=True)
        await alerts.ask_after_going(interaction, result)


@client.tree.command(name='discuss', description="Open a screening's discussion thread (and add a comment)")
@app_commands.describe(
    date='Optional: narrow the screening list to a date (or start of a range)',
    end='Optional: end of a date range (use with date)',
    theatre='Optional: narrow the screening list to a theatre',
    showtime='The screening (narrows as you set date/theatre, or type a movie)',
    comment='Optional: your comment, posted as the thread\'s next message',
)
async def discuss(interaction: discord.Interaction, showtime: str, date: str = None, end: str = None,
                  theatre: str = None, comment: app_commands.Range[str, 1, 2000] = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    if not showtime.isdigit():
        await interaction.followup.send('Pick a screening from the **showtime** list.', ephemeral=True)
        return
    await open_discussion(interaction, int(showtime), comment)


discuss.autocomplete('date')(rsvp_date_autocomplete)
discuss.autocomplete('end')(rsvp_end_autocomplete)
discuss.autocomplete('theatre')(rsvp_theatre_autocomplete)
discuss.autocomplete('showtime')(rsvp_showtime_autocomplete)


# ─── Shared from the site (R3d) ───────────────────────────────────────────────
# Members choose what reaches #movies (their RSVPs, "who's in?" invites, poll
# announcements and results, or starting a screening's thread). The backend
# keeps the queue; this posts what's due, edits posts whose content changed
# (an RSVP cancelled, more people going, a poll closed) and deletes ones with
# nothing left to show. Shared posts never @-ping anyone.

NO_PINGS = discord.AllowedMentions.none()


def share_content(kind, data):
    """(content, embed, view) for a shared post."""
    if kind == 'rsvp':
        view = discord.ui.View(timeout=None)
        items = data['items'][:4]
        for i in items:
            label = "🎟️ I'm in too" if len(items) == 1 else f"🎟️ {i['title']}"
            view.add_item(ThreadRsvpButton('going', i['showtime_id'], label=label))
        if len(items) == 1:
            view.add_item(DiscussButton(items[0]['showtime_id']))
        return embeds.rsvp_share_message(data), None, view
    if kind == 'invite':
        card = data['card']
        view = discord.ui.View(timeout=None)
        if not data.get('started'):
            view.add_item(ThreadRsvpButton('going', card['showtime_id']))
            view.add_item(ThreadRsvpButton('maybe', card['showtime_id']))
            view.add_item(DiscussButton(card['showtime_id']))
        view.add_item(discord.ui.Button(label='On the site', url=f"{SITE_URL}{card['site_path']}"))
        return embeds.invite_message(data), embeds.invite_embed(data), view
    if kind == 'poll':
        view = (polls.vote_open_view([{'id': data['poll_id'], 'title': data['title']}])
                if data.get('status', 'open') == 'open' else None)
        return None, embeds.poll_post_embed(data), view
    if kind == 'poll_results':
        return None, embeds.poll_results_embed(data), None
    raise ValueError(f'unknown share kind {kind}')


async def handle_share(channel, item):
    pid, kind, action, data = item['id'], item['kind'], item['action'], item.get('data')
    done = lambda **body: api.post(f'/api/internal/discord/posts/{pid}/done', body)
    if action == 'delete':
        if item.get('message_id'):
            try:
                await channel.get_partial_message(int(item['message_id'])).delete()
            except discord.NotFound:
                pass
        await done(action='deleted')
        return
    if kind == 'thread':                      # "Start a Discord thread" from the site
        thread, _, _ = await ensure_thread(data['showtime_id'], club())
        await done(action='posted', message_id=str(thread.id), jump_url=thread.jump_url)
        return
    content, embed, view = share_content(kind, data)
    if action == 'post':
        msg = await channel.send(content=content, embed=embed, view=view or discord.utils.MISSING,
                                 allowed_mentions=NO_PINGS)
        await done(action='posted', message_id=str(msg.id), jump_url=msg.jump_url)
        return
    try:
        await channel.get_partial_message(int(item['message_id'])).edit(
            content=content, embed=embed, view=view, allowed_mentions=NO_PINGS)
    except discord.NotFound:                  # deleted in Discord: stop tracking it
        await done(action='deleted')
        return
    await done(action='edited')


@tasks.loop(seconds=10)
async def share_loop():
    """What members shared from the site, posted (and kept in step) in each club's server."""
    for group_id, _ in connected_clubs():
        channel = channel_for(group_id)
        if channel is None:
            continue
        use_club(group_id)
        try:
            due = await api.get('/api/internal/discord/posts/due', group_id=group_id)
        except Exception as e:
            print(f'share_loop (club {group_id}): fetch failed: {e}')
            continue
        for item in due:
            try:
                await handle_share(channel, item)
            except discord.Forbidden as e:    # say so once; retried next round
                await warn_permissions(e, group_id)
                break
            except Exception as e:            # tried again next round
                print(f"share_loop: {item.get('action')} {item.get('kind')} {item.get('id')} failed: {e}")


@share_loop.before_loop
async def before_share():
    await client.wait_until_ready()


register(items=(DiscussButton, ThreadRsvpButton,), loops=(discussion_loop, share_loop,))

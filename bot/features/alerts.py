"""What the bot tells people: schedule drops (/announcements), the Monday digest
(/digest), "did you go?" after a screening, and members' alerts by DM (/notifications).
"""

import re
import time
from datetime import datetime, time as dtime
import discord
from discord import app_commands
from discord.ext import tasks
from api import ApiError
import embeds
from .shared import DEFAULT_GROUP_ID, ET, GONE_MSG, SITE_URL, api, client, discord_identity, dm_owner, movies_channel, register, reply_failure, tell, theatre_choices
from . import games, polls, threads      # used at call time, so the order they load in doesn't matter


# ─── Announce loop ────────────────────────────────────────────────────────────

@tasks.loop(seconds=60)
async def announce_loop():
    channel = movies_channel()
    if channel is None:
        return
    try:
        events = await api.get('/api/internal/scrape-events', unannounced=1)
    except Exception as e:
        print(f'announce_loop: fetch failed: {e}')
        return

    # Theatre drops are announced only for theatres someone enabled with
    # /announcements (fail closed — they're opt-in). Every theatre's new showtimes,
    # and watchlist tags, reach people through the Monday digest regardless.
    try:
        enabled = set((await api.get('/api/internal/alerts',
                                     group_id=DEFAULT_GROUP_ID)).get('slugs', []))
    except Exception as e:
        print(f'announce_loop: alerts fetch failed: {e}')
        enabled = set()

    for event in events:
        try:
            if event['event_type'] in ('new_drop', 'new_showtimes'):
                if (event.get('payload') or {}).get('theatre_slug') in enabled:
                    await channel.send(embed=embeds.drop_embed(event))
            elif event['event_type'] == 'scrape_error':
                await dm_owner(embeds.error_message(event))   # not channel news
            await api.post(f"/api/internal/scrape-events/{event['id']}/announced")
        except Exception as e:
            print(f"announce_loop: failed for event {event.get('id')}: {e}")

    # Site activity — RSVPs and other actions taken on the website.
    try:
        activity = await api.get('/api/internal/activity-events', unannounced=1)
    except Exception as e:
        print(f'announce_loop: activity fetch failed: {e}')
        activity = []

    for ev in activity:
        try:
            p = ev.get('payload') or {}
            if ev['kind'] == 'llm_switch':                      # the shared AI changed models: owner only
                await dm_owner(p.get('message') or 'The AI models changed.')
            elif ev['kind'] in ('poll_opened', 'poll_scored'):
                if p.get('group_id') == DEFAULT_GROUP_ID:      # only this server's group's polls
                    if ev['kind'] == 'poll_opened':
                        await channel.send(embed=embeds.poll_opened_embed(p),
                                           view=polls.vote_open_view([{'id': p['poll_id'], 'title': p['title']}]))
                    else:
                        await channel.send(embed=embeds.poll_results_embed(p))
            elif msg := embeds.activity_message(ev):
                await channel.send(msg)
            await api.post(f"/api/internal/activity-events/{ev['id']}/announced")
        except Exception as e:
            print(f"announce_loop: activity failed for {ev.get('id')}: {e}")


@announce_loop.before_loop
async def before_announce():
    await client.wait_until_ready()


# ─── Weekly digest (Mondays 10:00 ET) ─────────────────────────────────────────

@tasks.loop(time=dtime(hour=10, minute=0, tzinfo=ET))
async def digest_loop():
    if datetime.now(ET).weekday() != 0:   # Monday only
        return
    await post_digest(movies_channel(), tag_watchers=True)


@digest_loop.before_loop
async def before_digest():
    await client.wait_until_ready()


async def post_digest(channel, tag_watchers=False):
    """Post the weekly digest to `channel`; returns True on success. Only the
    scheduled Monday post tags watchlist owners, and the tags are recorded so
    nobody is re-tagged about the same film for two weeks."""
    if channel is None:
        return False
    try:
        digest = await api.get('/api/internal/digest', group_id=DEFAULT_GROUP_ID, days=7)
        content, embed, tagged, plans = embeds.digest_message(digest, tag_watchers=tag_watchers)
        await channel.send(content, embed=embed, view=threads.plans_view(plans),
                           allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False))
    except Exception as e:
        print(f'digest failed: {e}')
        return False
    if tagged:
        try:
            await api.post('/api/internal/digest/delivered', {'watchlist_ids': tagged})
        except Exception as e:
            print(f'digest: recording tagged watchers failed: {e}')
    return True


# ─── "Did you go?" (attendance) ───────────────────────────────────────────────
# After a screening someone RSVP'd going to, the bot asks by DM — privately,
# daytime only, at most once a day (the backend enforces the daily cap and never
# re-asks about a screening). Buttons survive bot restarts: their custom ids
# carry the answer + screening, and DynamicItem rebuilds them on any click.

ATTENDANCE_ID_RE = re.compile(r'att:(?P<status>went|missed):(?P<sid>[0-9]+)')
_dm_fallback = {}   # discord id -> screenings, for people whose DMs are closed


class AttendanceButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r'att:(?P<status>went|missed):(?P<sid>[0-9]+)'):
    def __init__(self, status, showtime_id, label=None, row=None):
        super().__init__(discord.ui.Button(
            label=label or ('Went' if status == 'went' else "Didn't go"),
            style=discord.ButtonStyle.success if status == 'went' else discord.ButtonStyle.secondary,
            custom_id=f'att:{status}:{showtime_id}', row=row))
        self.status, self.showtime_id = status, showtime_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['status'], int(match['sid']))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            result = await api.post('/api/internal/attendance', {
                **discord_identity(interaction), 'showtime_id': self.showtime_id, 'status': self.status})
        except Exception as e:
            await reply_failure(interaction, e, 'attendance answer', "Couldn't save that ({status}).", GONE_MSG)
            return
        await interaction.edit_original_response(
            view=answered_view(interaction.message, self.showtime_id, self.status, result))
        if self.status == 'went':
            await interaction.followup.send(
                f"🍿 Logged **{result['title']}** to your watch history. Got a take? Tap **Discuss** to "
                f"comment (it opens the screening's thread), or add it on the site → "
                f"{SITE_URL}/calendar?showtime={self.showtime_id}", view=threads.discuss_view(self.showtime_id), ephemeral=True)


def _when_short(iso):
    return datetime.fromisoformat(iso).strftime('%a %-m/%-d')


def attendance_text(screenings):
    lines = []
    for s in screenings:
        fmt = f" · {s['format_label']}" if s.get('format_label') else ''
        diary = ' · 📓 in your Letterboxd diary' if s.get('letterboxd') else ''
        lines.append(f"• **{s['title']}** — {_when_short(s['start_time'])} @ {s['theatre']}{fmt}{diary}")
    return ("🎬 **Did you make it?** You were going to:\n" + '\n'.join(lines) +
            "\nTap below — it keeps your watch history (and the leaderboard) honest.")


def attendance_view(screenings):
    view = discord.ui.View(timeout=None)
    for row, s in enumerate(screenings[:5]):   # one row per screening; Discord allows 5
        suffix = f" ({_when_short(s['start_time'])})"
        view.add_item(AttendanceButton('went', s['showtime_id'],
                                       label=f"Went · {s['title']}"[:80 - len(suffix)] + suffix, row=row))
        view.add_item(AttendanceButton('missed', s['showtime_id'], row=row))
    return view


def answered_view(message, showtime_id, status, result):
    """The prompt's buttons with the answered screening replaced by its answer."""
    view = discord.ui.View(timeout=None)
    for row, action_row in enumerate(message.components if message else []):
        for comp in getattr(action_row, 'children', []):
            match = ATTENDANCE_ID_RE.fullmatch(comp.custom_id or '')
            if match and int(match['sid']) == showtime_id:
                if match['status'] == 'went':      # one result button where the pair was
                    mark = '✅ Went' if status == 'went' else "❌ Didn't go"
                    view.add_item(discord.ui.Button(label=f"{mark} · {result['title']}"[:80], disabled=True,
                                                    style=comp.style, row=row))
            elif match:
                view.add_item(AttendanceButton(match['status'], int(match['sid']), label=comp.label, row=row))
            elif getattr(comp, 'url', None):       # a link (e.g. History on the site)
                view.add_item(discord.ui.Button(label=comp.label, url=comp.url, row=row))
            else:                                  # an earlier answer — keep it as is
                view.add_item(discord.ui.Button(label=comp.label, style=comp.style, disabled=True, row=row))
    return view


@tasks.loop(minutes=30)
async def attendance_loop():
    if not 10 <= datetime.now(ET).hour < 21:      # no DMs at night
        return
    try:
        prompts = await api.get('/api/internal/attendance/prompts')
    except Exception as e:
        print(f'attendance_loop: fetch failed: {e}')
        return
    for p in prompts:
        uid = p['discord_user_id']
        try:
            user = await client.fetch_user(int(uid))
            await user.send(attendance_text(p['screenings']), view=attendance_view(p['screenings']))
        except discord.Forbidden:
            _dm_fallback[uid] = p['screenings']   # DMs closed: ask on their next command
        except Exception as e:
            print(f'attendance_loop: DM to {uid} failed: {e}')
            continue                              # try again next run
        try:
            await api.post('/api/internal/attendance/prompted', {
                'discord_user_id': uid, 'showtime_ids': [s['showtime_id'] for s in p['screenings']]})
        except Exception as e:
            print(f'attendance_loop: marking prompted failed: {e}')


@attendance_loop.before_loop
async def before_attendance():
    await client.wait_until_ready()


# ─── Your alerts by DM (R8) ───────────────────────────────────────────────────
# A film on your watchlist got showings, tickets went on sale…: the site
# bundles each person's news per scrape run; this sends it. Nights wait for
# the morning. DMs closed: the alert is still in the site's bell.

@tasks.loop(seconds=60)
async def notify_loop():
    if not 8 <= datetime.now(ET).hour < 23:
        return
    try:
        pending = await api.get('/api/internal/notifications/dm')
    except Exception as e:
        print(f'notify_loop: fetch failed: {e}')
        return
    for p in pending:
        try:
            user = await client.fetch_user(int(p['discord_user_id']))
            await user.send(embed=embeds.alerts_embed(p['items'], p.get('title')))
            for post_id in [r for r in p.get('reviews') or [] if r]:          # game posts waiting for this admin (R14)
                await games.send_review(user, p['discord_user_id'], post_id)
        except discord.Forbidden:
            pass                                   # DMs closed: the bell has it
        except Exception as e:
            print(f"notify_loop: DM to {p['discord_user_id']} failed: {e}")
            continue                               # try again next run
        try:
            await api.post('/api/internal/notifications/dm-sent', {'ids': p['ids']})
        except Exception as e:
            print(f'notify_loop: marking sent failed: {e}')


@notify_loop.before_loop
async def before_notify():
    await client.wait_until_ready()


class NotifyView(discord.ui.View):
    """Toggles under /notifications (only you see them)."""

    def __init__(self, ident, settings):
        super().__init__(timeout=600)
        self.ident = ident
        for key, label in embeds.NOTIFY_CHANNELS:
            if not settings['available'].get(key):
                continue
            on = settings['channels'][key]
            b = discord.ui.Button(label=f"{label}: {'on' if on else 'off'}", row=0,
                                  style=discord.ButtonStyle.success if on else discord.ButtonStyle.secondary)
            b.callback = self._toggle(key, not on)
            self.add_item(b)
        types = discord.ui.Select(placeholder='Which alerts you get', min_values=0, row=1,
                                  max_values=len(settings['types_info']),
                                  options=[discord.SelectOption(label=t['label'][:100], value=t['key'],
                                                                description=t['hint'][:100],
                                                                default=settings['types'][t['key']])
                                           for t in settings['types_info']])
        types.callback = self._types(types, [t['key'] for t in settings['types_info']])
        self.add_item(types)
        if settings.get('searches'):
            stop = discord.ui.Select(placeholder='Stop alerts for a saved search…', row=2,
                                     options=[discord.SelectOption(label=x['label'][:100], value=str(x['id']))
                                              for x in settings['searches'][:25]])
            stop.callback = self._stop(stop)
            self.add_item(stop)

    def _toggle(self, key, value):
        async def callback(interaction):
            await self.save(interaction, {'channels': {key: value}})
        return callback

    def _stop(self, select):
        async def callback(interaction):
            await self.save(interaction, {'remove_search': int(select.values[0])})
        return callback

    def _types(self, select, keys):
        async def callback(interaction):
            await self.save(interaction, {'types': {k: k in select.values for k in keys}})
        return callback

    async def save(self, interaction, change):
        await interaction.response.defer()
        try:
            s = await api.post('/api/internal/notifications/settings', {**self.ident, **change})
        except Exception as e:
            print(f'/notifications save failed: {e}')
            await tell(interaction, "Couldn't save that — try again in a bit.")
            return
        await interaction.edit_original_response(embed=embeds.notify_settings_embed(s), view=NotifyView(self.ident, s))


class AskView(discord.ui.View):
    """The one-time "how should we tell you?" question (opt-in notifications):
    each button saves one yes; "No thanks" closes it. Only the asker sees it."""

    def __init__(self, ident, choices):
        super().__init__(timeout=900)
        self.ident = ident
        for label, change in choices:
            b = discord.ui.Button(label=label, style=discord.ButtonStyle.success)
            b.callback = self._save(b, change)
            self.add_item(b)
        done = discord.ui.Button(label='No thanks', style=discord.ButtonStyle.secondary)
        done.callback = self._done
        self.add_item(done)

    def _save(self, button, change):
        async def callback(interaction):
            await interaction.response.defer()
            try:
                await api.post('/api/internal/notifications/settings', {**self.ident, **change})
            except Exception as e:
                print(f'opt-in save failed: {e}')
                await tell(interaction, "Couldn't save that — try `/notifications`.")
                return
            button.disabled, button.label = True, f'✓ {button.label}'
            await interaction.edit_original_response(view=self)
        return callback

    async def _done(self, interaction):
        await interaction.response.edit_message(
            content='Got it. Change this any time with `/notifications`.', view=None)


ASK_ALERTS = ('🔔 Want to hear when a theatre books (or announces) films on your watchlist? '
              'Nothing is sent unless you choose. Every alert also shows in the bell on the site.')
ASK_SEARCH = ('🔔 Want a DM when a theatre books a film that fits your saved searches (or one on your watchlist)? '
              'Nothing is sent unless you choose. Every alert also shows in the bell on the site.')
ASK_ATTENDANCE = ('🎟️ Want a DM after screenings you\'re going to, to log whether you made it? '
                  'It keeps your history (and kernels) right. Nothing is sent unless you choose.')


async def ask_after_watch(interaction, result):
    """First watchlist add: ask how (if at all) to hear about watchlist news."""
    if not result.get('alert_prompt'):
        return
    choices = [('DM me', {'channels': {'discord': True}})]
    if result.get('digest_choice') == 'ask':
        choices.append(('Mention me in the Monday digest', {'digest_mentions': True}))
    await interaction.followup.send(ASK_ALERTS, view=AskView(discord_identity(interaction), choices), ephemeral=True)


async def ask_after_going(interaction, result):
    """First "Going": ask about "Did you make it?" DMs."""
    if result.get('attendance_prompt'):
        await interaction.followup.send(ASK_ATTENDANCE, ephemeral=True, view=AskView(
            discord_identity(interaction), [('Yes, DM me', {'types': {'attendance': True}})]))


@client.tree.command(name='notifications', description='What alerts you get (watchlist, saved searches…) and where')
async def notifications_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    ident = discord_identity(interaction)
    try:
        s = await api.post('/api/internal/notifications/settings', ident)
    except Exception as e:
        await reply_failure(interaction, e, '/notifications', 'Settings lookup failed ({status}).')
        return
    await interaction.followup.send(embed=embeds.notify_settings_embed(s), view=NotifyView(ident, s), ephemeral=True)


@client.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    """Members with DMs closed get the "did you go?" prompt privately after
    their next command instead."""
    screenings = _dm_fallback.pop(str(interaction.user.id), None)
    if not screenings:
        return
    try:
        await interaction.followup.send(attendance_text(screenings), view=attendance_view(screenings),
                                        ephemeral=True)
    except Exception as e:                        # e.g. the command answered with a form
        _dm_fallback[str(interaction.user.id)] = screenings
        print(f'attendance fallback prompt failed: {e}')


async def fetch_alerts():
    return await api.get('/api/internal/alerts', group_id=DEFAULT_GROUP_ID)


@client.tree.command(name='announcements',
                     description="New-showtime posts in the channel: which theatres post here, or turn one on/off")
@app_commands.describe(
    action="Show what's on (default); Enable posts a theatre's new showtimes here; Disable stops them",
    theatre='The theatre to turn on or off',
)
@app_commands.choices(action=[
    app_commands.Choice(name='Show', value='show'),
    app_commands.Choice(name='Enable', value='enable'),
    app_commands.Choice(name='Disable', value='disable'),
])
async def announcements(interaction: discord.Interaction,
                        action: app_commands.Choice[str] = None, theatre: str = None):
    act = action.value if action else 'show'
    if act == 'show':
        await interaction.response.defer(ephemeral=True)
        try:
            enabled = (await fetch_alerts()).get('enabled', [])
        except Exception as e:
            await reply_failure(interaction, e, '/announcements show')
            return
        if enabled:
            msg = (f"🔔 New showtimes are announced here for **{', '.join(t['name'] for t in enabled)}**.\n"
                   "Every other theatre's new showtimes are in Monday's digest. "
                   "`/announcements action:Disable` turns one off. (Your own alerts: `/notifications`.)")
        else:
            msg = ("🔕 Theatre announcements are all off — new showtimes show up in Monday's digest.\n"
                   "`/announcements action:Enable` posts a theatre's new showtimes here as they drop.")
        await interaction.followup.send(msg, ephemeral=True)
        return

    if not theatre:
        await interaction.response.send_message('Pick a theatre to turn on or off.', ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        result = await api.post('/api/internal/alerts', {
            'group_id': DEFAULT_GROUP_ID, 'theatre_slug': theatre, 'action': act,
        })
    except ApiError as e:
        msg = "I don't know that theatre — pick one from the list." if e.status == 404 \
            else f"Couldn't update announcements ({e.status})."
        await interaction.followup.send(msg, ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, f'/announcements {act}')
        return

    name = result['theatre_name']
    if not result['changed']:
        state = 'on' if result['enabled'] else 'off'
        await interaction.followup.send(f"**{name}** announcements are already {state}.", ephemeral=True)
        return
    # Everyone sees what changed (and who changed it) — the setting is shared.
    who = interaction.user.mention
    note = (f"🔔 {who} turned on new-showtime announcements for **{name}** — its drops will post here."
            if result['enabled'] else
            f"🔕 {who} turned off new-showtime announcements for **{name}** — "
            "its new showtimes will be in Monday's digest.")
    try:
        await interaction.channel.send(note, allowed_mentions=discord.AllowedMentions.none())
    except Exception as e:
        print(f'/announcements: channel note failed: {e}')
    await interaction.followup.send('Done ✓', ephemeral=True)


@announcements.autocomplete('theatre')
async def announcements_theatre_autocomplete(interaction: discord.Interaction, current: str):
    # Enable suggests theatres that are off; Disable suggests ones that are on.
    action = getattr(interaction.namespace, 'action', None)
    choices = await theatre_choices(current)
    if action in ('enable', 'disable'):
        try:
            enabled = set((await fetch_alerts()).get('slugs', []))
        except Exception:
            return choices
        choices = [c for c in choices if (c.value in enabled) == (action == 'disable')]
    return choices


DIGEST_COOLDOWN_SEC = 30 * 60
_digest_posted = {}   # channel id -> monotonic time of the last /digest post there


@client.tree.command(name='digest', description="This week's digest — post it here, or preview it just for you")
@app_commands.describe(preview='Show it only to you instead of posting it in the channel')
async def digest_now(interaction: discord.Interaction, preview: bool = False):
    if preview:
        await interaction.response.defer(ephemeral=True)
        try:
            digest = await api.get('/api/internal/digest', group_id=DEFAULT_GROUP_ID, days=7)
        except Exception as e:
            await reply_failure(interaction, e, '/digest preview')
            return
        _, embed, _, plans = embeds.digest_message(digest)
        await interaction.followup.send(embed=embed, view=threads.plans_view(plans), ephemeral=True)
        return

    # Anyone can post it, so keep the channel from getting spammed.
    ago = time.monotonic() - _digest_posted.get(interaction.channel_id, -DIGEST_COOLDOWN_SEC)
    if ago < DIGEST_COOLDOWN_SEC:
        mins = max(1, round(ago / 60))
        await interaction.response.send_message(
            f"The digest was posted here {mins} min ago — use `/digest preview:True` to see it just for you.",
            ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if await post_digest(interaction.channel):   # manual posts never tag anyone
        _digest_posted[interaction.channel_id] = time.monotonic()
        await interaction.followup.send('Digest posted.', ephemeral=True)
    else:
        await interaction.followup.send("Couldn't post the digest right now — try again in a bit.", ephemeral=True)


register(items=(AttendanceButton,), loops=(announce_loop, digest_loop, attendance_loop, notify_loop,))

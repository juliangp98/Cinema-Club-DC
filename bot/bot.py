"""Cinema Club DC Discord bot.

Announces theatre schedule drops in #movies, posts a Monday digest, and
serves slash commands (/showtimes, /movie, /rsvp, /whosgoing, /polls, /link).
All data comes from the Flask backend's /api/internal/* endpoints — the bot
never touches the database directly.
"""

import os
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

# Load env BEFORE importing api/embeds (they read env at import time).
# Docker supplies env via env_file; locally we borrow the backend's env files.
_here = Path(__file__).resolve().parent
for candidate in (_here / '.env',
                  _here.parent / 'backend' / '.env.development',
                  _here.parent / 'backend' / '.env'):
    if candidate.exists():
        load_dotenv(candidate)
        break

import discord
from discord import app_commands
from discord.ext import tasks

from api import InternalApi, ApiError
import embeds

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')
DISCORD_GUILD_ID = int(os.environ.get('DISCORD_GUILD_ID', '0') or 0)
DISCORD_CHANNEL_ID = int(os.environ.get('DISCORD_CHANNEL_ID', '0') or 0)
DEFAULT_GROUP_ID = int(os.environ.get('DEFAULT_GROUP_ID', '1') or 1)
SITE_URL = os.environ.get('SITE_URL', 'https://cinemaclubdc.com')

ET = ZoneInfo('America/New_York')
GUILD = discord.Object(id=DISCORD_GUILD_ID) if DISCORD_GUILD_ID else None

api = InternalApi()

intents = discord.Intents.default()


class CinemaClubBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        if GUILD:
            self.tree.copy_global_to(guild=GUILD)
            await self.tree.sync(guild=GUILD)
        else:
            await self.tree.sync()
        announce_loop.start()
        digest_loop.start()

    async def close(self):
        await api.close()
        await super().close()


client = CinemaClubBot()


def movies_channel():
    return client.get_channel(DISCORD_CHANNEL_ID)


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

    for event in events:
        try:
            if event['event_type'] in ('new_drop', 'new_showtimes'):
                await channel.send(embed=embeds.drop_embed(event))
                await notify_watchers(channel, event)
            elif event['event_type'] == 'scrape_error':
                await channel.send(embeds.error_message(event))
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
            msg = embeds.activity_message(ev)
            if msg:
                await channel.send(msg)
            await api.post(f"/api/internal/activity-events/{ev['id']}/announced")
        except Exception as e:
            print(f"announce_loop: activity failed for {ev.get('id')}: {e}")


async def notify_watchers(channel, event):
    """Ping members whose watchlisted movies just got showtimes."""
    try:
        matches = await api.get('/api/internal/watch-matches', event_id=event['id'])
    except Exception as e:
        print(f'watch-matches failed for event {event.get("id")}: {e}')
        return
    for m in matches:
        when = datetime.fromisoformat(m['first_showtime']).strftime('%A %-m/%-d %-I:%M %p')
        await channel.send(
            f"👀 <@{m['discord_user_id']}> — **{m['movie_title']}**, from your watchlist, "
            f"just got showtimes at {m['theatre_name']} (first: {when}) → "
            f"{SITE_URL}/?showtime={m['showtime_id']}")


@announce_loop.before_loop
async def before_announce():
    await client.wait_until_ready()


# ─── Weekly digest (Mondays 10:00 ET) ─────────────────────────────────────────

@tasks.loop(time=dtime(hour=10, minute=0, tzinfo=ET))
async def digest_loop():
    if datetime.now(ET).weekday() != 0:   # Monday only
        return
    await post_digest()


@digest_loop.before_loop
async def before_digest():
    await client.wait_until_ready()


async def post_digest():
    channel = movies_channel()
    if channel is None:
        return
    try:
        digest = await api.get('/api/internal/digest', group_id=DEFAULT_GROUP_ID, days=7)
        await channel.send(embed=embeds.digest_embed(digest))
    except Exception as e:
        print(f'digest failed: {e}')


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def fetch_window(days, search=None):
    now = datetime.now()
    return await api.get(
        '/api/internal/showtimes',
        group_id=DEFAULT_GROUP_ID,
        start=now.isoformat(timespec='seconds'),
        end=(now + timedelta(days=days)).isoformat(timespec='seconds'),
        q=search,
    )


def _fmt_choice(s):
    dt = datetime.fromisoformat(s['start_time'])
    theatre = s['theatre'].get('short_name') or s['theatre']['name']
    label = f"{dt.strftime('%a %-m/%-d %-I:%M %p')} — {s['movie']['title']} ({theatre})"
    return label[:100]


# ─── Slash commands ───────────────────────────────────────────────────────────

@client.tree.command(name='link', description='Link your Discord to your Cinema Club DC account')
@app_commands.describe(code='The 6-character code from your profile menu on the site')
async def link(interaction: discord.Interaction, code: str):
    try:
        result = await api.post('/api/internal/link/verify', {
            'code': code, 'discord_user_id': str(interaction.user.id),
            'discord_username': interaction.user.name,
        })
        await interaction.response.send_message(
            f"🔗 Linked! You're **{result['user']['name']}** on Cinema Club DC. "
            f"You can now `/rsvp` right from Discord.", ephemeral=True)
    except ApiError as e:
        msg = 'That code is invalid.' if e.status == 404 else \
              'That code expired — grab a fresh one from your profile menu on the site.' if e.status == 410 else \
              f'Linking failed ({e.status}).'
        await interaction.response.send_message(msg, ephemeral=True)


@client.tree.command(name='showtimes', description="What's playing across the club's theatres")
@app_commands.describe(days='How many days ahead (default 7)', theatre='Filter by theatre name')
async def showtimes(interaction: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7,
                    theatre: str | None = None):
    await interaction.response.defer()
    sts = await fetch_window(days)
    if theatre:
        t = theatre.lower()
        sts = [s for s in sts if t in s['theatre']['name'].lower()
               or t in (s['theatre'].get('short_name') or '').lower()
               or t in s['theatre']['slug'].lower()]
    title = f"🎬 Showtimes — next {days} day{'s' if days != 1 else ''}"
    if theatre:
        title += f" · {theatre}"
    await interaction.followup.send(embed=embeds.showtimes_embed(sts[:120], title))


@client.tree.command(name='movie', description='Details + upcoming showtimes for a movie')
@app_commands.describe(title='Movie title')
async def movie(interaction: discord.Interaction, title: str):
    await interaction.response.defer()
    sts = await fetch_window(30, search=title)
    if not sts:
        await interaction.followup.send(f"Nothing upcoming matching **{title}**.")
        return
    await interaction.followup.send(embed=embeds.movie_embed(sts[:60], sts[0]['movie']))


@movie.autocomplete('title')
async def movie_autocomplete(interaction: discord.Interaction, current: str):
    try:
        sts = await fetch_window(30, search=current or None)
    except Exception:
        return []
    titles = []
    for s in sts:
        t = s['movie']['title']
        if t not in titles:
            titles.append(t)
    return [app_commands.Choice(name=t[:100], value=t[:100]) for t in titles[:25]]


@client.tree.command(name='rsvp', description='RSVP to a screening right from Discord')
@app_commands.describe(showtime='Pick a screening', status='Are you going?')
@app_commands.choices(status=[
    app_commands.Choice(name='Going', value='going'),
    app_commands.Choice(name='Maybe', value='maybe'),
    app_commands.Choice(name="Can't go", value='not_going'),
])
async def rsvp(interaction: discord.Interaction, showtime: str, status: app_commands.Choice[str]):
    try:
        result = await api.post('/api/internal/rsvp', {
            'discord_user_id': str(interaction.user.id),
            'showtime_id': int(showtime),
            'status': status.value,
            'group_id': DEFAULT_GROUP_ID,
        })
    except ApiError as e:
        if e.status == 404:
            await interaction.response.send_message(
                "You haven't linked your account yet — open your profile on "
                f"{SITE_URL}, hit **Link Discord**, then run `/link <code>`.", ephemeral=True)
        else:
            await interaction.response.send_message(f'RSVP failed ({e.status}).', ephemeral=True)
        return
    except ValueError:
        await interaction.response.send_message('Pick a screening from the list.', ephemeral=True)
        return

    dt = datetime.fromisoformat(result['start_time'])
    theatre = result['theatre'].get('short_name') or result['theatre']['name']
    verb = {'going': 'is going to', 'maybe': 'might go to', 'not_going': "can't make"}[status.value]
    going_count = len(result.get('attendees', []))
    suffix = f" ({going_count} going)" if going_count else ''
    await interaction.response.send_message(
        f"🎟️ **{result['user']['name']}** {verb} **{result['movie']['title']}** — "
        f"{dt.strftime('%A %-m/%-d %-I:%M %p')} at {theatre}{suffix}")


@rsvp.autocomplete('showtime')
async def rsvp_autocomplete(interaction: discord.Interaction, current: str):
    try:
        sts = await fetch_window(14, search=current or None)
    except Exception:
        return []
    return [app_commands.Choice(name=_fmt_choice(s), value=str(s['id'])) for s in sts[:25]]


@client.tree.command(name='whosgoing', description="Who's RSVP'd this week")
@app_commands.describe(days='How many days ahead (default 7)')
async def whosgoing(interaction: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7):
    await interaction.response.defer()
    sts = await fetch_window(days)
    going = [s for s in sts if s.get('attendees') or s.get('maybes')]
    embed = embeds.showtimes_embed(
        going, f"🎟️ Who's going — next {days} days",
        empty_text=f"No RSVPs yet for the next {days} days. Be the first: `/rsvp` or {SITE_URL}")
    await interaction.followup.send(embed=embed)


@client.tree.command(name='polls', description='Open polls and predictions')
async def polls(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        open_polls = await api.get('/api/internal/polls', group_id=DEFAULT_GROUP_ID)
    except ApiError:
        open_polls = []
    if not open_polls:
        await interaction.followup.send(f'No open polls right now. Start one: {SITE_URL}/polls')
        return
    lines = [f"🗳️ **{p['title']}** — vote at {SITE_URL}/polls/{p['id']}" for p in open_polls[:10]]
    await interaction.followup.send('\n'.join(lines))


@client.tree.command(name='watch', description="Watchlist a movie — I'll ping you when it gets showtimes")
@app_commands.describe(title='Movie title')
async def watch(interaction: discord.Interaction, title: str):
    try:
        result = await api.post('/api/internal/watch', {
            'discord_user_id': str(interaction.user.id), 'title': title,
        })
    except ApiError as e:
        if e.status == 404 and 'linked' in e.body.lower():
            await interaction.response.send_message(
                f"Link your account first: profile menu on {SITE_URL} → **Link Discord** → `/link <code>`.",
                ephemeral=True)
        else:
            await interaction.response.send_message(
                f"Couldn't find **{title}** — try `/movie` to check what's tracked.", ephemeral=True)
        return
    if result['watching']:
        await interaction.response.send_message(
            f"👀 **{result['user_name']}** is watching for **{result['movie_title']}** showtimes.")
    else:
        await interaction.response.send_message(
            f"Removed **{result['movie_title']}** from your watchlist.", ephemeral=True)


@watch.autocomplete('title')
async def watch_autocomplete(interaction: discord.Interaction, current: str):
    try:
        sts = await fetch_window(60, search=current or None)
    except Exception:
        return []
    titles = []
    for s in sts:
        t = s['movie']['title']
        if t not in titles:
            titles.append(t)
    return [app_commands.Choice(name=t[:100], value=t[:100]) for t in titles[:25]]


@client.tree.command(name='leaderboard', description='Season kernel standings 🍿')
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        rows = await api.get('/api/internal/leaderboard', group_id=DEFAULT_GROUP_ID)
    except ApiError:
        rows = []
    if not rows:
        await interaction.followup.send('No standings yet — vote in a poll!')
        return
    medals = ['🥇', '🥈', '🥉']
    lines = []
    for i, r in enumerate(rows[:10]):
        badge = medals[i] if i < 3 else f'{i + 1}.'
        lines.append(f"{badge} **{r['user']['name']}** — 🍿 {r['kernels']} "
                     f"({r['correct']} correct · {r['attendance']} movies attended)")
    embed = discord.Embed(title='🍿 Kernel Leaderboard', description='\n'.join(lines),
                          colour=embeds.AMBER, url=f'{SITE_URL}/leaderboard')
    await interaction.followup.send(embed=embed)


@client.tree.command(name='digest', description='Post the weekly digest now')
async def digest_now(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await post_digest()
    await interaction.followup.send('Digest posted.', ephemeral=True)


@client.event
async def on_ready():
    print(f'Logged in as {client.user} — announcing to channel {DISCORD_CHANNEL_ID}')


if __name__ == '__main__':
    if not DISCORD_BOT_TOKEN:
        raise SystemExit('DISCORD_BOT_TOKEN is not set')
    client.run(DISCORD_BOT_TOKEN)

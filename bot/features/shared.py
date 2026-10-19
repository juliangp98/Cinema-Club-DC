"""What every part of the bot uses: settings, the client and its command tree, the
backend API, the owner DM, the failure messages, date/theatre helpers and the
shared autocompletes — and the registry each feature adds its buttons and loops to.
"""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv


# Load env BEFORE importing api/embeds (they read env at import time).
# Docker supplies env via env_file; locally we borrow the backend's env files.
_here = Path(__file__).resolve().parent.parent      # bot/
for candidate in (_here / '.env',
                  _here.parent / 'backend' / '.env.development',
                  _here.parent / 'backend' / '.env'):
    if candidate.exists():
        load_dotenv(candidate)
        break

import discord                                   # noqa: E402 — after the env is loaded
from discord import app_commands                 # noqa: E402
from api import InternalApi, ApiError            # noqa: E402
import llm                                       # noqa: E402

DISCORD_BOT_TOKEN = os.environ.get('DISCORD_BOT_TOKEN', '')
DISCORD_CHANNEL_ID = int(os.environ.get('DISCORD_CHANNEL_ID', '0') or 0)
DEFAULT_GROUP_ID = int(os.environ.get('DEFAULT_GROUP_ID', '1') or 1)
SITE_URL = os.environ.get('SITE_URL', 'https://cinemaclubdc.com')

ET = ZoneInfo('America/New_York')
# Commands are synced globally (see setup_hook) — no guild ID needed.

api = InternalApi()

intents = discord.Intents.default()
# Privileged intent — REQUIRED for the typed-name "what is thy wisdom" trigger and
# the ambient quote triggers to read messages that don't @-mention the bot. Also
# enable "Message Content Intent" in the Discord Developer Portal (Bot settings)
# or the gateway connection will fail / message content will arrive empty.
intents.message_content = True
# Privileged intent — who's in the club's server. Only members who've linked
# Discord and are in it ever appear there (names, pings, their shares); the
# bot keeps the site's list current (member_sync). Enable "Server Members
# Intent" in the Developer Portal too.
intents.members = True


# Each feature module registers its persistent buttons (DynamicItems), its
# background loops and anything to run at start; setup_hook starts them all.
_registry = {'items': [], 'loops': [], 'startup': []}


def register(items=(), loops=(), startup=()):
    _registry['items'].extend(items)
    _registry['loops'].extend(loops)
    _registry['startup'].extend(startup)


class CinemaClubBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        try:
            # Sweep every server the bot is CURRENTLY in and clear any
            # guild-scoped commands left over from earlier per-guild syncs
            # (this bot was pointed at different guilds via DISCORD_GUILD_ID
            # at different times while testing; a guild that isn't the
            # *current* value never got cleaned up and keeps showing its old
            # guild command definitions side-by-side with the new global
            # ones). Uses fetch_guilds() (a direct API call) rather than
            # self.guilds, since the gateway-populated cache isn't ready yet
            # this early in startup. Cheap and a no-op once a guild is clean,
            # so it's safe to run on every restart.
            async for guild in self.fetch_guilds(limit=None):
                try:
                    self.tree.clear_commands(guild=guild)
                    await self.tree.sync(guild=guild)
                except Exception as e:
                    print(f'Could not clear guild-scoped commands in '
                          f'{guild.id} ({guild.name}): {e!r}')

            # Global sync — slash commands work in every server the bot is
            # added to (takes up to ~1h to first appear in a server; instant
            # to update after that).
            synced = await self.tree.sync()
            print(f'Synced {len(synced)} global commands '
                  f'(every server the bot is in; up to ~1h to first appear)')
        except Exception as e:
            print(f'Command sync FAILED: {e!r}')
        # In the background so a slow Groq never delays the bot coming online.
        asyncio.create_task(setup_llm())
        for job in _registry['startup']:
            asyncio.create_task(job())
        for item in _registry['items']:
            self.add_dynamic_items(item)          # their buttons work across restarts
        for loop in _registry['loops']:
            loop.start()

    async def close(self):
        await api.close()
        await super().close()


client = CinemaClubBot()


async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    """Safety net: any exception a command doesn't catch itself still gets a
    reply instead of leaving the interaction to die silently as 'did not respond'."""
    name = interaction.command.name if interaction.command else '?'
    print(f'/{name} error: {error}')
    msg = "Something went wrong running that command — try again in a bit."
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass  # interaction token already expired — nothing more we can do


client.tree.on_error = on_tree_error


_owner = {}


async def dm_owner(text):
    """DM the bot's owner (the Discord application's owner) — for things the
    channel doesn't need to see, like scraper errors and chatbot model switches."""
    try:
        if 'user' not in _owner:
            info = await client.application_info()
            _owner['user'] = info.team.owner if info.team else info.owner
        await _owner['user'].send(text[:2000])
    except Exception as e:
        print(f'owner DM failed: {e}')


async def setup_llm():
    """The AI lives in the backend now (shared with the site, R6a): point the
    chatbot at it and warm its model choice."""
    llm.configure(api)
    try:
        await llm.status()
    except Exception as e:
        print(f'llm: AI status check failed: {e}')


def movies_channel():
    return client.get_channel(DISCORD_CHANNEL_ID)


NO_ACCOUNT_MSG = ("Use this in the Cinema Club server first — that sets up your account "
                  "(no site sign-up needed).")


def discord_identity(interaction):
    """Identity fields every personal internal call sends. Discord members need
    no site account: used inside the club's server (the one with #movies), the
    backend creates a Discord-only account on first use and adds them to the
    group. Elsewhere (DMs, other servers) only existing accounts are used."""
    user = interaction.user
    channel = movies_channel()
    home = getattr(getattr(channel, 'guild', None), 'id', None)
    avatar = getattr(user, 'display_avatar', None)
    return {
        'discord_user_id': str(user.id),
        'discord_name': getattr(user, 'display_name', None) or user.name,
        'discord_username': user.name,
        'discord_avatar': str(avatar.url) if avatar else None,
        'create': '1' if home and interaction.guild_id == home else '0',
        'group_id': DEFAULT_GROUP_ID,
    }


def no_account(err):
    return isinstance(err, ApiError) and err.status == 404 and 'no_account' in (err.body or '')


READ_ONLY_MSG = "You're read-only in this club, so you can follow along but not RSVP, vote or comment. Ask an admin to change that."


def read_only(err):
    """The site refused because the member is read-only in the club (R5c)."""
    return isinstance(err, ApiError) and err.status == 403 and 'read_only' in (err.body or '')


UNREACHABLE_MSG = "Couldn't reach the server — try again in a bit."
GONE_MSG = "That screening isn't on the calendar anymore."


def api_error_text(e):
    """The server's own words for a refused request, if it gave any."""
    try:
        return json.loads(e.body).get('error') or f"That didn't work ({e.status})."
    except (ValueError, TypeError, AttributeError):
        return f"That didn't work ({e.status})."


def api_failure(e, fallback=None, missing=None):
    """The one wording for a failed internal API call: the server couldn't be
    reached; use the club's server first (no account yet); you're read-only;
    `missing` for a 404 when given; else `fallback` ({status} filled in) or
    the server's own words."""
    if not isinstance(e, ApiError):
        return UNREACHABLE_MSG
    if no_account(e):
        return NO_ACCOUNT_MSG
    if read_only(e):
        return READ_ONLY_MSG
    if missing and e.status == 404:
        return missing
    return fallback.replace('{status}', str(e.status)) if fallback else api_error_text(e)


async def tell(interaction, msg, ephemeral=True, **kwargs):
    """A message as the reply, or as a follow-up once the interaction was
    answered (deferred)."""
    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=ephemeral, **kwargs)
    else:
        await interaction.response.send_message(msg, ephemeral=ephemeral, **kwargs)


async def reply_failure(interaction, e, what, fallback=None, missing=None, ephemeral=True):
    """Say an internal call failed (api_failure's wording) — as the reply, or
    a follow-up after a defer — logging anything the server didn't refuse."""
    if not isinstance(e, ApiError):
        print(f'{what} failed: {e}')
    await tell(interaction, api_failure(e, fallback, missing), ephemeral=ephemeral)


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


async def fetch_range(start_iso, end_iso, search=None, limit=300, tickets=None):
    return await api.get(
        '/api/internal/showtimes',
        group_id=DEFAULT_GROUP_ID,
        start=start_iso, end=end_iso, q=search, limit=limit, tickets=tickets,
    )


def theatre_match(showtimes, theatre):
    """Client-side theatre filter shared by the picker commands. Returns
    (filtered, label) where label is the friendly theatre name for titles."""
    if not theatre:
        return showtimes, None
    t = theatre.lower()
    filtered = [s for s in showtimes
                if t in s['theatre']['slug'].lower()
                or t in s['theatre']['name'].lower()
                or t in (s['theatre'].get('short_name') or '').lower()]
    label = filtered[0]['theatre']['name'] if filtered else theatre
    return filtered, label


# Theatre list changes rarely; cache it so autocomplete (which fires per
# keystroke) doesn't hit the backend on every character.
_theatre_cache = {'data': None, 'ts': 0.0}


async def fetch_theatres():
    if _theatre_cache['data'] is None or time.monotonic() - _theatre_cache['ts'] > 300:
        _theatre_cache['data'] = await api.get('/api/internal/theatres', group_id=DEFAULT_GROUP_ID)
        _theatre_cache['ts'] = time.monotonic()
    return _theatre_cache['data']


async def theatre_choices(current):
    """Autocomplete choices for a theatre parameter, filtered by typed text."""
    try:
        theatres = await fetch_theatres()
    except Exception:
        return []
    cur = (current or '').lower()
    matches = [t for t in theatres
               if not cur
               or cur in t['name'].lower()
               or cur in (t.get('short_name') or '').lower()
               or cur in t['slug'].lower()]
    return [app_commands.Choice(name=t['name'], value=t['slug']) for t in matches[:25]]


def date_choices(current):
    """Upcoming dates for a date-filter parameter. Value is an ISO date the
    showtime autocomplete uses to narrow to that day."""
    today = datetime.now().date()
    cur = (current or '').lower()
    out = []
    for i in range(30):
        d = today + timedelta(days=i)
        label = 'Today' if i == 0 else 'Tomorrow' if i == 1 else d.strftime('%a, %b %-d')
        iso = d.isoformat()
        if not cur or cur in label.lower() or cur in iso or cur in d.strftime('%-m/%-d'):
            out.append(app_commands.Choice(name=label, value=iso))
        if len(out) >= 25:
            break
    return out


def parse_iso_date(value):
    """Return a date object if value is a YYYY-MM-DD string, else None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def resolve_window(days, date=None, end=None):
    """Turn the (days / date / end) filter trio into ISO (start, end) bounds for
    the /api/internal/showtimes endpoint. A single `date` means just that day; a
    `date`+`end` pair means an inclusive range; neither means the next N days.
    Returns (start_iso, end_iso, label) — label describes the window for titles."""
    day = parse_iso_date(date)
    if day:
        last = parse_iso_date(end) or day
        if last < day:
            last = day
        start = datetime.combine(day, dtime.min)
        finish = datetime.combine(last, dtime.max)
        if last == day:
            label = day.strftime('%a %-m/%-d')
        else:
            label = f"{day.strftime('%a %-m/%-d')} – {last.strftime('%a %-m/%-d')}"
        return start.isoformat(timespec='seconds'), finish.isoformat(timespec='seconds'), label
    now = datetime.now()
    return (now.isoformat(timespec='seconds'),
            (now + timedelta(days=days)).isoformat(timespec='seconds'),
            f"next {days} day{'s' if days != 1 else ''}")


# ─── Dependent autocompletes ──────────────────────────────────────────────────
# Options narrow to what's actually available given the sibling selections a
# user has made (e.g. pick a movie -> only its dates/theatres). The backend
# facets endpoint returns distinct dates/theatres for the current filter.

async def fetch_facets(title=None, theatre=None, start=None, end=None):
    return await api.get('/api/internal/showtime-facets', group_id=DEFAULT_GROUP_ID,
                         q=title, theatre=theatre, start=start, end=end)


def _dates_to_choices(dates, current, after=None):
    """Build date Choices from ISO date strings, filtered by typed text and an
    optional lower bound (for range 'end' fields)."""
    cur = (current or '').lower()
    today = datetime.now().date()
    out = []
    for iso in dates:
        if after and iso < after:
            continue
        try:
            d = datetime.strptime(iso, '%Y-%m-%d').date()
        except ValueError:
            continue
        label = ('Today' if d == today else 'Tomorrow' if d == today + timedelta(days=1)
                 else d.strftime('%a, %b %-d'))
        if not cur or cur in label.lower() or cur in iso or cur in d.strftime('%-m/%-d'):
            out.append(app_commands.Choice(name=label, value=iso))
        if len(out) >= 25:
            break
    return out


def _theatres_to_choices(theatres, current):
    cur = (current or '').lower()
    out = []
    for t in theatres:
        if (not cur or cur in t['name'].lower()
                or cur in (t.get('short_name') or '').lower() or cur in t['slug'].lower()):
            out.append(app_commands.Choice(name=t['name'], value=t['slug']))
        if len(out) >= 25:
            break
    return out


async def dynamic_date_ac(interaction, current, title_attr=None):
    """Date options narrowed to a selected movie (title_attr) and/or theatre."""
    title = getattr(interaction.namespace, title_attr, None) if title_attr else None
    theatre = getattr(interaction.namespace, 'theatre', None)
    if not title and not theatre:
        return date_choices(current)
    try:
        facets = await fetch_facets(title=title, theatre=theatre)
    except Exception:
        return date_choices(current)
    return _dates_to_choices(facets.get('dates', []), current)


async def dynamic_end_ac(interaction, current, title_attr=None):
    """Range-end options: same as date, but only on/after the chosen start date."""
    title = getattr(interaction.namespace, title_attr, None) if title_attr else None
    theatre = getattr(interaction.namespace, 'theatre', None)
    start = parse_iso_date(getattr(interaction.namespace, 'date', None))
    after = start.isoformat() if start else None
    if not title and not theatre:
        return date_choices(current)
    try:
        facets = await fetch_facets(title=title, theatre=theatre)
    except Exception:
        return date_choices(current)
    return _dates_to_choices(facets.get('dates', []), current, after=after)


async def dynamic_theatre_ac(interaction, current, title_attr=None):
    """Theatre options narrowed to a selected movie (title_attr) and/or date range."""
    title = getattr(interaction.namespace, title_attr, None) if title_attr else None
    date = getattr(interaction.namespace, 'date', None)
    end = getattr(interaction.namespace, 'end', None)
    day = parse_iso_date(date)
    start_iso = end_iso = None
    if day:
        start_iso, end_iso, _ = resolve_window(0, date, end)
    if not title and not day:
        return await theatre_choices(current)
    try:
        facets = await fetch_facets(title=title, start=start_iso, end=end_iso)
    except Exception:
        return await theatre_choices(current)
    return _theatres_to_choices(facets.get('theatres', []), current)


def _fmt_choice(s):
    dt = datetime.fromisoformat(s['start_time'])
    theatre = s['theatre'].get('short_name') or s['theatre']['name']
    label = f"{dt.strftime('%a %-m/%-d %-I:%M %p')} — {s['movie']['title']} ({theatre})"
    return label[:100]


# Autocompletes for a screening picker (date, end, theatre, then the showing);
# /rsvp and /discuss attach them.
async def rsvp_date_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_date_ac(interaction, current)


async def rsvp_end_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_end_ac(interaction, current)


async def rsvp_theatre_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_theatre_ac(interaction, current)


async def rsvp_showtime_autocomplete(interaction: discord.Interaction, current: str):
    # Read the sibling filters the user has already set to narrow the list.
    date = getattr(interaction.namespace, 'date', None)
    end = getattr(interaction.namespace, 'end', None)
    theatre = getattr(interaction.namespace, 'theatre', None)
    # No date set -> default to a 14-day picker window; else honor the range.
    default_days = 14
    if parse_iso_date(date):
        start_iso, end_iso, _ = resolve_window(default_days, date, end)
    else:
        now = datetime.now()
        start_iso = now.isoformat(timespec='seconds')
        end_iso = (now + timedelta(days=default_days)).isoformat(timespec='seconds')
    try:
        sts = await fetch_range(start_iso, end_iso, search=current or None)
    except Exception:
        return []
    sts, _ = theatre_match(sts, theatre)
    return [app_commands.Choice(name=_fmt_choice(s), value=str(s['id'])) for s in sts[:25]]


@client.event
async def on_ready():
    print(f'Logged in as {client.user} — announcing to channel {DISCORD_CHANNEL_ID}')

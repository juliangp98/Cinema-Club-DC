"""What every part of the bot uses: settings, the client and its command tree, the
backend API, the owner DM, the failure messages, date/theatre helpers and the
shared autocompletes — and the registry each feature adds its buttons and loops to.
"""

import asyncio
import contextvars
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
SITE_NAME = os.environ.get('SITE_NAME') or 'Cinema Club DC'      # the backend's setting (one .env.production)

# Clocks: every club is on its city's (cities.py on the backend). Until the
# backend has said, the first city's.
DEFAULT_ZONE = ZoneInfo('America/New_York')
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
        _startup['backend'] = asyncio.create_task(wait_for_backend())
        asyncio.create_task(_after_backend(setup_llm))
        for job in _registry['startup']:
            asyncio.create_task(_after_backend(job))
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


# The containers start together, so the backend can still be getting ready
# (bringing the database up to date) when the bot logs in.
BACKEND_WAIT_SEC = 120
_startup = {}


async def wait_for_backend():
    """Returns once the backend answers (any answer), or after BACKEND_WAIT_SEC."""
    deadline = time.monotonic() + BACKEND_WAIT_SEC
    while True:
        try:
            await api.get('/api/internal/servers')
            return True
        except ApiError:
            return True                       # it answered
        except Exception:
            if time.monotonic() > deadline:
                print(f'backend: still unreachable after {BACKEND_WAIT_SEC}s; carrying on')
                return False
            await asyncio.sleep(3)


async def backend_ready():
    """Wait for the start-up check, if one is running (tests never start one)."""
    task = _startup.get('backend')
    if task is not None:
        await asyncio.shield(task)


async def _after_backend(job):
    await backend_ready()
    await job()


async def setup_llm():
    """The AI lives in the backend now (shared with the site, R6a): point the
    chatbot at it and warm its model choice."""
    llm.configure(api)
    try:
        await llm.status()
    except Exception as e:
        print(f'llm: AI status check failed: {e}')


def movies_channel():
    """The home server's channel (DISCORD_CHANNEL_ID): the bot's first server."""
    return client.get_channel(DISCORD_CHANNEL_ID)


# ─── Servers: which club each is ──────────────────────────────────────────────
# One server, one club. The map comes from the backend (connected with /setup;
# the home server registered by the bot at start) and is refreshed every few
# minutes. Before the home server is registered, its channel's server is the
# home club's (DEFAULT_GROUP_ID) — as before servers were per club.

_servers = {}                    # guild id → {'group_id', 'channel_id', 'home', 'city', 'tz'}
_cities = {'multi': False, 'default': 'dc', 'zone': DEFAULT_ZONE, 'short': {}, 'names': {}}   # from /api/cities
_UNSET = object()
# The club the current interaction (or loop pass) is for: set by the tree's
# check, by discord_identity, and by the loops for each server — so helpers
# deep in a command (fetch_window, autocompletes…) ask about the right club.
_club = contextvars.ContextVar('club', default=_UNSET)
_dm_last = {}                    # Discord user id → (club, when): the last club picked in DMs
DM_PICK_KEEP = 30 * 60           # buttons in a DM follow the pick for this long


def _home_guild_id():
    return getattr(getattr(movies_channel(), 'guild', None), 'id', None)


async def refresh_servers():
    """Load the server → club map from the backend."""
    try:
        rows = await api.get('/api/internal/servers')
    except Exception as e:
        print(f'servers: refresh failed: {e}')
        return
    _servers.clear()
    for r in rows:
        if str(r.get('guild_id') or '').isdigit():
            _servers[int(r['guild_id'])] = {'group_id': r.get('group_id'), 'home': bool(r.get('home')),
                                            'channel_id': int(r['channel_id']) if str(r.get('channel_id') or '').isdigit() else None,
                                            'city': r.get('city'), 'tz': r.get('tz')}
    try:
        got = await api.get('/api/cities')
        first = next((c for c in got['cities'] if c['slug'] == got.get('default')), got['cities'][0])
        _cities.update(multi=bool(got.get('multi')), default=first['slug'], zone=ZoneInfo(first['tz']),
                       short={c['slug']: c['short'] for c in got['cities']},
                       names={c['slug']: c['name'] for c in got['cities']})
    except Exception as e:
        print(f'servers: cities refresh failed: {e}')


def club_zone(group_id=None):
    """A club's clock (its city's); the current club's if none is named."""
    gid = group_id if group_id is not None else club()
    tz = next((s['tz'] for s in _servers.values() if s['group_id'] == gid and s.get('tz')), None)
    return ZoneInfo(tz) if tz else _cities['zone']


def club_now(group_id=None):
    """The wall-clock time at a club (naive, like showtimes)."""
    return datetime.now(club_zone(group_id)).replace(tzinfo=None)


def zone_now(tz):
    """The time somewhere (a person's zone, from the backend), as a naive local time."""
    try:
        zone = ZoneInfo(tz) if tz else _cities['zone']
    except Exception:
        zone = _cities['zone']
    return datetime.now(zone).replace(tzinfo=None)


def club_city(group_id=None):
    """The club's city slug (the current club's if none is named)."""
    gid = group_id if group_id is not None else club()
    return next((s['city'] for s in _servers.values() if s['group_id'] == gid and s.get('city')), None) \
        or _cities['default']


def where_args(city=None):
    """What to send for a command's `city` option: the club (its theatres,
    who's going), or — another city asked for — that city's public view."""
    if city and city != club_city():
        return {'city': city}
    return {'group_id': club(), 'city': club_city()}


async def city_choices(current):
    """Autocomplete for a `city` option: the cities with theatres."""
    cur = (current or '').lower()
    return [app_commands.Choice(name=name, value=slug) for slug, name in _cities['names'].items()
            if not cur or cur in name.lower() or cur in slug][:25]


def club_for_guild(guild_id):
    """The club connected to this server, or None (not connected yet)."""
    if not guild_id:
        return None
    s = _servers.get(int(guild_id))
    if s:
        return s['group_id']
    return DEFAULT_GROUP_ID if guild_id == _home_guild_id() else None


def is_home_guild(guild_id):
    s = _servers.get(int(guild_id or 0))
    return bool(s and s['home']) or (guild_id is not None and guild_id == _home_guild_id())


def connected_clubs():
    """Every club with a server the bot can post in: [(group_id, guild_id)]."""
    out = [(s['group_id'], gid) for gid, s in _servers.items() if s['group_id']]
    home = _home_guild_id()
    if not any(g == DEFAULT_GROUP_ID for g, _ in out) and movies_channel() is not None:
        out.append((DEFAULT_GROUP_ID, home))
    return out


def channel_for(group_id):
    """The channel this club's server posts in (None: no server, or the bot can't see it)."""
    for s in _servers.values():
        if s['group_id'] == group_id and s['channel_id']:
            ch = client.get_channel(s['channel_id'])
            if ch is not None:
                return ch
    return movies_channel() if group_id == DEFAULT_GROUP_ID else None


def use_club(group_id):
    """This task works for `group_id` from here on (a loop pass, a command)."""
    _club.set(group_id)


def club_of(interaction=None):
    """The club this interaction is for: its server's (None: not connected),
    or in DMs the one picked (the menu, or the last pick for buttons)."""
    c = _club.get()
    if c is not _UNSET:
        return c
    guild_id = getattr(interaction, 'guild_id', None)
    if guild_id:
        return club_for_guild(guild_id)
    return dm_club(getattr(getattr(interaction, 'user', None), 'id', None))


def dm_club(user_id):
    """In DMs with no menu (a message, a button): the last club picked, else the home club."""
    last = _dm_last.get(user_id)
    return last[0] if last and time.monotonic() - last[1] < DM_PICK_KEEP else DEFAULT_GROUP_ID


def club():
    """The current task's club (the home club if nothing set it)."""
    c = _club.get()
    return DEFAULT_GROUP_ID if c is _UNSET else c


NO_ACCOUNT_MSG = ("Use this in your club's Discord server first — that sets up your account "
                  "(no site sign-up needed).")
NOT_CONNECTED_MSG = ("This server isn't connected to a club yet. A server admin can connect it: make a code in "
                     "Club settings → Discord on the site, then run /setup here. (/showtimes, /movie, /find, "
                     "/surprise and /theatre work meanwhile.)")


def discord_identity(interaction):
    """Identity fields every personal internal call sends, with the club it's
    for. Discord members need no site account: used inside a connected club's
    server, the backend creates a Discord-only account on first use and adds
    them to that club. Elsewhere (DMs, unconnected servers) only existing
    accounts are used."""
    user = interaction.user
    group_id = club_of(interaction)
    if _club.get() is _UNSET:
        _club.set(group_id)
    avatar = getattr(user, 'display_avatar', None)
    guild_id = getattr(interaction, 'guild_id', None)
    return {
        'discord_user_id': str(user.id),
        'discord_name': getattr(user, 'display_name', None) or user.name,
        'discord_username': user.name,
        'discord_avatar': str(avatar.url) if avatar else None,
        'create': '1' if guild_id and group_id else '0',
        'group_id': group_id,
        'guild_id': str(guild_id) if guild_id else None,
    }


def no_account(err):
    return isinstance(err, ApiError) and err.status == 404 and 'no_account' in (err.body or '')


READ_ONLY_MSG = "You're read-only in this club, so you can follow along but not RSVP, vote or comment. Ask an admin to change that."


def read_only(err):
    """The site refused because the member is read-only in the club (R5c)."""
    return isinstance(err, ApiError) and err.status == 403 and 'read_only' in (err.body or '')


UNREACHABLE_MSG = "Couldn't reach the server — try again in a bit."
GONE_MSG = "That screening isn't on the calendar anymore."
DIGEST_OFF_MSG = ("The Monday digest is off for this club — an organizer can turn it on in Club settings → Theatres "
                  "on the site. `/digest preview:True` still shows it just to you.")


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
    now = club_now()
    return await api.get(
        '/api/internal/showtimes',
        group_id=club(),
        start=now.isoformat(timespec='seconds'),
        end=(now + timedelta(days=days)).isoformat(timespec='seconds'),
        q=search,
    )


async def fetch_range(start_iso, end_iso, search=None, limit=300, tickets=None, city=None):
    return await api.get(
        '/api/internal/showtimes',
        **where_args(city),
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
_theatre_cache = {}              # club → (when, theatres)


async def fetch_theatres():
    """{theatres (the club's first, each saying its city), multi, city}."""
    hit = _theatre_cache.get(club())
    if hit is None or time.monotonic() - hit[0] > 300:
        hit = _theatre_cache[club()] = (time.monotonic(), await api.get(
            '/api/internal/theatres', group_id=club(), city=club_city()))
    return hit[1]


def theatre_label(t, multi):
    """A theatre's name — with its city when it isn't the club's and there's more than one."""
    if multi and not t.get('yours'):
        return f"{t['name']} ({_cities['short'].get(t.get('city'), t.get('city'))})"
    return t['name']


async def theatre_choices(current):
    """Autocomplete choices for a theatre parameter, filtered by typed text:
    the club's theatres first, other cities' labelled."""
    try:
        got = await fetch_theatres()
    except Exception:
        return []
    cur = (current or '').lower()
    matches = [t for t in got['theatres']
               if not cur
               or cur in t['name'].lower()
               or cur in (t.get('short_name') or '').lower()
               or cur in t['slug'].lower()]
    return [app_commands.Choice(name=theatre_label(t, got.get('multi'))[:100], value=t['slug']) for t in matches[:25]]


def date_choices(current):
    """Upcoming dates for a date-filter parameter. Value is an ISO date the
    showtime autocomplete uses to narrow to that day."""
    today = club_now().date()
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
    now = club_now()
    return (now.isoformat(timespec='seconds'),
            (now + timedelta(days=days)).isoformat(timespec='seconds'),
            f"next {days} day{'s' if days != 1 else ''}")


# ─── Dependent autocompletes ──────────────────────────────────────────────────
# Options narrow to what's actually available given the sibling selections a
# user has made (e.g. pick a movie -> only its dates/theatres). The backend
# facets endpoint returns distinct dates/theatres for the current filter.

async def fetch_facets(title=None, theatre=None, start=None, end=None):
    return await api.get('/api/internal/showtime-facets', group_id=club(),
                         q=title, theatre=theatre, start=start, end=end)


def _dates_to_choices(dates, current, after=None):
    """Build date Choices from ISO date strings, filtered by typed text and an
    optional lower bound (for range 'end' fields)."""
    cur = (current or '').lower()
    today = club_now().date()
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
        now = club_now()
        start_iso = now.isoformat(timespec='seconds')
        end_iso = (now + timedelta(days=default_days)).isoformat(timespec='seconds')
    try:
        sts = await fetch_range(start_iso, end_iso, search=current or None)
    except Exception:
        return []
    sts, _ = theatre_match(sts, theatre)
    return [app_commands.Choice(name=_fmt_choice(s), value=str(s['id'])) for s in sts[:25]]

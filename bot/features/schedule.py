"""What's playing: /link, /showtimes, /movie, /rsvp, /watch, /find, /surprise,
/foryou and /theatre.
"""

import time
from datetime import datetime, timedelta
import discord
from discord import app_commands
from api import ApiError
import embeds
from .shared import (GONE_MSG, SITE_NAME, SITE_URL, api, city_choices, client, club, club_city, club_now, club_of, date_choices, discord_identity,
                     dynamic_date_ac, dynamic_end_ac, dynamic_theatre_ac, fetch_range, fetch_window, where_args,
                     parse_iso_date, register, reply_failure, resolve_window, rsvp_date_autocomplete,
                     rsvp_end_autocomplete, rsvp_showtime_autocomplete, rsvp_theatre_autocomplete, tell,
                     theatre_choices, theatre_match)
from . import alerts, threads      # used at call time, so the order they load in doesn't matter


# ─── Slash commands ───────────────────────────────────────────────────────────

@client.tree.command(name='link', description='Optional: connect your Discord to an existing site account')
@app_commands.describe(code='The 6-character code from your profile menu on the site')
async def link(interaction: discord.Interaction, code: str):
    await interaction.response.defer(ephemeral=True)
    try:
        result = await api.post('/api/internal/link/verify', {
            'code': code, 'discord_user_id': str(interaction.user.id),
            'discord_username': interaction.user.name,
        })
        await interaction.followup.send(
            f"🔗 Linked! You're **{result['user']['name']}** on {SITE_NAME} — anything you did "
            "here (RSVPs, watchlist, profile) is now part of that account.", ephemeral=True)
    except ApiError as e:
        msg = 'That code is invalid.' if e.status == 404 else \
              'That code expired — grab a fresh one from your profile menu on the site.' if e.status == 410 else \
              f'Linking failed ({e.status}).'
        await interaction.followup.send(msg, ephemeral=True)
    except Exception as e:
        await reply_failure(interaction, e, '/link')


TICKET_CHOICES = [app_commands.Choice(name=n, value=v) for v, n in (
    ('available', 'Tickets available'), ('soldout', 'Sold out'), ('soon', 'Coming soon (announced, not on sale yet)'))]


@client.tree.command(name='showtimes', description="What's playing across the club's theatres — or who's going")
@app_commands.describe(
    days='How many days ahead (default 7; ignored if you pick a date)',
    date='Optional: a specific date (or the start of a range)',
    end='Optional: end of a date range (use with date)',
    theatre='Optional: filter to a theatre',
    going="Only screenings members RSVP'd to (who's going)",
    tickets='Optional: tickets available, sold out, or coming soon (default: all)',
    city="Optional: another city's showtimes (when the site has more than one)",
)
@app_commands.choices(tickets=TICKET_CHOICES)
async def showtimes(interaction: discord.Interaction, days: app_commands.Range[int, 1, 30] = 7,
                    date: str = None, end: str = None, theatre: str = None, going: bool = False,
                    tickets: app_commands.Choice[str] = None, city: str = None):
    await interaction.response.defer()
    start_iso, end_iso, label = resolve_window(days, date, end)
    t = tickets.value if tickets else None
    try:
        if t == 'soon':
            soon = await api.get('/api/internal/announced', **where_args(city), theatre=theatre,
                                 start=start_iso[:10], end=end_iso[:10])
            await interaction.followup.send(embed=embeds.announced_embed(soon, f"🔜 Coming soon — {label}"))
            return
        sts = await fetch_range(start_iso, end_iso, tickets=t, city=city)
    except Exception as e:
        await reply_failure(interaction, e, '/showtimes', ephemeral=False)
        return
    sts, theatre_label = theatre_match(sts, theatre)
    if going:
        sts = [s for s in sts if s.get('attendees') or s.get('maybes') or s.get('attendees_more') or s.get('maybes_more')]
    title = ("🎟️ Who's going" if going else '🎬 Showtimes') + f' — {label}'
    if theatre_label:
        title += f" · {theatre_label}"
    if t:
        title += f" · {dict((c.value, c.name) for c in TICKET_CHOICES)[t]}"
    empty = (f"No RSVPs yet for {label}. Be the first: `/rsvp` or {SITE_URL}/calendar" if going
             else 'Nothing on the calendar for that window.')
    await interaction.followup.send(embed=embeds.showtimes_embed(sts[:120], title, empty_text=empty))


@showtimes.autocomplete('city')
async def showtimes_city_autocomplete(interaction: discord.Interaction, current: str):
    return await city_choices(current)


@showtimes.autocomplete('theatre')
async def showtimes_theatre_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_theatre_ac(interaction, current)


@showtimes.autocomplete('date')
async def showtimes_date_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_date_ac(interaction, current)


@showtimes.autocomplete('end')
async def showtimes_end_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_end_ac(interaction, current)


@client.tree.command(name='movie', description='Details + upcoming showtimes for a movie')
@app_commands.describe(
    title='Movie title',
    theatre='Optional: only show this theatre',
    date='Optional: a specific date (or the start of a range)',
    end='Optional: end of a date range (use with date)',
)
async def movie(interaction: discord.Interaction, title: str,
                theatre: str = None, date: str = None, end: str = None):
    await interaction.response.defer()
    start_iso, end_iso, label = resolve_window(30, date, end)
    sts = await fetch_range(start_iso, end_iso, search=title)
    sts, theatre_label = theatre_match(sts, theatre)
    if not sts:
        where = f" at {theatre_label}" if theatre_label else ''
        # only mention the window when the user actually narrowed it
        window = '' if (date is None) else f" ({label})"
        await interaction.followup.send(f"Nothing matching **{title}**{where}{window}.")
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


@movie.autocomplete('theatre')
async def movie_theatre_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_theatre_ac(interaction, current, 'title')


@movie.autocomplete('date')
async def movie_date_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_date_ac(interaction, current, 'title')


@movie.autocomplete('end')
async def movie_end_autocomplete(interaction: discord.Interaction, current: str):
    return await dynamic_end_ac(interaction, current, 'title')


@client.tree.command(name='rsvp', description='RSVP to a screening right from Discord')
@app_commands.describe(
    date='Optional: narrow the screening list to a date (or start of a range)',
    end='Optional: end of a date range (use with date)',
    theatre='Optional: narrow the screening list to a theatre',
    showtime='The screening (narrows as you set date/theatre, or type a movie)',
    status='Going, maybe, or can\'t go (defaults to Going)',
)
@app_commands.choices(status=[
    app_commands.Choice(name='Going', value='going'),
    app_commands.Choice(name='Maybe', value='maybe'),
    app_commands.Choice(name="Can't go", value='not_going'),
])
async def rsvp(interaction: discord.Interaction, date: str = None, end: str = None,
               theatre: str = None, showtime: str = None,
               status: app_commands.Choice[str] = None):
    await interaction.response.defer()
    if not showtime:
        await interaction.followup.send(
            'Pick a screening from the **showtime** list (set **date**/**theatre** first to narrow it).',
            ephemeral=True)
        return

    status_value = status.value if status else 'going'
    try:
        result = await api.post('/api/internal/rsvp', {
            **discord_identity(interaction), 'showtime_id': int(showtime), 'status': status_value,
        })
    except ValueError:
        await interaction.followup.send('Pick a screening from the list.', ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/rsvp', 'RSVP failed ({status}).', GONE_MSG)
        return

    dt = datetime.fromisoformat(result['start_time'])
    theatre_name = result['theatre'].get('short_name') or result['theatre']['name']
    verb = {'going': 'is going to', 'maybe': 'might go to', 'not_going': "can't make"}[status_value]
    lines = [f"🎟️ {interaction.user.mention} {verb} **{result['movie']['title']}** — "
             f"{dt.strftime('%A %-m/%-d %-I:%M %p')} at {theatre_name}"]
    # List everyone else already going to this screening (members who aren't
    # in this server are only counted).
    going, on_site = [a['name'] for a in result.get('attendees', [])], result.get('attendees_more') or 0
    if going or on_site:
        who = embeds.more_on_site(going[:12], on_site, max(0, len(going) - 12))
        lines.append(f"🍿 Going ({len(going) + on_site}): {who}")
    await interaction.followup.send('\n'.join(lines), view=threads.discuss_view(int(showtime)))
    await alerts.ask_after_going(interaction, result)


rsvp.autocomplete('date')(rsvp_date_autocomplete)
rsvp.autocomplete('end')(rsvp_end_autocomplete)
rsvp.autocomplete('theatre')(rsvp_theatre_autocomplete)
rsvp.autocomplete('showtime')(rsvp_showtime_autocomplete)


async def fetch_my_watchlist(interaction, member_id=None, start=None, end=None):
    return await api.get('/api/internal/watchlist', **discord_identity(interaction),
                         member_id=member_id, start=start, end=end)


@client.tree.command(name='watch', description='Watchlist: add, remove, or show a member\'s list')
@app_commands.describe(
    action='Add to / remove from your watchlist, or show a list (default Add)',
    title='Any film — playing or not (for Add/Remove)',
    member='Whose watchlist to show (default you)',
    date='Show only: a date (or start of a range) to filter the list',
    end='Show only: end of a date range (use with date)',
)
@app_commands.choices(action=[
    app_commands.Choice(name='Add', value='add'),
    app_commands.Choice(name='Remove', value='remove'),
    app_commands.Choice(name='Show', value='show'),
])
async def watch(interaction: discord.Interaction, action: app_commands.Choice[str] = None,
                title: str = None, member: str = None, date: str = None, end: str = None):
    # Add & Show are public — they're engaging for the group. Remove is a
    # private one-off, so it (and its replies) stay ephemeral. Visibility is
    # locked at defer time, so decide it from the action up front.
    act = action.value if action else 'add'
    eph = (act == 'remove')
    await interaction.response.defer(ephemeral=eph)

    if act == 'show':
        member_id = int(member) if (member and member.isdigit()) else None
        start_iso = end_iso = window_label = None
        if parse_iso_date(date):
            start_iso, end_iso, window_label = resolve_window(0, date, end)
        try:
            data = await fetch_my_watchlist(interaction, member_id, start_iso, end_iso)
        except Exception as e:
            await reply_failure(interaction, e, '/watch show', 'Watchlist lookup failed ({status}).', ephemeral=eph)
            return
        await interaction.followup.send(
            embed=embeds.watchlist_embed(data.get('items', []), data.get('owner', 'Someone'),
                                         window_label),
            ephemeral=eph)
        return

    # add / remove
    if not title:
        await interaction.followup.send('Pick a movie to add or remove.', ephemeral=eph)
        return
    try:
        result = await api.post('/api/internal/watch', {
            **discord_identity(interaction), 'title': title, 'action': act,
        })
    except Exception as e:
        await reply_failure(interaction, e, '/watch', f"Couldn't find **{title}** — try `/movie` to check what's tracked.",
                            ephemeral=eph)
        return

    if result['watching']:
        # Public, engaging callout.
        await interaction.followup.send(
            f"{interaction.user.mention} is watching for **{result['movie_title']}** showtimes.")
        await alerts.ask_after_watch(interaction, result)
    else:
        await interaction.followup.send(
            f"Removed **{result['movie_title']}** from your watchlist.", ephemeral=True)


@watch.autocomplete('title')
async def watch_title_autocomplete(interaction: discord.Interaction, current: str):
    action = getattr(interaction.namespace, 'action', None)
    cur = (current or '').lower()
    # For Remove, suggest what's actually on the caller's watchlist.
    if action == 'remove':
        try:
            data = await fetch_my_watchlist(str(interaction.user.id))
            titles = [it['title'] for it in data.get('items', [])]
        except Exception:
            titles = []
    elif len(cur) >= 2:
        # Any film (R8c): ours first (playing, then the catalog), then TMDB's.
        try:
            found = await api.get('/api/internal/films/find', q=current)
        except Exception:
            found = []
        return [app_commands.Choice(name=f['name'][:100], value=f['value'][:100]) for f in found[:25]]
    else:
        try:
            sts = await fetch_window(60)
        except Exception:
            sts = []
        titles = []
        for s in sts:
            t = s['movie']['title']
            if t not in titles:
                titles.append(t)
    matches = [t for t in titles if not cur or cur in t.lower()]
    return [app_commands.Choice(name=t[:100], value=t[:100]) for t in matches[:25]]


@watch.autocomplete('member')
async def watch_member_autocomplete(interaction: discord.Interaction, current: str):
    try:
        members = await api.get('/api/internal/members', group_id=club())
    except Exception:
        return []
    cur = (current or '').lower()
    matches = [m for m in members if not cur or cur in m['name'].lower()]
    return [app_commands.Choice(name=m['name'], value=str(m['id'])) for m in matches[:25]]


@watch.autocomplete('date')
async def watch_date_autocomplete(interaction: discord.Interaction, current: str):
    return date_choices(current)


@watch.autocomplete('end')
async def watch_end_autocomplete(interaction: discord.Interaction, current: str):
    return date_choices(current)


# ─── /find and /surprise ──────────────────────────────────────────────────────
# The site's Discover engine, in Discord: a short list of a kind of film, or
# one random pick. Both post in the channel (private:True keeps it to you) and
# need no account; an existing one personalizes "For you" and "Your list".

WHEN_CHOICES = [app_commands.Choice(name=n, value=v) for v, n in (
    ('tonight', 'Tonight'), ('tomorrow', 'Tomorrow'), ('weekend', 'This weekend'),
    ('week', 'Next 7 days'), ('2weeks', 'Next 2 weeks'), ('month', 'Next 30 days'))]
_find_options_cache = {}           # club → (when, options)


async def fetch_find_options():
    hit = _find_options_cache.get(club())
    if hit is None or time.monotonic() - hit[0] > 600:
        hit = _find_options_cache[club()] = (time.monotonic(),
                                             await api.get('/api/internal/discover/options', group_id=club(), city=club_city()))
    return hit[1]


def viewer_args(interaction, city=None):
    """Who's asking, for personal touches only (never creates an account) —
    and what about: the club, or another city it asked for (its public view)."""
    args = {'discord_user_id': str(interaction.user.id), 'group_id': club_of(interaction), 'city': club_city()}
    if city and city != club_city():
        args.update(group_id=None, city=city)
    return args


async def type_ac(interaction, current):
    try:
        types_ = (await fetch_find_options())['types']
    except Exception:
        return []
    cur = (current or '').strip().lower()
    hits = [t for t in types_ if not cur or cur in t['label'].lower() or cur in t['hint'].lower()]
    # Typing something that isn't on the list still works (it's read as words).
    out = [app_commands.Choice(name=f"{t['label']} — {t['hint']}"[:100], value=t['value']) for t in hits[:25]]
    if cur and not hits:
        out = [app_commands.Choice(name=f'Find “{current.strip()}”'[:100], value=current.strip()[:100])]
    return out


async def where_ac(interaction, current):
    cur = (current or '').strip().lower()
    try:
        regions = (await fetch_find_options())['regions']
    except Exception:
        regions = []
    out = [app_commands.Choice(name=f"Anywhere in {r['label']}", value=r['value'])
           for r in regions if not cur or cur in r['label'].lower()]
    for c in await theatre_choices(current):
        out.append(app_commands.Choice(name=c.name, value=f'theatre:{c.value}'))
    return out[:25]


class FindPickSelect(discord.ui.DynamicItem[discord.ui.Select], template=r'find:pick'):
    """"Pick a film" under a /find list: that film's showtimes, privately,
    with Going buttons for the next few and a Discuss button."""
    def __init__(self, options=None):
        super().__init__(discord.ui.Select(custom_id='find:pick', placeholder='Pick a film for showtimes…',
                                           options=options or [discord.SelectOption(label='—', value='0')]))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        values = (interaction.data or {}).get('values') or []
        if not values or not values[0].isdigit():
            await interaction.response.defer()
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_film_details(interaction, int(values[0]))


async def send_film_details(interaction, movie_id):
    now = club_now()
    try:
        sts = await api.get('/api/internal/showtimes', group_id=club(), movie_id=movie_id,
                            start=now.isoformat(timespec='seconds'),
                            end=(now + timedelta(days=30)).isoformat(timespec='seconds'), limit=60)
    except Exception as e:
        await reply_failure(interaction, e, 'film details')
        return
    if not sts:
        await interaction.followup.send('No upcoming showings for that one anymore.', ephemeral=True)
        return
    view = discord.ui.View(timeout=None)
    for s in sts[:3]:
        theatre = s['theatre'].get('short_name') or s['theatre']['name']
        when = datetime.fromisoformat(s['start_time']).strftime('%a %-m/%-d %-I:%M %p')
        view.add_item(threads.ThreadRsvpButton('going', s['id'], label=f'Going · {when} · {theatre}'))
    view.add_item(threads.DiscussButton(sts[0]['id']))
    await interaction.followup.send(embed=embeds.movie_embed(sts, sts[0]['movie']), view=view, ephemeral=True)


class FindAlertButton(discord.ui.DynamicItem[discord.ui.Button], template=r'find:alert'):
    """🔔 Alert me under /find: saves the search (the site's saved searches) —
    read back from the card's own link, so it works after a restart. What
    reaches you, and how, is still your choice (asked the first time)."""
    def __init__(self):
        super().__init__(discord.ui.Button(label='🔔 Alert me', style=discord.ButtonStyle.secondary, custom_id='find:alert'))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        from urllib.parse import parse_qsl, urlparse
        embed = (interaction.message.embeds or [None])[0] if interaction.message else None
        params = dict(parse_qsl(urlparse(embed.url).query)) if embed and embed.url else {}
        try:
            r = await api.post('/api/internal/searches', {**discord_identity(interaction), 'params': params})
        except Exception as e:
            await reply_failure(interaction, e, 'find alert')
            return
        fits = r['fitting_now']
        now = f" ({embeds.plural(fits, 'film fits', 'films fit')} already — those won't alert)" if fits else ''
        how = "I'll DM you" if r.get('dm') else "it'll show in the bell on the site (`/notifications` turns on DMs)"
        await interaction.followup.send(f"🔔 Saved **{r['search']['label']}**{now}. When a theatre books a film that fits, "
                                        f"{how}. Stop it any time in `/notifications`.", ephemeral=True)
        if r.get('alert_prompt'):
            await interaction.followup.send(alerts.ASK_SEARCH, ephemeral=True, view=alerts.AskView(
                discord_identity(interaction), [('DM me', {'channels': {'discord': True}})]))


def find_view(result, alert=False):
    """Pick a film (its showtimes), the Browse link, and (on /find) Alert me."""
    view = discord.ui.View(timeout=None)
    films = result['films']
    if films:
        view.add_item(FindPickSelect([
            discord.SelectOption(
                label=(f"{c['movie']['title']} ({c['movie']['year']})" if c['movie'].get('year')
                       else c['movie']['title'])[:100],
                description=(f"{datetime.fromisoformat(c['next']['start_time']).strftime('%a %-m/%-d %-I:%M %p')}"
                             f" · {c['next']['theatre']}")[:100],
                value=str(c['movie']['id']))
            for c in films[:25]]))
    total = result['total']
    label = f'See all {total} on the site' if total > len(films) else 'Open on the site'
    view.add_item(discord.ui.Button(label=label, url=f"{SITE_URL}{result['browse_path']}"))
    if alert and result.get('params'):
        view.add_item(FindAlertButton())
    return view


@client.tree.command(name='find', description='Find films by kind: rare, arthouse, a mood, a genre…')
@app_commands.describe(
    type='What kind of film: rare, one night only, arthouse, a mood, a genre… (or type your own words)',
    when='When (default: next 7 days)',
    where='An area or theatre',
    search='Words in the title, director or cast',
    private='Show the answer only to you instead of posting it',
    city="Optional: another city (when the site has more than one)",
)
@app_commands.choices(when=WHEN_CHOICES)
async def find(interaction: discord.Interaction, type: str = None, when: app_commands.Choice[str] = None,
               where: str = None, search: str = None, private: bool = False, city: str = None):
    await interaction.response.defer(ephemeral=private)
    try:
        result = await api.get('/api/internal/discover/find', **viewer_args(interaction, city), type=type,
                               when=when.value if when else None, where=where, q=search, limit=8)
    except Exception as e:
        await reply_failure(interaction, e, '/find')
        return
    await interaction.followup.send(embed=embeds.find_embed(result), view=find_view(result, alert=True))


@find.autocomplete('type')
async def find_type_autocomplete(interaction: discord.Interaction, current: str):
    return await type_ac(interaction, current)


@find.autocomplete('city')
async def find_city_autocomplete(interaction: discord.Interaction, current: str):
    return await city_choices(current)


@find.autocomplete('where')
async def find_where_autocomplete(interaction: discord.Interaction, current: str):
    return await where_ac(interaction, current)


SURPRISE_ID = r'sur:(?P<when>[a-z0-9]+):(?P<where>[^:]*):(?P<ex>[0-9,]*)'


def _where_code(where):
    """'region:dc' -> 'r.dc', 'theatre:afi' -> 't.afi' (custom ids can't spare the colons)."""
    w = (where or '').strip()
    if w.startswith('region:'):
        return 'r.' + w[7:]
    if w.startswith('theatre:'):
        return 't.' + w[8:]
    return w.replace(':', ' ')[:30]


def _where_value(code):
    if code.startswith('r.'):
        return 'region:' + code[2:]
    if code.startswith('t.'):
        return 'theatre:' + code[2:]
    return code or None


def _surprise_id(when, where_code, seen):
    seen = [str(x) for x in seen]
    while seen and len(f'sur:{when}:{where_code}:{",".join(seen)}') > 100:
        seen.pop(0)                   # forget the oldest picks first
    return f'sur:{when}:{where_code}:{",".join(seen)}'


class SpinButton(discord.ui.DynamicItem[discord.ui.Button], template=SURPRISE_ID):
    """🎲 Spin again — swaps the card for another pick (never one already shown)."""
    def __init__(self, when, where_code, seen):
        super().__init__(discord.ui.Button(label='🎲 Spin again', style=discord.ButtonStyle.primary,
                                           custom_id=_surprise_id(when, where_code, seen)))
        self.when, self.where_code, self.seen = when, where_code, list(seen)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['when'], match['where'], [int(x) for x in match['ex'].split(',') if x])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            pick = await api.get('/api/internal/discover/surprise', **viewer_args(interaction), when=self.when,
                                 where=_where_value(self.where_code), exclude=','.join(map(str, self.seen)))
        except ApiError as e:
            msg = ("That's everything playing — no more spins left." if e.status == 404
                   else f'Spin failed ({e.status}).')
            await tell(interaction, msg)
            return
        except Exception as e:
            await reply_failure(interaction, e, 'spin')
            return
        await interaction.edit_original_response(
            embed=embeds.surprise_embed(pick, self.when, spun_by=interaction.user.display_name),
            view=surprise_view(pick, self.when, self.where_code, self.seen))


def surprise_view(pick, when, where_code, seen=()):
    view = discord.ui.View(timeout=None)
    view.add_item(SpinButton(when, where_code, [*seen, pick['movie']['id']]))
    view.add_item(threads.ThreadRsvpButton('going', pick['next']['showtime_id'], label="🎟️ I'm in"))
    view.add_item(discord.ui.Button(label='Film page', url=f"{SITE_URL}/films/{pick['movie']['id']}"))
    return view


@client.tree.command(name='surprise', description='One random pick: rare, the club’s favorites and your taste weigh in')
@app_commands.describe(
    when='When (default: tonight; widens to the week if tonight is empty)',
    where='An area or theatre',
    private='Show the pick only to you instead of posting it',
    city="Optional: another city (when the site has more than one)",
)
@app_commands.choices(when=WHEN_CHOICES)
async def surprise(interaction: discord.Interaction, when: app_commands.Choice[str] = None,
                   where: str = None, private: bool = False, city: str = None):
    await interaction.response.defer(ephemeral=private)
    w = when.value if when else 'tonight'
    try:
        pick = await api.get('/api/internal/discover/surprise', **viewer_args(interaction, city), when=w, where=where)
    except ApiError as e:
        msg = "Nothing's playing that matches — try a wider `when` or another `where`." if e.status == 404 \
            else f'Surprise failed ({e.status}).'
        await interaction.followup.send(msg, ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/surprise')
        return
    await interaction.followup.send(
        embed=embeds.surprise_embed(pick, w, spun_by=interaction.user.display_name),
        view=surprise_view(pick, w, _where_code(where)))


@surprise.autocomplete('city')
async def surprise_city_autocomplete(interaction: discord.Interaction, current: str):
    return await city_choices(current)


@surprise.autocomplete('where')
async def surprise_where_autocomplete(interaction: discord.Interaction, current: str):
    return await where_ac(interaction, current)


@client.tree.command(name='theatre', description="A theatre: where it is, what's on this week, your picks there, members' notes")
@app_commands.describe(theatre='Which theatre', private='Show it only to you instead of posting it')
async def theatre_cmd(interaction: discord.Interaction, theatre: str, private: bool = False):
    await interaction.response.defer(ephemeral=private)
    try:
        t = await api.get('/api/internal/theatre', **viewer_args(interaction), slug=theatre)
    except Exception as e:
        await reply_failure(interaction, e, '/theatre', missing="I don't know that theatre — pick one from the list.")
        return
    view = find_view({'films': t['week'], 'total': t['week_total'], 'browse_path': t['week_path']})
    view.add_item(discord.ui.Button(label='Map', url=embeds.map_url(t)))
    view.add_item(discord.ui.Button(label='Theatre page', url=f"{SITE_URL}/theatres/{t['slug']}"))
    await interaction.followup.send(embed=embeds.theatre_embed(t), view=view)


@theatre_cmd.autocomplete('theatre')
async def theatre_cmd_autocomplete(interaction: discord.Interaction, current: str):
    return await theatre_choices(current)


@client.tree.command(name='foryou', description="Films picked for you: Your taste, your watchlist, what you've seen")
async def foryou_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        result = await api.get('/api/internal/foryou', **discord_identity(interaction), limit=6)
    except Exception as e:
        await reply_failure(interaction, e, '/foryou')
        return
    await interaction.followup.send(embed=embeds.foryou_embed(result), view=find_view(result), ephemeral=True)


register(items=(FindPickSelect, FindAlertButton, SpinButton,))

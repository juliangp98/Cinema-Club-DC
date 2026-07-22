"""Discord embed builders for Cinema Club DC."""

import os
from datetime import datetime

import discord

SITE_URL = os.environ.get('SITE_URL', 'https://cinemaclubdc.com')

AMBER = discord.Colour.from_str('#e8a838')
RED = discord.Colour.from_str('#c45c3a')


def _fmt_time(iso):
    dt = datetime.fromisoformat(iso)
    return dt.strftime('%-I:%M %p')


def _fmt_day(iso):
    dt = datetime.fromisoformat(iso)
    return dt.strftime('%a %-m/%-d')


def _image_url(url):
    """Discord rejects an entire embed (400 Bad Request) if a thumbnail/image
    URL isn't a valid absolute http(s) URL. Many scraped poster URLs are
    relative paths or malformed, so drop anything that isn't clearly valid.
    (A 404 on a valid URL is fine — Discord just shows no image.)"""
    if isinstance(url, str):
        url = url.strip()
        if url.startswith(('http://', 'https://')) and ' ' not in url:
            return url
    return None


def drop_embed(event):
    """Rich announcement for a 'new_drop' scrape event."""
    p = event['payload']
    name = p.get('theatre_name') or p.get('theatre_slug', 'A theatre')
    n = p.get('new_showtime_count', 0)
    date_min, date_max = p.get('date_min'), p.get('date_max')

    if p.get('first_scrape'):
        title = f"🎬 Now tracking {name} — {n} showtimes added"
    else:
        title = f"🎬 {name} just dropped {n} new showtimes"

    desc_lines = []
    if date_min and date_max:
        lo, hi = _fmt_day(date_min), _fmt_day(date_max)
        desc_lines.append(f"**{lo} – {hi}**" if lo != hi else f"**{lo}**")

    for m in p.get('movie_summaries', [])[:8]:
        first = _fmt_day(m['first_showtime']) if m.get('first_showtime') else ''
        count = m.get('showtime_count', 0)
        plural = 's' if count != 1 else ''
        desc_lines.append(f"• **{m['title']}** — {count} showing{plural}, from {first}")

    more = len(p.get('movie_summaries', [])) - 8
    if p.get('new_movie_count', 0) > 8 and more > 0:
        desc_lines.append(f"…and more")

    embed = discord.Embed(
        title=title,
        description='\n'.join(desc_lines)[:4000],
        colour=AMBER,
        url=f"{SITE_URL}/?theatre={p.get('theatre_slug', '')}",
    )
    posters = [_image_url(m.get('poster_url')) for m in p.get('movie_summaries', [])]
    posters = [p for p in posters if p]
    if posters:
        embed.set_thumbnail(url=posters[0])
    embed.set_footer(text='Cinema Club DC — tap the title to open the calendar')
    return embed


def error_message(event):
    p = event['payload']
    name = p.get('theatre_name') or p.get('theatre_slug', 'a theatre')
    return f"⚠️ Scraper trouble at **{name}**: `{(p.get('error') or 'unknown')[:180]}` (I'll keep retrying)"


def actor_ref(name, discord_user_id):
    """@-mention when we know the person's Discord id, else fall back to their
    site display name so unlinked members still get a readable callout."""
    return f"<@{discord_user_id}>" if discord_user_id else f"**{name}**"


def activity_message(event):
    """Plain-text announcement for a site action (currently RSVPs)."""
    if event.get('kind') != 'rsvp':
        return None
    p = event['payload']
    verb = {'going': 'is going to', 'maybe': 'might go to'}.get(p.get('status'), 'RSVP’d to')
    when = ''
    if p.get('start_time'):
        when = ' — ' + datetime.fromisoformat(p['start_time']).strftime('%a %-m/%-d %-I:%M %p')
    theatre = f" at {p['theatre_name']}" if p.get('theatre_name') else ''
    link = f"\n{SITE_URL}/?showtime={p['showtime_id']}" if p.get('showtime_id') else ''
    who = actor_ref(p.get('user_name'), p.get('discord_user_id'))
    return f"🎟️ {who} {verb} **{p.get('movie_title')}**{when}{theatre}.{link}"


def group_showtimes_by_day(showtimes):
    days = {}
    for s in showtimes:
        key = s['start_time'][:10]
        days.setdefault(key, []).append(s)
    return dict(sorted(days.items()))


def _showtime_line(s, include_counts=True):
    theatre = s['theatre'].get('short_name') or s['theatre']['name']
    line = f"`{_fmt_time(s['start_time'])}` **{s['movie']['title']}** @ {theatre}"
    if s.get('is_sold_out'):
        line += ' *(sold out)*'
    if include_counts and s.get('attendees'):
        names = ', '.join(a['name'] for a in s['attendees'][:6])
        line += f" — 🎟️ {names}"
    return line


def showtimes_embed(showtimes, title, empty_text='Nothing on the calendar for that window.'):
    embed = discord.Embed(title=title, colour=AMBER, url=SITE_URL)
    if not showtimes:
        embed.description = empty_text
        return embed

    for day, day_shows in list(group_showtimes_by_day(showtimes).items())[:24]:
        heading = datetime.fromisoformat(day_shows[0]['start_time']).strftime('%A %-m/%-d')
        lines = []
        for s in day_shows:
            line = _showtime_line(s)
            if sum(len(l) + 1 for l in lines) + len(line) > 980:
                lines.append('…')
                break
            lines.append(line)
        embed.add_field(name=heading, value='\n'.join(lines)[:1024], inline=False)
    return embed


def movie_embed(showtimes, movie):
    """Detail card for one movie + its upcoming showtimes."""
    ratings = movie.get('ratings') or []
    bits = []
    if movie.get('release_year'):
        bits.append(str(movie['release_year']))
    if movie.get('director'):
        bits.append(f"dir. {movie['director']}")
    if movie.get('runtime_minutes'):
        bits.append(f"{movie['runtime_minutes']} min")
    if movie.get('content_rating'):
        bits.append(movie['content_rating'])

    desc_parts = []
    if movie.get('tagline'):
        desc_parts.append(f"*{movie['tagline']}*")
    if bits:
        desc_parts.append(' · '.join(bits))
    rating_bits = [f"{r['Source'].replace('Internet Movie Database', 'IMDb')}: {r['Value']}"
                   for r in ratings if isinstance(r, dict) and r.get('Source') and r.get('Value')]
    if movie.get('vote_average'):
        rating_bits.insert(0, f"TMDB: {movie['vote_average']:.1f}")
    if rating_bits:
        desc_parts.append(' · '.join(rating_bits[:4]))
    if movie.get('description'):
        desc_parts.append(movie['description'][:500])

    first_id = showtimes[0]['id'] if showtimes else None
    embed = discord.Embed(
        title=movie['title'],
        description='\n\n'.join(desc_parts)[:4000],
        colour=AMBER,
        url=f"{SITE_URL}/?showtime={first_id}" if first_id else SITE_URL,
    )
    thumb = _image_url(movie.get('poster_url'))
    if thumb:
        embed.set_thumbnail(url=thumb)

    for day, day_shows in list(group_showtimes_by_day(showtimes).items())[:10]:
        heading = datetime.fromisoformat(day_shows[0]['start_time']).strftime('%A %-m/%-d')
        lines = [_showtime_line(s) for s in day_shows]
        embed.add_field(name=heading, value='\n'.join(lines)[:1024], inline=False)
    return embed


def watchlist_embed(items, owner_name, window_label=None):
    """A member's watchlist — each movie with its next upcoming showtime."""
    title = f"👀 {owner_name}'s watchlist"
    if window_label:
        title += f" · {window_label}"
    embed = discord.Embed(title=title, colour=AMBER, url=SITE_URL)
    if not items:
        embed.description = ('Nothing on the watchlist for that window.'
                             if window_label else 'Watchlist is empty.')
        return embed

    lines = []
    for it in items[:40]:
        year = f" ({it['year']})" if it.get('year') else ''
        st = it.get('next_showtime')
        if st:
            theatre = st['theatre'].get('short_name') or st['theatre']['name']
            when = datetime.fromisoformat(st['start_time']).strftime('%a %-m/%-d %-I:%M %p')
            lines.append(f"• **{it['title']}**{year} — next: {when} @ {theatre}")
        else:
            lines.append(f"• **{it['title']}**{year} — *(no upcoming showtimes)*")
    embed.description = '\n'.join(lines)[:4000]
    embed.set_footer(text=f'Full watchlist → {SITE_URL}')
    return embed


def digest_embed(digest):
    group_name = (digest.get('group') or {}).get('name') or 'Cinema Club DC'
    embed = discord.Embed(
        title=f"🍿 This week at the movies — {group_name}",
        colour=AMBER,
        url=SITE_URL,
    )

    showtimes = digest.get('showtimes', [])
    going = [s for s in showtimes if s.get('attendees')]
    if going:
        lines = [_showtime_line(s) for s in going[:10]]
        embed.add_field(name="Who's going", value='\n'.join(lines)[:1024], inline=False)

    by_movie = {}
    for s in showtimes:
        by_movie.setdefault(s['movie']['title'], []).append(s)
    if by_movie:
        lines = []
        for title, sts in sorted(by_movie.items(), key=lambda kv: -len(kv[1]))[:12]:
            theatres = sorted({s['theatre'].get('short_name') or s['theatre']['name'] for s in sts})
            lines.append(f"**{title}** — {len(sts)} showings ({', '.join(theatres[:4])})")
        embed.add_field(name='Playing this week', value='\n'.join(lines)[:1024], inline=False)

    polls = digest.get('open_polls', [])
    if polls:
        lines = [f"🗳️ **{p['title']}** — [vote]({SITE_URL}/polls/{p['id']})" for p in polls[:5]]
        embed.add_field(name='Open polls', value='\n'.join(lines)[:1024], inline=False)

    drops = digest.get('recent_drops', [])
    if drops:
        lines = []
        for e in drops[:5]:
            p = e['payload']
            lines.append(f"📅 {p.get('theatre_name')} added {p.get('new_showtime_count')} showtimes")
        embed.add_field(name='New this week', value='\n'.join(lines)[:1024], inline=False)

    embed.set_footer(text=f'Full calendar → {SITE_URL}')
    return embed

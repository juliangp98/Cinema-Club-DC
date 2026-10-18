"""Discord embed builders for Cinema Club DC."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import discord

SITE_URL = os.environ.get('SITE_URL', 'https://cinemaclubdc.com')
ET = ZoneInfo('America/New_York')

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
        url=f"{SITE_URL}/calendar?theatre={p.get('theatre_slug', '')}",
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


def more_on_site(names, on_site=0, extra=0):
    """'Ana, Bo +1 · +2 on the site': `extra` more names that didn't fit, and
    members who aren't in this server, who are only ever counted (the backend
    never sends their names)."""
    text = ', '.join(names) + (f" +{extra}" if extra else '')
    if on_site:
        text += f" · +{on_site} on the site" if text else f"{on_site} on the site"
    return text


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
    link = f"\n{SITE_URL}/calendar?showtime={p['showtime_id']}" if p.get('showtime_id') else ''
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
    if s.get('format_label'):
        line += f" · {s['format_label']}"
    if s.get('is_sold_out'):
        line += ' *(sold out)*'
    if include_counts and (s.get('attendees') or s.get('attendees_more')):
        shown = s.get('attendees') or []
        line += f" — 🎟️ {more_on_site([a['name'] for a in shown[:6]], s.get('attendees_more'), max(0, len(shown) - 6))}"
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
        url=(f"{SITE_URL}/films/{movie['id']}" if movie.get('id')       # every showing, on the film page
             else f"{SITE_URL}/calendar?showtime={first_id}" if first_id else SITE_URL),
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


def profile_embed(profile, own=False):
    """A member's /profile card. `own` adds the prompts for editing it."""
    u = profile['user']
    embed = discord.Embed(title=f"🎬 {u['name']}", colour=AMBER, description=u.get('bio') or None)
    genres = ', '.join(g['label'] for g in profile.get('genres') or [])
    embed.add_field(name='Favorite genres', inline=False, value=genres or (
        'None yet — pick some below; they shape your picks (/foryou) and the chatbot\'s.' if own
        else 'Kept private' if profile.get('taste_hidden') else '—'))
    if u.get('letterboxd_username'):
        handle = u['letterboxd_username']
        embed.add_field(name='Letterboxd', value=f"[{handle}](https://letterboxd.com/{handle}/)")
    embed.add_field(name='Watchlist', value=f"{profile['watchlist_count']} films")
    embed.add_field(name='Going to', value=f"{profile['upcoming_rsvps']} upcoming")
    if profile.get('kernels'):
        embed.add_field(name='Kernels', value=f"🍿 {profile['kernels']['kernels']} ({kernel_parts(profile['kernels'])})")
    avatar = _image_url(u.get('avatar_url'))
    if avatar:
        embed.set_thumbnail(url=avatar)
    if own and not profile.get('site_account'):
        embed.set_footer(text=f"Optional: sign in at {SITE_URL} with Discord to see it all on the calendar.")
    return embed


def compare_embed(data, limit=5):
    """/compare: where you and a member line up, to plan outings together."""
    name = data.get('name', 'them')
    embed = discord.Embed(title=f"🤝 You & {name}", colour=AMBER, url=SITE_URL)

    def next_line(item):
        nxt = item.get('next')
        return (f"**{item['movie']['title']}** — next: {_when(nxt['start_time'])} @ {nxt['theatre']}"
                if nxt else f"**{item['movie']['title']}** — no showings yet")

    sections = [
        ('🎯 You both want to see', [next_line(i) for i in data.get('both_want', [])]),
        ('🎟️ You\'re both going', [_screening(i) for i in data.get('both_going', [])]),
        (f"👀 {name}'s going to something on your watchlist", [_screening(i) for i in data.get('they_go_you_want', [])]),
        (f"📣 You're going to something on {name}'s watchlist", [_screening(i) for i in data.get('you_go_they_want', [])]),
        ('🍿 Seen together', [f"**{i['title']}** — {datetime.fromisoformat(i['start_time']).strftime('%b %-d, %Y')}"
                             for i in data.get('seen_together', [])]),
    ]
    for title, lines in sections:
        _add_field(embed, title[:256], lines, limit=limit)
    t = data.get('taste')                                    # R13: only when they show their taste
    if t and t.get('score') is not None:
        shared = ', '.join(t['shared'][:6])
        embed.add_field(name=f"🎨 Taste match: {t['score']}%", inline=False,
                        value=f"You both love {shared}"[:1024] if shared else 'Nothing in common yet.')
    if not embed.fields:
        embed.description = "Nothing lines up yet — add films with `/watch` and RSVP with `/rsvp`."
    embed.set_footer(text='Open their profile on the site → Compare for the full picture')
    return embed


def history_embed(data, limit=15):
    """/history: screenings someone saw with the club, newest first."""
    items = data.get('items') or []
    embed = discord.Embed(title=f"🎞️ {data.get('name', 'Someone')}'s watch history", colour=AMBER)
    if not items:
        embed.description = ("Nothing logged yet — RSVP to a screening, and tap **Went** when "
                             "the bot asks afterwards.")
        return embed
    lines = []
    for i in items[:limit]:
        mark = '✅' if i['status'] == 'went' else '🎟️'
        fmt = f" · {i['format_label']}" if i.get('format_label') else ''
        day = datetime.fromisoformat(i['start_time']).strftime('%b %-d, %Y')
        lines.append(f"{mark} **{i['title']}** — {day} @ {i['theatre']}{fmt}")
    if len(items) > limit:
        lines.append(f"…and {len(items) - limit} more on the site")
    embed.description = '\n'.join(lines)[:4096]
    embed.set_footer(text=f"{len(items)} screening{'' if len(items) == 1 else 's'} · "
                          "✅ confirmed · 🎟️ RSVP'd going")
    return embed


def _when(iso):
    return f"{_fmt_day(iso)} {_fmt_time(iso)}"


def _screening(item, after_title=''):
    """'**TITLE** — Sat 10/10 9:00 PM @ AFI · 70mm'"""
    fmt = f" · {item['format_label']}" if item.get('format_label') else ''
    return f"**{item['title']}**{after_title} — {_when(item['start_time'])} @ {item['theatre']}{fmt}"


def _add_field(embed, name, lines, limit=10):
    """Add a field with as many lines as fit Discord's 1,024-character cap."""
    out, used = [], 0
    for i, line in enumerate(lines):
        if i == limit or used + len(line) > 980:
            out.append(f"…and {len(lines) - i} more")
            break
        out.append(line)
        used += len(line) + 1
    if out:
        embed.add_field(name=name, value='\n'.join(out)[:1024], inline=False)


def _short_when(iso):
    return datetime.fromisoformat(iso).strftime('%a %-m/%-d %-I:%M %p').replace(':00 ', ' ')


def _names(names, limit=3, more=0):
    """A few names, then '+N', then members on the site (counted only)."""
    return more_on_site(names[:limit], more, max(0, len(names) - limit))


def digest_message(digest, tag_watchers=False):
    """The weekly digest as (content, embed, tagged_watchlist_ids, plan_picks).

    Short by design: each section is capped (the backend already trims and
    de-duplicates films across sections), empty ones are skipped, and schedule
    drops are one footer line. @mentions inside an embed don't notify anyone,
    so when tag_watchers is set (the scheduled Monday post) the people to ping
    go in `content` — only for films they haven't been tagged about in two
    weeks. plan_picks are the "make plans" screenings, for Going buttons."""
    group_name = digest.get('group_name') or 'Cinema Club DC'
    embed = discord.Embed(title=f"🍿 This week at the movies — {group_name}",
                          colour=AMBER, url=f'{SITE_URL}/calendar')

    def line(item, extra=''):
        fmt = f" · {item['format_label']}" if item.get('format_label') else ''
        return f"**{item['title']}** — {_short_when(item['start_time'])} @ {item['theatre']}{fmt}{extra}"

    going = digest.get('whos_going', [])
    if going:
        lines = [line(s, f" — {_names(s['going'], more=s.get('going_more', 0))}") for s in going[:5]]
        if len(going) > 5:
            lines.append(f"+{len(going) - 5} more → `/whosgoing`")
        embed.add_field(name="🎟️ Who's going", value='\n'.join(lines)[:1024], inline=False)

    plans = digest.get('plans', [])
    if plans:
        _add_field(embed, '🤝 Make plans — nobody’s going yet',
                   [f"**{p['title']}** — {_names(p['wanters'], 2, p.get('wanters_more', 0))} want to see it · next "
                    f"{_short_when(p['start_time'])} @ {p['theatre']}" for p in plans])
    _add_field(embed, '💎 Rare this week',      # the reasons already name the print format
               [f"**{r['title']}** — {_short_when(r['start_time'])} @ {r['theatre']}"
                + (f" · {' · '.join(r['reasons'])}" if r.get('reasons') else '')
                for r in digest.get('rare', [])])
    _add_field(embed, '🆕 Opening this week',
               [f"**{o['title']}** — from {_short_when(o['start_time'])} @ {o['theatre']}"
                + (f" (+{o['theatres'] - 1} more)" if o.get('theatres', 1) > 1 else '')
                for o in digest.get('opening', [])])
    _add_field(embed, '⏳ Last chance', [line(x, ' · last showing') for x in digest.get('last_chance', [])])

    tagged, pings, lines = [], {}, []
    for item in digest.get('watchlist', []):
        names = []
        if tag_watchers:                         # not named here, but marked (and emailed) all the same
            tagged += item.get('quiet_ids') or []
        for w in item['watchers']:
            if tag_watchers and w['fresh']:
                tagged.append(w['watchlist_id'])
                if w.get('discord_user_id'):
                    pings.setdefault(w['discord_user_id'], []).append(item['title'])
            names.append(f"<@{w['discord_user_id']}>" if w.get('discord_user_id') else w['name'])
        if not item.get('planned') and (names or item.get('more')):   # planned: already under "Make plans"
            lines.append(f"**{item['title']}** — {more_on_site(names, item.get('more', 0))}")
    _add_field(embed, '👀 On your watchlists', lines, limit=5)

    polls = digest.get('open_polls', [])
    if polls:
        embed.add_field(name='🗳️ Polls', inline=False,
                        value=(' · '.join(f"**{p['title']}**" for p in polls[:3]) + ' — vote with `/vote`')[:1024])

    recap = digest.get('recap') or {}
    bits = []
    if recap.get('checkins'):
        top = recap.get('top_film')
        bits.append(f"{recap['checkins']} check-in{'s' if recap['checkins'] != 1 else ''} across "
                    f"{recap['films']} film{'s' if recap['films'] != 1 else ''}"
                    + (f" (most: {top['title']} ×{top['count']})" if top else ''))
    if recap.get('discussed'):
        d = recap['discussed']
        title = f"[{d['title']}]({d['url']})" if d.get('url') else d['title']
        bits.append(f"most talked about: {title} ({d['comments']} comments)")
    if recap.get('poll'):
        p = recap['poll']
        bits.append(f"🏆 {p['title']}: {p['winner'] or 'a member on the site'} ({p['kernels']} 🍿)")
    if bits:
        embed.add_field(name='📊 Last week', value=' · '.join(bits)[:1024], inline=False)

    if not embed.fields:
        embed.description = 'A quiet week — nothing on the calendar yet.'
    drops = digest.get('new_on_calendar') or []
    new_line = ('New on the calendar: ' + ' · '.join(f"{d['theatre']} +{d['showtimes']}" for d in drops[:5]) + '\n') \
        if drops else ''
    embed.set_footer(text=f"{new_line}Full calendar → {SITE_URL}/calendar")

    content = None
    if pings:
        content = '👀 **On your watchlists this week:**\n' + '\n'.join(
            f"<@{uid}> — {', '.join(titles)}" for uid, titles in pings.items())
        content = content[:2000]
    return content, embed, tagged, plans


# ─── Polls (/vote ballots and #movies posts) ──────────────────────────────────

POLL_MODES = {
    'confidence': 'Confidence: stake 1–10 🍿 on each pick (lose them if wrong)',
    'ranked': 'Ranked: your top 3 in each category',
    'single': '1 🍿 per correct pick',
    'none': 'Just for fun',
}
MEDALS = ['🥇', '🥈', '🥉']


def _pct(count, total):
    return f"{round(100 * count / total)}%" if total else '0%'


def _pick_line(cat, mode):
    """The member's current pick(s) for a category, as one line."""
    names = {o['id']: o['text'] for o in cat['options']}
    picks = cat['picks']
    if not picks:
        return '*No pick yet*'
    if mode == 'ranked':
        return '  '.join(f"**{p['rank']}.** {names.get(p['option_id'], '?')}" for p in picks)
    p = picks[0]
    stake = f" · {p['confidence']} 🍿" if mode == 'confidence' else ''
    return f"**{names.get(p['option_id'], '?')}**{stake}"


def ballot_embed(ballot, idx, note=None):
    """One category of a /vote ballot. Open polls show your pick and (once
    you've picked) the split; closed ones show the split; scored ones mark the
    winner, ✅/❌ on your picks, and the kernels they earned."""
    poll, cats = ballot['poll'], ballot['categories']
    cat = cats[idx]
    mode, status = poll['scoring_mode'], poll['status']
    picked = {p['option_id'] for p in cat['picks']}
    lines = [f"### {cat['title']}", f"Category {idx + 1} of {len(cats)}"]
    if status == 'open':
        lines[-1] += f" · **{ballot['answered']}/{len(cats)} answered**"
        lines.append(f"Your pick: {_pick_line(cat, mode)}")
    if 'split' in cat:
        win = cat.get('correct_option_id')
        rows = []
        for o in sorted(cat['options'], key=lambda o: -cat['split'].get(str(o['id']), 0)):
            n = cat['split'].get(str(o['id']), 0)
            mark = '🏆 ' if o['id'] == win else ''
            if o['id'] in picked:
                mark += '✅ ' if win and o['id'] == win else '❌ ' if win else '👉 '
            rows.append(f"{mark}{o['text']} — {_pct(n, cat['voters'])}")
        header = f"**How everyone voted** ({cat['voters']} {'vote' if cat['voters'] == 1 else 'votes'})"
        lines += ['', header] + rows[:15]
    elif status == 'open':
        lines += ['', '*Pick yours to see how everyone voted.*']
    if cat.get('kernels') is not None:
        lines.append(f"\nYou earned **{cat['kernels']:+d} 🍿** here")
    if note:
        lines += ['', note]

    state = {'open': '🗳️', 'closed': '🔒', 'scored': '🏆'}.get(status, '🗳️')
    embed = discord.Embed(title=f"{state} {poll['title']}"[:256], colour=AMBER,
                          description='\n'.join(lines)[:4000], url=f"{SITE_URL}/polls/{poll['id']}")
    score = ballot.get('score')
    if status == 'scored' and score:
        embed.add_field(name='Your result', inline=False,
                        value=f"**{score['kernels']} 🍿** · {score['correct']} correct · "
                              f"#{score['place']} of {score['of']}")
    footer = {'open': 'Picks save as you go — finish any time, here or on the site.',
              'closed': 'Voting has closed — results come once it’s scored.',
              'scored': 'Final results.'}.get(status, '')
    embed.set_footer(text=f"{POLL_MODES.get(mode, '')} · {footer}" if status == 'open' else footer)
    return embed


def poll_opened_embed(p):
    embed = discord.Embed(title=f"🗳️ New poll: {p['title']}"[:256], colour=AMBER, url=f"{SITE_URL}/polls/{p['poll_id']}")
    by = f" · from {p['creator']}" if p.get('creator') else ''
    n = p.get('categories', 0)
    embed.description = (f"{n} {'category' if n == 1 else 'categories'}{by}\n{POLL_MODES.get(p.get('scoring_mode'), '')}\n\n"
                         "Tap **Vote** — your ballot is private and picks save as you go.")
    return embed


def poll_results_embed(p):
    embed = discord.Embed(title=f"🏆 Results: {p['title']}"[:256], colour=AMBER, url=f"{SITE_URL}/polls/{p['poll_id']}")
    top = p.get('top') or []
    if not top:
        embed.description = 'Scored — nobody voted this time.'
        return embed
    lines = [f"{MEDALS[i]} {actor_ref(t['name'], t.get('discord_user_id')) if t.get('name') else '*a member on the site*'}"
             f" — **{t['kernels']} 🍿** ({t['correct']} correct)" for i, t in enumerate(top)]
    voters = p.get('voters', len(top))
    embed.description = '\n'.join(lines) + f"\n\n{voters} {'member' if voters == 1 else 'members'} voted · " \
                                           f"see your own picks with `/vote`"
    return embed


# ─── Screening discussion threads ─────────────────────────────────────────────

def thread_name(card):
    """'SIRÂT · Thu 10/8 9:05 PM · AFI' (Discord's limit is 100)."""
    when = datetime.fromisoformat(card['start_time']).strftime('%a %-m/%-d %-I:%M %p')
    return f"{card['title']} · {when} · {card['theatre_short']}"[:100]


def _people(people, limit=10, on_site=0):
    names = [f"<@{p['discord_user_id']}>" if p.get('discord_user_id') else p['name'] for p in people[:limit]]
    return more_on_site(names, on_site, max(0, len(people) - limit))


def thread_card_embed(card):
    """The #movies post a screening's thread hangs off. Mentions inside an
    embed never notify anyone."""
    when = datetime.fromisoformat(card['start_time']).strftime('%a, %b %-d · %-I:%M %p')
    fmt = f" · {card['format_label']}" if card.get('format_label') else ''
    lines = [f"{when} · {card['theatre']}{fmt}"]
    who = []
    if card.get('going') or card.get('going_more'):
        who.append(f"**Going:** {_people(card.get('going') or [], on_site=card.get('going_more', 0))}")
    if card.get('maybe') or card.get('maybe_more'):
        who.append(f"**Maybe:** {_people(card.get('maybe') or [], on_site=card.get('maybe_more', 0))}")
    lines.append(' · '.join(who) if who else '*Nobody has RSVP’d yet.*')
    lines.append('-# Discuss in the thread below — comments here and on the site stay in sync.')
    embed = discord.Embed(title=card['title'][:256], url=f"{SITE_URL}{card['site_path']}",
                          description='\n'.join(lines), colour=AMBER)
    if card.get('poster_url'):
        embed.set_thumbnail(url=card['poster_url'])
    return embed


def backfill_intro(total, shown, site_path):
    link = f"[full discussion]({SITE_URL}{site_path})"
    if total > shown:
        return f"-# Earlier on the site · {total} comments, the last {shown} below · {link}"
    return f"-# Earlier on the site · {total} {'comment' if total == 1 else 'comments'}"


def backfilled_comment(item):
    """A copied site comment: its text, then when it was really written."""
    day = datetime.fromisoformat(item['created_at']).astimezone(ET).strftime('%b %-d')
    return f"{item['body'][:1950]}\n-# {day} · on the site"


# ─── Discover: /find and /surprise ────────────────────────────────────────────

def _film_title(movie):
    return f"{movie['title']} ({movie['year']})" if movie.get('year') else movie['title']


def _next_line(card):
    nxt = card['next']
    bits = [f"{_fmt_day(nxt['start_time'])} {_fmt_time(nxt['start_time'])}", nxt['theatre']]
    if nxt.get('format_label'):
        bits.append(nxt['format_label'])
    more = card.get('showings', 1) - 1
    return ' · '.join(bits) + (f"  (+{more} more)" if more > 0 else '')


def _reasons(card):
    """Why it's notable, minus the year (already in the title)."""
    year = str(card['movie'].get('year') or '')
    return [str(r) for r in card.get('reasons') or [] if str(r) != year]


def _club_bits(club):
    bits = []
    if club.get('you_going'):
        bits.append("you're going")
    if club.get('going'):
        bits.append(f"🎟️ {club['going']} going")
    if club.get('wanted'):
        bits.append(f"⭐ {club['wanted']} want it")
    return bits


def find_embed(result):
    """/find: a short list of films of one kind, linking to the same Browse view."""
    films, total = result['films'], result['total']
    embed = discord.Embed(title=f"🔎 {result['label']}"[:256], colour=AMBER,
                          url=f"{SITE_URL}{result['browse_path']}")
    if not films:
        embed.description = 'Nothing matches that right now. Try a wider window (`when`) or fewer filters.'
        return embed
    lines = []
    for c in films:
        m = c['movie']
        extra = [f"*{' · '.join(_reasons(c))}*"] if _reasons(c) else []
        extra += _club_bits(c.get('club') or {})
        lines.append(f"**[{_film_title(m)}]({SITE_URL}/films/{m['id']})**\n{_next_line(c)}"
                     + (f"\n{' · '.join(extra)}" if extra else ''))
    embed.description = '\n\n'.join(lines)[:4000]
    thumb = _image_url(films[0]['movie'].get('poster_url'))
    if thumb:
        embed.set_thumbnail(url=thumb)
    shown = len(films)
    embed.set_footer(text=f"{total} film{'s' if total != 1 else ''} match"
                          + (f" · showing {shown}" if total > shown else '')
                          + ' · pick one below for showtimes')
    return embed


def foryou_embed(result):
    """/foryou (R13): your For you picks, each with why — the site's shelf."""
    films, total = result['films'], result['total']
    embed = discord.Embed(title='✨ For you', colour=AMBER, url=f"{SITE_URL}{result['browse_path']}")
    if not films:
        embed.description = ("Nothing for you in the next two weeks yet — theatres add films every week."
                             if result.get('taste_set') else
                             "Tell us what you like and this fills with films for you: pick genres with `/profile`, "
                             f"or set favorite films, people and theatres in Edit profile → Your taste on the site ({SITE_URL}).")
        return embed
    lines = []
    for c in films:
        m = c['movie']
        why = ' · '.join(_reasons(c))
        lines.append(f"**[{_film_title(m)}]({SITE_URL}/films/{m['id']})**\n{_next_line(c)}" + (f"\n*{why}*" if why else ''))
    embed.description = '\n\n'.join(lines)[:4000]
    thumb = _image_url(films[0]['movie'].get('poster_url'))
    if thumb:
        embed.set_thumbnail(url=thumb)
    embed.set_footer(text=f"{total} for you in the next two weeks" + (f" · showing {len(films)}" if total > len(films) else '')
                          + ' · pick one below for showtimes')
    return embed


SURPRISE_WHEN = {'tonight': 'tonight', 'tomorrow': 'tomorrow', 'weekend': 'this weekend',
                 'week': 'this week', '2weeks': 'in the next two weeks', 'month': 'this month'}


def surprise_embed(pick, asked_when=None, spun_by=None):
    """/surprise: one film, why it was picked, and its next showing."""
    m = pick['movie']
    meta = [b for b in (f"dir. {m['director']}" if m.get('director') else None,
                        f"{m['runtime']} min" if m.get('runtime') else None,
                        ', '.join(g.title() for g in (m.get('genres') or [])[:3]) or None) if b]
    lines = []
    if asked_when and pick.get('when') != asked_when:
        lines.append(f"*Nothing left {SURPRISE_WHEN.get(asked_when, asked_when)}, so here's one from this week.*")
    if meta:
        lines.append(' · '.join(meta))
    lines.append(f"**Next:** {_next_line(pick)}")
    why = _reasons(pick) + _club_bits(pick.get('club') or {})
    if why:
        lines.append(f"**Why:** {' · '.join(why)}")
    embed = discord.Embed(title=f"🎲 {_film_title(m)}"[:256], description='\n'.join(lines)[:4000],
                          colour=AMBER, url=f"{SITE_URL}/films/{m['id']}")
    poster, backdrop = _image_url(m.get('poster_url')), _image_url(m.get('backdrop_url'))
    if backdrop:
        embed.set_image(url=backdrop)
        if poster:
            embed.set_thumbnail(url=poster)
    elif poster:
        embed.set_thumbnail(url=poster)
    embed.set_footer(text=(f"Spun by {spun_by} · " if spun_by else '') + 'Spin again for another pick')
    return embed


# ─── Shared from the site (R3d) ───────────────────────────────────────────────
# Members choose what goes to #movies; these never @-ping (plain names).

def _show_when(item):
    dt = datetime.fromisoformat(item['start_time'])
    fmt = f" · {item['format_label']}" if item.get('format_label') else ''
    return f"{dt.strftime('%a %-m/%-d %-I:%M %p')} · {item['theatre']}{fmt}"


def rsvp_share_message(d):
    """'🎟️ **Ana** is going to **Psycho** — Fri 10/9 9:30 PM · SUNS', or one
    post for several RSVPs made in a row."""
    items = d['items']
    statuses = {i['status'] for i in items}
    verb = 'is going to' if statuses == {'going'} else 'might go to' if statuses == {'maybe'} else 'has plans for'
    if len(items) == 1:
        i = items[0]
        return f"🎟️ **{d['user']}** {verb} **{i['title']}** — {_show_when(i)}"
    lines = [f"🎟️ **{d['user']}** {verb} {len(items)} screenings:"]
    for i in items:
        maybe = ' *(maybe)*' if i['status'] == 'maybe' and statuses != {'maybe'} else ''
        lines.append(f"• **{i['title']}** — {_show_when(i)}{maybe}")
    return '\n'.join(lines)[:2000]


def invite_message(d):
    return f"🍿 **{d['by']}** is asking: who's in?" if d.get('by') else "🍿 Who's in?"


def invite_embed(d):
    """A 'who's in?' card for one screening; its going / maybe lists stay current."""
    c = d['card']
    lines = []
    if d.get('note'):
        lines.append(f"> {d['note']}")
    lines.append(_show_when({**c, 'theatre': c['theatre']}))
    who = []
    for key, label in (('going', 'Going'), ('maybe', 'Maybe')):
        people = c.get(key) or []
        if people or c.get(f'{key}_more'):
            who.append(f"**{label}:** "
                       f"{more_on_site([p['name'] for p in people[:12]], c.get(f'{key}_more'), max(0, len(people) - 12))}")
    lines.append(' · '.join(who) if who else '*Nobody has said yet.*')
    if d.get('started'):
        lines.append('-# This screening has started.')
    else:
        lines.append('-# Tap Going or Maybe — it updates here and on the site.')
    embed = discord.Embed(title=c['title'][:256], url=f"{SITE_URL}{c['site_path']}",
                          description='\n'.join(lines)[:4000], colour=AMBER)
    thumb = _image_url(c.get('poster_url'))
    if thumb:
        embed.set_thumbnail(url=thumb)
    return embed


def poll_post_embed(p):
    """A poll announcement as it stands: open (vote) or closed."""
    if p.get('status', 'open') == 'open':
        return poll_opened_embed(p)
    embed = discord.Embed(title=f"🔒 Voting closed: {p['title']}"[:256], colour=AMBER,
                          url=f"{SITE_URL}/polls/{p['poll_id']}")
    embed.description = ('Results are in — see them on the site.' if p.get('status') == 'scored'
                         else 'Results coming soon.')
    return embed


# ─── /help ────────────────────────────────────────────────────────────────────

HELP_SECTIONS = [
    ('🎬 Find something to see', [
        ('/showtimes', "what's playing (pick days, a date or a theatre)"),
        ('/movie', 'a film\'s details and showtimes'),
        ('/foryou', 'films picked for you from Your taste and what you\'ve seen'),
        ('/find', 'a kind of film: rare, arthouse, a mood, a genre…'),
        ('/surprise', 'one random pick (spin again for another)'),
        ('@CinemaBot', 'ask for a rec, or just talk movies'),
    ]),
    ('🎟️ Make plans', [
        ('/rsvp', 'Going / Maybe / Can\'t go to a screening'),
        ('/whosgoing', 'who\'s RSVP\'d this week'),
        ('/discuss', 'open a screening\'s thread (and comment)'),
        ('/watch', 'add to, remove from, or show a watchlist'),
        ('/notifications', 'what alerts you get (watchlist, saved searches) and where'),
    ]),
    ('🗳️ Polls, games & kernels', [
        ('/polls', 'what\'s open right now'),
        ('/vote', 'your private ballot'),
        ('/leaderboard', 'season kernel standings 🍿'),
        ('/kernels', 'your kernels, where they came from, and how to earn more'),
        ('/trivia', "a movie trivia question — today's, or another anytime (if your club has trivia on)"),
        ('/play', 'your day in the club: trivia, bingo, polls to vote in, kernels'),
        ('/bingo', "this month's repertory bingo card (if your club has bingo on)"),
        ('/games', 'quiz games — higher or lower, who said it… (the ones your club has on)'),
        ('/poll make', 'describe a poll and the AI drafts it (organizers)'),
    ]),
    ('👤 You and the club', [
        ('/profile', 'your profile (genres, bio, Letterboxd) or someone\'s'),
        ('/history', 'screenings you (or someone) saw with the club'),
        ('/compare', 'what you and @someone both want to see, and are going to'),
        ('/link', 'optional: connect an existing site account'),
    ]),
    ('📰 Extras', [
        ('/digest', 'this week\'s digest (preview it just for you)'),
        ('/alerts', 'which theatres\' new showtimes post here'),
        ('/quote', 'add, fix or find the bot\'s movie quotes'),
        ('/wisdom', 'a random line of cinematic wisdom'),
    ]),
]


def alerts_embed(items, title=None):
    """Your alerts (R8), bundled: everything new for you from one scrape run
    (`title`: what the server calls several at once)."""
    one = len(items) == 1
    many = title or f'{len(items)} updates on your watchlist'
    embed = discord.Embed(title=f"🔔 {items[0]['headline']}" if one else f'🔔 {many}',
                          colour=AMBER, url=items[0]['url'] if one else SITE_URL)
    if one:
        embed.description = items[0]['detail']
    else:
        embed.description = '\n'.join(f"**[{it['headline']}]({it['url']})**\n{it['detail']}" for it in items[:15])[:4000]
        if len(items) > 15:
            embed.description += f'\n…and {len(items) - 15} more on the site.'
    if poster := _image_url(items[0].get('poster_url')):
        embed.set_thumbnail(url=poster)
    embed.set_footer(text='Change what you get and where: /notifications')
    return embed


NOTIFY_CHANNELS = (('discord', 'Discord DMs'), ('email', 'Email'), ('push', 'Push'))


def notify_settings_embed(s):
    """/notifications: where your alerts reach you, and which you get."""
    embed = discord.Embed(title='🔔 Your notifications', colour=AMBER, url=SITE_URL,
                          description='The same setting as on the site. Every alert also shows in the bell there.')
    where = [f"{'✅' if s['channels'][k] else '⬜'} {label}" for k, label in NOTIFY_CHANNELS if s['available'].get(k)]
    if not s['available'].get('email'):
        where.append('*Email: add an address to your account on the site to get alerts by email.*')
    embed.add_field(name='Where', value='\n'.join(where), inline=False)
    embed.add_field(name='What', inline=False, value='\n'.join(
        f"{'✅' if s['types'][t['key']] else '⬜'} {t['label']}" for t in s['types_info']))
    searches = s.get('searches') or []
    embed.add_field(name=f'Saved searches ({len(searches)})', inline=False, value=(
        '\n'.join(f"• [{x['label']}]({SITE_URL}{x['path']})" for x in searches)[:1000] if searches
        else '*None yet — on the site, Browse with some filters and tap 🔔 Alert me.*'))
    return embed


def kernel_parts(k):
    """'polls 12 · going out 20 · from members 3' — where someone's kernels came
    from (trivia and bingo only once there's some)."""
    return ' · '.join(f'{label} {k[key]}' for key, label in (('polls', 'polls'), ('going_out', 'going out'),
                                                              ('trivia', 'trivia'), ('bingo', 'bingo'),
                                                              ('games', 'games'), ('members', 'from members'))
                      if key not in ('trivia', 'bingo', 'games') or k.get(key))


def kernels_embed(k):
    """/kernels: your total, where it came from, this week's allowance, and how to earn more."""
    d, r, a = k['detail'], k['rules'], k['allowance']
    embed = discord.Embed(title=f"🍿 Your kernels: {k['kernels']}", colour=AMBER, url=f'{SITE_URL}/club?tab=leaderboard',
                          description=kernel_parts(k))
    embed.add_field(name='Going out', inline=False, value=(
        f"Checked in +{d['went']} · planned it +{d['planned']} · trailblazer +{d['trailblazer']} · crew nights +{d['crew']}"))
    embed.add_field(name='This week', inline=False, value=(
        f"{a['give_left']} to give · {a['take_left']} to take — on the club feed at {SITE_URL}/club (resets Monday)"))
    embed.add_field(name='How to earn', inline=False, value='\n'.join([
        f"• Check in after a screening: **+{r['went']}** (+{r['planned']} more if you'd said you were going)",
        f"• Be first going to a screening: **+1** for each member who joins (up to {r['trailblazer_max']})",
        f"• Crew night — {r['crew_min']}+ members check in to the same screening: **+{r['crew']}** each",
        '• Right picks in scored polls',
        *([f"• Trivia question of the day: {by_level(r['trivia'])} for a right answer (`/trivia`)"] if r.get('trivia') else []),
        *([f"• Anytime trivia: {by_level(r['trivia_anytime']['each'])} each, up to {r['trivia_anytime']['per_day']} a day"]
          if r.get('trivia_anytime') else []),
        *([f"• Repertory bingo: **+{r['bingo']['line']}** for a line, **+{r['bingo']['full']}** for the full card (`/bingo`)"]
          if r.get('bingo') else []),
        *[f"• {g['label']}: **+{g['each']}** a right call, up to {g['per_day']} a day (`/games`)" for g in r.get('games') or []],
        f"• Members can give you up to {r['give']} a week for what you do (and take a few back)",
    ]))
    return embed


LETTERS = 'ABCD'


def trivia_embed(q, yesterday=None, title='🧠 Daily trivia'):
    """The question of the day (R10d): the options lettered, how hard it is
    and what it's worth (R15), and yesterday's answer underneath when there was one."""
    embed = discord.Embed(title=title, colour=AMBER, url=f'{SITE_URL}/feed', description='\n'.join(
        [q['prompt'], ''] + [f"**{LETTERS[i]}.** {o}" for i, o in enumerate(q['options'])]))
    if yesterday and yesterday.get('answer') is not None:
        st = yesterday.get('stats') or {}
        embed.add_field(name='Yesterday', inline=False, value=(
            f"{yesterday['prompt'][:300]} → **{yesterday['options'][yesterday['answer']]}**"
            f" ({st.get('correct', 0)} of {st.get('answered', 0)} got it)")[:1024])
    left = q.get('kernels_left_today')
    worth = (f"+{q.get('kernels', 2)} 🍿 for a right answer" if left is None or left > 0
             else "just for fun (today's anytime kernels are used up)")
    level = LEVELS.get(q.get('difficulty'))
    embed.set_footer(text=f"{level + ' · ' if level else ''}One try · {worth} · your answer stays private")
    return embed


def bingo_card_post_embed(post):
    """The month's card in #movies (R14): its eight squares around the free middle."""
    sq = post['squares']
    lines = [f"{s['emoji']} **{s['label']}** — *{s['hint']}*" for s in sq]
    embed = discord.Embed(title=f"🎱 {post['month_label']}'s repertory bingo card", colour=AMBER, url=f'{SITE_URL}/play#bingo',
                          description='Fills in by itself when you check in ("Went") to screenings this month — '
                                      'the middle is free.\n\n' + '\n'.join(lines))
    embed.set_footer(text=f"A line of 3 is bingo: +{post['rules']['line']} 🍿 · the full card +{post['rules']['full']} 🍿 · /bingo for yours")
    return embed


def bingo_win_embed(post):
    """A win in #movies (R14) — naming them only if they said Always."""
    who = post.get('name') or 'Someone'
    what = 'filled the whole card 🎉🎉' if post.get('which') == 'full' else 'got bingo 🎉'
    return discord.Embed(title=f"🎱 {who} {what}", colour=AMBER, url=f'{SITE_URL}/play#bingo',
                         description=f"{post.get('month_label', 'This month')}'s repertory bingo · /bingo for your card")


LEVELS = {'easy': 'Easy', 'medium': 'Medium', 'hard': 'Hard'}


def quiz_games_embed(games):
    """/games (R15): the quiz games the club has on, what you've earned today."""
    lines = [f"{g['emoji']} **{g['label']}** — {g['blurb']}\n-# +{g['each']} 🍿 a right call · "
             f"{g['earned_today']}/{g['cap']} today" + (f" · best {g['best']}" if g.get('best') else '') for g in games]
    return discord.Embed(title='🎮 Quiz games', colour=AMBER, url=f'{SITE_URL}/play#games', description='\n\n'.join(lines))


def _year_film(f):
    return f"**{f['title']}**" + (f" ({f['year']})" if f.get('year') else '')


def quiz_round_embed(r):
    """A quiz round (R15): what to answer — or, once it's over, how it went."""
    last = r.get('last') or {}
    paid = f" +{last['paid']} 🍿" if last.get('paid') else ''
    said = f"✅ Right!{paid}" if last.get('right') else '❌ Not quite.' if last else ''
    if r['kind'] == 'higher_lower':
        cur, nxt = r['current'], r['next']
        if r['done']:
            body = (f"{said}\n{_year_film(nxt)} came out in **{nxt['year']}** — "
                    f"{'before' if nxt['year'] < cur['year'] else 'after'} {_year_film(cur)}.\n\n"
                    f"Streak: **{r['score']}**")
        else:
            body = (f"{said + chr(10) if said else ''}{_year_film(cur)}\n\nDid **{nxt['title']}** come out before or after "
                    f"{cur['year']}?\n-# Streak: {r['score']}")
    else:
        opts = '\n'.join(f"**{LETTERS[i]}.** {o}" + (' ✅' if r['done'] and i == r.get('answer') else '')
                         for i, o in enumerate(r['options']))
        body = (f"{said + chr(10) if said else ''}“{r['quote']}”\n\nWho says it in {_year_film(r['film'])}?\n\n{opts}")
    embed = discord.Embed(title=f"{r['emoji']} {r['label']}", colour=AMBER, url=f'{SITE_URL}/play#games', description=body)
    embed.set_footer(text=f"+{r['each']} 🍿 a right call · {r['left_today']} left to earn today · only you see this")
    return embed


def by_level(table):
    """{'easy': 1, 'medium': 2, 'hard': 3} → "**+1** easy · **+2** medium · **+3** hard" (trivia's kernels, R15)."""
    return ' · '.join(f"**+{table[k]}** {k}" for k in LEVELS if k in table)


def review_note(post, error=None):
    """The line above a game post in an organizer's or admin's DM (R14)."""
    status = post.get('status')
    if error:
        return f"⚠️ {error}"
    if status == 'waiting':
        what = "today's trivia question" if post['kind'] == 'trivia' else 'the bingo card'
        extra = (f" The answer: **{post['question']['options'][post['answer']]}**."
                 if post['kind'] == 'trivia' and post.get('answer') is not None else '')
        return f"👀 Waiting for your OK: here's {what} as it'll look in #movies.{extra}"
    if status == 'skipped' and post.get('until'):
        return f"⏭️ Skipped — nothing was posted. Changed your mind? You can post it after all until {post['until']}."
    return {'approved': '✅ Approved — it goes up in #movies in a minute.', 'posted': '✅ Posted in #movies.',
            'skipped': '⏭️ Skipped — nothing was posted.', 'expired': '⌛ Too late — nothing was posted.'}.get(status, '')


def play_embed(p):
    """/play: your day in the club — trivia, bingo, polls waiting for your
    vote, your kernels (games the club has off are left out)."""
    lines = []
    t = p.get('trivia')
    if t:
        if t['to_answer']:
            lines.append("🧠 **Today's trivia question is waiting** — one try")
        elif t['answered']:
            lines.append(f"🧠 Today's question: {'✅ you got it' if t['correct'] else '❌ missed'}"
                         + (' · more anytime' if t['anytime'] else ' · a new one tomorrow'))
        elif t['anytime']:
            lines.append('🎲 Anytime trivia is on — play a question whenever you like')
    b = p.get('bingo')
    if b:
        grid = '\n'.join(' '.join('🟩' if b['cells'][r * 3 + c] else '⬛' for c in range(3)) for r in range(3))
        lines.append(f"🎱 Bingo · {b['month_label']}: **{b['filled']}/8**"
                     + (' — 🎉 full card!' if b['full'] else ' — 🎉 bingo!' if b['line'] else '') + f"\n{grid}")
    waiting = [x for x in p.get('polls', []) if not x['you_voted']]
    if waiting:
        lines.append('🗳️ Waiting for your vote: ' + ', '.join(f"**{x['title']}**" for x in waiting[:3]))
    elif p.get('polls'):
        lines.append("🗳️ You've voted in every open poll")
    k = p['kernels']
    lines.append(f"🍿 **{k['kernels']}** kernels ({kernel_parts(k)}) · {k['allowance']['give_left']} to give, "
                 f"{k['allowance']['take_left']} to take this week")
    embed = discord.Embed(title=f"🎮 Your day at {p.get('club') or 'the club'}", colour=AMBER, url=f'{SITE_URL}/play',
                          description='\n\n'.join(lines))
    embed.set_footer(text=f'Everything is on the site too: {SITE_URL}/play')
    return embed


def bingo_embed(b):
    """/bingo: your card for the month (R10e) — the grid, what each square
    asks for (✅ with the screening that filled it; 🏠 with the diary entry,
    when the club counts home viewing, R15), and your lines."""
    sq = b['squares']
    mark = lambda s: '🏠' if s.get('home') else '✅'
    grid = '\n'.join(' '.join(mark(sq[r * 3 + c]) if sq[r * 3 + c]['done'] and sq[r * 3 + c]['key'] != 'free'
                               else sq[r * 3 + c]['emoji'] if sq[r * 3 + c]['key'] == 'free' else '⬜'
                               for c in range(3)) for r in range(3))
    lines = [f"{mark(s) if s['done'] else '⬜'} {s['emoji']} **{s['label']}**"
             + (f" — {s['by']['title']}" if s.get('by') else f" — {s['home']['title']} (at home)" if s.get('home')
                else f" — *{s['hint']}*") for s in sq if s['key'] != 'free']
    status = ('🎉 **Full card!**' if b['full'] else '🎉 **Bingo!** Now the full card…' if b['line']
              else f"{b['filled']} of 8 — a line of 3 (the middle's free) is bingo")
    embed = discord.Embed(title=f"🎱 Repertory bingo · {b['month_label']}", colour=AMBER, url=f'{SITE_URL}/feed',
                          description=f"{grid}\n\n{status}\n\n" + '\n'.join(lines))
    leaders = [f"{r['user']['name']} {r['filled']}/8" + (' 🎉' if r['line'] else '') for r in b.get('club', [])[:6]]
    if leaders:
        embed.add_field(name='The club', value=' · '.join(leaders)[:1024], inline=False)
    r = b['rules']
    home = (f" · 🏠 your Letterboxd diary fills film squares (a line that needs one +{r['home_line']}, "
            f"the full card +{r['home_full']})") if r.get('home') else ''
    embed.set_footer(text=f"Fills in from your check-ins · first line +{r['line']} 🍿, full card "
                          f"+{r['full']} 🍿{home} · you've earned {b['kernels']} this month")
    return embed


def trivia_result(q):
    """What you see after answering: right or not, the answer, and the tally."""
    right = q['options'][q['answer']]
    st = q.get('stats') or {}
    earned = q.get('earned', q.get('kernels', 2))
    head = (f"✅ Right — **{right}**!" + (f" +{earned} 🍿" if earned else '') if q['mine']['correct']
            else f"❌ Not quite — it was **{right}**.")
    if q.get('anytime'):
        return head
    return f"{head}\n-# {st.get('correct', 0)} of {st.get('answered', 0)} got it so far. New question tomorrow."


def help_embed():
    """/help: the main commands, grouped, one line each."""
    embed = discord.Embed(title='🍿 CinemaBot — quick guide', colour=AMBER, url=f'{SITE_URL}/help',
                          description='No setup needed: commands work as soon as you use them here.\n'
                                      f'📖 **Full guide** — how everything works, on the site and here: {SITE_URL}/help')
    for name, rows in HELP_SECTIONS:
        embed.add_field(name=name, inline=False, value='\n'.join(f'`{cmd}` — {what}' for cmd, what in rows))
    embed.set_footer(text=f'Everything else (calendar, Discover, your lists) → {SITE_URL}')
    return embed


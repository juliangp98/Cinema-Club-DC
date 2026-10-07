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
        url=f"{SITE_URL}/calendar?showtime={first_id}" if first_id else SITE_URL,
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
    genres = ', '.join(g.title() for g in profile.get('genres') or [])
    embed.add_field(name='Favorite genres', inline=False, value=genres or (
        'None yet — pick some below; the chatbot uses them for recommendations.' if own else '—'))
    if u.get('letterboxd_username'):
        handle = u['letterboxd_username']
        embed.add_field(name='Letterboxd', value=f"[{handle}](https://letterboxd.com/{handle}/)")
    embed.add_field(name='Watchlist', value=f"{profile['watchlist_count']} films")
    embed.add_field(name='Going to', value=f"{profile['upcoming_rsvps']} upcoming")
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


def _names(names, limit=3):
    return ', '.join(names[:limit]) + (f" +{len(names) - limit}" if len(names) > limit else '')


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
        lines = [line(s, f" — {_names(s['going'])}") for s in going[:5]]
        if len(going) > 5:
            lines.append(f"+{len(going) - 5} more → `/whosgoing`")
        embed.add_field(name="🎟️ Who's going", value='\n'.join(lines)[:1024], inline=False)

    plans = digest.get('plans', [])
    if plans:
        _add_field(embed, '🤝 Make plans — nobody’s going yet',
                   [f"**{p['title']}** — {_names(p['wanters'], 2)} want to see it · next "
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
        for w in item['watchers']:
            if tag_watchers and w['fresh']:
                tagged.append(w['watchlist_id'])
                if w.get('discord_user_id'):
                    pings.setdefault(w['discord_user_id'], []).append(item['title'])
            names.append(f"<@{w['discord_user_id']}>" if w.get('discord_user_id') else w['name'])
        if not item.get('planned'):              # already under "Make plans"
            lines.append(f"**{item['title']}** — {', '.join(names)}")
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
        bits.append(f"🏆 {p['title']}: {p['winner']} ({p['kernels']} 🍿)")
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
    lines = [f"{MEDALS[i]} {actor_ref(t['name'], t.get('discord_user_id'))} — **{t['kernels']} 🍿** "
             f"({t['correct']} correct)" for i, t in enumerate(top)]
    voters = p.get('voters', len(top))
    embed.description = '\n'.join(lines) + f"\n\n{voters} {'member' if voters == 1 else 'members'} voted · " \
                                           f"see your own picks with `/vote`"
    return embed


# ─── Screening discussion threads ─────────────────────────────────────────────

def thread_name(card):
    """'SIRÂT · Thu 10/8 9:05 PM · AFI' (Discord's limit is 100)."""
    when = datetime.fromisoformat(card['start_time']).strftime('%a %-m/%-d %-I:%M %p')
    return f"{card['title']} · {when} · {card['theatre_short']}"[:100]


def _people(people, limit=10):
    names = [f"<@{p['discord_user_id']}>" if p.get('discord_user_id') else p['name'] for p in people[:limit]]
    more = f" +{len(people) - limit}" if len(people) > limit else ''
    return ', '.join(names) + more


def thread_card_embed(card):
    """The #movies post a screening's thread hangs off. Mentions inside an
    embed never notify anyone."""
    when = datetime.fromisoformat(card['start_time']).strftime('%a, %b %-d · %-I:%M %p')
    fmt = f" · {card['format_label']}" if card.get('format_label') else ''
    lines = [f"{when} · {card['theatre']}{fmt}"]
    who = []
    if card.get('going'):
        who.append(f"**Going:** {_people(card['going'])}")
    if card.get('maybe'):
        who.append(f"**Maybe:** {_people(card['maybe'])}")
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

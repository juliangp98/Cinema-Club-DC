"""Discovery engine: themed shelves, browse filters + search, and the fun
finders (surprise me, double features, spotlights, moods).

One engine, two front doors: the site's /api/discover… routes and the bot's
/api/internal/discover… routes (R3b) both call these functions, and filter
names match the site's URL parameters so a bot answer can link to the same
view on the web.

Everything works on a "catalog": the club's showings in a time window,
grouped into one entry per film. Screening-level filters (when, theatre,
format, time of day) decide which showings count; film-level filters (genre,
decade, rarity, club, search…) then pick films.
"""

import random
import re
import unicodedata
from datetime import datetime, timedelta

# Rough regions for the Where filter.
REGIONS = {
    'suns': 'DC', 'alamo-dc': 'DC', 'regal-gallery': 'DC', 'smi-dc': 'DC', 'avalon': 'DC', 'nga': 'DC',
    'angelika-popup': 'DC', 'amc-georgetown': 'DC',
    'afi': 'Maryland', 'regal-majestic': 'Maryland',
    'alamo-crystal': 'Virginia', 'regal-ballston': 'Virginia', 'smi-udvar': 'Virginia',
    'angelika-mosaic': 'Virginia', 'amc-hoffman': 'Virginia',
}
ARTHOUSE_THEATRES = {'afi', 'suns', 'angelika-mosaic', 'angelika-popup', 'nga', 'avalon'}
BIG_SCREEN_THEATRES = {'smi-dc', 'smi-udvar'}
FILM_PRINTS = ('35mm', '16mm', '70mm')
BIG_FORMATS = ('IMAX', '70mm', 'Dolby')

MOODS = {
    'scare-me':    {'label': 'Scare me',      'genres': {'horror', 'thriller'}},
    'laugh':       {'label': 'Make me laugh', 'genres': {'comedy'}},
    'mind-bender': {'label': 'Mind-bender',   'genres': {'science fiction', 'mystery', 'fantasy'}},
    'date-night':  {'label': 'Date night',    'genres': {'romance', 'comedy', 'music'}},
    'tissues':     {'label': 'Bring tissues', 'genres': {'drama', 'romance', 'war'}},
    'feel-good':   {'label': 'Feel-good',     'genres': {'family', 'animation', 'music', 'comedy'}},
    'thrills':     {'label': 'Pure thrills',  'genres': {'action', 'adventure', 'thriller'}},
}

WHEN = {'tonight': 'Tonight', 'tomorrow': 'Tomorrow', 'weekend': 'This weekend',
        'week': 'Next 7 days', '2weeks': 'Next 2 weeks', 'month': 'Next 30 days'}


def normalize(text):
    """Case- and accent-insensitive form for search ('SIRÂT' ~ 'sirat')."""
    text = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in text if not unicodedata.combining(c)).casefold()


def window(when, now=None, start=None, end=None):
    """(start, end) for a When choice, or explicit YYYY-MM-DD dates."""
    now = now or datetime.now()
    day_end = lambda d: datetime.combine(d, datetime.max.time())
    if start or end:
        s = datetime.fromisoformat(start) if start else now
        e = day_end(datetime.fromisoformat(end).date()) if end else s + timedelta(days=7)
        return max(s, now), e
    if when == 'tonight':
        return now, day_end(now.date())
    if when == 'tomorrow':
        d = now.date() + timedelta(days=1)
        return datetime.combine(d, datetime.min.time()), day_end(d)
    if when == 'weekend':
        wd = now.weekday()                                   # Mon=0 … Sun=6
        if wd >= 5 or (wd == 4 and now.hour >= 17):
            return now, day_end(now.date() + timedelta(days=6 - wd))
        fri = now.date() + timedelta(days=4 - wd)
        return datetime.combine(fri, datetime.min.time()).replace(hour=17), day_end(fri + timedelta(days=2))
    days = {'week': 7, '2weeks': 14, 'month': 30}.get(when, 14)
    return now, now + timedelta(days=days)


class Film:
    """One film's showings in a window, with what discovery needs to know."""
    __slots__ = ('movie', 'shows', 'venues', 'formats', 'events', 'rare_score', 'rare_reasons',
                 'year', 'genres', 'wanted', 'going', 'you_want', 'you_going')

    def __init__(self, movie):
        self.movie, self.shows = movie, []
        self.wanted = self.going = 0
        self.you_want = self.you_going = False

    def finish(self, this_year, rarity, event_words):
        self.shows.sort(key=lambda s: s.start_time)
        self.venues = {s.theatre.slug for s in self.shows}
        self.formats = {f.strip() for s in self.shows for f in (s.format_label or '').split('·') if f.strip()}
        self.events = []
        for s in self.shows:
            for pattern, label in event_words:
                if re.search(pattern, s.event_label or '', re.I) and label not in self.events:
                    self.events.append(label)
        best = max((rarity(s, len(self.shows), len(self.venues), this_year) for s in self.shows), key=lambda x: x[0])
        self.rare_score, self.rare_reasons = best
        y = (self.movie.release_year or '')[:4]
        self.year = int(y) if y.isdigit() else None
        self.genres = {g.strip().lower() for g in (self.movie.genres or '').split(',') if g.strip()}
        return self

    @property
    def next(self):
        return self.shows[0]


def _show_ok(s, theatres, formats, time_of_day):
    if theatres and s.theatre.slug not in theatres:
        return False
    fmt = s.format_label or ''
    if formats:
        wants_film = 'film' in formats and any(f in fmt for f in FILM_PRINTS)
        wants_big = 'big' in formats and (any(f in fmt for f in BIG_FORMATS) or s.theatre.slug in BIG_SCREEN_THEATRES)
        if not (wants_film or wants_big):
            return False
    if time_of_day == 'late' and (s.start_time.hour, s.start_time.minute) < (21, 30):
        return False
    if time_of_day == 'matinee' and s.start_time.hour >= 17:
        return False
    if time_of_day == 'evening' and not 17 <= s.start_time.hour < 21:
        return False
    return True


def catalog(group, start, end, viewer=None, theatres=None, formats=None, time_of_day=None):
    """{movie_id: Film} for the group's showings in [start, end] that pass the
    screening-level filters, with club interest (members' watchlists, RSVPs)."""
    from sqlalchemy.orm import contains_eager
    from app import (db, Showtime, Watchlist, RSVP, GroupMembership, _group_showtime_query,
                     rarity, EVENT_WORDS)
    rows = (_group_showtime_query(group)
            .options(contains_eager(Showtime.movie), contains_eager(Showtime.theatre))
            .filter(Showtime.start_time >= start, Showtime.start_time <= end)
            .order_by(Showtime.start_time).all())
    films = {}
    for s in rows:
        if _show_ok(s, theatres, formats, time_of_day):
            films.setdefault(s.movie_id, Film(s.movie)).shows.append(s)
    this_year = datetime.now().year
    for f in films.values():
        f.finish(this_year, rarity, EVENT_WORDS)
    if not films:
        return films
    if not group:
        # Public mode: no club, only the viewer's own personal plans and watchlist (R5b).
        if viewer:
            show_ids = {s.id: s.movie_id for f in films.values() for s in f.shows}
            for r in RSVP.query.filter(RSVP.user_id == viewer.id, RSVP.group_id.is_(None),
                                       RSVP.status.in_(('going', 'maybe')), RSVP.showtime_id.in_(show_ids)):
                films[show_ids[r.showtime_id]].you_going = True
            for w in Watchlist.query.filter(Watchlist.user_id == viewer.id, Watchlist.movie_id.in_(films)):
                films[w.movie_id].you_want = True
        return films

    members = {m.user_id for m in GroupMembership.query.filter_by(group_id=group.id, status='active')}
    for mid, n in (db.session.query(Watchlist.movie_id, db.func.count())
                   .filter(Watchlist.movie_id.in_(films), Watchlist.user_id.in_(members))
                   .group_by(Watchlist.movie_id)):
        films[mid].wanted = n
    show_ids = {s.id: s.movie_id for f in films.values() for s in f.shows}
    going = {}
    for r in RSVP.query.filter(RSVP.group_id == group.id, RSVP.status == 'going', RSVP.showtime_id.in_(show_ids)):
        going.setdefault(show_ids[r.showtime_id], set()).add(r.user_id)
    for mid, users in going.items():
        films[mid].going = len(users)
        films[mid].you_going = bool(viewer and viewer.id in users)
    if viewer:
        for w in Watchlist.query.filter(Watchlist.user_id == viewer.id, Watchlist.movie_id.in_(films)):
            films[w.movie_id].you_want = True
    return films


def card(f, reasons=()):
    """A film as Discover / Browse / the bot show it."""
    m, s = f.movie, f.next
    return {
        'movie': {'id': m.id, 'title': m.title, 'year': f.year, 'poster_url': m.poster_url,
                  'backdrop_url': m.backdrop_url, 'genres': sorted(f.genres), 'runtime': m.runtime_minutes,
                  'director': m.director},
        'next': {'showtime_id': s.id, 'start_time': s.start_time.isoformat(),
                 'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label},
        'showings': len(f.shows), 'theatres': len(f.venues),
        'reasons': [r for r in reasons if r][:4],
        'club': {'wanted': f.wanted, 'going': f.going, 'you_want': f.you_want, 'you_going': f.you_going},
    }


# ─── Shelves ──────────────────────────────────────────────────────────────────
# Each returns [(film, reasons)] in display order. `ctx` carries the year,
# the viewer's genres, and the opening / last-chance sets.

def _decade(year):
    return f"'{str(year)[2]}0s" if year else ''


def _ratings(m):
    import json
    try:
        out = {}
        for r in json.loads(m.ratings_json or '[]'):
            v = str(r.get('value', ''))
            if 'Rotten' in r.get('source', '') and v.endswith('%'):
                out['RT'] = int(v[:-1])
            elif 'Metacritic' in r.get('source', '') and '/' in v:
                out['MC'] = int(v.split('/')[0])
            elif 'Internet Movie' in r.get('source', '') and '/' in v:
                out['IMDb'] = float(v.split('/')[0])
        return out
    except Exception:
        return {}


def _critics(f):
    r = _ratings(f.movie)
    if r.get('RT', 0) >= 90:
        return f"RT {r['RT']}%"
    if r.get('MC', 0) >= 80:
        return f"MC {r['MC']}"
    if r.get('IMDb', 0) >= 8.0:
        return f"IMDb {r['IMDb']}"
    if not r and (f.movie.vote_average or 0) >= 7.8:
        return f"TMDB {f.movie.vote_average:.1f}"
    return None


def _award(f):
    a = f.movie.awards or ''
    m = re.search(r'Won (\d+) Oscars?', a)
    if m:
        return f"Won {m.group(1)} Oscar{'s' if m.group(1) != '1' else ''}"
    m = re.search(r'Nominated for (\d+) Oscars?', a)
    return f"{m.group(1)} Oscar nomination{'s' if m.group(1) != '1' else ''}" if m else None


def _late(f):
    return next((s for s in f.shows if (s.start_time.hour, s.start_time.minute) >= (21, 30)), None)


SHELVES = [
    # key, title, blurb
    ('rare', 'Rare gems', 'Hard to catch again: one-offs, film prints, old favorites, special events'),
    ('friends', 'Friends are going', "Screenings the club has RSVP'd to"),
    ('one-night', 'One night only', 'A single showing in the window'),
    ('on-film', 'On film', 'Projected from 35mm, 16mm and 70mm prints'),
    ('big-screen', 'Big screen', 'IMAX, 70mm and Dolby'),
    ('events', 'Special events', 'Q&As, intros, premieres, anniversaries, marathons'),
    ('opening', 'Opening', 'New releases arriving at the club’s theatres'),
    ('last-chance', 'Last chance', 'Final scheduled showings'),
    ('most-wanted', 'Most wanted in the club', 'On the most members’ watchlists'),
    ('for-you', 'For you', 'Your favorite genres and your watchlist'),
    ('blockbusters', 'Blockbusters', 'The big new releases, playing everywhere'),
    ('arthouse', 'Arthouse & indie', 'Recent films at a theatre or two'),
    ('classics', 'Classics', 'Twenty years old and up'),
    ('critics', "Critics' darlings", 'Top marks from critics and audiences'),
    ('awards', 'Award winners', 'Oscar winners and nominees'),
    ('documentaries', 'Documentaries', 'True stories on the big screen'),
    ('horror', 'Horror', 'Something to watch through your fingers'),
    ('short', 'Short & sweet', 'Under 95 minutes'),
    ('epics', 'Epics', 'Over two and a half hours'),
    ('late-night', 'Late night', 'Starts at 9:30 pm or later'),
]
SHELF_TITLES = {k: t for k, t, _ in SHELVES}


def shelf(key, films, ctx):
    fl = list(films.values())
    y = ctx['year']
    by_soonest = lambda xs: sorted(xs, key=lambda p: p[0].next.start_time)
    if key == 'rare':
        out = [(f, f.rare_reasons) for f in fl if f.rare_score >= ctx['rare_min']]
        return sorted(out, key=lambda p: (-p[0].rare_score, p[0].next.start_time))
    if key == 'friends':
        return sorted([(f, [f"{f.going} going"]) for f in fl if f.going],
                      key=lambda p: (-p[0].going, p[0].next.start_time))
    if key == 'one-night':
        return by_soonest([(f, ['one night only'] + ([f.year] if f.year and f.year <= y - 5 else []))
                           for f in fl if len(f.shows) == 1])
    if key == 'on-film':
        return by_soonest([(f, sorted(f.formats & set(FILM_PRINTS))) for f in fl if f.formats & set(FILM_PRINTS)])
    if key == 'big-screen':
        out = []
        for f in fl:
            big = [x for x in BIG_FORMATS if x in f.formats]
            if not big and f.venues & BIG_SCREEN_THEATRES:
                big = ['IMAX']
            if big:
                out.append((f, big))
        return by_soonest(out)
    if key == 'events':
        return by_soonest([(f, f.events) for f in fl if f.events])
    if key == 'opening':
        return sorted([(f, [f"{len(f.venues)} theatre{'s' if len(f.venues) != 1 else ''}"])
                       for f in fl if f.movie.id in ctx['opening']], key=lambda p: (-len(p[0].venues), p[0].next.start_time))
    if key == 'last-chance':
        return by_soonest([(f, ['last showing']) for f in fl if f.movie.id in ctx['last_chance']])
    if key == 'most-wanted':
        return sorted([(f, [f"{f.wanted} want to see it"]) for f in fl if f.wanted],
                      key=lambda p: (-p[0].wanted, p[0].next.start_time))
    if key == 'for-you':
        out = []
        for f in fl:
            match = sorted(f.genres & ctx['genres'])
            if f.you_want or match:
                out.append((f, (['on your watchlist'] if f.you_want else []) + match[:2]))
        return sorted(out, key=lambda p: (not p[0].you_want, -p[0].rare_score, p[0].next.start_time))
    if key == 'blockbusters':
        return sorted([(f, [f"{len(f.shows)} showings", f"{len(f.venues)} theatres"]) for f in fl
                       if f.year and f.year >= y - 1 and len(f.venues) >= 3 and len(f.shows) >= 10],
                      key=lambda p: -len(p[0].shows))
    if key == 'arthouse':
        return by_soonest([(f, sorted({x.theatre.short_name or x.theatre.name for x in f.shows}))
                           for f in fl if f.year and f.year >= y - 3 and len(f.venues) <= 2
                           and f.venues & ARTHOUSE_THEATRES and len(f.shows) < 10])
    if key == 'classics':
        return sorted([(f, [str(f.year), _decade(f.year)]) for f in fl if f.year and f.year <= y - 20],
                      key=lambda p: (-p[0].rare_score, p[0].year))
    if key == 'critics':
        return by_soonest([(f, [_critics(f)]) for f in fl if _critics(f)])
    if key == 'awards':
        return by_soonest([(f, [_award(f)]) for f in fl if _award(f)])
    if key == 'documentaries':
        return by_soonest([(f, []) for f in fl if 'documentary' in f.genres])
    if key == 'horror':
        return by_soonest([(f, []) for f in fl if 'horror' in f.genres])
    if key == 'short':
        return by_soonest([(f, [f"{f.movie.runtime_minutes} min"]) for f in fl
                           if f.movie.runtime_minutes and 0 < f.movie.runtime_minutes < 95])
    if key == 'epics':
        return by_soonest([(f, [f"{f.movie.runtime_minutes} min"]) for f in fl
                           if (f.movie.runtime_minutes or 0) > 150])
    if key == 'late-night':
        return sorted([(f, [_late(f).start_time.strftime('%-I:%M %p')]) for f in fl if _late(f)],
                      key=lambda p: _late(p[0]).start_time)
    return []


def context(group, viewer, films, now):
    """What shelves need beyond the films: opening / last-chance sets (same
    rules as the weekly digest), the viewer's genres."""
    from app import db, Showtime, _group_showtime_query, schedule_horizons, is_last_chance, RARE_MIN_SCORE
    ctx = {'year': now.year, 'rare_min': RARE_MIN_SCORE, 'opening': set(), 'last_chance': set(),
           'genres': {g.strip().lower() for g in ((viewer.favorite_genres if viewer else '') or '').split(',') if g.strip()}}
    if not films:
        return ctx
    span = {mid: (first, last, n) for mid, first, last, n in _group_showtime_query(group).with_entities(
        Showtime.movie_id, db.func.min(Showtime.start_time), db.func.max(Showtime.start_time),
        db.func.count(Showtime.id)).filter(Showtime.movie_id.in_(films)).group_by(Showtime.movie_id)}
    horizon = schedule_horizons(group, now)
    for mid, f in films.items():
        first, last, total = span.get(mid, (None, None, 0))
        if f.year and f.year >= now.year - 1 and first and first >= now - timedelta(hours=12):
            ctx['opening'].add(mid)
        final = f.shows[-1]
        if total >= 3 and last == final.start_time and \
                is_last_chance(final.start_time, {s.theatre_id for s in f.shows}, horizon):
            ctx['last_chance'].add(mid)
    return ctx


def discover(group, viewer, per_shelf=12, now=None):
    """The Discover page: every non-empty shelf for the next two weeks."""
    now = now or datetime.now()
    start, end = window('2weeks', now)
    films = catalog(group, start, end, viewer)
    ctx = context(group, viewer, films, now)
    shelves = []
    for key, title, blurb in SHELVES:
        items = shelf(key, films, ctx)
        if items:
            shelves.append({'key': key, 'title': title, 'blurb': blurb, 'total': len(items),
                            'items': [card(f, r) for f, r in items[:per_shelf]]})
    return {'window': {'start': start.isoformat(), 'end': end.isoformat()}, 'shelves': shelves,
            'moods': [{'key': k, 'label': v['label']} for k, v in MOODS.items()],
            'spotlights': spotlights(group, viewer, now), 'double_features': double_features(films)}


# ─── Browse / search ──────────────────────────────────────────────────────────

SORTS = ('soonest', 'rarest', 'wanted', 'critics', 'title')


def select(group, viewer, params, now=None):
    """The films matching Browse's filters, sorted, as (films, ctx, reasons,
    start, end). `params` is a dict of the URL filters: when/from/to,
    theatres, regions, genres, decade, format, time, rarity, club, runtime,
    mood, shelf, q, sort. Browse and the Calendar both use this, so a filter
    means the same thing on both."""
    now = now or datetime.now()
    p = {k: v for k, v in params.items() if v not in (None, '')}
    split = lambda k: {x.strip().lower() for x in str(p.get(k, '')).split(',') if x.strip()}
    start, end = window(p.get('when', 'week'), now, p.get('from'), p.get('to'))
    theatres = split('theatres') | {slug for slug, region in REGIONS.items()
                                    if region.lower() in split('regions')} or None
    films = catalog(group, start, end, viewer, theatres=theatres, formats=split('format') or None,
                    time_of_day=p.get('time'))
    ctx = context(group, viewer, films, now)
    reasons = {}
    if p.get('shelf'):
        picked = shelf(p['shelf'], films, ctx)
        reasons = {f.movie.id: r for f, r in picked}
        films = {f.movie.id: f for f, _ in picked}

    genres = split('genres') | (MOODS.get(p.get('mood'), {}).get('genres') or set())
    decade = p.get('decade')
    q = normalize(p.get('q', ''))
    out = []
    for f in films.values():
        if genres and not f.genres & genres:
            continue
        if decade and not (f.year and str(f.year).startswith(str(decade)[:3])):
            continue
        tier = p.get('rarity')
        if tier == 'rare' and f.rare_score < ctx['rare_min']:
            continue
        if tier == 'repertory' and not (f.year and f.year <= now.year - 5):
            continue
        if tier == 'wide' and not (len(f.venues) >= 3 and len(f.shows) >= 10):
            continue
        club = p.get('club')
        if (club == 'going' and not f.going) or (club == 'wanted' and not f.wanted) or \
                (club == 'mine' and not (f.you_want or f.you_going)):
            continue
        rt = f.movie.runtime_minutes or 0
        if (p.get('runtime') == 'short' and not 0 < rt < 95) or (p.get('runtime') == 'long' and rt <= 150):
            continue
        if q:
            import json
            cast = ' '.join(c.get('name', '') for c in json.loads(f.movie.cast_json or '[]')[:12])
            if q not in normalize(f'{f.movie.title} {f.movie.director or ""} {cast}'):
                continue
        out.append(f)

    sort = p.get('sort') or ('rarest' if p.get('shelf') == 'rare' else 'soonest')
    keys = {
        'soonest': lambda f: f.next.start_time,
        'rarest': lambda f: (-f.rare_score, f.next.start_time),
        'wanted': lambda f: (-f.wanted, -f.going, f.next.start_time),
        'critics': lambda f: (-(f.movie.vote_average or 0), f.next.start_time),
        'title': lambda f: normalize(f.movie.title),
    }
    if not (p.get('shelf') and 'sort' not in p):        # shelves keep their own order
        out.sort(key=keys.get(sort, keys['soonest']))
    return out, ctx, reasons, start, end


def facets(films):
    """Counts per genre, theatre and decade (for the Filters sheet)."""
    out = {'genres': {}, 'theatres': {}, 'decades': {}}
    for f in films:
        for g in f.genres:
            out['genres'][g] = out['genres'].get(g, 0) + 1
        for slug in {x.theatre.slug for x in f.shows}:
            out['theatres'][slug] = out['theatres'].get(slug, 0) + 1
        if f.year:
            d = f"{str(f.year)[:3]}0"
            out['decades'][d] = out['decades'].get(d, 0) + 1
    return out


def browse(group, viewer, params, now=None, limit=24, offset=0):
    """Filtered, sorted films (a page of cards) + facet counts."""
    p = {k: v for k, v in params.items() if v not in (None, '')}
    out, ctx, reasons, start, end = select(group, viewer, p, now)
    page = out[offset:offset + limit]
    return {'films': [card(f, reasons.get(f.movie.id) or (f.rare_reasons if f.rare_score >= ctx['rare_min'] else []))
                      for f in page],
            'total': len(out), 'next_offset': offset + limit if len(out) > offset + limit else None,
            'facets': facets(out), 'regions': REGIONS, 'window': {'start': start.isoformat(), 'end': end.isoformat()},
            'title': SHELF_TITLES.get(p.get('shelf')) or MOODS.get(p.get('mood'), {}).get('label')}


# ─── Fun finders ──────────────────────────────────────────────────────────────

def surprise(group, viewer, when='tonight', exclude=(), now=None, rng=random, theatres=None):
    """One pick, weighted toward rare screenings, your genres, and what the
    club wants. Falls back to a wider window when tonight is empty."""
    now = now or datetime.now()
    for w in (when, 'week') if when != 'week' else ('week',):
        start, end = window(w, now)
        films = [f for f in catalog(group, start, end, viewer, theatres=theatres).values()
                 if f.movie.id not in set(exclude)]
        if films:
            break
    else:
        return None
    genres = context(group, viewer, {}, now)['genres']
    weights = [1 + max(0, f.rare_score) + 2 * len(f.genres & genres) + f.wanted + 2 * f.you_want for f in films]
    f = rng.choices(films, weights=weights, k=1)[0]
    why = list(f.rare_reasons if f.rare_score >= 4 else [])
    if f.genres & genres:
        why.append(sorted(f.genres & genres)[0])
    if f.wanted:
        why.append(f"{f.wanted} in the club want it")
    return {**card(f, why), 'when': w}


def double_features(films, limit=8):
    """Two films at the same theatre the same day, with a 15–75 minute gap."""
    shows = sorted((s for f in films.values() for s in f.shows), key=lambda s: s.start_time)
    by_venue_day = {}
    for s in shows:
        by_venue_day.setdefault((s.theatre_id, s.start_time.date()), []).append(s)
    pairs = []
    for group_shows in by_venue_day.values():
        for a in group_shows:
            a_end = a.end_time or a.start_time + timedelta(minutes=(a.movie.runtime_minutes or 110) + 15)
            for b in group_shows:
                gap = (b.start_time - a_end).total_seconds() / 60
                if b.movie_id != a.movie_id and 15 <= gap <= 75:
                    fa, fb = films[a.movie_id], films[b.movie_id]
                    score = max(0, fa.rare_score) + max(0, fb.rare_score) + fa.wanted + fb.wanted \
                        + (2 if fa.genres & fb.genres else 0)
                    pairs.append((score, a, b, int(gap)))
    pairs.sort(key=lambda p: (-p[0], p[1].start_time))
    # Variety: each film in at most one pair, at most three pairs per theatre
    # (otherwise one repertory series fills the whole list).
    used, per_theatre, out = set(), {}, []
    for score, a, b, gap in pairs:
        if a.movie_id in used or b.movie_id in used or per_theatre.get(a.theatre_id, 0) >= 3:
            continue
        used.update((a.movie_id, b.movie_id))
        per_theatre[a.theatre_id] = per_theatre.get(a.theatre_id, 0) + 1
        out.append({'theatre': a.theatre.short_name or a.theatre.name, 'gap_minutes': gap,
                    'first': card(films[a.movie_id]) | {'next': _show_brief(a)},
                    'second': card(films[b.movie_id]) | {'next': _show_brief(b)}})
        if len(out) >= limit:
            break
    return out


def _show_brief(s):
    return {'showtime_id': s.id, 'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label}


def spotlights(group, viewer, now=None, limit=6):
    """Directors (2+ films) and actors (3+ films) with work playing this month."""
    import json
    now = now or datetime.now()
    start, end = window('month', now)
    films = catalog(group, start, end, viewer)
    people = {}
    for f in films.values():
        for d in (f.movie.director or '').split(','):
            if d.strip():
                people.setdefault(('director', d.strip()), []).append(f)
        try:
            cast = json.loads(f.movie.cast_json or '[]')[:3]
        except ValueError:
            cast = []
        for c in cast:
            if c.get('name'):
                people.setdefault(('actor', c['name']), []).append(f)
    out = [(role, name, fs) for (role, name), fs in people.items()
           if len(fs) >= (2 if role == 'director' else 3)]
    out.sort(key=lambda x: (-len(x[2]), x[0] != 'director', x[1]))
    return [{'role': role, 'name': name, 'count': len(fs),
             'films': [card(f) for f in sorted(fs, key=lambda f: f.next.start_time)[:6]]}
            for role, name, fs in out[:limit]]


# ─── Discord: /find, /surprise and the chatbot (R3b) ─────────────────────────
# The bot sends a "type" (shelf:rare, mood:laugh, genre:horror, or free text)
# and a "where" (region:dc, theatre:afi, or free text); these turn them into
# the same params Browse uses, so every answer can link to the matching view.

BROWSE_KEYS = ('when', 'from', 'to', 'theatres', 'regions', 'genres', 'decade', 'format', 'time',
               'rarity', 'club', 'runtime', 'mood', 'shelf', 'q', 'sort')
REGION_KEYS = {'dc': 'DC', 'maryland': 'Maryland', 'virginia': 'Virginia'}
# /find's type list, in the order it's offered before anyone types.
FIND_SHELVES = ('rare', 'one-night', 'on-film', 'big-screen', 'events', 'arthouse', 'classics', 'opening',
                'last-chance', 'friends', 'most-wanted', 'for-you', 'critics', 'awards', 'blockbusters',
                'documentaries', 'horror', 'late-night', 'short', 'epics')


def browse_path(params):
    """The site's Browse URL for a set of filters."""
    from urllib.parse import urlencode
    return '/browse?' + urlencode([(k, params[k]) for k in BROWSE_KEYS if params.get(k)])


def describe(params, title=None):
    """Short human label: 'Rare gems · Horror · This weekend · Virginia'."""
    bits = [title or SHELF_TITLES.get(params.get('shelf')) or MOODS.get(params.get('mood'), {}).get('label')]
    if params.get('shelf') and params.get('mood') and not title:          # both named: say both
        bits.append(MOODS.get(params['mood'], {}).get('label'))
    if params.get('genres') and not params.get('mood'):
        bits.append(', '.join(g.title() for g in params['genres'].split(',')))
    if params.get('decade'):
        bits.append(f"{params['decade']}s")
    if params.get('format') == 'film' and params.get('shelf') != 'on-film':
        bits.append('On film')
    if params.get('club') == 'mine':
        bits.append('Your list')
    if params.get('q'):
        bits.append(f"“{params['q']}”")
    bits.append(WHEN.get(params.get('when') or 'week'))
    if params.get('regions'):
        bits.append(' + '.join(REGION_KEYS.get(r, r) for r in params['regions'].split(',')))
    if params.get('theatres'):
        bits.append(params.get('_theatre_label') or params['theatres'].replace(',', ', '))
    return ' · '.join(b for b in bits if b)


def find_types(group, now=None):
    """Everything /find's type box offers: shelves, moods, and the genres
    actually playing in the next month (most common first)."""
    now = now or datetime.now()
    blurbs = {k: b for k, _, b in SHELVES}
    out = [{'value': f'shelf:{k}', 'label': SHELF_TITLES[k], 'hint': blurbs[k]} for k in FIND_SHELVES]
    out += [{'value': f'mood:{k}', 'label': v['label'], 'hint': 'Mood'} for k, v in MOODS.items()]
    counts = {}
    for f in catalog(group, *window('month', now)).values():
        for g in f.genres:
            counts[g] = counts.get(g, 0) + 1
    out += [{'value': f'genre:{g}', 'label': g.title(), 'hint': f'Genre · {n} film{"s" if n != 1 else ""}'}
            for g, n in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]
    return out


# Words people use for each filter, for free-text /find input and the chatbot.
# Order matters where one message could match several shelves: the first wins.
_SHELF_WORDS = [
    ('one-night', r"\bone[- ]night( only)?\b|\bone[- ]offs?\b|\bsingle (showing|screening)\b"),
    ('last-chance', r"\blast chance\b|\bbefore (it'?s|they'?re) gone\b|\bfinal (showing|screening)s?\b|\bleaving theat"),
    ('on-film', r"\b(35|16|70) ?mm\b|\bon film\b|\bfilm prints?\b|\bcelluloid\b"),
    ('big-screen', r"\bimax\b|\bdolby\b|\bbig(gest)? screen\b"),
    ('events', r"\bq ?(&|and) ?a\b|\bpremieres?\b|\bspecial events?\b|\bmarathons?\b|\bin person\b|\bintroduction\b"),
    ('rare', r"\brare\b|\brarit|\bhard to (find|see|catch)\b|\bobscure\b|\bweird\b|\bstrange\b|\bcult\b"
             r"|\bunusual\b|\bdeep cuts?\b|\boff the beaten"),
    ('arthouse', r"\bart ?house\b|\bindie\b|\bindependent\b|\bartsy\b|\bforeign\b|\binternational\b"),
    ('classics', r"\bclassics?\b|\bold(er)? (movie|film)s?\b|\boldies?\b|\brepertory\b|\bretro\b|\bvintage\b"),
    ('blockbusters', r"\bblockbusters?\b|\bbig (new )?(movie|release)s?\b|\bpopcorn (movie|flick)s?\b|\bmainstream\b"),
    ('opening', r"\bnew (release|movie|film)s?\b|\bjust (came out|opened|released)\b|\bwhat'?s opening\b"
                r"|\bopening (this|next) week\b|\bnew this week\b"),
    ('critics', r"\bacclaimed\b|\bcritics?'? (pick|darling|favorite)s?\b|\bbest reviewed\b|\bhighly rated\b|\bwell reviewed\b"),
    ('awards', r"\boscars?\b|\baward[- ]winn|\bacademy awards?\b"),
    ('friends', r"\b(friends|anyone|everyone|people|the club|who'?s) (are |is )?going\b"),
    ('most-wanted', r"\bmost wanted\b|\bclub wants\b|\beveryone wants\b"),
    ('late-night', r"\blate[- ]night\b|\blate (show|screening)s?\b|\bmidnight\b"),
    ('short', r"\bshort (one|movie|film)\b|\bquick (one|movie|watch)\b|\bnot too long\b"),
    ('epics', r"\bepics?\b|\blong (one|movie|film)\b|\b(3|three)[- ]hours?\b"),
    ('documentaries', r"\bdocumentar(y|ies)\b|\bdocs\b"),
    ('for-you', r"\bfor me\b|\bmy taste\b|\bmy (kind|type) of\b"),
]
_MOOD_WORDS = [
    ('scare-me', r"\bscar(e|ed|y|iest)\b|\bspooky\b|\bcreepy\b|\bterrif|\bfrighten|\bhorror\b|\bhalloween\b"),
    ('laugh', r"\bfunny\b|\blaugh|\bhilarious\b|\bcomed(y|ies)\b|\blight ?hearted\b"),
    ('mind-bender', r"\bmind[- ]?(bend|blow)|\btrippy\b|\bsci[- ]?fi\b|\bcerebral\b|\bheady\b"),
    ('date-night', r"\bdate night\b|\bon a date\b|\bfor a date\b|\bromantic\b|\bromance\b|\brom ?coms?\b"),
    ('tissues', r"\bcry\b|\bsad\b|\btear ?jerkers?\b|\bemotional\b"),
    ('feel-good', r"\bfeel[- ]good\b|\buplifting\b|\bwholesome\b|\bcheer (me|us) up\b|\bcozy\b|\bfamily\b|\bkids\b"),
    ('thrills', r"\baction\b|\bthrill|\bexciting\b|\badrenaline\b|\bintense\b"),
]
_WHEN_WORDS = [
    ('tonight', r"\btonight\b|\btoday\b|\bthis evening\b"),
    ('tomorrow', r"\btomorrow\b"),
    ('weekend', r"\bweekend\b|\b(friday|saturday|sunday)\b"),
    ('2weeks', r"\bnext week\b|\b(two|2|couple( of)?) weeks\b"),
    ('week', r"\bthis week\b|\bnext few days\b"),
    ('month', r"\b(this|next) month\b"),
]
_REGION_WORDS = [
    ('dc', r"\bd\.?c\.?\b|\bthe district\b"),
    ('maryland', r"\bmaryland\b|\bmd\b|\bsilver spring\b|\bbethesda\b|\brockville\b"),
    ('virginia', r"\bvirginia\b|\bva\b|\bnova\b|\barlington\b|\balexandria\b|\bfairfax\b|\bcrystal city\b"),
]
_THEATRE_WORDS = [
    ('afi', r"\bafi\b"), ('suns', r"\bsuns\b"), ('alamo', r"\balamo\b"), ('regal', r"\bregal\b"),
    ('angelika', r"\bangelika\b"), ('amc', r"\bamc\b"), ('avalon', r"\bavalon\b"),
    ('nga', r"\bnational gallery\b|\bnga\b"), ('smi', r"\bsmithsonian\b|\bair and space\b|\budvar"),
]
_DECADE = re.compile(r"(?<![\d])'?(?:19)?([2-9]0)'?s\b|\b(20[0-2]0)'?s\b")
_ASKING = re.compile(r"\?|\b(any|anything|something|recommend\w*|recs?|suggest\w*|what'?s (on|playing|showing)"
                     r"|where can|should (i|we)|looking for|worth (seeing|catching)|playing|showing)\b")


def _match(words, text):
    return [key for key, pattern in words if re.search(pattern, text)]


def _theatre_slugs(prefix):
    return {s for s in REGIONS if s == prefix or s.startswith(prefix + '-')}


def parse_request(text, genres=()):
    """Filters a plain-English ask names: ("anything weird and rare in
    Virginia this weekend?") -> {'shelf': 'rare', 'when': 'weekend',
    'regions': 'virginia'}. Only what's clearly named; never search text."""
    t = normalize(text).replace('’', "'")
    p = {}
    shelves = _match(_SHELF_WORDS, t)
    if shelves:
        p['shelf'] = shelves[0]
    moods = _match(_MOOD_WORDS, t)
    if moods:
        p['mood'] = moods[0]
    picked = sorted(g for g in genres if re.search(rf"\b{re.escape(g)}\b", t))
    if picked:
        p['genres'] = ','.join(picked)
    m = _DECADE.search(t)
    if m:
        d = m.group(2) or m.group(1)
        p['decade'] = d if len(d) == 4 else ('19' + d)
    if re.search(r"\b(my watchlist|on my list)\b", t):
        p['club'] = 'mine'
    when = _match(_WHEN_WORDS, t)
    if when:
        p['when'] = when[0]
    regions = _match(_REGION_WORDS, t)
    if regions:
        p['regions'] = ','.join(regions)
    theatres = set().union(*[_theatre_slugs(k) for k in _match(_THEATRE_WORDS, t)])
    if theatres:
        p['theatres'] = ','.join(sorted(theatres))
    return p


def find_params(type_value=None, where=None, when=None, q=None):
    """Browse params for /find's (type, where, when, search) options."""
    p = {}
    tv = (type_value or '').strip()
    kind, _, key = tv.partition(':')
    if kind == 'shelf' and key in SHELF_TITLES:
        p['shelf'] = key
    elif kind == 'mood' and key in MOODS:
        p['mood'] = key
    elif kind == 'genre' and key:
        p['genres'] = key.lower()
    elif tv:
        n = normalize(tv)
        exact = next((k for k, title, _ in SHELVES if normalize(title) == n or k == n), None) \
            or next((k for k, v in MOODS.items() if normalize(v['label']) == n or k == n), None)
        if exact in SHELF_TITLES:
            p['shelf'] = exact
        elif exact:
            p['mood'] = exact
        else:
            parsed = {k: v for k, v in parse_request(tv, COMMON_GENRES).items()
                      if k not in ('when', 'regions', 'theatres')}
            p.update(parsed or {'q': tv})

    w = (where or '').strip()
    kind, _, key = w.partition(':')
    if kind == 'region' and key in REGION_KEYS:
        p['regions'] = key
    elif kind == 'theatre' and key:
        p['theatres'] = key
    elif w:
        n = normalize(w)
        if n in REGIONS:
            p['theatres'] = n
        else:
            parsed = parse_request(w)
            if parsed.get('theatres') or parsed.get('regions'):
                p.update({k: parsed[k] for k in ('theatres', 'regions') if k in parsed})
            else:
                p['theatres'] = n

    if when in WHEN:
        p['when'] = when
    if q and q.strip():
        p['q'] = (p.get('q', '') + ' ' + q.strip()).strip() if 'q' in p else q.strip()
    return p


# Genre names free-text /find input is checked against (the chatbot uses
# whatever's actually playing instead).
COMMON_GENRES = {'action', 'adventure', 'animation', 'comedy', 'crime', 'documentary', 'drama', 'family',
                 'fantasy', 'history', 'horror', 'music', 'mystery', 'romance', 'science fiction', 'thriller',
                 'war', 'western'}


def _pick_line(f, reasons=()):
    s = f.next
    return {'title': f.movie.title, 'year': f.year, 'when': s.start_time.strftime('%a %-m/%-d %-I:%M %p'),
            'theatre': s.theatre.short_name or s.theatre.name, 'format': s.format_label or '',
            'more': len(f.shows) - 1, 'reasons': [str(r) for r in reasons if r and str(r) != str(f.year)][:2]}


def chat_picks(group, viewer, text, now=None, limit=10):
    """What the @CinemaBot chat gets handed as "what's playing": films that fit
    what was asked (or, for a vague ask, a mix of rare, club and soonest),
    plus anything playing that the message names. `link` says whether the
    reply should carry a "more like this" Browse link."""
    now = now or datetime.now()
    films = catalog(group, *window('2weeks', now), viewer)
    genres = {g for f in films.values() for g in f.genres}
    p = parse_request(text, genres)
    t = normalize(text).replace('’', "'")
    typed = any(k in p for k in ('shelf', 'mood', 'genres', 'decade', 'club'))
    placed = any(k in p for k in ('regions', 'theatres'))

    picks, seen = [], set()

    def add(f, reasons=()):
        if f.movie.id not in seen and len(picks) < limit:
            seen.add(f.movie.id)
            picks.append(_pick_line(f, reasons))

    # Films the message names come first, so "is X still playing?" gets a real answer.
    for f in sorted(films.values(), key=lambda f: -len(f.movie.title)):
        name = normalize(f.movie.title)
        name = name[4:] if name.startswith('the ') else name
        if len(name) >= 4 and re.search(rf"(?<!\w){re.escape(name)}(?!\w)", t):
            add(f, f.rare_reasons if f.rare_score >= 4 else ())
        if len(picks) >= 3:
            break

    if typed or placed or 'when' in p:
        params = {**p, 'when': p.get('when', '2weeks')}
        if typed:
            result = browse(group, viewer, params, now, limit=limit)
            for c in result['films']:
                f = films.get(c['movie']['id'])
                if f:
                    add(f, c['reasons'])
                else:            # outside the two-week catalog (e.g. "this month")
                    if c['movie']['id'] not in seen and len(picks) < limit:
                        seen.add(c['movie']['id'])
                        dt = datetime.fromisoformat(c['next']['start_time'])
                        picks.append({'title': c['movie']['title'], 'year': c['movie']['year'],
                                      'when': dt.strftime('%a %-m/%-d %-I:%M %p'), 'theatre': c['next']['theatre'],
                                      'format': c['next']['format_label'] or '', 'more': c['showings'] - 1,
                                      'reasons': [str(r) for r in c['reasons'] if str(r) != str(c['movie']['year'])][:2]})
            total = result['total']
        else:
            start, end = window(params['when'], now)
            theatres = {x for x in (p.get('theatres') or '').split(',') if x} | \
                {s for s, r in REGIONS.items() if r.lower() in (p.get('regions') or '').split(',')}
            scoped = catalog(group, start, end, viewer, theatres=theatres or None)
            _mix(scoped, group, viewer, now, add)
            total = len(scoped)
    else:
        params = {'when': '2weeks'}
        _mix(films, group, viewer, now, add)
        total = len(films)

    return {'label': describe(params), 'films': picks, 'total': total,
            'browse_path': browse_path(params),
            'link': bool((typed or placed) and _ASKING.search(t))}


def _mix(films, group, viewer, now, add):
    """A vague ask: a few rare ones, what friends are going to, then soonest."""
    ctx = context(group, viewer, films, now)
    for f, r in shelf('rare', films, ctx)[:4]:
        add(f, r)
    for f, r in shelf('friends', films, ctx)[:3]:
        add(f, r)
    for f in sorted(films.values(), key=lambda f: f.next.start_time):
        add(f)


# ─── Search suggestions (R6c) ─────────────────────────────────────────────────
# As you type in a search box: films (playing first, then the rest of the
# database), directors and actors in what's playing, and every Browse filter
# whose name (or a common word for it) matches — so "spooky" offers "Scare me",
# "70" offers "On film", "afi" offers AFI Silver.

SUGGEST_TTL = 120                 # seconds a club's index is reused (per server process)
_suggest_index = {}

_MOOD_TERMS = {
    'scare-me': ['scary', 'spooky', 'horror', 'creepy', 'halloween', 'frightening'],
    'laugh': ['funny', 'comedy', 'hilarious'],
    'mind-bender': ['trippy', 'sci-fi', 'science fiction', 'cerebral'],
    'date-night': ['romantic', 'romance', 'date', 'rom-com'],
    'tissues': ['sad', 'cry', 'tearjerker', 'emotional'],
    'feel-good': ['uplifting', 'cozy', 'wholesome', 'family'],
    'thrills': ['action', 'exciting', 'adrenaline', 'intense'],
}
_OTHER_FILTERS = [
    # (params, label, hint, extra terms)
    ({'format': 'film'}, 'On film (35/16/70mm)', 'Format', ['35mm', '16mm', '70mm', 'film print', 'celluloid']),
    ({'format': 'big'}, 'Big screen (IMAX, 70mm, Dolby)', 'Format', ['imax', 'dolby', '70mm', 'big screen']),
    ({'time': 'matinee'}, 'Matinee (before 5pm)', 'Time of day', ['afternoon', 'daytime']),
    ({'time': 'evening'}, 'Evening (5–9pm)', 'Time of day', ['night']),
    ({'time': 'late'}, 'Late night (9:30pm+)', 'Time of day', ['midnight', 'late show']),
    ({'runtime': 'short'}, 'Under 95 minutes', 'Length', ['short', 'quick']),
    ({'runtime': 'long'}, 'Over 2½ hours', 'Length', ['long', 'epic']),
    ({'rarity': 'repertory'}, 'Repertory (5+ years old)', 'Rarity', ['old', 'revival', 'retro']),
    ({'rarity': 'wide'}, 'Wide release', 'Rarity', ['mainstream', 'everywhere']),
]
_CLUB_FILTERS = [
    ({'club': 'going'}, 'Friends going', 'Club', ['friends', 'club going']),
    ({'club': 'wanted'}, 'The club wants it', 'Club', ['wanted', 'club wants']),
]
_DECADE_TYPED = re.compile(r"^'?(?:(19|20)?(\d)0)'?s?$")


def _score(n, terms, words_only=False):
    """How well typed text `n` matches any of `terms` (lower is better), or
    None. words_only: only at the start of a word (names and titles)."""
    best = None
    for term in terms:
        t = normalize(term)
        if not t:
            continue
        if t.startswith(n):
            s = 0
        elif any(w.startswith(n) for w in re.split(r"[\s\-/&,.:']+", t)) or (' ' in n and n in t):
            s = 1
        elif words_only:
            continue
        elif re.search(rf"(?<!\w){re.escape(t)}(?!\w)", n) or n in t:      # "horror movies", "rama" in "drama"
            s = 2
        else:
            continue
        best = s if best is None else min(best, s)
    return best


def _suggest_films_index(group, now):
    """What's playing in the next month, boiled down to what suggestions need
    (plain data: safe to reuse across requests)."""
    import json
    key = group.id if group else None
    hit = _suggest_index.get(key)
    clock = __import__('time').monotonic()
    if hit and clock - hit[0] < SUGGEST_TTL:
        return hit[1]
    films, people, genres = [], {}, {}
    for f in catalog(group, *window('month', now)).values():
        m, s = f.movie, f.next
        films.append({'id': m.id, 'title': m.title, 'year': f.year, 'poster_url': m.poster_url,
                      'next': s.start_time.isoformat(), 'theatre': s.theatre.short_name or s.theatre.name,
                      'showings': len(f.shows)})
        for d in (m.director or '').split(','):
            if d.strip():
                people.setdefault((d.strip(), 'director'), set()).add(m.id)
        try:
            cast = json.loads(m.cast_json or '[]')[:8]
        except ValueError:
            cast = []
        for c in cast:
            if isinstance(c, dict) and c.get('name'):
                people.setdefault((c['name'], 'actor'), set()).add(m.id)
        for g in f.genres:
            genres[g] = genres.get(g, 0) + 1
    index = {'films': films, 'people': {k: len(v) for k, v in people.items()}, 'genres': genres}
    if len(_suggest_index) > 50:
        _suggest_index.clear()
    _suggest_index[key] = (clock, index)
    return index


def suggest(group, viewer, text, now=None, limit_films=6, limit_people=4, limit_filters=6):
    """{films, people, filters} matching what's been typed so far. Films are
    {id, title, year, poster_url, playing, next?, theatre?}; people and filters
    carry the Browse `params` that picking them applies."""
    from app import Movie, Theatre
    now = now or datetime.now()
    n = normalize(text).strip()
    empty = {'films': [], 'people': [], 'filters': [], 'order': ['films', 'people', 'filters']}
    if len(n) < 2:
        return empty
    index = _suggest_films_index(group, now)

    scored = []
    for f in index['films']:
        s = _score(n, [f['title']], words_only=True)
        if s is not None:
            scored.append((s, -f['showings'], f['title'], f))
    films = [{**f, 'playing': True} for *_, f in sorted(scored, key=lambda x: x[:3])[:limit_films]]
    if len(films) < limit_films:
        playing = {f['id'] for f in index['films']}
        like = f"%{n.replace('%', '').replace('_', '')}%"
        from app import db
        more = (Movie.query.filter(db.or_(Movie.title_normalized.like(like), db.func.lower(Movie.title).like(like)),
                                   Movie.tmdb_id.isnot(None))
                .order_by(Movie.vote_average.desc().nullslast()).limit(30).all())
        lib = []
        for m in more:
            s = _score(n, [m.title], words_only=True)
            if m.id not in playing and s is not None:
                y = (m.release_year or '')[:4]
                lib.append((s, m.title, {'id': m.id, 'title': m.title, 'year': int(y) if y.isdigit() else None,
                                         'poster_url': m.poster_url, 'playing': False}))
        films += [x for *_, x in sorted(lib, key=lambda x: x[:2])[:limit_films - len(films)]]

    people = []
    for (name, role), count in index['people'].items():
        s = _score(n, [name], words_only=True)
        if s is not None:
            people.append((s, -count, name, role, count))
    people.sort()
    people_best = people[0][0] if people else 9
    people = [{'name': name, 'role': role, 'count': count, 'params': {'q': name}}
              for _, _, name, role, count in people[:limit_people]]

    options = []        # (params, label, hint, terms)
    for k, title, blurb in SHELVES:
        if (k in ('friends', 'most-wanted') and not group) or (k == 'for-you' and not viewer):
            continue
        options.append(({'shelf': k}, title, blurb, [title, k.replace('-', ' ')]))
    for k, v in MOODS.items():
        options.append(({'mood': k}, v['label'], 'Mood', [v['label'], *_MOOD_TERMS.get(k, [])]))
    for g, count in sorted(index['genres'].items(), key=lambda x: -x[1]):
        options.append(({'genres': g}, g.title(), f"Genre · {count} film{'s' if count != 1 else ''}", [g]))
    for k, label in WHEN.items():
        options.append(({'when': k}, label, 'When', [label, *(['today', 'this evening'] if k == 'tonight' else [])]))
    for k, label in REGION_KEYS.items():
        options.append(({'regions': k}, label, 'Area', [label, k]))
    slugs = {t.strip() for t in ((group.theatres or '') if group else '').split(',') if t.strip()}
    for t in Theatre.query.filter(Theatre.is_active.isnot(False)).all():
        if not slugs or t.slug in slugs:
            options.append(({'theatres': t.slug}, t.name, 'Theatre', [t.name, t.short_name or '', t.slug]))
    options += _OTHER_FILTERS
    if group:
        options += _CLUB_FILTERS
    if viewer:
        options.append(({'club': 'mine'}, 'My plans & watchlist', 'Yours', ['mine', 'my list', 'watchlist']))

    filters, seen = [], set()
    m = _DECADE_TYPED.match(n)
    if m:
        decade = f"{m.group(1) or ('20' if m.group(2) in '012' else '19')}{m.group(2)}0"
        filters.append((0, {'params': {'decade': decade}, 'label': f'{decade}s', 'hint': 'Decade'}))
    for params, label, hint, terms in options:
        s = _score(n, terms)
        key = tuple(sorted(params.items()))
        if s is not None and key not in seen:
            seen.add(key)
            filters.append((s, {'params': params, 'label': label, 'hint': hint}))
    filters.sort(key=lambda x: x[0])
    # Groups in order of how well they match: typing "dra" leads with Drama.
    best = {'films': min((s for s, *_ in scored), default=9), 'people': people_best,
            'filters': filters[0][0] if filters else 9}
    order = sorted(('films', 'people', 'filters'), key=lambda k: best[k])
    return {'films': films, 'people': people, 'filters': [f for _, f in filters[:limit_filters]], 'order': order}

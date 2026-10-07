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
    if not films or not group:
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


def browse(group, viewer, params, now=None, limit=24, offset=0):
    """Filtered, sorted films + facet counts. `params` is a dict of the URL
    filters: when/from/to, theatres, regions, genres, decade, format, time,
    rarity, club, runtime, mood, shelf, q, sort."""
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

    facets = {'genres': {}, 'theatres': {}, 'decades': {}}
    for f in out:
        for g in f.genres:
            facets['genres'][g] = facets['genres'].get(g, 0) + 1
        for s in {x.theatre for x in f.shows}:
            key = s.slug
            facets['theatres'][key] = facets['theatres'].get(key, 0) + 1
        if f.year:
            d = f"{str(f.year)[:3]}0"
            facets['decades'][d] = facets['decades'].get(d, 0) + 1
    page = out[offset:offset + limit]
    return {'films': [card(f, reasons.get(f.movie.id) or (f.rare_reasons if f.rare_score >= ctx['rare_min'] else []))
                      for f in page],
            'total': len(out), 'next_offset': offset + limit if len(out) > offset + limit else None,
            'facets': facets, 'regions': REGIONS, 'window': {'start': start.isoformat(), 'end': end.isoformat()},
            'title': SHELF_TITLES.get(p.get('shelf')) or MOODS.get(p.get('mood'), {}).get('label')}


# ─── Fun finders ──────────────────────────────────────────────────────────────

def surprise(group, viewer, when='tonight', exclude=(), now=None, rng=random):
    """One pick, weighted toward rare screenings, your genres, and what the
    club wants. Falls back to a wider window when tonight is empty."""
    now = now or datetime.now()
    for w in (when, 'week') if when != 'week' else ('week',):
        start, end = window(w, now)
        films = [f for f in catalog(group, start, end, viewer).values() if f.movie.id not in set(exclude)]
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

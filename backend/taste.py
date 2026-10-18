"""Your taste (R13): what you like, so Discover, theatre pages, Browse and
/foryou can pick films for you. One definition for the whole site:

  · GENRES — TMDB's genres (what films store, lowercased) plus the ones only
    OMDb/IMDb names (film noir, musical, biography, sport); merge_genres()
    turns either source's names into these keys
  · WAYS — how you like to see films (on film, 70mm/IMAX, Q&As, classics…)
  · everything someone tells us is a TasteItem: favorite genres, genres
    they're not into, ways, favorite theatres, films, directors, actors and
    writers, and films they said aren't for them. Read and written only here.

Your taste shows on your profile only if you switch that on
(User.taste_public); recommendations use it either way."""

GENRES = [                     # key (as films store it), label
    ('action', 'Action'), ('adventure', 'Adventure'), ('animation', 'Animation'), ('biography', 'Biography'),
    ('comedy', 'Comedy'), ('crime', 'Crime'), ('documentary', 'Documentary'), ('drama', 'Drama'),
    ('family', 'Family'), ('fantasy', 'Fantasy'), ('film-noir', 'Film noir'), ('history', 'History'),
    ('horror', 'Horror'), ('music', 'Music'), ('musical', 'Musical'), ('mystery', 'Mystery'),
    ('romance', 'Romance'), ('science fiction', 'Sci-fi'), ('sport', 'Sport'), ('thriller', 'Thriller'),
    ('war', 'War'), ('western', 'Western'),
]
GENRE_KEYS = [k for k, _ in GENRES]
GENRE_LABELS = dict(GENRES)
# Other names for our genres (OMDb's, and the old profile list's); names not
# here or in GENRES (TV Movie, Short, News, Reality-TV…) are dropped.
ALIASES = {'sci-fi': 'science fiction', 'science-fiction': 'science fiction', 'film noir': 'film-noir',
           'noir': 'film-noir', 'biographical': 'biography', 'biopic': 'biography'}

WAYS = [                       # key, label, emoji — what each means is discover.way_fits()
    ('film', 'On film prints', '🎞️'), ('big', '70mm, IMAX & Dolby', '🖥️'), ('events', 'Q&As & special events', '🎤'),
    ('classics', 'Classics', '🏛️'), ('foreign', 'Foreign-language', '🌍'), ('arthouse', 'Arthouse & indie', '🎨'),
    ('late', 'Late shows', '🌙'), ('matinee', 'Matinees', '☀️'),
]
WAY_KEYS = [k for k, _, _ in WAYS]

# The old profile list (before R13): names that weren't genres become ways.
LEGACY_WAYS = {'classic': 'classics', 'foreign': 'foreign', 'indie': 'arthouse', 'experimental': 'arthouse'}

PEOPLE = ('director', 'actor', 'writer')
KINDS = ('genre', 'avoid', 'way', 'theatre', 'movie', *PEOPLE, 'hide')
LIMIT = 40                     # per kind


def genre_key(name):
    """Our key for a genre name from TMDB, OMDb or a person, or None."""
    n = ' '.join((name or '').strip().lower().split())
    n = ALIASES.get(n, n)
    return n if n in GENRE_LABELS else None


def merge_genres(*sources):
    """One comma string of our genre keys from any lists of names (TMDB's,
    OMDb's), first-seen order, no repeats."""
    out = []
    for names in sources:
        for name in names or ():
            k = genre_key(name)
            if k and k not in out:
                out.append(k)
    return ','.join(out)


def genres(user):
    """Someone's favorite genres, as keys in GENRES order (remembered on the
    user object for the rest of the request)."""
    if not user or not getattr(user, 'id', None):
        return []
    if getattr(user, '_taste_genres', None) is None:
        mine = {i.key for i in items(user, 'genre')}
        user._taste_genres = [k for k in GENRE_KEYS if k in mine]
    return user._taste_genres


def set_genres(user, raw):
    """Favorite genres from a list or comma string of names; a genre picked
    here stops being one you're not into."""
    from app import TasteItem
    raw = raw.split(',') if isinstance(raw, str) else (raw or [])
    picked = [k for k in GENRE_KEYS if k in {genre_key(g) for g in raw}]
    _replace(user, 'genre', picked, GENRE_LABELS.get)
    if picked:
        TasteItem.query.filter(TasteItem.user_id == user.id, TasteItem.kind == 'avoid',
                               TasteItem.key.in_(picked)).delete(synchronize_session=False)
    user._taste_genres = picked


def items(user, kind=None):
    from app import TasteItem
    if not user or not user.id:
        return []
    q = TasteItem.query.filter_by(user_id=user.id)
    if kind:
        q = q.filter_by(kind=kind)
    return q.order_by(TasteItem.created_at, TasteItem.id).all()


def _replace(user, kind, keys, label=lambda k: k):
    """Make `kind`'s items exactly `keys` (kept ones keep their date)."""
    from app import db, TasteItem
    keys = list(dict.fromkeys(keys))[:LIMIT]
    have = {i.key: i for i in items(user, kind)}
    for k, row in have.items():
        if k not in keys:
            db.session.delete(row)
    for k in keys:
        if k not in have:
            db.session.add(TasteItem(user_id=user.id, kind=kind, key=k, label=label(k)))


def update(user, data):
    """Change any of: genres, avoid (genres you're not into), ways, theatres
    (slugs), public. Returns an error message or None (nothing saved then)."""
    from app import db, Theatre
    if 'theatres' in data:
        known = {t.slug: t.name for t in Theatre.query.filter(Theatre.is_active.isnot(False))}
        if any(s not in known for s in data['theatres'] or []):
            return 'Pick theatres from the list.'
    if 'ways' in data and any(w not in WAY_KEYS for w in data['ways'] or []):
        return 'Pick ways to watch from the list.'
    if 'genres' in data:
        set_genres(user, data['genres'] or [])
    if 'avoid' in data:
        avoid = [k for k in (genre_key(g) for g in data['avoid'] or []) if k and k not in genres(user)]
        _replace(user, 'avoid', avoid, GENRE_LABELS.get)
    if 'ways' in data:
        _replace(user, 'way', data['ways'] or [], {k: label for k, label, _ in WAYS}.get)
    if 'theatres' in data:
        _replace(user, 'theatre', data['theatres'] or [], known.get)
    if 'public' in data:
        user.taste_public = bool(data['public'])
    db.session.commit()
    return None


def _person_key(name):
    return ' '.join((name or '').lower().split())


def add(user, data):
    """Add a favorite film ({kind: 'movie', movie_id | tmdb_id}), person
    ({kind: director|actor|writer, name}) or a film that's not for you
    ({kind: 'hide', movie_id}). Returns an error message or None."""
    from app import db, Movie, TasteItem, movie_for_tmdb
    kind = data.get('kind')
    if kind not in ('movie', 'hide', *PEOPLE):
        return 'Pick a film or a person.'
    if len(items(user, kind)) >= LIMIT:
        return f'That’s {LIMIT} already — remove one first.'
    if kind in PEOPLE:
        name = ' '.join((data.get('name') or '').split())[:200]
        if len(name) < 2:
            return 'Type a name.'
        key, label, movie = _person_key(name), name, None
    else:
        movie = db.session.get(Movie, int(data['movie_id'])) if str(data.get('movie_id') or '').isdigit() else None
        if not movie and kind == 'movie' and str(data.get('tmdb_id') or '').isdigit():
            movie = movie_for_tmdb(int(data['tmdb_id']))
        if not movie:
            return 'That film isn’t one we can find.'
        key, label = str(movie.id), movie.title
    if not TasteItem.query.filter_by(user_id=user.id, kind=kind, key=key).first():
        db.session.add(TasteItem(user_id=user.id, kind=kind, key=key, label=label, movie_id=movie.id if movie else None))
        db.session.commit()
    return None


def remove(user, kind, key):
    from app import db, TasteItem
    TasteItem.query.filter_by(user_id=user.id, kind=kind, key=str(key)).delete()
    db.session.commit()


def _movie(i):
    m = i.movie
    return {'key': i.key, 'label': i.label, 'movie_id': i.movie_id,
            'year': m.release_year if m else None, 'poster_url': m.poster_url if m else None}


def is_set(user):
    """Has someone told us anything about their taste yet?"""
    return any(i.kind != 'hide' for i in items(user))


def view(user):
    """Everything the Your taste sheet shows: the choices and your picks."""
    from app import Theatre
    mine = items(user)
    by = lambda kind: [i for i in mine if i.kind == kind]
    return {
        'options': {
            'genres': [{'key': k, 'label': label} for k, label in GENRES],
            'ways': [{'key': k, 'label': label, 'emoji': e} for k, label, e in WAYS],
            'theatres': [{'slug': t.slug, 'name': t.name, 'short_name': t.short_name or t.name, 'color': t.color}
                         for t in Theatre.query.filter(Theatre.is_active.isnot(False)).order_by(Theatre.name)],
        },
        'genres': genres(user),
        'avoid': [i.key for i in by('avoid')],
        'ways': [i.key for i in by('way')],
        'theatres': [i.key for i in by('theatre')],
        'movies': [_movie(i) for i in by('movie')],
        'people': [{'kind': i.kind, 'key': i.key, 'label': i.label} for i in mine if i.kind in PEOPLE],
        'hidden': [_movie(i) for i in by('hide')],
        'public': bool(user.taste_public),
        'set': is_set(user),
        'summary': summary(user),
    }


def summary(user):
    """What a profile shows of someone's taste (when they've made it public):
    labels only."""
    mine = items(user)
    ways = {k: f'{e} {label}' for k, label, e in WAYS}
    return {
        'genres': [GENRE_LABELS[k] for k in genres(user)],
        'ways': [ways[i.key] for i in mine if i.kind == 'way' and i.key in ways],
        'movies': [_movie(i) for i in mine if i.kind == 'movie'],
        'people': [{'kind': i.kind, 'label': i.label} for i in mine if i.kind in PEOPLE],
        'theatres': [i.label for i in mine if i.kind == 'theatre'],
    }


def people_search(q, kind=None, limit=8):
    """Names for the favorite-people search: from our films' credits first,
    then TMDB's people. [{name, kind}] (kind: director | actor | writer)."""
    import json
    from app import Movie
    from discover import normalize
    n = normalize(q).strip()
    if len(n) < 2:
        return []
    like = f'%{q.strip()}%'
    found = {}

    def note(name, k):
        if name and n in normalize(name) and (not kind or kind == k):
            found.setdefault((name, k), 0)
            found[(name, k)] += 1
    for m in Movie.query.filter((Movie.director.ilike(like)) | (Movie.cast_json.ilike(like))
                                | (Movie.crew_json.ilike(like))).limit(200):
        for d in (m.director or '').split(','):
            note(d.strip(), 'director')
        for field, pick in (('cast_json', lambda c: 'actor'),
                            ('crew_json', lambda c: 'writer' if c.get('job') in ('Writer', 'Screenplay') else None)):
            try:
                rows = json.loads(getattr(m, field) or '[]')
            except ValueError:
                rows = []
            for c in rows:
                if isinstance(c, dict) and pick(c):
                    note(c.get('name'), pick(c))
    out = [{'name': name, 'kind': k} for (name, k), _ in sorted(found.items(), key=lambda kv: (-kv[1], kv[0][0]))]
    if len(out) < limit:
        import enrich
        for p in enrich.tmdb_people(q):
            if (not kind or p['kind'] == kind) and not any(o['name'] == p['name'] and o['kind'] == p['kind'] for o in out):
                out.append(p)
    return out[:limit]


def migrate_legacy_genres():
    """Profiles from before R13 kept favorite genres in User.favorite_genres
    (with old names, and some that weren't genres): move them to TasteItems —
    classic, foreign, indie… become ways to watch — and clear the column.
    Safe to re-run."""
    from app import db, TasteItem, User
    way_labels = {k: label for k, label, _ in WAYS}
    for u in User.query.filter(User.favorite_genres.isnot(None), User.favorite_genres != ''):
        names = [g.strip().lower() for g in u.favorite_genres.split(',') if g.strip()]
        have = {(i.kind, i.key) for i in TasteItem.query.filter_by(user_id=u.id)}
        for kind, key, label in ([('genre', k, GENRE_LABELS[k]) for k in dict.fromkeys(filter(None, map(genre_key, names)))]
                                 + [('way', LEGACY_WAYS[g], way_labels[LEGACY_WAYS[g]]) for g in names if g in LEGACY_WAYS]):
            if (kind, key) not in have:
                have.add((kind, key))
                db.session.add(TasteItem(user_id=u.id, kind=kind, key=key, label=label))
        u.favorite_genres = ''
    db.session.commit()


# ─── For you: the engine ──────────────────────────────────────────────────────
# A film playing soon earns points for what you told us (favorite films,
# people, genres, ways, theatres, your watchlist) and, more lightly, for what
# you've done (the genres and directors of films you planned, saw, rated
# well on Letterboxd or watchlisted). Genres you're not into count against
# it; films you've seen or said aren't for you are left out. Each point
# comes with the reason shown on the card.

POINTS = {'watchlist': 5, 'favorite_film': 6, 'person': 4, 'learned_director': 2, 'genre': 2, 'way': 1.5,
          'theatre': 1.5, 'learned_genre': 0.5, 'avoid': -3}
MIN_SCORE = 2          # below this, not "for you"
LIKED_RATING = 3.5     # Letterboxd stars that count as liking a film
DISLIKED_RATING = 2


def _people_of(movie):
    """[(key, label, kind)] — a film's director(s), writers and top-billed cast."""
    import json
    out = [(_person_key(d), d.strip(), 'director') for d in (movie.director or '').split(',') if d.strip()]
    for field, kind_of, top in (('crew_json', lambda c: 'writer' if c.get('job') in ('Writer', 'Screenplay') else None, 50),
                                ('cast_json', lambda c: 'actor', 8)):
        try:
            rows = json.loads(getattr(movie, field) or '[]')[:top]
        except ValueError:
            rows = []
        out += [(_person_key(c['name']), c['name'], kind_of(c)) for c in rows
                if isinstance(c, dict) and c.get('name') and kind_of(c)]
    return out


def profile(user):
    """Everything scoring needs about someone, gathered once per request."""
    from collections import Counter
    from app import Attendance, LetterboxdEntry, Movie, RSVP, Showtime, Watchlist, db
    if not user or not getattr(user, 'id', None):
        return None
    if getattr(user, '_taste_profile', None) is not None:
        return user._taste_profile
    mine = items(user)
    of = lambda kind: {i.key for i in mine if i.kind == kind}
    p = {'genres': set(genres(user)), 'avoid': of('avoid'), 'ways': of('way'), 'theatres': of('theatre'),
         'movies': {i.movie_id for i in mine if i.kind == 'movie'}, 'hide': {i.movie_id for i in mine if i.kind == 'hide'},
         'people': {i.key: (i.label, i.kind) for i in mine if i.kind in PEOPLE}}
    p['seen'] = {mid for (mid,) in db.session.query(Showtime.movie_id).join(Attendance, Attendance.showtime_id == Showtime.id)
                 .filter(Attendance.user_id == user.id, Attendance.status == 'went')}
    planned = {mid for (mid,) in db.session.query(Showtime.movie_id).join(RSVP, RSVP.showtime_id == Showtime.id)
               .filter(RSVP.user_id == user.id, RSVP.status.in_(('going', 'maybe')))}
    wanted = {w.movie_id for w in Watchlist.query.filter_by(user_id=user.id)}
    rated = {e.tmdb_id: e.rating for e in LetterboxdEntry.query.filter(LetterboxdEntry.user_id == user.id,
                                                                       LetterboxdEntry.rating.isnot(None),
                                                                       LetterboxdEntry.tmdb_id.isnot(None))}
    by_tmdb = {m.tmdb_id: m.id for m in Movie.query.filter(Movie.tmdb_id.in_(list(rated)))} if rated else {}
    liked = p['movies'] | planned | p['seen'] | wanted | {by_tmdb[t] for t, r in rated.items() if t in by_tmdb and r >= LIKED_RATING}
    disliked = {by_tmdb[t] for t, r in rated.items() if t in by_tmdb and r <= DISLIKED_RATING}
    p['seen'] |= {by_tmdb[t] for t in rated if t in by_tmdb}          # on your Letterboxd diary: seen
    learned, directors = Counter(), {}
    for m in Movie.query.filter(Movie.id.in_(list(liked | disliked))) if liked | disliked else []:
        sign = -1 if m.id in disliked else 1
        for g in (m.genres or '').split(','):
            if g in GENRE_LABELS:
                learned[g] += sign
        if sign > 0:
            for key, label, kind in _people_of(m):
                if kind == 'director':
                    directors.setdefault(key, label)
    p['learned_genres'], p['learned_directors'] = learned, directors
    user._taste_profile = p
    return p


def score(f, p, ctx):
    """(points, reasons) for a discover.Film, or None when it isn't for you."""
    import discover
    m = f.movie
    if not p or m.id in p['hide'] or m.id in p['seen']:
        return None
    points, why = 0.0, []

    def add(n, reason=None):
        nonlocal points
        points += n
        if reason and reason not in why:
            why.append(reason)
    if f.you_want:
        add(POINTS['watchlist'], 'on your watchlist')
    if m.id in p['movies']:
        add(POINTS['favorite_film'], 'a favorite of yours')
    named = set()
    for key, label, kind in _people_of(m):
        if key in p['people'] and key not in named:
            named.add(key)
            add(POINTS['person'], label)
        elif kind == 'director' and key in p['learned_directors'] and key not in named:
            named.add(key)
            add(POINTS['learned_director'], f'more from {label}')
    for g in sorted(f.genres & p['genres'])[:2]:
        add(POINTS['genre'], GENRE_LABELS[g])
    points += POINTS['avoid'] * len(f.genres & p['avoid'])
    for w in WAY_KEYS:
        if w in p['ways']:
            reason = discover.way_fits(w, f, ctx)
            if reason:
                add(POINTS['way'], reason)
    here = sorted(f.venues & p['theatres'])
    if here:
        add(POINTS['theatre'], f'at {next(s.theatre.short_name or s.theatre.name for s in f.shows if s.theatre.slug == here[0])}')
    points += POINTS['learned_genre'] * max(-4, min(4, sum(p['learned_genres'][g] for g in f.genres)))
    return (points, why) if points >= MIN_SCORE else None


def for_you(films, user, ctx):
    """[(film, reasons)], best first (then soonest)."""
    p = ctx.get('taste') if ctx else profile(user)
    scored = [(f, score(f, p, ctx)) for f in films]
    return [(f, s[1]) for f, s in sorted(((f, s) for f, s in scored if s), key=lambda x: (-x[1][0], x[0].next.start_time))]



# ─── Taste match (profiles, Compare — on the site and /profile) ───────────────

MATCH_WEIGHTS = {'genre': 1, 'way': 1, 'theatre': 1, 'avoid': 0.5, 'movie': 2, **{k: 2 for k in PEOPLE}}


def match(me, other):
    """How alike two people's tastes are — only when `other` shows theirs:
    {'score': 0–100, 'shared': [labels]}, else None."""
    if not other or not other.taste_public or not me or me.id == other.id:
        return None
    def picks(u):
        return {(i.kind, i.key): i.label for i in items(u) if i.kind in MATCH_WEIGHTS}
    a, b = picks(me), picks(other)
    if not a or not b:
        return {'score': None, 'shared': []}
    weight = lambda keys: sum(MATCH_WEIGHTS[k[0]] for k in keys)
    both = a.keys() & b.keys()
    score = round(100 * weight(both) / weight(a.keys() | b.keys()))
    order = ('movie', *PEOPLE, 'genre', 'way', 'theatre', 'avoid')
    shared = [('Not into ' if k[0] == 'avoid' else '') + a[k] for k in sorted(both, key=lambda k: (order.index(k[0]), a[k]))]
    return {'score': score, 'shared': shared}

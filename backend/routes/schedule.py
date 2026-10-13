"""What's playing: theatres, showtimes, films, Discover/Browse/Calendar, search, link previews, calendar feeds.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
from app import (FRONTEND_URL, Group, GroupMembership, Movie, RARE_MIN_SCORE, RSVP, Showtime, Theatre, User,
    Watchlist, _active_membership, _ai, _ai_searches, _as_int, _brief_user, _group_showtime_query,
    _with_attendance, app, attended_showtime_ids, current_user, datetime, db, guest_blocked, interest_counts,
    jsonify, make_response, movie_for_tmdb, public_cached, public_showtimes, rarity, re, request,
    require_auth, require_group_member, secrets, time, timedelta, tmdb_matches)


# ─── Routes: Theatres ─────────────────────────────────────────────────────────

@app.route('/api/theatres')
def get_theatres():
    theatres = Theatre.query.filter(Theatre.is_active.isnot(False)).order_by(Theatre.name).all()
    return jsonify([t.to_dict() for t in theatres])


def _theatre_summary(t, now):
    """How busy a theatre is over the next month (films, showings, next one)."""
    q = Showtime.query.filter(Showtime.theatre_id == t.id, Showtime.start_time >= now,
                              Showtime.start_time <= now + timedelta(days=30), Showtime.is_cancelled.isnot(True))
    nxt = q.order_by(Showtime.start_time).first()
    return {'films': q.with_entities(db.func.count(db.distinct(Showtime.movie_id))).scalar() or 0,
            'showings': q.count(), 'next': nxt.start_time.isoformat() if nxt else None}


@app.route('/api/theatres/<slug>/notes')
@require_auth
def theatre_notes(slug):
    """What the club's members say about this theatre's screenings lately
    (screening notes, R10f) — only for members of a club that has them on."""
    import notes
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    theatre = Theatre.query.filter_by(slug=slug).first()
    if not theatre:
        return jsonify({'error': 'Theatre not found'}), 404
    return jsonify(notes.theatre(db.session.get(Group, group_id), theatre.id) or {'enabled': False})


@app.route('/api/theatres/<slug>')
def get_theatre(slug):
    """A theatre's page (R7a, public): where it is, its area, and how much is
    playing in the next month. Its films come from Browse (?theatres=<slug>)."""
    import discover
    t = Theatre.query.filter_by(slug=slug).first()
    if not t or t.is_active is False:
        return jsonify({'error': 'Theatre not found'}), 404
    return jsonify({**t.to_dict(), 'region': discover.REGIONS.get(t.slug), **_theatre_summary(t, datetime.now())})


@app.route('/api/theatres-overview')
def theatres_overview():
    """Every theatre with its area, next month's numbers, and a preview of the
    next two weeks there (posters, rare films, formats, tonight) — the Theatres page."""
    import discover

    def build():
        now = datetime.now()
        previews = discover.theatre_previews(None, now)
        empty = {'posters': [], 'rare': 0, 'formats': [], 'tonight': 0, 'film_count': 0}
        return [{**t.to_dict(), 'region': discover.REGIONS.get(t.slug), **_theatre_summary(t, now),
                 'preview': previews.get(t.slug, empty)}
                for t in Theatre.query.filter(Theatre.is_active.isnot(False)).order_by(Theatre.name)]
    return jsonify(public_cached(('theatres-overview',), build))


@app.route('/api/sitemap.xml')
def sitemap():
    """The public pages, for search engines (served at /sitemap.xml): home,
    Calendar, Theatres, each theatre, and every film playing in the next 60
    days. Private pages are never listed."""
    from xml.sax.saxutils import escape as xesc
    now = datetime.now()
    urls = [('/', 'daily'), ('/calendar', 'daily'), ('/browse', 'daily'), ('/theatres', 'weekly')]
    urls += [(f'/theatres/{t.slug}', 'daily') for t in Theatre.query.filter(Theatre.is_active.isnot(False))]
    films = (db.session.query(Showtime.movie_id).join(Theatre)
             .filter(Showtime.start_time >= now, Showtime.start_time <= now + timedelta(days=60),
                     Showtime.is_cancelled.isnot(True), Theatre.is_active.isnot(False))
             .distinct().all())
    urls += [(f'/films/{mid}', 'weekly') for (mid,) in films]
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    body += [f'<url><loc>{xesc(FRONTEND_URL + path)}</loc><changefreq>{freq}</changefreq></url>' for path, freq in urls]
    body.append('</urlset>')
    resp = make_response('\n'.join(body))
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    resp.headers['Cache-Control'] = 'public, max-age=3600'
    return resp


# ─── Routes: Showtimes ────────────────────────────────────────────────────────

@app.route('/api/showtimes')
@require_auth
def get_showtimes():
    user = current_user()
    start_str = request.args.get('start')
    end_str = request.args.get('end')
    theatre_slug = request.args.get('theatre')
    movie_id = request.args.get('movie_id')
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err

    query = Showtime.query.join(Movie).join(Theatre).filter(Showtime.is_cancelled.isnot(True))

    if start_str:
        query = query.filter(Showtime.start_time >= datetime.fromisoformat(start_str))
    if end_str:
        query = query.filter(Showtime.start_time <= datetime.fromisoformat(end_str))
    if theatre_slug:
        query = query.filter(Theatre.slug == theatre_slug)
    if movie_id:
        query = query.filter(Showtime.movie_id == int(movie_id))

    showtimes = query.order_by(Showtime.start_time).all()
    return jsonify(_with_attendance(user, showtimes, [
        s.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)
        for s in showtimes
    ], group_id))


@app.route('/api/showtimes/<int:showtime_id>')
def get_showtime(showtime_id):
    """Single showtime — the screening sheet and ?showtime= deep links.
    Club mode with ?group_id, public mode without."""
    user, group, err = view_scope()
    if err:
        return err
    group_id = group.id if group else None
    showtime = db.session.get(Showtime, showtime_id)
    if not showtime or showtime.is_cancelled:
        return jsonify({'error': 'Showtime not found'}), 404
    if not group:
        return jsonify(public_showtimes([showtime], user)[0])
    return jsonify(_with_attendance(user, [showtime], [
        showtime.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)], group_id)[0])


@app.route('/api/films/<int:movie_id>')
def film_detail(movie_id):
    """A film's page: its details, every upcoming screening at the group's
    theatres (with the viewer's RSVPs and who's going), where the club stands
    on it (want to see / going / seen), and whether this week's screenings
    are rare. Public mode (no ?group_id): every tracked theatre, anonymous
    interest only, no club section."""
    import discover
    user, group, err = view_scope()
    if err:
        return err
    group_id = group.id if group else None
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return jsonify({'error': 'Film not found'}), 404
    now = datetime.now()

    base = _group_showtime_query(group).filter(Showtime.movie_id == movie_id)
    upcoming = base.filter(Showtime.start_time >= now).order_by(Showtime.start_time).all()
    if group:
        showtimes = _with_attendance(user, upcoming, [
            s.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres) for s in upcoming
        ], group_id)
    else:
        showtimes = public_showtimes(upcoming, user)
    for d in showtimes:
        d.pop('movie', None)          # the page has it once, at the top

    members = {m.user_id: m.user for m in GroupMembership.query.filter_by(group_id=group_id, status='active') if m.user}
    watchers = {w.user_id for w in Watchlist.query.filter_by(movie_id=movie_id)}
    going = {r.user_id for s in upcoming for r in s.rsvps if r.group_id == group_id and r.status == 'going'}
    past = {s.id for s in base.filter(Showtime.start_time < now)}
    seen = {uid for uid in members if past and past & attended_showtime_ids(uid, {group_id})}

    rare = None
    week = [s for s in upcoming if s.start_time <= now + timedelta(days=7)]
    if week:
        venues = len({s.theatre_id for s in week})
        score, why = max((rarity(s, len(week), venues, now.year) for s in week), key=lambda x: x[0])
        if score >= RARE_MIN_SCORE:
            rare = {'score': score, 'reasons': why}

    if not group:
        want, _ = interest_counts([movie_id])
        return jsonify({
            'movie': movie.to_dict(), 'showtimes': showtimes, 'club': None, 'rare': rare,
            'announced': discover.announced(movie_id=movie_id),
            'interest': {'want': want.get(movie_id)},
            'viewer_wants': bool(user and Watchlist.query.filter_by(user_id=user.id, movie_id=movie_id).first()),
        })

    def people(ids):
        return [_brief_user(members[i]) for i in ids if i in members]

    return jsonify({
        'movie': movie.to_dict(),
        'showtimes': showtimes,
        'club': {'wanters': people(watchers), 'going': people(going), 'seen': people(seen)},
        'viewer_wants': user.id in watchers,
        'rare': rare,
        'announced': discover.announced(movie_id=movie_id),
    })


def view_scope():
    """(viewer or None, group or None, error). No group_id → public mode."""
    user = current_user()
    group_id = request.args.get('group_id', type=int)
    if not group_id:
        return user, None, None
    if not user:
        return None, None, (jsonify({'error': 'Not authenticated'}), 401)
    if not _active_membership(user, group_id):
        return user, None, (jsonify({'error': 'Not a member of this group'}), 403)
    return user, db.session.get(Group, group_id), None


def _cards_in(obj):
    """Every Discover card (a dict with 'movie' and 'club') inside a response."""
    if isinstance(obj, dict):
        if 'movie' in obj and 'club' in obj:
            yield obj
        for v in obj.values():
            yield from _cards_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _cards_in(v)


def publicize_cards(payload):
    """Discover cards in public mode: drop the club block, add anonymous interest."""
    cards = list(_cards_in(payload))
    want, going = interest_counts({c['movie']['id'] for c in cards}, {c['next']['showtime_id'] for c in cards if c.get('next')})
    for c in cards:
        c.pop('club', None)
        c['interest'] = {'want': want.get(c['movie']['id']),
                         'going': going.get(c['next']['showtime_id']) if c.get('next') else None}
    return payload


def _discover_group():
    """(viewer, group or None, error): club mode with ?group_id, public otherwise."""
    return view_scope()


@app.route('/api/discover')
def discover_page():
    """Club mode with ?group_id; public mode (cached for visitors) without."""
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    # ?theatres=<slug>: the same page for one theatre (its own page, R7b).
    asked = [x for x in (request.args.get('theatres') or '').split(',') if x]
    theatres = {t.slug for t in Theatre.query.filter(Theatre.slug.in_(asked))} if asked else None
    if asked and not theatres:
        return jsonify({'error': 'Theatre not found'}), 404
    if group:
        return jsonify(discover.discover(group, user, theatres=theatres))
    build = lambda: publicize_cards(discover.discover(None, user, theatres=theatres))
    return jsonify(build() if user else public_cached(('discover', tuple(sorted(theatres or ()))), build))


@app.route('/api/discover/browse')
def discover_browse():
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    params = {k: request.args.get(k) for k in BROWSE_PARAMS}
    offset = max(0, request.args.get('offset', 0, type=int))
    if not group and params.get('club') not in (None, 'mine'):   # public mode: only your own plans
        params['club'] = None
    try:
        if group:
            return jsonify(discover.browse(group, user, params, offset=offset))
        build = lambda: publicize_cards(discover.browse(None, user, params, offset=offset))
        key = ('browse', offset, tuple(sorted((k, v) for k, v in params.items() if v)))
        return jsonify(build() if user else public_cached(key, build))
    except ValueError:
        return jsonify({'error': 'Bad date'}), 400


BROWSE_PARAMS = ('when', 'from', 'to', 'theatres', 'regions', 'genres', 'decade', 'format', 'time', 'rarity',
                 'club', 'runtime', 'mood', 'shelf', 'q', 'person', 'sort')


def _discover_more(name, build):
    """Discover's See-all pages (R7b): ?theatres= and/or ?regions= narrow
    them; club mode with ?group_id, public (cached for visitors) without."""
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    slugs = {x for x in (request.args.get('theatres') or '').split(',') if x}
    regions = {x.lower() for x in (request.args.get('regions') or '').split(',') if x}
    slugs |= {s for s, r in discover.REGIONS.items() if r.lower() in regions}
    theatres = slugs or None
    if group:
        return jsonify(build(group, user, theatres))
    run = lambda: publicize_cards(build(None, user, theatres))
    return jsonify(run() if user else public_cached((name, tuple(sorted(slugs))), run))


@app.route('/api/discover/spotlights')
def discover_spotlights():
    import discover
    return _discover_more('spotlights', lambda g, u, th: {
        'spotlights': discover.spotlights(g, u, theatres=th, limit=None, films_each=8)})


@app.route('/api/discover/doubles')
def discover_doubles():
    import discover
    return _discover_more('doubles', lambda g, u, th: discover.every_double(g, u, theatres=th))


@app.route('/api/films/tmdb-search')
@require_auth
def films_tmdb_search():
    q = (request.args.get('q') or '').strip()[:80]
    if len(q) < 3:
        return jsonify({'results': []})
    results = tmdb_matches(q, current_user().id)
    if results is None:
        return jsonify({'error': 'Lots of searching — try again in a while.', 'results': []}), 429
    return jsonify({'results': results})


@app.route('/api/films/from-tmdb', methods=['POST'])
@require_auth
def films_from_tmdb():
    """Open a TMDB film: {tmdb_id} → {movie_id} (added to the catalog if new)."""
    tmdb_id = _as_int((request.json or {}).get('tmdb_id'))
    movie = movie_for_tmdb(tmdb_id) if tmdb_id else None
    if not movie:
        return jsonify({'error': "Couldn't find that film."}), 404
    return jsonify({'movie_id': movie.id})


AI_SEARCHES_PER_HOUR = 15


@app.route('/api/search/suggest')
def search_suggest():
    import discover
    user, group, err = view_scope()
    if err:
        return err
    q = (request.args.get('q') or '').strip()[:80]
    build = lambda: discover.suggest(group, user, q)
    if group or user:
        return jsonify(build())
    return jsonify(public_cached(('suggest', discover.normalize(q)), build))


@app.route('/api/search/ai', methods=['POST'])
@require_auth
def search_ai_route():
    """{q, group_id?} → {params, path, explain, ai, note}: Browse filters for a
    plain-English request."""
    import discover
    import search_ai
    user = current_user()
    blocked = guest_blocked(user)
    if blocked:
        return blocked
    data = request.json or {}
    q = re.sub(r'\s+', ' ', str(data.get('q') or '')).strip()[:300]
    if len(q) < 3:
        return jsonify({'error': 'Say a bit more about what you want to see.'}), 400
    group = None
    group_id = _as_int(data.get('group_id'))
    if group_id:
        if not _active_membership(user, group_id):
            return jsonify({'error': 'Not a member of this group'}), 403
        group = db.session.get(Group, group_id)
    now = time.monotonic()
    recent = [t for t in _ai_searches.get(user.id, []) if now - t < 3600]
    if len(recent) >= AI_SEARCHES_PER_HOUR:
        return jsonify({'error': "That's a lot of AI searches — try the regular search, or again in a while."}), 429
    _ai()                                     # the shared AI, with its model-switch notices
    result = search_ai.interpret(group, user, q)
    if result['ai']:
        _ai_searches[user.id] = recent + [now]
    params = result['params']
    names = {t.slug: t.short_name or t.name for t in Theatre.query.filter(Theatre.slug.in_(
        (params.get('theatres') or '').split(',')))} if params.get('theatres') else {}
    label = ', '.join(names.get(s, s) for s in (params.get('theatres') or '').split(',') if s) or None
    return jsonify({**result, 'path': discover.browse_path(params),
                    'explain': discover.describe({**params, '_theatre_label': label})})


CALENDAR_PAST_DAYS = 60          # the Calendar can look back this far


@app.route('/api/discover/calendar')
def discover_calendar():
    """The Calendar's screenings: every showing of the films matching Browse's
    filters (same parameters, from/to = the days shown), each marked rare as
    Discover would, plus facet counts for the Filters sheet."""
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    params = {k: request.args.get(k) for k in BROWSE_PARAMS}
    if not group and params.get('club') not in (None, 'mine'):   # public mode: only your own plans
        params['club'] = None

    def build():
        films, ctx, reasons, start, end = discover.select(group, user, params, past_days=CALENDAR_PAST_DAYS)
        rare = {f.movie.id: f.rare_reasons for f in films if f.rare_score >= ctx['rare_min']}
        shows = sorted((s for f in films for s in f.shows), key=lambda s: s.start_time)
        if group:
            dicts = _with_attendance(user, shows, [
                s.to_dict(user_id=user.id, group_id=group.id, user_genres=user.favorite_genres) for s in shows], group.id)
        else:
            dicts = public_showtimes(shows, user)
        # Each film and theatre once (a busy week repeated them per screening:
        # megabytes); the Calendar puts them back together.
        movies, theatres = {}, {}
        for s, d in zip(shows, dicts):
            d['rare'] = rare.get(s.movie_id)
            d['shelf_reasons'] = reasons.get(s.movie_id)
            movies.setdefault(s.movie_id, d.pop('movie'))
            theatres.setdefault(s.theatre_id, d.pop('theatre'))
            d['movie_id'], d['theatre_id'] = s.movie_id, s.theatre_id
        return {'showtimes': dicts, 'movies': movies, 'theatres': theatres, 'total': len(films), 'facets': discover.facets(films),
                'regions': discover.REGIONS,
                'title': discover.SHELF_TITLES.get(params.get('shelf'))
                or discover.MOODS.get(params.get('mood') or '', {}).get('label')}
    try:
        if group or user:
            return jsonify(build())
        return jsonify(public_cached(('calendar', tuple(sorted((k, v) for k, v in params.items() if v))), build))
    except ValueError:
        return jsonify({'error': 'Bad date'}), 400


@app.route('/api/discover/surprise')
def discover_surprise():
    import discover
    user, group, err = _discover_group()
    if err:
        return err
    exclude = [_as_int(x) for x in (request.args.get('exclude') or '').split(',') if _as_int(x)]
    pick = discover.surprise(group, user, request.args.get('when', 'tonight'), exclude)
    if pick and not group:
        pick = publicize_cards(pick)
    return jsonify(pick or {'error': 'nothing_playing'}), (200 if pick else 404)


# ─── Link previews (Open Graph) ───────────────────────────────────────────────
# Discord (and other chat apps) fetch a link to show a preview card, but the
# site is a single-page app with one generic <head>. nginx sends those
# crawlers here instead (see frontend/nginx.conf); people never see these
# pages. Only public schedule information is used — never who's going.

def _og_page(title, description, image, path, large=False):
    import html as _html
    esc = _html.escape
    url = f"{FRONTEND_URL}{path}"
    image_tags = (f'<meta property="og:image" content="{esc(image)}">\n'
                  f'<meta name="twitter:image" content="{esc(image)}">') if image else ''
    body = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{esc(title if title == 'Cinema Club DC' else f'{title} · Cinema Club DC')}</title>
<meta property="og:site_name" content="Cinema Club DC">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(url)}">
{image_tags}
<meta name="twitter:card" content="{'summary_large_image' if large else 'summary'}">
<meta name="theme-color" content="#dcb15c">
<meta http-equiv="refresh" content="0; url={esc(url)}">
</head><body><a href="{esc(url)}">{esc(title)}</a></body></html>"""
    resp = make_response(body)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    resp.headers['Cache-Control'] = 'public, max-age=900'
    return resp


def _when_text(dt):
    return dt.strftime('%a %b %-d · %-I:%M %p')


def _blurb(text, limit=180):
    text = (text or '').strip()
    return text if len(text) <= limit else text[:limit - 1].rsplit(' ', 1)[0] + '…'


@app.route('/api/og/films/<int:movie_id>')
def og_film(movie_id):
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return _og_page('Cinema Club DC', "DC's repertory and new-release screenings, together.", None, '/')
    now = datetime.now()
    upcoming = (Showtime.query.join(Theatre).filter(
        Showtime.movie_id == movie_id, Showtime.start_time >= now,
        Showtime.is_cancelled.isnot(True), Theatre.is_active.isnot(False))
        .order_by(Showtime.start_time).all())
    year = f" ({movie.release_year[:4]})" if movie.release_year else ''
    bits = []
    if upcoming:
        s = upcoming[0]
        fmt = f" · {s.format_label}" if s.format_label else ''
        bits.append(f"Next: {_when_text(s.start_time)} @ {s.theatre.short_name or s.theatre.name}{fmt}")
        theatres = len({x.theatre_id for x in upcoming})
        bits.append(f"{len(upcoming)} showing{'s' if len(upcoming) != 1 else ''}"
                    + (f" at {theatres} theatres" if theatres > 1 else ''))
    else:
        bits.append('No upcoming showings')
    if movie.director:
        bits.append(f"Dir. {movie.director}")
    description = ' · '.join(bits) + (f"\n{_blurb(movie.description)}" if movie.description else '')
    return _og_page(f"{movie.title}{year}", description, movie.backdrop_url or movie.poster_url,
                    f"/films/{movie_id}", large=bool(movie.backdrop_url))


@app.route('/api/og/theatres/<slug>')
def og_theatre(slug):
    t = Theatre.query.filter_by(slug=slug).first()
    if not t or t.is_active is False:
        return _og_page('Cinema Club DC', "DC's repertory and new-release screenings, together.", None, '/')
    n = _theatre_summary(t, datetime.now())
    bits = [t.address or '', f"{n['films']} film{'s' if n['films'] != 1 else ''} in the next month" if n['films'] else '']
    return _og_page(t.name, ' · '.join(b for b in bits if b), None, f'/theatres/{slug}')


@app.route('/api/og/showtimes/<int:showtime_id>')
def og_showtime(showtime_id):
    s = db.session.get(Showtime, showtime_id)
    if not s or not s.movie:
        return _og_page('Cinema Club DC', "DC's repertory and new-release screenings, together.", None, '/')
    bits = [s.theatre.name]
    if s.format_label:
        bits.append(s.format_label)
    if s.event_label and s.event_label != s.movie.title:
        bits.append(s.event_label)
    if s.is_cancelled:
        bits.append('cancelled')
    elif s.is_sold_out:
        bits.append('sold out')
    description = ' · '.join(bits) + (f"\n{_blurb(s.movie.description)}" if s.movie.description else '')
    return _og_page(f"{s.movie.title} — {_when_text(s.start_time)}", description,
                    s.movie.backdrop_url or s.movie.poster_url, f"/calendar?showtime={showtime_id}",
                    large=bool(s.movie.backdrop_url))


# ─── Routes: Calendar Export ──────────────────────────────────────────────────

@app.route('/api/showtimes/<int:sid>/ical')
def showtime_ical(sid):
    import ics
    showtime = db.session.get(Showtime, sid)
    if not showtime:
        return jsonify({'error': 'Showtime not found'}), 404
    body = ics.calendar([_screening_event(showtime, f'showtime-{sid}@cinemaclubdc')])
    response = make_response(body)
    response.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    safe = re.sub(r'[^\w\- ]+', '', showtime.movie.title).strip() or 'screening'
    response.headers['Content-Disposition'] = f'attachment; filename="{safe}.ics"'
    return response


def _screening_event(s, uid, summary=None, extra=(), updated=None):
    """A screening as a calendar event: film, theatre and address, format,
    the venue's billing, tickets, and a link back to it on the site."""
    import ics
    movie, theatre = s.movie, s.theatre
    start, end = ics.screening_times(s)
    lines = [x for x in (s.event_label, s.format_label,
                         ' · '.join(b for b in (f"Dir. {movie.director}" if movie.director else '',
                                                f"{movie.runtime_minutes} min" if movie.runtime_minutes else '') if b),
                         *extra,
                         f"Tickets: {s.purchase_link}" if s.purchase_link else '',
                         f"{FRONTEND_URL}/calendar?showtime={s.id}") if x]
    return ics.event(uid, start, end, summary or movie.title,
                     location=f"{theatre.name}, {theatre.address}" if theatre.address else theatre.name,
                     description='\n'.join(lines), url=f"{FRONTEND_URL}/calendar?showtime={s.id}",
                     cancelled=bool(s.is_cancelled), updated=updated,
                     sequence=int(updated.timestamp()) // 60 % 100000 if updated else 0)


# ─── Calendar subscriptions (R7a) ─────────────────────────────────────────────
# A link a calendar app subscribes to and re-checks: your Going and Maybe plans,
# or (per member) a club's plans. Calendar apps can't sign in, so each link
# carries a long random code; resetting it turns the old link off. Leaving a
# club ends its link (the code lives on the membership).

FEED_PAST = timedelta(days=30)          # recent screenings stay on the calendar a while


def _calendar_url(token, club=False):
    return f"{FRONTEND_URL}/api/calendar/{'club/' if club else ''}{token}.ics"


def _feed_response(body):
    resp = make_response(body)
    resp.headers['Content-Type'] = 'text/calendar; charset=utf-8'
    resp.headers['Cache-Control'] = 'private, no-cache'
    return resp


@app.route('/api/me/calendar')
@require_auth
def my_calendar_links():
    """Your subscription links (made on first ask): {personal, clubs: [{group_id, name, url}]}."""
    user = current_user()
    blocked = guest_blocked(user)
    if blocked:
        return blocked
    if not user.calendar_token:
        user.calendar_token = secrets.token_urlsafe(32)
    clubs = []
    for m in GroupMembership.query.filter_by(user_id=user.id, status='active').all():
        if not m.calendar_token:
            m.calendar_token = secrets.token_urlsafe(32)
        clubs.append({'group_id': m.group_id, 'name': m.group.name, 'url': _calendar_url(m.calendar_token, club=True)})
    db.session.commit()
    return jsonify({'personal': _calendar_url(user.calendar_token), 'clubs': clubs})


@app.route('/api/me/calendar/reset', methods=['POST'])
@require_auth
def reset_calendar_link():
    """A new link (the old one stops working): {group_id} for a club's, else yours."""
    user = current_user()
    group_id = _as_int((request.json or {}).get('group_id'))
    if group_id:
        m = _active_membership(user, group_id)
        if not m:
            return jsonify({'error': 'Not a member of this group'}), 403
        m.calendar_token = secrets.token_urlsafe(32)
    else:
        user.calendar_token = secrets.token_urlsafe(32)
    db.session.commit()
    return my_calendar_links()


@app.route('/api/calendar/<token>.ics')
def personal_feed(token):
    """Your Going and Maybe screenings (every club, and your own plans)."""
    import ics
    user = User.query.filter_by(calendar_token=token).first() if len(token) >= 30 else None
    if not user or not user.is_active or user.is_guest:
        return jsonify({'error': 'Not found'}), 404
    since = datetime.now() - FEED_PAST
    best = {}                     # showtime id -> (rsvp) — going beats maybe across clubs
    for r in (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
              .filter(RSVP.user_id == user.id, RSVP.status.in_(('going', 'maybe')), Showtime.start_time >= since)):
        cur = best.get(r.showtime_id)
        if not cur or (cur.status == 'maybe' and r.status == 'going'):
            best[r.showtime_id] = r
    events = []
    for r in sorted(best.values(), key=lambda r: r.showtime.start_time):
        s = r.showtime
        title = s.movie.title + (' (maybe)' if r.status == 'maybe' else '')
        events.append(_screening_event(s, f'plan-{user.id}-{s.id}@cinemaclubdc', summary=title,
                                       updated=r.updated_at or r.created_at))
    return _feed_response(ics.calendar(events, name='Cinema Club: my plans', refresh_hours=1))


@app.route('/api/calendar/club/<token>.ics')
def club_feed(token):
    """A club's plans: every screening its members are going (or maybe going) to."""
    import ics
    m = GroupMembership.query.filter_by(calendar_token=token).first() if len(token) >= 30 else None
    if not m or m.status != 'active' or not m.user or not m.user.is_active:
        return jsonify({'error': 'Not found'}), 404
    since = datetime.now() - FEED_PAST
    by_show = {}
    for r in (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
              .filter(RSVP.group_id == m.group_id, RSVP.status.in_(('going', 'maybe')), Showtime.start_time >= since)
              .order_by(RSVP.created_at)):
        by_show.setdefault(r.showtime_id, []).append(r)
    events = []
    for sid, rsvps in sorted(by_show.items(), key=lambda kv: kv[1][0].showtime.start_time):
        s = rsvps[0].showtime
        going = [r.user.name for r in rsvps if r.status == 'going' and r.user]
        maybe = [r.user.name for r in rsvps if r.status == 'maybe' and r.user]
        n = len(going)
        summary = f"{s.movie.title} · {n} going" if n else f"{s.movie.title} · maybe"
        who = [f"Going: {', '.join(going)}" if going else '', f"Maybe: {', '.join(maybe)}" if maybe else '']
        updated = max((r.updated_at or r.created_at) for r in rsvps)
        events.append(_screening_event(s, f'club-{m.group_id}-{sid}@cinemaclubdc', summary=summary,
                                       extra=[w for w in who if w], updated=updated))
    return _feed_response(ics.calendar(events, name=f"Cinema Club: {m.group.name}", refresh_hours=1))


@app.route('/api/showtimes/<int:sid>/gcal-url')
def showtime_gcal_url(sid):
    showtime = db.session.get(Showtime, sid)
    if not showtime:
        return jsonify({'error': 'Showtime not found'}), 404

    movie = showtime.movie
    theatre = showtime.theatre
    start = showtime.start_time
    end = showtime.end_time or (start + timedelta(minutes=(movie.runtime_minutes or 120) + 20))

    def fmt_gcal(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    details = []
    if movie.director:
        details.append(f"Dir. {movie.director}")
    if showtime.purchase_link:
        details.append(f"Tickets: {showtime.purchase_link}")

    from urllib.parse import quote
    url = (
        f"https://calendar.google.com/calendar/render?action=TEMPLATE"
        f"&text={quote(movie.title)}"
        f"&dates={fmt_gcal(start)}/{fmt_gcal(end)}"
        f"&location={quote(theatre.name + ', ' + (theatre.address or ''))}"
        f"&details={quote(' | '.join(details))}"
    )

    return jsonify({'url': url})

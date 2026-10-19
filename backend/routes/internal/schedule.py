"""What's playing, for the bot: showtimes, Discover, theatres, films, RSVPs,
watchlists, saved searches, account linking and the weekly digest.
"""
import app as core
import html as _html
import cities
import places
import taste
from app import (DIGEST_CAPS, FRONTEND_URL, Message, Movie, PLAN_MIN_WATCHERS, Poll, Showtime, ShowtimeThread,
    Theatre, User, Watchlist, _as_int, _group_showtime_query, _utcnow_naive, app, apply_rsvp,
    attended_showtime_ids, datetime, db, jsonify, merge_users, movie_for_tmdb, on_discord, poll_scores,
    present_user_ids, public_showtimes, request, require_role, share_prefs, split_present, timedelta,
    tmdb_matches, watch_shared)
from routes.internal.common import _discord_member, request_group, request_scope, require_internal, resolve_discord_user


@app.route('/api/internal/films/find')
@require_internal
def internal_films_find():
    """/watch's film picker: films we list (playing first), then TMDB's —
    [{name, value}] with value 'movie:<id>' or 'tmdb:<id>'."""
    import discover
    q = (request.args.get('q') or '').strip()[:80]
    if len(q) < 2:
        return jsonify([])
    ours = discover.suggest(None, None, q)['films']
    year = lambda x: f" ({x['year']})" if x.get('year') else ''
    out = [{'name': f"{x['title']}{year(x)}{' — playing' if x.get('playing') else ''}", 'value': f"movie:{x['id']}"}
           for x in ours]
    if len(q) >= 3:
        listed = {x['id'] for x in ours}
        for r in tmdb_matches(q, 'bot') or []:
            if r['movie_id'] in listed:
                continue
            out.append({'name': f"{r['title']}{year(r)}", 'value': f"movie:{r['movie_id']}" if r['movie_id'] else f"tmdb:{r['tmdb_id']}"})
    return jsonify([{**o, 'name': o['name'][:100]} for o in out[:25]])


@app.route('/api/internal/showtimes')
@require_internal
def internal_showtimes():
    group_id = request.args.get('group_id', type=int)
    group = request_scope()
    q = _group_showtime_query(group)

    start_str = request.args.get('start')
    end_str = request.args.get('end')
    search = (request.args.get('q') or '').strip()
    if start_str:
        q = q.filter(Showtime.start_time >= datetime.fromisoformat(start_str))
    if end_str:
        q = q.filter(Showtime.start_time <= datetime.fromisoformat(end_str))
    if search:
        q = q.filter(Movie.title.ilike(f'%{search}%'))
    movie_id = request.args.get('movie_id', type=int)
    if movie_id:
        q = q.filter(Showtime.movie_id == movie_id)
    tickets = request.args.get('tickets')                # the Calendar's ticket chips (discover.TICKETS)
    if tickets == 'available':
        q = q.filter(Showtime.is_sold_out.isnot(True))
    elif tickets == 'soldout':
        q = q.filter(Showtime.is_sold_out.is_(True))

    limit = min(request.args.get('limit', 200, type=int), 500)
    showtimes = q.order_by(Showtime.start_time).limit(limit).all()
    return jsonify([for_discord(s.to_dict(group_id=group_id), group_id or request_group()) for s in showtimes])


def for_discord(d, group_id):
    """A showtime dict as that club's server may show it: attendees / maybes
    name only members in its server (attendees_more / maybes_more count the
    rest), and reactions are counts only."""
    shown = present_user_ids(group_id)
    for key in ('attendees', 'maybes'):
        people = d.get(key) or []
        d[key] = [p for p in people if p['id'] in shown]
        d[f'{key}_more'] = len(people) - len(d[key])
    for r in (d.get('reactions') or {}).values():
        r['users'] = [u for u in r.get('users', []) if u['id'] in shown]
    return d


# ─── Discover in Discord (R3b) ───────────────────────────────────────────────
# /find and /surprise. Anyone can use them; an existing account (never created
# here) personalizes "For you", "Your list" and the you-are-going marks.

def _internal_discover_args():
    discord_id = str(request.args.get('discord_user_id') or '').strip()
    viewer = User.query.filter_by(discord_user_id=discord_id, is_active=True).first() if discord_id.isdigit() else None
    return viewer, request_scope()


@app.route('/api/internal/discover/options')
@require_internal
def internal_discover_options():
    import discover
    _, group = _internal_discover_args()
    return jsonify({'types': discover.find_types(group),
                    'regions': [{'value': f'region:{k}', 'label': v}
                                for k, v in cities.area_keys(places.club_city(group)).items()]})


@app.route('/api/internal/discover/find')
@require_internal
def internal_discover_find():
    import discover
    viewer, group = _internal_discover_args()
    if not group:
        return jsonify({'error': 'group not found'}), 404
    a = request.args
    params = discover.find_params(a.get('type'), a.get('where'), a.get('when'), a.get('q'))
    limit = max(1, min(a.get('limit', 8, type=int), 25))
    result = discover.browse(group, viewer, params, limit=limit)
    names = {t.slug: t.short_name or t.name for t in Theatre.query.filter(
        Theatre.slug.in_([x for x in params.get('theatres', '').split(',') if x]))}
    if params.get('theatres'):
        params['_theatre_label'] = ', '.join(names.get(x, x) for x in params['theatres'].split(','))
    result.pop('facets', None)
    result.pop('regions', None)
    return jsonify({**result, 'params': {k: v for k, v in params.items() if not k.startswith('_')},
                    'label': discover.describe(params, result.get('title')),
                    'browse_path': discover.browse_path(params)})


@app.route('/api/internal/foryou')
@require_internal
def internal_foryou():
    """/foryou: the caller's For you picks (R13) in the club, with reasons."""
    import discover
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    group = request_scope()
    params = {'shelf': 'for-you', 'when': '2weeks'}
    result = discover.browse(group, user, params, limit=max(1, min(request.args.get('limit', 6, type=int), 10)))
    return jsonify({'films': result['films'], 'total': result['total'], 'taste_set': taste.is_set(user),
                    'browse_path': discover.browse_path(params)})


@app.route('/api/internal/discover/surprise')
@require_internal
def internal_discover_surprise():
    import discover
    viewer, group = _internal_discover_args()
    a = request.args
    params = discover.find_params(where=a.get('where'))
    theatres = {x for x in params.get('theatres', '').split(',') if x} | \
        places.area_slugs(params.get('regions', '').split(','))
    exclude = [_as_int(x) for x in (a.get('exclude') or '').split(',') if _as_int(x)]
    when = a.get('when') if a.get('when') in discover.WHEN else 'tonight'
    pick = discover.surprise(group, viewer, when, exclude, theatres=theatres or None)
    return jsonify(pick or {'error': 'nothing_playing'}), (200 if pick else 404)


@app.route('/api/internal/theatres')
@require_internal
def internal_theatres():
    """Active theatres for the bot's theatre autocomplete: the club's (or, no
    club, the city's) first, then every other active theatre — each says its
    city, so the bot can label other cities' when there's more than one."""
    group = request_scope()
    mine = places.club_slugs(group)
    theatres = places.theatres_in()
    ordered = [t for t in theatres if t.slug in mine] + [t for t in theatres if t.slug not in mine]
    return jsonify({'theatres': [{**t.to_dict(), 'yours': t.slug in mine} for t in ordered],
                    'multi': places.multi_city(), 'city': places.club_city(group)})


@app.route('/api/internal/announced')
@require_internal
def internal_announced():
    """/showtimes tickets:Coming soon — films announced with a date whose
    tickets aren't on sale yet, in a window (start/end, YYYY-MM-DD), at the
    club's theatres or one (`theatre`, a slug)."""
    import discover
    group = request_scope()
    a = request.args
    params = {'tickets': 'soon', 'theatres': a.get('theatre'), 'from': a.get('start'), 'to': a.get('end')}
    return jsonify(discover.announced_matching(group, params))


@app.route('/api/internal/theatre')
@require_internal
def internal_theatre():
    """/theatre: a theatre's card — where it is, what's on this week, the
    caller's For you picks there (if they've set a taste) and what members
    noted about its screenings lately (when the club has notes on)."""
    import discover
    import notes
    t = Theatre.query.filter_by(slug=request.args.get('slug') or '').first()
    if not t or t.is_active is False:
        return jsonify({'error': 'Theatre not found'}), 404
    viewer, group = _internal_discover_args()
    week = discover.browse(group, viewer, {'theatres': t.slug, 'when': 'week', 'sort': 'soonest'}, limit=8)
    mine = (discover.browse(group, viewer, {'theatres': t.slug, 'when': '2weeks', 'shelf': 'for-you'}, limit=3)['films']
            if viewer and taste.is_set(viewer) else [])
    now = places.now_at(t)
    month = Showtime.query.filter(Showtime.theatre_id == t.id, Showtime.start_time >= now,
                                  Showtime.start_time <= now + timedelta(days=30),
                                  Showtime.is_cancelled.isnot(True))
    return jsonify({**t.to_dict(),
                    'films_month': month.with_entities(db.func.count(db.distinct(Showtime.movie_id))).scalar() or 0,
                    'week': week['films'], 'week_total': week['total'], 'announced': week.get('announced') or [],
                    'for_you': mine, 'notes': notes.theatre(group, t.id),
                    'week_path': discover.browse_path({'theatres': t.slug, 'when': 'week'})})


@app.route('/api/internal/showtime-facets')
@require_internal
def internal_showtime_facets():
    """Distinct dates + theatres available for the current filter selection,
    powering dependent autocompletes (pick a movie -> only its dates/theatres).
    Computed with DISTINCT so it's complete and cheap regardless of volume.
    Optional filters: q (movie title), theatre (slug), start/end (ISO)."""
    group = request_scope()
    now = places.club_now(group)
    q = _group_showtime_query(group)

    start = request.args.get('start')
    end = request.args.get('end')
    q = q.filter(Showtime.start_time >= (datetime.fromisoformat(start) if start else now))
    q = q.filter(Showtime.start_time <= (datetime.fromisoformat(end) if end
                                         else now + timedelta(days=60)))
    title = (request.args.get('q') or '').strip()
    if title:
        q = q.filter(Movie.title.ilike(f'%{title}%'))
    theatre = (request.args.get('theatre') or '').strip()
    if theatre:
        q = q.filter(Theatre.slug == theatre)

    date_rows = q.with_entities(db.func.date(Showtime.start_time)).distinct().all()
    dates = sorted({r[0] for r in date_rows if r[0]})

    th_rows = q.with_entities(Theatre.slug, Theatre.short_name, Theatre.name).distinct().all()
    theatres, seen = [], set()
    for slug, short, name in th_rows:
        if slug in seen:
            continue
        seen.add(slug)
        theatres.append({'slug': slug, 'name': name, 'short_name': short or name})
    theatres.sort(key=lambda t: (t['name'] or '').lower())

    return jsonify({'dates': dates, 'theatres': theatres})


DIGEST_RETAG_AFTER = timedelta(days=14)  # tag someone about a watchlisted film at most fortnightly


def digest_recap(group, members, now):
    """Last week in a line or two: check-ins, the most-discussed screening,
    and any poll that was scored."""
    week_ago = now - timedelta(days=7)
    recent = {s.id: s for s in _group_showtime_query(group)
              .filter(Showtime.start_time >= week_ago, Showtime.start_time < now)}
    per_film, checkins = {}, 0
    for uid in members or []:
        for sid in attended_showtime_ids(uid, {group.id}) & recent.keys():
            checkins += 1
            title = recent[sid].movie.title
            per_film[title] = per_film.get(title, 0) + 1
    top = max(per_film.items(), key=lambda kv: kv[1]) if per_film else None
    talk = (db.session.query(Message.showtime_id, db.func.count(Message.id))
            .filter(Message.group_id == group.id, Message.created_at >= _utcnow_naive() - timedelta(days=7))
            .group_by(Message.showtime_id).order_by(db.func.count(Message.id).desc()).first())
    discussed = None
    if talk and talk[1] >= 3:
        st = db.session.get(Showtime, talk[0])
        thread = ShowtimeThread.query.filter_by(showtime_id=talk[0], group_id=group.id).first()
        discussed = {'title': st.movie.title, 'comments': talk[1], 'url': thread.url if thread else None}
    poll = (Poll.query.filter(Poll.group_id == group.id, Poll.status == 'scored',
                              Poll.scored_at >= _utcnow_naive() - timedelta(days=7))
            .order_by(Poll.scored_at.desc()).first())
    board = poll_scores(poll) if poll else []
    return {'checkins': checkins, 'films': len(per_film),
            'top_film': {'title': top[0], 'count': top[1]} if top and top[1] > 1 else None,
            'discussed': discussed,
            'poll': {'title': poll.title, 'kernels': board[0]['kernels'],
                     'winner': board[0]['user'].name if on_discord(board[0]['user'], group.id) else None}
            if board else None}


@app.route('/api/internal/digest')
@require_internal
def internal_digest():
    """The weekly digest's sections, computed here so the bot gets a small,
    already-trimmed payload. Each film appears in at most one of plans / rare /
    last_chance / opening (in that priority):
      whos_going      — screenings in the window with group RSVPs
      plans           — films PLAN_MIN_WATCHERS+ members want, nobody's going to yet
      rare            — top screenings by rarity() score (>= RARE_MIN_SCORE), with reasons
      last_chance     — a film's final showing, when its theatre's schedule clearly runs on
      opening         — recent releases appearing on the club's theatres for the first time
      watchlist       — watchlisted films playing, with their watchers (`fresh`: taggable)
      open_polls, recap (last week), new_on_calendar (schedule-drop counts per theatre)."""
    import digest
    import discover
    days = request.args.get('days', 7, type=int)
    group = request_scope()
    now = places.club_now(group)
    digest.publish_due()                 # the site's copy (Feed, bell) goes out with the bot's
    _showtime_brief = digest.showtime_brief

    # The films come from the Discover engine (R9a): the same rules as its shelves.
    films, picks = discover.weekly(group, now, days, DIGEST_CAPS, PLAN_MIN_WATCHERS)
    by_movie = {mid: f.shows for mid, f in films.items()}
    showtimes = sorted((s for f in films.values() for s in f.shows), key=lambda s: s.start_time)
    members = ({m.user_id for m in group.memberships if m.status == 'active'} if group else None)

    # Names are only members in the club's server (and, for watchlists, only
    # if they let the digest mention them); everyone else is a *_more count.
    whos_going = []
    for s in showtimes:
        going = [r.user for r in s.rsvps
                 if r.status == 'going' and r.user and (not group or r.group_id == group.id)]
        if going:
            # Members who never share their RSVPs are counted, not named.
            shown, more = split_present(going, group.id if group else request_group())
            quiet = [u for u in shown if share_prefs(u)['rsvp'] == 'never']
            shown, more = [u for u in shown if u not in quiet], more + len(quiet)
            whos_going.append({**_showtime_brief(s), 'going': [u.name for u in shown], 'going_more': more})

    import notify
    retag_before = _utcnow_naive() - DIGEST_RETAG_AFTER
    watchers_by_movie = {}
    for w in (Watchlist.query.filter(Watchlist.movie_id.in_(by_movie)).all() if by_movie else []):
        if w.user and w.user.is_active and (members is None or w.user_id in members):
            alerts = notify.watch_alerts(w)      # an imported film they didn't want alerts for: counted only
            watchers_by_movie.setdefault(w.movie_id, []).append({
                'watchlist_id': w.id, 'name': w.user.name,
                'discord_user_id': w.user.discord_user_id,
                'fresh': alerts and (not w.last_notified_at or w.last_notified_at < retag_before),
                'shown': alerts and watch_shared(w, group.id if group else request_group()),
            })

    def watchers_out(ws):
        """Watchers the digest may name; the rest are counted, and fresh ones
        are still marked (and emailed) when the digest goes out."""
        shown = [{k: w[k] for k in ('watchlist_id', 'name', 'discord_user_id', 'fresh')} for w in ws if w['shown']]
        return shown, len(ws) - len(shown), [w['watchlist_id'] for w in ws if not w['shown'] and w['fresh']]

    plans = []
    for f, s, _ in picks['plans']:
        shown, more, _ = watchers_out(watchers_by_movie.get(f.movie.id, []))
        plans.append({**_showtime_brief(s), 'wanters': [w['name'] for w in shown], 'wanters_more': more})
    rare = [{**_showtime_brief(s), 'score': f.rare_score, 'reasons': why} for f, s, why in picks['rare']]
    last_chance = [_showtime_brief(s) for _, s, _ in picks['last_chance']]
    opening = [{**_showtime_brief(s), 'theatres': n} for _, s, n in picks['opening']]

    planned = {p['showtime_id'] for p in plans}
    watchlist = []
    for mid, ws in watchers_by_movie.items():
        shown, more, quiet = watchers_out(ws)
        watchlist.append({**_showtime_brief(by_movie[mid][0]), 'watchers': shown, 'more': more,
                          'quiet_ids': quiet, 'planned': by_movie[mid][0].id in planned})
    watchlist.sort(key=lambda item: item['start_time'])

    open_polls = ([p.to_dict() for p in Poll.query.filter_by(group_id=group.id, status='open')]
                  if group else [])

    return jsonify({
        'group_name': group.name if group else None,
        'enabled': bool(group and group.digest_enabled),   # off: the bot only previews it
        'days': days,
        'whos_going': whos_going,
        'plans': plans,
        'rare': rare,
        'last_chance': last_chance,
        'opening': opening,
        'watchlist': watchlist,
        'open_polls': open_polls,
        'recap': digest_recap(group, members, now) if group else None,
        'new_on_calendar': digest.new_on_calendar(days),
    })


@app.route('/api/internal/digest/delivered', methods=['POST'])
@require_internal
def internal_digest_delivered():
    """Called once the weekly digest has been posted with these watchlist
    entries tagged: marks them notified (no re-tag for two weeks) and emails
    watchers the digest didn't name (not on Discord, or not shared) the same news."""
    import notify
    ids = [i for i in (request.json or {}).get('watchlist_ids') or [] if isinstance(i, int)]
    now = _utcnow_naive()
    by_user = {}
    for w in (Watchlist.query.filter(Watchlist.id.in_(ids)).all() if ids else []):
        w.last_notified_at = now
        if w.user and w.user.email and not watch_shared(w, request_group()) and w.movie \
                and notify.prefs(w.user)['channels']['email']:
            by_user.setdefault(w.user.id, (w.user, []))[1].append(w.movie)
    db.session.commit()

    for user, movies in by_user.values():
        items = ''.join(f'<li><strong>{_html.escape(m.title)}</strong></li>' for m in movies)
        core.send_email(user.email, 'Your watchlist is playing this week',
            core.email_page(f"""<p>Films on your watchlist are showing this week:</p><ul>{items}</ul>
            {core.email_button(FRONTEND_URL, 'See showtimes')}"""))
    return jsonify({'marked': len(ids), 'emailed': len(by_user)})


@app.route('/api/internal/link/verify', methods=['POST'])
@require_internal
def internal_link_verify():
    data = request.json or {}
    code = (data.get('code') or '').strip().upper()
    discord_user_id = str(data.get('discord_user_id') or '').strip()
    if not code or not discord_user_id:
        return jsonify({'error': 'code and discord_user_id required'}), 400

    user = User.query.filter_by(discord_link_code=code).first()
    if not user:
        return jsonify({'error': 'Invalid code'}), 404
    if not user.discord_link_code_expires or user.discord_link_code_expires < _utcnow_naive():
        return jsonify({'error': 'Code expired — generate a new one on the site'}), 410

    # One site account per Discord account. A Discord-only account (made by
    # using the bot first) merges into this one; another site account just
    # loses the link.
    other = User.query.filter_by(discord_user_id=discord_user_id).first()
    if other and other.id != user.id:
        if other.email is None:
            merge_users(user, other)
        else:
            other.discord_user_id = None
            db.session.flush()

    user.discord_user_id = discord_user_id
    user.discord_username = (data.get('discord_username') or user.discord_username or '')[:40] or None
    user.discord_link_code = None
    user.discord_link_code_expires = None
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route('/api/internal/rsvp', methods=['POST'])
@require_internal
def internal_rsvp():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err

    group_id = _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'member')
    if err:
        return err
    showtime, err = apply_rsvp(user, data.get('showtime_id'), data.get('status'), group_id)
    if err:
        return err
    result = for_discord(showtime.to_dict(user_id=user.id, group_id=group_id), group_id)
    result['user'] = user.to_dict()
    import notify
    result['attendance_prompt'] = data.get('status') == 'going' and notify.ask_once(user, 'attendance')
    db.session.commit()
    return jsonify(result)


@app.route('/api/internal/watch', methods=['POST'])
@require_internal
def internal_watch():
    """Watchlist a movie from Discord's /watch command. `action` is
    'add' | 'remove' | 'toggle' (default toggle, for backwards compatibility)."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    title = (data.get('title') or '').strip()
    action = (data.get('action') or 'toggle').lower()
    kind, _, ref = title.partition(':')
    if kind == 'movie' and ref.isdigit():
        movie = db.session.get(Movie, int(ref))
    elif kind == 'tmdb' and ref.isdigit():
        movie = movie_for_tmdb(int(ref))
    else:
        movie = Movie.query.filter(Movie.title.ilike(title)).first() \
            or Movie.query.filter(Movie.title.ilike(f'%{title}%')).first()
        if not movie and action != 'remove' and len(title) >= 3:       # any film: TMDB's best match
            from enrich import search_tmdb
            best = search_tmdb(title)
            movie = movie_for_tmdb(best['id']) if best else None
    if not movie:
        return jsonify({'error': 'Movie not found'}), 404

    # Digest pings are opt-in too: your "watchlist" choice decides (asked below).
    # A film from Letterboxd that's added here becomes yours (re-imports leave
    # it); one removed here stays off (letterboxd.removed_here).
    import letterboxd
    existing = Watchlist.query.filter_by(user_id=user.id, movie_id=movie.id).first()
    if action == 'add':
        if not existing:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
        elif existing.source == 'letterboxd':
            existing.source = None
        watching = True
    elif action == 'remove':
        if existing:
            db.session.delete(existing)
        letterboxd.removed_here(user.id, movie.id)
        watching = False
    else:  # toggle
        if existing:
            db.session.delete(existing)
            letterboxd.removed_here(user.id, movie.id)
            watching = False
        else:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
            watching = True
    import notify
    alert_prompt = watching and notify.ask_once(user, 'alerts')
    db.session.commit()
    return jsonify({'movie_title': movie.title, 'watching': watching, 'user_name': user.name,
                    'alert_prompt': alert_prompt, 'digest_choice': share_prefs(user)['watchlist']})


@app.route('/api/internal/watchlist')
@require_internal
def internal_watchlist():
    """A member's watchlist (+ each movie's next upcoming showtime), for
    /watch show and Watchlist on /profile. Defaults to the caller; any active
    member is viewable (member_id, or member_discord_id).
    Optional start/end (ISO) keep only movies with a showtime in that window."""
    member_id = request.args.get('member_id', type=int)
    if member_id:
        target = db.session.get(User, member_id)
        if not on_discord(target, request_group()):     # someone else's: only members in this club's server
            target = None
    elif request.args.get('member_discord_id'):   # Watchlist on someone's /profile
        target = _discord_member(request.args['member_discord_id'], request_group())
    else:
        target, err = resolve_discord_user(request.args)
        if err:
            return err
    if not target or not target.is_active:
        return jsonify({'error': 'Member not found'}), 404

    start = request.args.get('start')
    end = request.args.get('end')
    start_dt = datetime.fromisoformat(start) if start else None
    end_dt = datetime.fromisoformat(end) if end else None
    in_cities = places.user_cities(target)          # their cities' showings only

    items = []
    for w in Watchlist.query.filter_by(user_id=target.id).all():
        if not w.movie:
            continue
        q = (Showtime.query.join(Theatre, Showtime.theatre_id == Theatre.id)
             .filter(Showtime.movie_id == w.movie_id, Theatre.city.in_(in_cities),
                     Showtime.is_cancelled.isnot(True)))
        q = q.filter(Showtime.start_time > start_dt) if start_dt else places.upcoming(q)
        if end_dt:
            q = q.filter(Showtime.start_time <= end_dt)
        next_st = q.order_by(Showtime.start_time).first()
        if (start_dt or end_dt) and not next_st:
            continue  # a window was requested and this movie has nothing in it
        items.append({
            'title': w.movie.title,
            'year': w.movie.release_year,
            'source': w.source,                       # 'letterboxd' = imported (/watch show marks it 📓)
            'next_showtime': public_showtimes([next_st])[0] if next_st else None,   # no names needed
        })
    items.sort(key=lambda i: i['next_showtime']['start_time'] if i['next_showtime'] else '9999')
    return jsonify({'owner': target.name, 'items': items})


@app.route('/api/internal/searches', methods=['POST'])
@require_internal
def internal_save_search():
    """🔔 Alert me under /find: save that search (the site's saved searches,
    R10a) — alerts come when a theatre books a film that fits, by the ways
    you've chosen (nothing unless you have)."""
    import notify
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    s, now_fitting, error = notify.save_search(user, data.get('params') or {}, _as_int(data.get('group_id')))
    if error:
        return jsonify({'error': error}), 400
    alert_prompt = notify.ask_once(user, 'alerts')
    db.session.commit()
    p = notify.prefs(user)
    return jsonify({'search': notify.search_dict(s), 'fitting_now': now_fitting, 'alert_prompt': alert_prompt,
                    'dm': p['channels']['discord'] and p['types']['searches']})

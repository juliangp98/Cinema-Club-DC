"""The Discord bot's API (X-Internal-Token): everything the bot reads and writes.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
import app as core
import html as _html
import json as _json
from app import (ATTENDANCE_LOOKBACK, AVATAR_COLORS, ActivityEvent, Attendance, BotSetting, DIGEST_CAPS,
    DiscordDeletion, DiscordPost, DiscordServerMember, FRONTEND_URL, GENRE_LIST, Group, GroupMembership,
    INTERNAL_API_TOKEN, IntegrityError, Message, Movie, Notification, PLAN_MIN_WATCHERS, Poll, PollCategory,
    PollDraft, PollVote, Quote, RANKED_PICKS, RSVP, SavedSearch, ScrapeEvent, Showtime, ShowtimeThread, Theatre,
    TriviaQuestion, User,
    Watchlist, _active_membership, _ai, _as_int, _draft_poll, _group_showtime_query, _notify_settings,
    _screening_item, _update_profile_fields, _utcnow_naive, announce_new_poll, app, apply_rsvp, apply_votes,
    attended_showtime_ids, build_leaderboard, build_poll, compare_members, datetime, db,
    follow_discord_avatar, history_items, jsonify, merge_users, movie_for_tmdb, on_discord,
    pending_attendance, poll_scores, post_dict, present_user_ids, public_showtimes, random, render_post,
    request, require_role, screening_card, secrets, set_attendance, set_share_pref, share_prefs,
    split_present, timedelta, tmdb_matches, utc_iso, vote_kernels, watch_shared, wraps)


def resolve_discord_user(data):
    """The account behind a Discord user, for the bot's internal endpoints.

    Discord members don't need a site account: the first time someone uses a
    personal command in the club's server (the bot sends create=True only
    there), they get a Discord-only account — no email, no site login unless
    they "Sign in with Discord" — and join that server's group. Discord-only
    accounts follow the member's current Discord name. Returns (user, error).
    """
    discord_id = str(data.get('discord_user_id') or '').strip()
    if not discord_id.isdigit():
        return None, (jsonify({'error': 'discord_user_id required'}), 400)
    create = str(data.get('create', '')).lower() in ('1', 'true')
    name = (data.get('discord_name') or '').strip()[:100]

    user = User.query.filter_by(discord_user_id=discord_id).first()
    if user is None:
        if not create:
            return None, (jsonify({'error': 'no_account'}), 404)
        user = User(discord_user_id=discord_id, name=name or 'Discord member',
                    avatar_color=random.choice(AVATAR_COLORS), is_active=True)
        db.session.add(user)
        try:
            db.session.flush()
        except IntegrityError:        # created by a simultaneous command
            db.session.rollback()
            user = User.query.filter_by(discord_user_id=discord_id).first()
    if not user or not user.is_active:
        return None, (jsonify({'error': 'no_account'}), 404)

    if user.email is None and name:
        user.name = name
    if data.get('discord_username'):
        user.discord_username = str(data['discord_username'])[:40]
    if data.get('discord_avatar'):
        follow_discord_avatar(user, str(data['discord_avatar']))

    # Being in the club's server is membership of its group.
    group = db.session.get(Group, _as_int(data.get('group_id'))) if create else None
    if group:
        membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
        if not membership:
            db.session.add(GroupMembership(user_id=user.id, group_id=group.id, role='member', status='active'))
        elif membership.status != 'active':
            membership.status = 'active'
    if create and not db.session.get(DiscordServerMember, discord_id):
        db.session.add(DiscordServerMember(discord_user_id=discord_id))   # they're using it in the server
        _present_changed()
    db.session.commit()
    return user, None

def require_internal(f):
    """Auth for /api/internal/* — shared-secret header used by the Discord bot
    over the Docker network. Rejects everything when the token is unset."""
    @wraps(f)
    def decorated(*args, **kwargs):
        supplied = request.headers.get('X-Internal-Token', '')
        if not INTERNAL_API_TOKEN or not secrets.compare_digest(supplied, INTERNAL_API_TOKEN):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated


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


def _present_changed():
    from flask import g, has_request_context
    if has_request_context():
        g.discord_present = None


def members_synced():
    """Has the bot reported the server's members yet? Until it has, nothing is posted."""
    return db.session.get(BotSetting, 'discord_members_synced_at') is not None


# ─── Discord posts: the bot's queue ───────────────────────────────────────────

@app.route('/api/internal/discord/posts/due')
@require_internal
def internal_posts_due():
    """What the bot should do now: post shares whose time has come, update
    posted ones whose content changed, delete ones with nothing left to show.
    Each item: {id, kind, action: post|edit|delete, message_id, data}.
    Nothing until the bot has reported who's in the server."""
    group_id = request.args.get('group_id', type=int)
    now = datetime.now()
    out = []
    if not members_synced():
        return jsonify(out)
    for p in (DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.status == 'pending',
                                       DiscordPost.post_at <= now)
              .order_by(DiscordPost.post_at, DiscordPost.id).limit(10)):
        data = render_post(p, now) if on_discord(p.user) else None
        if data is None:
            p.status = 'cancelled'            # nothing left to say (or they've left the server)
            continue
        out.append({'id': p.id, 'kind': p.kind, 'action': 'post', 'message_id': None, 'data': data})
    for p in (DiscordPost.query.filter(DiscordPost.group_id == group_id, DiscordPost.dirty.is_(True),
                                       DiscordPost.status.in_(('posted', 'removing')))
              .order_by(DiscordPost.id).limit(10)):
        data = render_post(p, now)
        if p.kind == 'thread':                 # a thread lives on its own once started
            p.dirty = False
            continue
        out.append({'id': p.id, 'kind': p.kind, 'action': 'edit' if data else 'delete',
                    'message_id': p.message_id, 'data': data})
    db.session.commit()
    return jsonify(out)


@app.route('/api/internal/discord/members', methods=['POST'])
@require_internal
def internal_discord_members():
    """Who's in the club's server, from the bot: {ids: [...], full: true} is
    the whole list (on start, and every half hour); {joined: [...]} /
    {left: [...]} are changes as they happen. Screenings whose Discord cards
    list someone who joined or left are refreshed."""
    data = request.json or {}
    clean = lambda key: {str(i) for i in data.get(key) or [] if str(i).isdigit()}
    current = {r[0] for r in db.session.query(DiscordServerMember.discord_user_id)}
    if data.get('full'):
        ids = clean('ids')
        joined, left = ids - current, current - ids
    else:
        joined, left = clean('joined') - current, clean('left') & current
    if left:
        DiscordServerMember.query.filter(DiscordServerMember.discord_user_id.in_(left)).delete(synchronize_session=False)
    for i in joined:
        db.session.add(DiscordServerMember(discord_user_id=i))
    changed = joined | left
    if changed:
        users = [u.id for u in User.query.filter(User.discord_user_id.in_(changed))]
        upcoming = {r.showtime_id for r in RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id).filter(
            RSVP.user_id.in_(users), RSVP.group_id == core.DISCORD_GROUP_ID, Showtime.start_time >= datetime.now())} \
            if users else set()
        if upcoming:
            ShowtimeThread.query.filter(ShowtimeThread.group_id == core.DISCORD_GROUP_ID,
                                        ShowtimeThread.showtime_id.in_(upcoming)) \
                .update({'card_dirty': True}, synchronize_session=False)
            DiscordPost.query.filter(DiscordPost.group_id == core.DISCORD_GROUP_ID, DiscordPost.kind == 'invite',
                                     DiscordPost.ref_id.in_(upcoming), DiscordPost.status == 'posted') \
                .update({'dirty': True}, synchronize_session=False)
    if data.get('full'):
        row = db.session.get(BotSetting, 'discord_members_synced_at') or BotSetting(key='discord_members_synced_at')
        row.value = _utcnow_naive().isoformat(timespec='seconds')
        db.session.add(row)
    db.session.commit()
    _present_changed()
    return jsonify({'members': len(current - left) + len(joined), 'joined': len(joined), 'left': len(left)})


@app.route('/api/internal/discord/posts/<int:post_id>/done', methods=['POST'])
@require_internal
def internal_post_done(post_id):
    """{action: posted (+message_id, jump_url) | edited | deleted}."""
    p = db.session.get(DiscordPost, post_id)
    if not p:
        return jsonify({'error': 'Not found'}), 404
    data = request.json or {}
    action = data.get('action')
    if action == 'posted':
        p.status, p.posted_at = 'posted', datetime.now()
        p.message_id = str(data.get('message_id') or '') or None
        p.jump_url = (data.get('jump_url') or '')[:200] or None
    elif action == 'edited':
        p.dirty = False
    elif action == 'deleted':
        p.status, p.dirty = 'removed', False
    else:
        return jsonify({'error': 'Unknown action'}), 400
    db.session.commit()
    return jsonify(post_dict(p))


@app.route('/api/internal/polls/draft', methods=['POST'])
@require_internal
def internal_draft_poll():
    """The bot's /poll make: — organizers only, same rules as the site."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group_id = _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'organizer')
    if err:
        return err
    body, status = _draft_poll(user, db.session.get(Group, group_id), data.get('prompt'), data.get('scope') or 'playing')
    return jsonify(body), status


@app.route('/api/internal/poll-drafts/<int:draft_id>/create', methods=['POST'])
@require_internal
def internal_create_from_draft(draft_id):
    """Discord's "Create now": the draft becomes an open poll, announced in #movies."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    d = db.session.get(PollDraft, draft_id)
    if not d:
        return jsonify({'error': 'draft_not_found'}), 404
    _, err = require_role(user, d.group_id, 'organizer')
    if err:
        return err
    if d.poll_id and db.session.get(Poll, d.poll_id):
        return jsonify({'error': 'already_created', 'poll_id': d.poll_id}), 409
    draft = _json.loads(d.data_json)
    poll, err = build_poll(d.group_id, user, draft)
    if err:
        return err
    d.poll_id = poll.id
    db.session.commit()
    announce_new_poll(poll, user, {'announce': 'now'})
    return jsonify(poll.to_dict(include_categories=True)), 201


def poll_ballot(user, poll):
    """Everything a Discord ballot shows, for one member: each category's
    nominees, their picks, the vote split (once they've picked, or voting has
    closed), and — once scored — the winners, their kernels and their place."""
    mine = {}
    for v in PollVote.query.join(PollCategory).filter(PollCategory.poll_id == poll.id,
                                                       PollVote.user_id == user.id):
        mine.setdefault(v.category_id, []).append(v)
    scored = poll.status == 'scored'
    cats = []
    for c in poll.categories:
        votes = sorted(mine.get(c.id, []), key=lambda v: v.rank or 0)
        d = {'id': c.id, 'title': c.title,
             'options': [{'id': o.id, 'text': o.text} for o in c.options],
             'picks': [{'option_id': v.option_id, 'confidence': v.confidence, 'rank': v.rank} for v in votes],
             'correct_option_id': c.correct_option_id if scored else None}
        if votes or poll.status != 'open':
            # Picks per nominee (ranked: any rank), out of the members who voted here.
            d['voters'] = len({v.user_id for v in c.votes})
            d['split'] = {}
            for v in c.votes:
                d['split'][str(v.option_id)] = d['split'].get(str(v.option_id), 0) + 1
        if scored and c.correct_option_id and votes:
            d['kernels'] = sum(vote_kernels(poll.scoring_mode, v, c.correct_option_id) for v in votes)
        cats.append(d)
    out = {'poll': {'id': poll.id, 'title': poll.title, 'status': poll.status,
                    'scoring_mode': poll.scoring_mode, 'poll_type': poll.poll_type,
                    'ranked_picks': RANKED_PICKS},
           'categories': cats, 'answered': sum(1 for c in cats if c['picks'])}
    if scored:
        board = poll_scores(poll)
        place = next((i for i, s in enumerate(board) if s['user'].id == user.id), None)
        out['score'] = ({'kernels': board[place]['kernels'], 'correct': board[place]['correct'],
                         'place': place + 1, 'of': len(board)} if place is not None else None)
    return out


@app.route('/api/internal/scrape-events')
@require_internal
def internal_scrape_events():
    q = ScrapeEvent.query
    if request.args.get('unannounced'):
        q = q.filter(ScrapeEvent.announced_at.is_(None))
    # Never announce stale events (e.g. backfill runs while the bot was down)
    since_hours = request.args.get('since_hours', 48, type=int)
    q = q.filter(ScrapeEvent.created_at > _utcnow_naive() - timedelta(hours=since_hours))
    events = q.order_by(ScrapeEvent.created_at).limit(20).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/internal/scrape-events/<int:event_id>/announced', methods=['POST'])
@require_internal
def internal_mark_announced(event_id):
    event = db.session.get(ScrapeEvent, event_id)
    if not event:
        return jsonify({'error': 'Not found'}), 404
    if not event.announced_at:
        event.announced_at = _utcnow_naive()
        db.session.commit()
    return jsonify(event.to_dict())


@app.route('/api/internal/activity-events')
@require_internal
def internal_activity_events():
    q = ActivityEvent.query
    if request.args.get('unannounced'):
        q = q.filter(ActivityEvent.announced_at.is_(None))
    # Don't announce stale actions if the bot was offline a while.
    since_hours = request.args.get('since_hours', 6, type=int)
    q = q.filter(ActivityEvent.created_at > _utcnow_naive() - timedelta(hours=since_hours))
    events = q.order_by(ActivityEvent.created_at).limit(20).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/internal/activity-events/<int:event_id>/announced', methods=['POST'])
@require_internal
def internal_mark_activity_announced(event_id):
    ev = db.session.get(ActivityEvent, event_id)
    if not ev:
        return jsonify({'error': 'Not found'}), 404
    if not ev.announced_at:
        ev.announced_at = _utcnow_naive()
        db.session.commit()
    return jsonify(ev.to_dict())


@app.route('/api/internal/showtimes')
@require_internal
def internal_showtimes():
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
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

    limit = min(request.args.get('limit', 200, type=int), 500)
    showtimes = q.order_by(Showtime.start_time).limit(limit).all()
    return jsonify([for_discord(s.to_dict(group_id=group_id)) for s in showtimes])


def for_discord(d):
    """A showtime dict as the bot may show it: attendees / maybes name only
    members in the club's server (attendees_more / maybes_more count the rest),
    and reactions are counts only."""
    shown = present_user_ids()
    for key in ('attendees', 'maybes'):
        people = d.get(key) or []
        d[key] = [p for p in people if p['id'] in shown]
        d[f'{key}_more'] = len(people) - len(d[key])
    for r in (d.get('reactions') or {}).values():
        r['users'] = [u for u in r.get('users', []) if u['id'] in shown]
    return d


@app.route('/api/internal/chat-context')
@require_internal
def internal_chat_context():
    """Compact per-user + what's-playing bundle powering the bot's @-mention
    chatbot. Everything is bounded to keep the prompt small, and the bot is
    told to treat `upcoming` as the ONLY source of real screenings."""
    discord_id = str(request.args.get('discord_user_id') or '').strip()
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()

    user = User.query.filter_by(discord_user_id=discord_id).first() if discord_id else None
    out = {'user': {'linked': bool(user)}}

    if user:
        out['user'].update({
            'name': user.name,
            'favorite_genres': user.favorite_genres or '',
            'letterboxd_username': user.letterboxd_username or '',
            'bio': (user.bio or '')[:300],
        })

        import kernels
        k = kernels.breakdown(user.id, group.id if group else None)
        standing = {'kernels': k['kernels'], 'correct_picks': k['correct']}
        if group:
            board = build_leaderboard(group)
            standing['of'] = len(board)
            for i, row in enumerate(board):
                if row['user']['id'] == user.id:
                    standing['rank'] = i + 1
                    standing['attendance'] = row['attendance']
                    break
        out['standing'] = standing

        wl = (Watchlist.query.filter_by(user_id=user.id)
              .order_by(Watchlist.created_at.desc()).limit(25).all())
        out['watchlist'] = [{'title': w.movie.title, 'year': w.movie.release_year}
                            for w in wl if w.movie]

        seen_ids = attended_showtime_ids(user.id, {group.id} if group else None)
        seen, attended = set(), []
        for s in (Showtime.query.filter(Showtime.id.in_(seen_ids))
                  .order_by(Showtime.start_time.desc()).limit(60).all() if seen_ids else []):
            m = s.movie
            if not m or m.title in seen:
                continue
            seen.add(m.title)
            attended.append({
                'title': m.title,
                'year': m.release_year,
                'theatre': s.theatre.short_name or s.theatre.name,
                'date': s.start_time.strftime('%Y-%m-%d'),
            })
            if len(attended) >= 20:
                break
        out['attended'] = attended

    # What the ask is about (R3b): films that fit it, from the Discover engine.
    prompt = (request.args.get('prompt') or '').strip()
    if prompt and group:
        import discover
        out['picks'] = discover.chat_picks(group, user, prompt[:500], now)

    # Always include what's playing (group-scoped) so unlinked askers still get help.
    upcoming = (_group_showtime_query(group)
                .filter(Showtime.start_time >= now,
                        Showtime.start_time <= now + timedelta(days=14))
                .order_by(Showtime.start_time).limit(60).all())
    out['upcoming'] = [{
        'title': s.movie.title,
        'genres': s.movie.genres or '',
        'theatre': s.theatre.short_name or s.theatre.name,
        'date': s.start_time.strftime('%a %-m/%-d'),
        'time': s.start_time.strftime('%-I:%M %p'),
    } for s in upcoming]

    return jsonify(out)


# ─── Discover in Discord (R3b) ───────────────────────────────────────────────
# /find and /surprise. Anyone can use them; an existing account (never created
# here) personalizes "For you", "Your list" and the you-are-going marks.

def _internal_discover_args():
    discord_id = str(request.args.get('discord_user_id') or '').strip()
    viewer = User.query.filter_by(discord_user_id=discord_id, is_active=True).first() if discord_id.isdigit() else None
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    return viewer, group


@app.route('/api/internal/discover/options')
@require_internal
def internal_discover_options():
    import discover
    _, group = _internal_discover_args()
    if not group:
        return jsonify({'error': 'group not found'}), 404
    return jsonify({'types': discover.find_types(group),
                    'regions': [{'value': f'region:{k}', 'label': v} for k, v in discover.REGION_KEYS.items()]})


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


@app.route('/api/internal/discover/surprise')
@require_internal
def internal_discover_surprise():
    import discover
    viewer, group = _internal_discover_args()
    if not group:
        return jsonify({'error': 'group not found'}), 404
    a = request.args
    params = discover.find_params(where=a.get('where'))
    theatres = {x for x in params.get('theatres', '').split(',') if x} | \
        {s for s, r in discover.REGIONS.items() if r.lower() in params.get('regions', '').split(',')}
    exclude = [_as_int(x) for x in (a.get('exclude') or '').split(',') if _as_int(x)]
    when = a.get('when') if a.get('when') in discover.WHEN else 'tonight'
    pick = discover.surprise(group, viewer, when, exclude, theatres=theatres or None)
    return jsonify(pick or {'error': 'nothing_playing'}), (200 if pick else 404)


@app.route('/api/internal/theatres')
@require_internal
def internal_theatres():
    """Active theatres for the bot's theatre autocomplete. Scoped to a group's
    theatre list when a group_id is given (all active theatres otherwise)."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    theatres = Theatre.query.filter(Theatre.is_active.isnot(False)).order_by(Theatre.name).all()
    if group:
        slugs = [t.strip() for t in (group.theatres or '').split(',') if t.strip()]
        if slugs:
            theatres = [t for t in theatres if t.slug in slugs]
    return jsonify([t.to_dict() for t in theatres])


@app.route('/api/internal/showtime-facets')
@require_internal
def internal_showtime_facets():
    """Distinct dates + theatres available for the current filter selection,
    powering dependent autocompletes (pick a movie -> only its dates/theatres).
    Computed with DISTINCT so it's complete and cheap regardless of volume.
    Optional filters: q (movie title), theatre (slug), start/end (ISO)."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()
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


def _showtime_brief(s):
    return {'showtime_id': s.id, 'title': s.movie.title, 'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label}


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
                     'winner': board[0]['user'].name if on_discord(board[0]['user']) else None}
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
    import json as _json
    import discover
    group_id = request.args.get('group_id', type=int)
    days = request.args.get('days', 7, type=int)
    group = db.session.get(Group, group_id) if group_id else None
    now = datetime.now()

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
            shown, more = split_present(going)
            quiet = [u for u in shown if share_prefs(u)['rsvp'] == 'never']
            shown, more = [u for u in shown if u not in quiet], more + len(quiet)
            whos_going.append({**_showtime_brief(s), 'going': [u.name for u in shown], 'going_more': more})

    retag_before = _utcnow_naive() - DIGEST_RETAG_AFTER
    watchers_by_movie = {}
    for w in (Watchlist.query.filter(Watchlist.movie_id.in_(by_movie)).all() if by_movie else []):
        if w.user and w.user.is_active and (members is None or w.user_id in members):
            watchers_by_movie.setdefault(w.movie_id, []).append({
                'watchlist_id': w.id, 'name': w.user.name,
                'discord_user_id': w.user.discord_user_id,
                'fresh': not w.last_notified_at or w.last_notified_at < retag_before,
                'shown': watch_shared(w),
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

    new_on_calendar = {}
    for e in (ScrapeEvent.query
              .filter(ScrapeEvent.event_type.in_(('new_drop', 'new_showtimes')),
                      ScrapeEvent.created_at > _utcnow_naive() - timedelta(days=days))):
        p = _json.loads(e.payload_json or '{}')
        name = (e.theatre.short_name or e.theatre.name) if e.theatre else p.get('theatre_name', '')
        new_on_calendar[name] = new_on_calendar.get(name, 0) + (p.get('new_showtime_count') or 0)

    open_polls = ([p.to_dict() for p in Poll.query.filter_by(group_id=group.id, status='open')]
                  if group else [])

    return jsonify({
        'group_name': group.name if group else None,
        'days': days,
        'whos_going': whos_going,
        'plans': plans,
        'rare': rare,
        'last_chance': last_chance,
        'opening': opening,
        'watchlist': watchlist,
        'open_polls': open_polls,
        'recap': digest_recap(group, members, now) if group else None,
        'new_on_calendar': [{'theatre': t, 'showtimes': n}
                            for t, n in sorted(new_on_calendar.items(), key=lambda kv: -kv[1]) if n],
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
        if w.user and w.user.email and not watch_shared(w) and w.movie and notify.prefs(w.user)['channels']['email']:
            by_user.setdefault(w.user.id, (w.user, []))[1].append(w.movie)
    db.session.commit()

    for user, movies in by_user.values():
        items = ''.join(f'<li><strong>{_html.escape(m.title)}</strong></li>' for m in movies)
        core.send_email(user.email, 'Your watchlist is playing this week',
            f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
            <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2>
            <p>Films on your watchlist are showing this week:</p><ul>{items}</ul>
            <p><a href="{FRONTEND_URL}" style="display:inline-block;padding:12px 24px;background:#e8a838;
            color:#0d0c09;text-decoration:none;border-radius:6px;font-weight:bold;">See showtimes</a></p>
            </div>""")
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
    result = for_discord(showtime.to_dict(user_id=user.id, group_id=group_id))
    result['user'] = user.to_dict()
    import notify
    result['attendance_prompt'] = data.get('status') == 'going' and notify.ask_once(user, 'attendance')
    db.session.commit()
    return jsonify(result)


@app.route('/api/internal/polls')
@require_internal
def internal_polls():
    group_id = request.args.get('group_id', type=int)
    if not group_id:
        return jsonify({'error': 'group_id required'}), 400
    q = Poll.query.filter_by(group_id=group_id)
    if request.args.get('include_closed'):
        # /vote's picker: open polls, then ones that closed in the last 60 days
        # (to check your picks and results).
        recent = _utcnow_naive() - timedelta(days=60)
        ended = db.func.coalesce(Poll.scored_at, Poll.closed_at, Poll.created_at)
        polls = q.filter(db.or_(Poll.status == 'open', ended >= recent)).all()
        polls.sort(key=lambda p: (p.status != 'open', -(p.scored_at or p.closed_at or p.created_at).timestamp()))
    else:
        polls = q.filter_by(status='open').all()
    return jsonify([p.to_dict() for p in polls])


def _internal_poll_voter(poll_id, data):
    """(user, poll, error) for a Discord member acting on a poll of a group
    they belong to."""
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return None, None, (jsonify({'error': 'poll_not_found'}), 404)
    user, err = resolve_discord_user(data)
    if err:
        return None, None, err
    if not _active_membership(user, poll.group_id):
        return None, None, (jsonify({'error': 'not_member'}), 403)
    return user, poll, None


@app.route('/api/internal/polls/<int:poll_id>/ballot')
@require_internal
def internal_poll_ballot(poll_id):
    user, poll, err = _internal_poll_voter(poll_id, request.args)
    if err:
        return err
    return jsonify(poll_ballot(user, poll))


@app.route('/api/internal/polls/<int:poll_id>/vote', methods=['POST'])
@require_internal
def internal_poll_vote(poll_id):
    """Save picks from a Discord ballot; returns the refreshed ballot."""
    data = request.json or {}
    user, poll, err = _internal_poll_voter(poll_id, data)
    if err:
        return err
    _, err = require_role(user, poll.group_id, 'member')
    if err:
        return err
    if poll.status != 'open':
        return jsonify({'error': 'poll_closed', **poll_ballot(user, poll)}), 409
    apply_votes(user, poll, data.get('votes'), data.get('clear'))
    return jsonify(poll_ballot(user, poll))


# ─── Discussion threads (mirrored with Discord) ───────────────────────────────
# Each screening's discussion can have a thread in #movies. The bot owns all
# Discord calls; the backend keeps the mapping and an outbox: site comments not
# yet copied to Discord, site deletions to carry out, and starter cards whose
# RSVP list changed. Thread messages come back in as comments.

DISCUSSION_BACKFILL = 10                      # earlier comments copied into a new thread
OUTBOX_WINDOW = timedelta(hours=24)           # older unsent comments are backfilled instead
CARD_REFRESH_EVERY = timedelta(minutes=3)


def _in_server():
    """Site user ids of members in the club's Discord server (a subquery)."""
    return (db.session.query(User.id)
            .join(DiscordServerMember, DiscordServerMember.discord_user_id == User.discord_user_id))


def _pending_post(q):
    """Site comments the bot still has to copy into Discord (never ones their
    writer kept off Discord, or by anyone not in the club's server)."""
    return q.filter(Message.source == 'site', Message.discord_message_id.is_(None),
                    Message.to_discord.isnot(False), Message.user_id.in_(_in_server()),
                    Message.created_at >= _utcnow_naive() - OUTBOX_WINDOW)


def _thread_dict(t):
    return {'thread_id': t.thread_id, 'channel_id': t.channel_id, 'guild_id': t.guild_id,
            'starter_message_id': t.starter_message_id, 'showtime_id': t.showtime_id, 'url': t.url}


def _outbound(m):
    """A comment as the bot posts it: under its author's name (and Discord avatar, if linked)."""
    avatar = m.user.avatar_url if (m.user.avatar_url or '').startswith('https://cdn.discordapp.com/') else None
    return {'message_id': m.id, 'showtime_id': m.showtime_id, 'body': m.body, 'created_at': utc_iso(m.created_at),
            'author': {'id': m.user.id, 'name': m.user.name, 'avatar_url': avatar}}


def thread_info(showtime, group_id):
    """The thread (if any) and starter card for a screening; when there's no
    thread yet, the comments to copy in when it's created: the last
    DISCUSSION_BACKFILL, minus any the outbox is about to post anyway."""
    t = ShowtimeThread.query.filter_by(showtime_id=showtime.id, group_id=group_id).first()
    out = {'thread': _thread_dict(t) if t else None, 'card': screening_card(showtime, group_id)}
    if not t:
        q = Message.query.filter_by(showtime_id=showtime.id, group_id=group_id)
        pending = {m.id for m in _pending_post(q)}
        earlier = [m for m in q.order_by(Message.created_at.desc(), Message.id.desc())
                   if m.id not in pending and m.to_discord is not False and m.user_id in present_user_ids()]
        out['earlier_total'] = len(earlier)
        out['backfill'] = [_outbound(m) for m in reversed(earlier[:DISCUSSION_BACKFILL])]
    return out


@app.route('/api/internal/discussion/threads')
@require_internal
def internal_discussion_threads():
    """Every linked thread id (the bot only mirrors these)."""
    group_id = request.args.get('group_id', type=int)
    return jsonify([t.thread_id for t in ShowtimeThread.query.filter_by(group_id=group_id)])


@app.route('/api/internal/discussion/thread')
@require_internal
def internal_discussion_thread():
    showtime = db.session.get(Showtime, request.args.get('showtime_id', type=int) or 0)
    if not showtime:
        return jsonify({'error': 'showtime_not_found'}), 404
    return jsonify(thread_info(showtime, request.args.get('group_id', type=int)))


@app.route('/api/internal/discussion/threads', methods=['POST'])
@require_internal
def internal_register_thread():
    """Link a newly created thread. If the screening already has one (a race),
    returns that with 409 so the bot can drop its duplicate."""
    data = request.json or {}
    showtime_id, group_id = _as_int(data.get('showtime_id')), _as_int(data.get('group_id'))
    existing = ShowtimeThread.query.filter_by(showtime_id=showtime_id, group_id=group_id).first()
    if existing:
        return jsonify({'error': 'exists', 'thread': _thread_dict(existing)}), 409
    t = ShowtimeThread(showtime_id=showtime_id, group_id=group_id, guild_id=str(data.get('guild_id')),
                       channel_id=str(data.get('channel_id')), thread_id=str(data.get('thread_id')),
                       starter_message_id=str(data['starter_message_id']) if data.get('starter_message_id') else None,
                       card_refreshed_at=_utcnow_naive())
    db.session.add(t)
    db.session.commit()
    return jsonify(_thread_dict(t)), 201


@app.route('/api/internal/discussion/threads/<thread_id>/unlink', methods=['POST'])
@require_internal
def internal_unlink_thread(thread_id):
    """The thread was deleted in Discord: forget it (comments stay on the site;
    the next comment starts a new thread)."""
    t = ShowtimeThread.query.filter_by(thread_id=str(thread_id)).first()
    if t:
        Message.query.filter_by(showtime_id=t.showtime_id, group_id=t.group_id) \
            .update({'discord_message_id': None}, synchronize_session=False)
        DiscordDeletion.query.filter_by(thread_id=t.thread_id, done_at=None).delete()
        db.session.delete(t)
        db.session.commit()
    return jsonify({'unlinked': bool(t)})


@app.route('/api/internal/discussion/outbox')
@require_internal
def internal_discussion_outbox():
    group_id = request.args.get('group_id', type=int)
    # Comments wait until their screening has a thread (Discord's Discuss, or
    # "Start a Discord thread" on the site); new comments never start one.
    threaded = db.session.query(ShowtimeThread.showtime_id).filter(ShowtimeThread.group_id == group_id)
    posts = _pending_post(Message.query.filter(Message.group_id == group_id, Message.showtime_id.in_(threaded))) \
        .order_by(Message.created_at, Message.id).limit(20).all()
    stale = _utcnow_naive() - CARD_REFRESH_EVERY
    cards = ShowtimeThread.query.filter(
        ShowtimeThread.group_id == group_id, ShowtimeThread.card_dirty.is_(True),
        db.or_(ShowtimeThread.card_refreshed_at.is_(None), ShowtimeThread.card_refreshed_at < stale)).limit(10).all()
    deletions = DiscordDeletion.query.filter_by(done_at=None).order_by(DiscordDeletion.id).limit(20).all()
    return jsonify({
        'posts': [_outbound(m) for m in posts],
        'deletions': [{'id': d.id, 'thread_id': d.thread_id, 'discord_message_id': d.discord_message_id}
                      for d in deletions],
        'cards': [{**_thread_dict(t), 'card': screening_card(db.session.get(Showtime, t.showtime_id), group_id)}
                  for t in cards if db.session.get(Showtime, t.showtime_id)],
    })


@app.route('/api/internal/discussion/mirrored', methods=['POST'])
@require_internal
def internal_discussion_mirrored():
    """Record the Discord copies of site comments ({items: [{message_id, discord_message_id}]})."""
    for item in (request.json or {}).get('items', []):
        m = db.session.get(Message, _as_int(item.get('message_id')))
        if m and not m.discord_message_id:
            m.discord_message_id = str(item.get('discord_message_id'))
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/discussion/deletions/<int:deletion_id>/done', methods=['POST'])
@require_internal
def internal_discussion_deletion_done(deletion_id):
    d = db.session.get(DiscordDeletion, deletion_id)
    if d and not d.done_at:
        d.done_at = _utcnow_naive()
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/discussion/cards/<thread_id>/refreshed', methods=['POST'])
@require_internal
def internal_discussion_card_refreshed(thread_id):
    t = ShowtimeThread.query.filter_by(thread_id=str(thread_id)).first()
    if t:
        t.card_dirty, t.card_refreshed_at = False, _utcnow_naive()
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/discussion/messages', methods=['POST'])
@require_internal
def internal_discussion_message():
    """A message from a screening thread (typed, or posted by the bot for a
    member) becomes that member's comment. Idempotent per Discord message."""
    data = request.json or {}
    t = ShowtimeThread.query.filter_by(thread_id=str(data.get('thread_id'))).first()
    if not t:
        return jsonify({'error': 'unknown_thread'}), 404
    did = str(data.get('discord_message_id') or '')
    existing = Message.query.filter_by(discord_message_id=did).first() if did else None
    if existing:
        return jsonify({'id': existing.id, 'duplicate': True})
    body = (data.get('body') or '').strip()[:2000]
    if not body or not did:
        return jsonify({'error': 'body and discord_message_id required'}), 400
    user, err = resolve_discord_user(data)
    if err:
        return err
    if not _active_membership(user, t.group_id):
        return jsonify({'error': 'not_member'}), 403
    source = 'discord_bot' if data.get('source') == 'discord_bot' else 'discord'
    # Typed in the thread: Discord's own permissions apply, so it mirrors. Posted
    # through the bot's Discuss button: read-only members can't (R5c).
    if source == 'discord_bot':
        _, err = require_role(user, t.group_id, 'member')
        if err:
            return err
    m = Message(user_id=user.id, showtime_id=t.showtime_id, group_id=t.group_id, body=body,
                source=source, discord_message_id=did)
    db.session.add(m)
    db.session.commit()
    return jsonify({'id': m.id}), 201


@app.route('/api/internal/discussion/messages/edit', methods=['POST'])
@require_internal
def internal_discussion_edit():
    data = request.json or {}
    m = Message.query.filter_by(discord_message_id=str(data.get('discord_message_id'))).first()
    body = (data.get('body') or '').strip()[:2000]
    updated = bool(m and body and m.source == 'discord')   # only messages typed in Discord are edited there
    if updated:
        m.body = body
        db.session.commit()
    return jsonify({'updated': updated})


@app.route('/api/internal/discussion/messages/delete', methods=['POST'])
@require_internal
def internal_discussion_delete():
    """Messages deleted in a thread (by their author or a moderator) leave the site too."""
    ids = [str(i) for i in (request.json or {}).get('discord_message_ids', [])]
    n = Message.query.filter(Message.discord_message_id.in_(ids)).delete(synchronize_session=False) if ids else 0
    db.session.commit()
    return jsonify({'deleted': n})


@app.route('/api/internal/leaderboard')
@require_internal
def internal_leaderboard():
    """/leaderboard: members in the club's server, with their real place;
    `hidden` counts the members on the site."""
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    shown_ids = present_user_ids()
    board = build_leaderboard(group)
    rows = [{'place': i + 1, 'user': {'name': r['user']['name']},
             **{k: r[k] for k in ('kernels', 'correct', 'attendance', 'breakdown')}}
            for i, r in enumerate(board) if r['user']['id'] in shown_ids]
    return jsonify({'rows': rows, 'hidden': len(board) - len(rows)})


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
    existing = Watchlist.query.filter_by(user_id=user.id, movie_id=movie.id).first()
    if action == 'add':
        if not existing:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
        watching = True
    elif action == 'remove':
        if existing:
            db.session.delete(existing)
        watching = False
    else:  # toggle
        if existing:
            db.session.delete(existing)
            watching = False
        else:
            db.session.add(Watchlist(user_id=user.id, movie_id=movie.id))
            watching = True
    import notify
    alert_prompt = watching and notify.ask_once(user, 'alerts')
    db.session.commit()
    return jsonify({'movie_title': movie.title, 'watching': watching, 'user_name': user.name,
                    'alert_prompt': alert_prompt, 'digest_choice': share_prefs(user)['watchlist']})


@app.route('/api/internal/members')
@require_internal
def internal_members():
    """Active members of a group who are in the club's server, for the /watch
    member picker."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    if not group:
        return jsonify([])
    members = [m.user for m in group.memberships
               if m.status == 'active' and m.user and m.user.is_active and on_discord(m.user)]
    members.sort(key=lambda u: (u.name or '').lower())
    return jsonify([{'id': u.id, 'name': u.name} for u in members])


@app.route('/api/internal/watchlist')
@require_internal
def internal_watchlist():
    """A member's watchlist (+ each movie's next upcoming showtime), for
    /watch show. Defaults to the caller; any active member is viewable.
    Optional start/end (ISO) keep only movies with a showtime in that window."""
    member_id = request.args.get('member_id', type=int)
    if member_id:
        target = db.session.get(User, member_id)
        if not on_discord(target):            # someone else's: only members in the server
            target = None
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
    now = datetime.now()

    items = []
    for w in Watchlist.query.filter_by(user_id=target.id).all():
        if not w.movie:
            continue
        q = (Showtime.query
             .filter(Showtime.movie_id == w.movie_id,
                     Showtime.is_cancelled.isnot(True))
             .filter(Showtime.start_time > (start_dt or now)))
        if end_dt:
            q = q.filter(Showtime.start_time <= end_dt)
        next_st = q.order_by(Showtime.start_time).first()
        if (start_dt or end_dt) and not next_st:
            continue  # a window was requested and this movie has nothing in it
        items.append({
            'title': w.movie.title,
            'year': w.movie.release_year,
            'next_showtime': public_showtimes([next_st])[0] if next_st else None,   # no names needed
        })
    items.sort(key=lambda i: i['next_showtime']['start_time'] if i['next_showtime'] else '9999')
    return jsonify({'owner': target.name, 'items': items})


def _profile_payload(user):
    import kernels
    now = datetime.now()
    k = kernels.breakdown(user.id)
    upcoming = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
                .filter(RSVP.user_id == user.id, RSVP.status == 'going', Showtime.start_time > now)
                .count())
    return {
        'user': user.to_dict(),
        'genres': [g for g in (user.favorite_genres or '').split(',') if g],
        'genre_options': GENRE_LIST,
        'watchlist_count': Watchlist.query.filter_by(user_id=user.id).count(),
        'upcoming_rsvps': upcoming,
        'site_account': user.email is not None,
        'kernels': {key: k[key] for key in ('kernels', *kernels.PARTS)},
    }


@app.route('/api/internal/profile')
@require_internal
def internal_profile():
    """A profile for Discord's /profile: someone else's (member_discord_id), or
    the caller's own — created on first use in the club's server."""
    other = request.args.get('member_discord_id')
    if other:
        user = User.query.filter_by(discord_user_id=str(other)).first()
        if not user or not user.is_active or not on_discord(user):
            return jsonify({'error': 'no_account'}), 404
    else:
        user, err = resolve_discord_user(request.args)
        if err:
            return err
    return jsonify(_profile_payload(user))


@app.route('/api/internal/kernels')
@require_internal
def internal_kernels():
    """/kernels: your kernels in the club, where they came from, and what's
    left of this week's allowance to give and take (on the site)."""
    import kernels
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    group_id = request.args.get('group_id', type=int)
    k = kernels.breakdown(user.id, group_id)
    return jsonify({**k, 'allowance': kernels.allowance(user.id),
                    'rules': kernels.rules(group_id)})


# ─── Daily trivia (R10d) ──────────────────────────────────────────────────────

@app.route('/api/internal/trivia/today')
@require_internal
def internal_trivia_today():
    """/trivia: the club's question of the day for this member."""
    import trivia
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    return jsonify(trivia.today_for(group, user))


@app.route('/api/internal/trivia/answer', methods=['POST'])
@require_internal
def internal_trivia_answer():
    """A trivia button in Discord: {discord ident, question_id, choice}."""
    import trivia
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group = db.session.get(Group, _as_int(data.get('group_id')) or 0)
    result, error = trivia.answer(group, user, _as_int(data.get('question_id')),
                                  data.get('choice') if isinstance(data.get('choice'), int) else None, source='discord')
    if error:
        return jsonify({'error': error}), 400
    return jsonify(result)


@app.route('/api/internal/trivia/another', methods=['POST'])
@require_internal
def internal_trivia_another():
    """/trivia or "🎲 Another one" in Discord: an anytime question for this member."""
    import trivia
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    q, error = trivia.another(db.session.get(Group, _as_int(data.get('group_id')) or 0), user)
    if error:
        return jsonify({'error': error}), 400
    return jsonify(trivia.as_dict(q, user))


@app.route('/api/internal/bingo')
@require_internal
def internal_bingo():
    """/bingo: this member's card for the month."""
    import bingo
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    return jsonify(bingo.view(db.session.get(Group, request.args.get('group_id', type=int) or 0), user))


@app.route('/api/internal/trivia/post')
@require_internal
def internal_trivia_post():
    """For the bot's daily post in #movies: today's question (without its
    answer) and yesterday's (with it) — only if the club turned trivia on AND
    said yes to Discord posts, and today's isn't posted yet."""
    import trivia
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group or not (group.trivia_enabled and group.trivia_discord):
        return jsonify({'post': None})
    q = trivia.question_for(group)
    if not q or q.discord_message_id:
        return jsonify({'post': None})
    prev = (TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id, TriviaQuestion.slot == 'daily',
                                        TriviaQuestion.day < q.day)
            .order_by(TriviaQuestion.day.desc()).first())
    return jsonify({'post': trivia.as_dict(q),
                    'yesterday': trivia.as_dict(prev, reveal=True) if prev and prev.day == q.day - timedelta(days=1) else None})


@app.route('/api/internal/trivia/posted', methods=['POST'])
@require_internal
def internal_trivia_posted():
    data = request.json or {}
    q = db.session.get(TriviaQuestion, _as_int(data.get('question_id')) or 0)
    if not q:
        return jsonify({'error': 'Not found'}), 404
    q.discord_message_id = str(data.get('message_id') or '')[:30] or None
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/profile', methods=['POST'])
@require_internal
def internal_profile_update():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    _update_profile_fields(user, data)
    db.session.commit()
    return jsonify(_profile_payload(user))


def _slug_list(value):
    return [s.strip() for s in (value or '').split(',') if s.strip()]


@app.route('/api/internal/alerts')
@require_internal
def internal_alerts():
    """Theatres whose new-showtime drops the bot announces for a group. Opt-in:
    a theatre not listed is quiet, and its new showtimes reach people through
    the weekly digest instead."""
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    slugs = _slug_list(group.announce_enabled_theatres if group else '')
    names = {t.slug: (t.short_name or t.name)
             for t in Theatre.query.filter(Theatre.slug.in_(slugs)).all()} if slugs else {}
    return jsonify({
        'slugs': slugs,
        'enabled': [{'slug': s, 'name': names.get(s, s)} for s in slugs],
    })


@app.route('/api/internal/alerts', methods=['POST'])
@require_internal
def internal_alerts_update():
    data = request.json or {}
    group = db.session.get(Group, data.get('group_id')) if data.get('group_id') else None
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    slug = (data.get('theatre_slug') or '').strip()
    action = (data.get('action') or '').lower()
    theatre = Theatre.query.filter_by(slug=slug).first()
    if not theatre:
        return jsonify({'error': 'Theatre not found'}), 404
    if action not in ('enable', 'disable'):
        return jsonify({'error': 'action must be enable or disable'}), 400

    current = _slug_list(group.announce_enabled_theatres)
    changed = (slug not in current) if action == 'enable' else (slug in current)
    if action == 'enable' and changed:
        current.append(slug)
    elif action == 'disable':
        current = [s for s in current if s != slug]
    group.announce_enabled_theatres = ','.join(current)
    db.session.commit()
    return jsonify({'theatre_slug': slug, 'theatre_name': theatre.short_name or theatre.name,
                    'enabled': action == 'enable', 'changed': changed, 'slugs': current})


ATTENDANCE_DM_GAP = timedelta(hours=20)   # at most one "did you go?" DM per person per day


@app.route('/api/internal/attendance/prompts')
@require_internal
def internal_attendance_prompts():
    """Who the bot should DM "did you go?" now: members on Discord with
    screenings nobody has asked them about, skipping anyone DMed in the last 20
    hours (so it's at most a daily nudge). Up to 5 screenings each — one DM's
    worth of buttons. Quiet hours are the bot's call."""
    now = datetime.now()
    candidates = {r.user_id for r in RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id).filter(
        RSVP.status == 'going', Showtime.start_time >= now - ATTENDANCE_LOOKBACK, Showtime.start_time <= now)}
    recently_asked = {a.user_id for a in Attendance.query.filter(
        Attendance.prompted_at > _utcnow_naive() - ATTENDANCE_DM_GAP)}
    out = []
    users = (User.query.filter(User.id.in_(candidates - recently_asked), User.discord_user_id.isnot(None),
                               User.is_active.is_(True)).all() if candidates - recently_asked else [])
    import notify
    for user in users:
        if not notify.wants_dm(user, 'attendance'):
            continue
        pending = pending_attendance(user, include_prompted=False)[:5]
        if pending:
            out.append({'discord_user_id': user.discord_user_id, 'name': user.name,
                        'screenings': [_screening_item(s) for s in pending]})
    return jsonify(out)


@app.route('/api/internal/notifications/dm')
@require_internal
def internal_notification_dms():
    """Alerts the bot should DM now, bundled per person."""
    import notify
    return jsonify(notify.pending_dms())


@app.route('/api/internal/notifications/dm-sent', methods=['POST'])
@require_internal
def internal_notification_dm_sent():
    """The bot DMed these (or couldn't — DMs closed): don't send them again."""
    ids = [i for i in (request.json or {}).get('ids') or [] if isinstance(i, int)]
    if ids:
        Notification.query.filter(Notification.id.in_(ids)).update(
            {'discord_at': _utcnow_naive()}, synchronize_session=False)
        db.session.commit()
    return jsonify({'marked': len(ids)})


@app.route('/api/internal/notifications/settings', methods=['POST'])
@require_internal
def internal_notification_settings():
    """/notifications in Discord: read (no changes sent) or change your setting."""
    import notify
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    if data.get('channels') or data.get('types'):
        notify.set_prefs(user, data)
    if isinstance(data.get('digest_mentions'), bool):       # "mention me in the Monday digest"
        set_share_pref(user, 'watchlist', 'always' if data['digest_mentions'] else 'never')
    if isinstance(data.get('remove_search'), int):           # "stop alerts for" a saved search
        SavedSearch.query.filter_by(id=data['remove_search'], user_id=user.id).delete()
    db.session.commit()
    return jsonify(_notify_settings(user))


@app.route('/api/internal/attendance/prompted', methods=['POST'])
@require_internal
def internal_attendance_prompted():
    """The bot asked about these (DM sent, or DMs were closed): never re-ask."""
    data = request.json or {}
    user = User.query.filter_by(discord_user_id=str(data.get('discord_user_id') or '')).first()
    if not user:
        return jsonify({'error': 'no_account'}), 404
    now = _utcnow_naive()
    for sid in {i for i in data.get('showtime_ids') or [] if isinstance(i, int)}:
        row = Attendance.query.filter_by(user_id=user.id, showtime_id=sid).first() \
            or Attendance(user_id=user.id, showtime_id=sid)
        row.prompted_at = now
        db.session.add(row)
    db.session.commit()
    return jsonify({'ok': True})


@app.route('/api/internal/attendance', methods=['POST'])
@require_internal
def internal_attendance_set():
    """A Went / Didn't-go button press from Discord."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    showtime, err = set_attendance(user, data.get('showtime_id'), data.get('status'), 'discord')
    if err:
        return err
    return jsonify(_screening_item(showtime, data.get('status')))


@app.route('/api/internal/history')
@require_internal
def internal_history():
    """Watch history for /history: someone else's (member_discord_id) or the
    caller's own. Only what they saw — RSVPs count from this group."""
    group_id = request.args.get('group_id', type=int)
    other = request.args.get('member_discord_id')
    if other:
        user = User.query.filter_by(discord_user_id=str(other)).first()
        if not user or not user.is_active or not on_discord(user):
            return jsonify({'error': 'no_account'}), 404
    else:
        user, err = resolve_discord_user(request.args)
        if err:
            return err
    items = history_items(user, False, {group_id} if group_id else None)
    return jsonify({'name': user.name, 'items': items})


@app.route('/api/internal/compare')
@require_internal
def internal_compare():
    """/compare @member: where the caller and a member line up (this group's RSVPs)."""
    me, err = resolve_discord_user(request.args)
    if err:
        return err
    other = User.query.filter_by(discord_user_id=str(request.args.get('member_discord_id') or '')).first()
    if not other or not other.is_active or not on_discord(other):
        return jsonify({'error': 'unknown_member'}), 404
    if other.id == me.id:
        return jsonify({'error': 'same_person'}), 400
    group_id = request.args.get('group_id', type=int)
    return jsonify(compare_members(me, other, {group_id} if group_id else set()))


# ─── Quotes (/quote, /wisdom) ─────────────────────────────────────────────────

def _quote_fields(data):
    """Validated text/movie/character from a request. Returns (fields, error)."""
    text = (data.get('text') or '').strip()
    if not text:
        return None, (jsonify({'error': 'The quote is empty'}), 400)
    if len(text) > 2000:   # Discord's message limit — the bot posts the line as-is
        return None, (jsonify({'error': "Quotes can't be longer than a Discord message (2,000 characters)"}), 400)
    return {'text': text,
            'movie': (data.get('movie') or '').strip()[:200] or None,
            'character': (data.get('character') or '').strip()[:200] or None}, None


def _duplicate_quote(text, exclude_id=None):
    q = Quote.query.filter(Quote.deleted_at.is_(None), db.func.lower(Quote.text) == text.lower())
    if exclude_id:
        q = q.filter(Quote.id != exclude_id)
    return q.first()


@app.route('/api/internal/quotes')
@require_internal
def internal_quotes():
    """Active quotes. With `q`: a search over text, movie and character (for
    /quote find and autocomplete). Without: the whole list, which the bot caches.
    `newest=1` puts recent additions first."""
    q = (request.args.get('q') or '').strip()
    limit = min(request.args.get('limit', 5000, type=int), 5000)
    query = Quote.query.filter(Quote.deleted_at.is_(None))
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Quote.text.ilike(like), Quote.movie.ilike(like),
                                    Quote.character.ilike(like)))
    order = Quote.id.desc() if request.args.get('newest') else Quote.id
    return jsonify([row.to_dict() for row in query.order_by(order).limit(limit)])


@app.route('/api/internal/quotes/<int:quote_id>')
@require_internal
def internal_quote(quote_id):
    quote = db.session.get(Quote, quote_id)
    if not quote or quote.deleted_at:
        return jsonify({'error': 'Quote not found'}), 404
    return jsonify(quote.to_dict())


@app.route('/api/internal/quotes', methods=['POST'])
@require_internal
def internal_quote_add():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    fields, err = _quote_fields(data)
    if err:
        return err
    dupe = _duplicate_quote(fields['text'])
    if dupe:
        return jsonify({'error': 'duplicate', 'id': dupe.id}), 409
    quote = Quote(**fields, added_by=user.id)
    db.session.add(quote)
    db.session.commit()
    return jsonify(quote.to_dict()), 201


@app.route('/api/internal/quotes/<int:quote_id>', methods=['PUT'])
@require_internal
def internal_quote_edit(quote_id):
    """Any member can correct a quote or its source; the last editor is kept."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    quote = db.session.get(Quote, quote_id)
    if not quote or quote.deleted_at:
        return jsonify({'error': 'Quote not found'}), 404
    fields, err = _quote_fields(data)
    if err:
        return err
    dupe = _duplicate_quote(fields['text'], exclude_id=quote.id)
    if dupe:
        return jsonify({'error': 'duplicate', 'id': dupe.id}), 409
    for key, value in fields.items():
        setattr(quote, key, value)
    quote.updated_by, quote.updated_at = user.id, _utcnow_naive()
    db.session.commit()
    return jsonify(quote.to_dict())


@app.route('/api/internal/quotes/<int:quote_id>', methods=['DELETE'])
@require_internal
def internal_quote_remove(quote_id):
    """Removable by whoever added it, or a server admin (the bot sends is_admin
    for members with Manage Server) — so nobody can wipe the list on a whim.
    Soft delete: the row stays, recoverable."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    quote = db.session.get(Quote, quote_id)
    if not quote or quote.deleted_at:
        return jsonify({'error': 'Quote not found'}), 404
    if quote.added_by != user.id and not data.get('is_admin'):
        owner = quote.author.name if quote.author else 'the original list'
        return jsonify({'error': 'not_yours', 'added_by': owner}), 403
    quote.deleted_at, quote.deleted_by = _utcnow_naive(), user.id
    db.session.commit()
    return jsonify({'removed': quote.id})


@app.route('/api/internal/quotes/seed', methods=['POST'])
@require_internal
def internal_quotes_seed():
    """One-time import of the bot's built-in list (bot/quotes.py), sent by the
    bot at startup. It only runs while the table is completely empty, so it can
    never resurrect removed quotes or duplicate edited ones."""
    if Quote.query.first():
        return jsonify({'seeded': 0, 'skipped': []})
    seen, skipped = set(), []
    for item in (request.json or {}).get('quotes') or []:
        fields, err = _quote_fields(item)
        if not fields or fields['text'].lower() in seen:
            skipped.append((item.get('text') or '')[:60])
            continue
        seen.add(fields['text'].lower())
        db.session.add(Quote(**fields))
    db.session.commit()
    return jsonify({'seeded': len(seen), 'skipped': skipped})


# Keys the bot may store; anything else is rejected.
BOT_SETTING_KEYS = {'llm_primary', 'llm_fallback'}


@app.route('/api/internal/ai/chat', methods=['POST'])
@require_internal
def internal_ai_chat():
    """The bot's chatbot: {messages, max_tokens} → {text}; 429 with retry_after
    when the daily token cap is spent; 503 when no model can answer."""
    ai = _ai()
    data = request.json or {}
    try:
        text = ai.chat(data.get('messages') or [], max_tokens=min(int(data.get('max_tokens') or 300), 2000))
    except ai.RateLimited as e:
        return jsonify({'error': 'rate_limited', 'retry_after': e.retry_after_sec}), 429
    except ai.Unavailable as e:
        return jsonify({'error': 'unavailable', 'detail': str(e)}), 503
    except Exception as e:
        print(f'ai chat failed: {e}')
        return jsonify({'error': 'failed', 'detail': str(e)[:200]}), 502
    return jsonify({'text': text})


@app.route('/api/internal/ai/status')
@require_internal
def internal_ai_status():
    ai = _ai()
    s = ai.status()
    if not s['primary']:
        s = ai.refresh('first use')
    return jsonify(s)


@app.route('/api/internal/ai/refresh', methods=['POST'])
@require_internal
def internal_ai_refresh():
    """Re-pick models now (e.g. after /llm changes an override)."""
    return jsonify(_ai().refresh((request.json or {}).get('reason') or 'requested'))


@app.route('/api/internal/settings')
@require_internal
def internal_settings():
    keys = [k for k in (request.args.get('keys') or '').split(',') if k in BOT_SETTING_KEYS]
    rows = {r.key: r.value for r in BotSetting.query.filter(BotSetting.key.in_(keys)).all()} if keys else {}
    return jsonify({k: rows.get(k, '') for k in keys})


@app.route('/api/internal/settings', methods=['POST'])
@require_internal
def internal_settings_update():
    data = request.json or {}
    key, value = data.get('key'), (data.get('value') or '').strip()[:200]
    if key not in BOT_SETTING_KEYS:
        return jsonify({'error': 'Unknown setting'}), 400
    row = db.session.get(BotSetting, key) or BotSetting(key=key)
    row.value = value
    db.session.add(row)
    db.session.commit()
    return jsonify({key: value})

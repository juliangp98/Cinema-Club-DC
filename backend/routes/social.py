"""Club activity: the feed, reactions, comments.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
from app import (Attendance, CINEMA_EMOJIS, DiscordDeletion, FEED_PAGE, Group, GroupMembership, KernelGift, Message, Movie,
    Poll, PollVote, RSVP, Reaction, Showtime, ShowtimeThread, User, Watchlist, _as_int, _brief_user,
    _screening_item, _utcnow_naive, _with_attendance, app, can_share, current_user, datetime, db, face,
    jsonify, next_showings, public_reactions, request, require_auth, require_group_member, require_role,
    share_prefs, timedelta, timezone, utc_iso)


def parse_utc(value):
    """Inverse of utc_iso for query params: naive UTC, comparable with columns."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt


# ─── Feed ─────────────────────────────────────────────────────────────────────
# Built straight from the source tables (RSVPs, check-ins, comments, reactions,
# watchlists, polls, memberships), so undoing something — an un-RSVP, a removed
# watchlist film — simply drops it, and Discord activity shows up like any other.
# Activity is grouped into one card per screening / film / poll / day of joins,
# ordered by its latest activity.

FEED_DAYS = 90


def _feed_user(u):
    return {'id': u.id, 'name': u.name, **face(u), 'discord_only': u.email is None}


def _went_visible_in(group_id, rows):
    """Check-ins aren't per group, so a "went" shows in a group's feed only if the
    RSVP was made there, or there was no RSVP anywhere (logged directly) — a
    check-in never reveals plans made in another group."""
    if not rows:
        return []
    pairs = {(r.user_id, r.showtime_id) for r in rows}
    rsvp_groups = {}
    for r in RSVP.query.filter(RSVP.user_id.in_({p[0] for p in pairs}),
                               RSVP.showtime_id.in_({p[1] for p in pairs})):
        rsvp_groups.setdefault((r.user_id, r.showtime_id), set()).add(r.group_id)
    return [r for r in rows if (r.user_id, r.showtime_id) not in rsvp_groups
            or group_id in rsvp_groups[(r.user_id, r.showtime_id)]]


def feed_events(group_id, since):
    """(kind, card_key, at, user_id, detail) for the group's activity since `since`."""
    member_ids = {m.user_id for m in GroupMembership.query.filter_by(group_id=group_id, status='active')}
    ev = []
    for r in RSVP.query.filter(RSVP.group_id == group_id, RSVP.status.in_(('going', 'maybe')),
                               RSVP.updated_at >= since):
        ev.append(('rsvp', f's{r.showtime_id}', r.updated_at, r.user_id, r.status))
    for m in Message.query.filter(Message.group_id == group_id, Message.created_at >= since):
        ev.append(('comment', f's{m.showtime_id}', m.created_at, m.user_id, None))
    for r in Reaction.query.filter(Reaction.group_id == group_id, Reaction.created_at >= since):
        ev.append(('reaction', f's{r.showtime_id}', r.created_at, r.user_id, r.emoji))
    if member_ids:
        went = Attendance.query.filter(Attendance.user_id.in_(member_ids), Attendance.status == 'went',
                                       Attendance.answered_at >= since).all()
        for a in _went_visible_in(group_id, went):
            ev.append(('went', f's{a.showtime_id}', a.answered_at, a.user_id, None))
        for w in Watchlist.query.filter(Watchlist.user_id.in_(member_ids), Watchlist.created_at >= since):
            ev.append(('watch', f'w{w.movie_id}', w.created_at, w.user_id, None))
    for g in KernelGift.query.filter(KernelGift.group_id == group_id, KernelGift.amount != 0,
                                     KernelGift.updated_at >= since):
        if g.recipient_id in member_ids:
            ev.append(('kernels', f's{g.showtime_id}', g.updated_at, g.giver_id,
                       {'to': g.recipient_id, 'amount': g.amount}))
    for m in GroupMembership.query.filter(GroupMembership.group_id == group_id, GroupMembership.status == 'active',
                                          GroupMembership.joined_at >= since):
        ev.append(('joined', f'j{m.joined_at.date().isoformat()}', m.joined_at, m.user_id, None))
    group = db.session.get(Group, group_id)
    if group and group.bingo_enabled and member_ids:          # repertory bingo (R10e)
        import bingo
        ev += bingo.feed_events(group_id, member_ids, since)
    if group and group.notes_enabled:                         # screening notes (R10f)
        import notes
        ev += notes.feed_events(group_id, member_ids, since)
    ev = [e for e in ev if e[3] in member_ids]   # people who've since left drop out
    for p in Poll.query.filter_by(group_id=group_id):
        for kind, at in (('poll_opened', p.created_at), ('poll_closed', p.closed_at), ('poll_scored', p.scored_at)):
            if at and at >= since:
                ev.append((kind, f'p{p.id}', at, p.created_by, None))
    return ev, member_ids


FEED_TYPES = {                 # ?type= on the feed page
    'screenings': lambda c: c['key'][0] == 's',
    'kernels': lambda c: c['key'][0] == 's' and any(e[0] == 'kernels' for e in c['events']),
    'watchlists': lambda c: c['key'][0] == 'w',
    'polls': lambda c: c['key'][0] == 'p',
    'recaps': lambda c: c['key'][0] == 'r',
    'joins': lambda c: c['key'][0] == 'j',
    'games': lambda c: c['key'][0] == 'b',
}


def _local_to_utc(dt):
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _recap_skeletons(events, since):
    """One "last week in the club" card each Monday (R10c), placed at Monday
    midnight and holding that week's events — only for weeks with any."""
    today = datetime.now().date()
    monday = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time())
    out = []
    for weeks_back in range(FEED_DAYS // 7 + 1):
        end = monday - timedelta(days=7 * weeks_back)
        start_utc, end_utc = _local_to_utc(end - timedelta(days=7)), _local_to_utc(end)
        if end_utc < since:
            break
        week = [e for e in events if start_utc <= e[2] < end_utc]
        if week:
            out.append({'key': f'r{end.date().isoformat()}', 'at': end_utc, 'events': week})
    return out


def feed_skeletons(group_id, kind=None):
    """Cards (key, latest activity time, their events), newest first —
    optionally only one FEED_TYPES kind."""
    since = _utcnow_naive() - timedelta(days=FEED_DAYS)
    events, member_ids = feed_events(group_id, since)
    cards = {}
    for e in events:
        cards.setdefault(e[1], {'key': e[1], 'events': []})['events'].append(e)
    for c in cards.values():
        c['events'].sort(key=lambda e: e[2], reverse=True)
        c['at'] = c['events'][0][2]
    out = list(cards.values()) + _recap_skeletons(events, since)
    if kind in FEED_TYPES:
        out = [c for c in out if FEED_TYPES[kind](c)]
    return sorted(out, key=lambda c: (c['at'], c['key']), reverse=True), member_ids


def _feed_bingo(month, events, users):
    """Who got bingo on a month's card (R10e), newest first; a full card
    supersedes that member's line."""
    best = {}
    for kind, _, at, uid, what in events:
        if uid in users and (uid not in best or what == 'full'):
            best[uid] = (what, at)
    if not best:
        return None
    rows = sorted(best.items(), key=lambda kv: kv[1][1], reverse=True)
    return {'type': 'bingo', 'month': month,
            'month_label': datetime.strptime(month, '%Y-%m').strftime('%B'),
            'winners': [{'user': _feed_user(users[uid]), 'kind': what} for uid, (what, _) in rows]}


def _feed_recap(group_id, week_of, events, users):
    """Last week in the club: check-ins (and the most-seen screening), crew
    nights, who members gave the most kernels to, polls scored, plans made,
    talk, and who joined. None when the week had nothing worth a card."""
    from app import poll_scores
    went = {}
    for kind, key, _, uid, _ in events:
        if kind == 'went' and uid in users:
            went.setdefault(int(key[1:]), set()).add(uid)
    top = max(went.items(), key=lambda kv: (len(kv[1]), -kv[0]), default=None)
    top_show = db.session.get(Showtime, top[0]) if top else None
    gifts = {}
    for kind, _, _, _, detail in events:
        if kind == 'kernels' and detail['to'] in users:
            gifts[detail['to']] = gifts.get(detail['to'], 0) + detail['amount']
    polls = []
    for kind, key, _, _, _ in events:
        p = db.session.get(Poll, int(key[1:])) if kind == 'poll_scored' else None
        if p:
            board = poll_scores(p)
            polls.append({'id': p.id, 'title': p.title, 'winner': board[0]['user'].name if board else None})
    joined = list(dict.fromkeys(uid for kind, _, _, uid, _ in events if kind == 'joined' and uid in users))
    bingos = list(dict.fromkeys(uid for kind, _, _, uid, _ in events if kind == 'bingo' and uid in users))
    recap = {
        'week_of': week_of,
        'checkins': sum(len(v) for v in went.values()),
        'people_out': len(set().union(*went.values())) if went else 0,
        'top': {'screening': _screening_item(top_show), 'users': [_feed_user(users[u]) for u in top[1]]}
               if top_show and top_show.movie else None,
        'crew_nights': sum(1 for v in went.values() if len(v) >= 3),
        'kernels': [{'user': _feed_user(users[u]), 'amount': n}
                    for u, n in sorted(gifts.items(), key=lambda kv: -kv[1]) if n > 0][:3],
        'polls': polls,
        'plans': sum(1 for e in events if e[0] == 'rsvp' and e[4] == 'going'),
        'comments': sum(1 for e in events if e[0] == 'comment'),
        'joined': [_feed_user(users[u]) for u in joined],
        'bingo': [_feed_user(users[u]) for u in bingos],
    }
    if not any((recap['checkins'], recap['kernels'], polls, recap['plans'], recap['comments'], joined, bingos)):
        return None
    return {'type': 'recap', 'recap': recap}


def _feed_screening(viewer, group_id, sid, events, users, member_ids):
    s = db.session.get(Showtime, sid)
    if not s or not s.movie:
        return None
    showtime = _with_attendance(viewer, [s], [
        s.to_dict(user_id=viewer.id, group_id=group_id, user_genres=viewer.favorite_genres)], group_id)[0]
    went_rows = [a for a in Attendance.query.filter_by(showtime_id=sid, status='went') if a.user_id in member_ids]
    went_ids = [a.user_id for a in _went_visible_in(group_id, went_rows)]
    went = User.query.filter(User.id.in_(went_ids)).all() if went_ids else []
    last = (Message.query.filter_by(showtime_id=sid, group_id=group_id)
            .order_by(Message.created_at.desc()).first())
    activity, seen = [], set()
    for kind, _, at, uid, detail in events:
        to = detail['to'] if kind == 'kernels' else None
        if (uid, kind, to) in seen or uid not in users or (to and to not in users):
            continue
        seen.add((uid, kind, to))
        if kind == 'kernels':
            detail = {'to': _feed_user(users[to]), 'amount': detail['amount']}
        activity.append({'kind': kind, 'user': _feed_user(users[uid]), 'detail': detail, 'at': utc_iso(at)})
    return {'type': 'screening', 'showtime': showtime, 'went': [_feed_user(u) for u in went],
            'latest_comment': {'user': _feed_user(last.user), 'body': last.body[:280],
                               'at': utc_iso(last.created_at)} if last else None,
            'activity': activity[:4], 'kernels': _card_kernels(viewer, group_id, sid),
            'letterboxd': _letterboxd_ratings(went, sid), 'notes': _card_notes(group_id, sid, member_ids)}


def _card_notes(group_id, sid, member_ids):
    import notes
    return notes.card(db.session.get(Group, group_id), sid, member_ids)


def _letterboxd_ratings(went, sid):
    """Ratings members who went chose to show with their check-ins (R10f)."""
    import letterboxd
    rated = letterboxd.ratings([u.id for u in went], sid)
    by_id = {u.id: u for u in went}
    return [{'user': _feed_user(by_id[uid]), **r} for uid, r in rated.items()]


def _card_kernels(viewer, group_id, sid):
    """Who on this screening can get kernels from the viewer (R10b): each
    member with activity here (not you), what they did, their kernels from
    members on it, and what you've given them this week."""
    import kernels
    people = kernels.card_people(group_id, sid)
    people.pop(viewer.id, None)
    if not people:
        return {'people': []}
    counts = kernels.card_kernels(group_id, sid, viewer.id)
    users = {u.id: u for u in User.query.filter(User.id.in_(list(people)))}
    return {'people': [{'user': _feed_user(users[uid]), 'did': did, 'net': counts['net'].get(uid, 0),
                        'mine': counts['mine'].get(uid, 0)} for uid, did in people.items() if uid in users]}


def _feed_watchlist(viewer, movie_id, events, users, member_ids):
    movie = db.session.get(Movie, movie_id)
    if not movie:
        return None
    adders = list(dict.fromkeys(e[3] for e in events if e[3] in users))
    nxt = next_showings({movie_id}).get(movie_id)
    return {'type': 'watchlist',
            'movie': {'id': movie.id, 'title': movie.title, 'release_year': movie.release_year,
                      'poster_url': movie.poster_url},
            'users': [_feed_user(users[u]) for u in adders],
            'wanters': Watchlist.query.filter(Watchlist.movie_id == movie_id,
                                              Watchlist.user_id.in_(member_ids)).count() if member_ids else 0,
            'viewer_wants': Watchlist.query.filter_by(user_id=viewer.id, movie_id=movie_id).first() is not None,
            'next': _screening_item(nxt) if nxt else None}


def _feed_poll(viewer, poll_id):
    p = db.session.get(Poll, poll_id)
    if not p:
        return None
    cat_ids = [c.id for c in p.categories]
    voters = {v.user_id for v in PollVote.query.filter(PollVote.category_id.in_(cat_ids))} if cat_ids else set()
    return {'type': 'poll',
            'poll': {'id': p.id, 'title': p.title, 'status': p.status, 'poll_type': p.poll_type,
                     'categories': len(cat_ids), 'creator': p.creator.name if p.creator else None},
            'voters': len(voters), 'you_voted': viewer.id in voters}


def hydrate_feed(viewer, group_id, skeletons, member_ids):
    uids = {e[3] for c in skeletons for e in c['events']} | \
        {e[4]['to'] for c in skeletons for e in c['events'] if e[0] == 'kernels'}
    users = {u.id: u for u in User.query.filter(User.id.in_(uids))} if uids else {}
    out = []
    for c in skeletons:
        kind, ref = c['key'][0], c['key'][1:]
        if kind == 's':
            card = _feed_screening(viewer, group_id, int(ref), c['events'], users, member_ids)
        elif kind == 'w':
            card = _feed_watchlist(viewer, int(ref), c['events'], users, member_ids)
        elif kind == 'p':
            card = _feed_poll(viewer, int(ref))
        elif kind == 'r':
            card = _feed_recap(group_id, ref, c['events'], users)
        elif kind == 'b':
            card = _feed_bingo(ref, c['events'], users)
        else:
            joined = list(dict.fromkeys(e[3] for e in c['events'] if e[3] in users))
            card = {'type': 'joined', 'users': [_feed_user(users[u]) for u in joined]}
        if card:
            out.append({'key': c['key'], 'at': utc_iso(c['at']), **card})
    return out


@app.route('/api/feed')
@require_auth
def feed():
    """The group's recent activity as cards, FEED_PAGE at a time (?offset=;
    ?type= one of FEED_TYPES)."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    offset = max(0, request.args.get('offset', 0, type=int))
    skeletons, member_ids = feed_skeletons(group_id, request.args.get('type'))
    page = skeletons[offset:offset + FEED_PAGE]
    more = len(skeletons) > offset + FEED_PAGE
    import kernels
    viewer = current_user()
    return jsonify({'cards': hydrate_feed(viewer, group_id, page, member_ids),
                    'next_offset': offset + FEED_PAGE if more else None, 'days': FEED_DAYS,
                    'allowance': kernels.allowance(viewer.id)})


@app.route('/api/notes', methods=['GET', 'POST'])
@require_auth
def screening_notes():
    """A screening's notes (R10f): GET ?showtime_id=&group_id=; POST {group_id,
    showtime_id, tag} adds or removes one of yours (once you've checked in)."""
    import notes
    data = (request.json or {}) if request.method == 'POST' else request.args
    group_id, showtime_id = _as_int(data.get('group_id')), _as_int(data.get('showtime_id'))
    err = require_group_member(group_id)
    if err:
        return err
    group, user = db.session.get(Group, group_id), current_user()
    if request.method == 'GET':
        return jsonify(notes.view(group, user, showtime_id))
    result, error = notes.toggle(group, user, showtime_id, data.get('tag'))
    if error:
        return jsonify({'error': error}), 400
    return jsonify(result)


@app.route('/api/kernels/toss', methods=['POST'])
@require_auth
def toss_kernel():
    """Give (+1) or take (−1) a kernel for a member's activity on a screening
    (R10b): {group_id, showtime_id, user_id, delta}. The opposite undoes one."""
    import kernels
    data = request.json or {}
    group_id, showtime_id, user_id = (_as_int(data.get(k)) for k in ('group_id', 'showtime_id', 'user_id'))
    err = require_group_member(group_id)
    if err:
        return err
    from sqlalchemy.exc import IntegrityError
    viewer = current_user()
    for attempt in (1, 2):                  # two quick taps can both create the week's row: retry once
        row, error = kernels.toss(viewer, user_id, group_id, showtime_id, _as_int(data.get('delta')))
        if error:
            return jsonify({'error': error}), 400
        try:
            db.session.commit()
            break
        except IntegrityError:
            db.session.rollback()
            if attempt == 2:
                return jsonify({'error': 'Try that again.'}), 409
    counts = kernels.card_kernels(group_id, showtime_id, viewer.id)
    return jsonify({'user_id': user_id, 'mine': row.amount, 'net': counts['net'].get(user_id, 0),
                    'allowance': kernels.allowance(viewer.id)})


@app.route('/api/kernels')
@require_auth
def my_kernels():
    """Your kernels (in a club with ?group_id=, else across them) and what's
    left of this week's allowance to give and take."""
    import kernels
    group_id = request.args.get('group_id', type=int)
    if group_id:
        err = require_group_member(group_id)
        if err:
            return err
    viewer = current_user()
    k = kernels.breakdown(viewer.id, group_id)
    return jsonify({**k, 'allowance': kernels.allowance(viewer.id),
                    'rules': kernels.rules(group_id)})


@app.route('/api/club/week')
@require_auth
def club_week():
    """Discover's "This week in the club" strip: screenings members are going
    to in the next 7 days (most-attended first), open polls, and how many
    comments others left this week (with the latest)."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    viewer, now = current_user(), datetime.now()
    rows = (db.session.query(RSVP, Showtime).join(Showtime, RSVP.showtime_id == Showtime.id)
            .filter(RSVP.group_id == group_id, RSVP.status == 'going',
                    Showtime.start_time >= now, Showtime.start_time <= now + timedelta(days=7)).all())
    by_show = {}
    for r, s in rows:
        by_show.setdefault(s.id, (s, []))[1].append(r.user)
    plans = sorted(by_show.values(), key=lambda x: (-len(x[1]), x[0].start_time))[:4]

    polls = Poll.query.filter_by(group_id=group_id, status='open').order_by(Poll.created_at.desc()).limit(3).all()
    open_polls = []
    for p in polls:
        cat_ids = [c.id for c in p.categories]
        voted = bool(cat_ids) and PollVote.query.filter(PollVote.category_id.in_(cat_ids),
                                                        PollVote.user_id == viewer.id).first() is not None
        open_polls.append({'id': p.id, 'title': p.title, 'you_voted': voted})

    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=7)
    recent = (Message.query.filter(Message.group_id == group_id, Message.user_id != viewer.id,
                                   Message.created_at >= since)
              .order_by(Message.created_at.desc()))
    latest = recent.first()
    return jsonify({
        'plans': [{'showtime_id': s.id, 'start_time': s.start_time.isoformat(),
                   'movie': {'id': s.movie.id, 'title': s.movie.title, 'poster_url': s.movie.poster_url},
                   'theatre': s.theatre.short_name or s.theatre.name,
                   'going': [_brief_user(u) for u in users], 'you_going': any(u.id == viewer.id for u in users)}
                  for s, users in plans],
        'polls': open_polls,
        'comments': {'count': recent.count(),
                     'latest': {'showtime_id': latest.showtime_id, 'movie': db.session.get(Showtime, latest.showtime_id).movie.title,
                                'user': latest.user.name, 'body': latest.body[:140]} if latest else None},
    })


# ─── Routes: Reactions ────────────────────────────────────────────────────────

@app.route('/api/reactions', methods=['POST'])
@require_auth
def toggle_reaction():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    group_id = _as_int(data.get('group_id'))
    emoji = data.get('emoji')
    if group_id:                       # no club: a personal reaction, public only as a count (R5b)
        _, err = require_role(user, group_id, 'member')
        if err:
            return err

    if not showtime_id or not emoji:
        return jsonify({'error': 'showtime_id and emoji required'}), 400
    if not db.session.get(Showtime, _as_int(showtime_id) or 0):
        return jsonify({'error': 'Showtime not found'}), 404

    if emoji not in CINEMA_EMOJIS:
        return jsonify({'error': 'Invalid emoji'}), 400

    existing = Reaction.query.filter_by(
        user_id=user.id, showtime_id=showtime_id, group_id=group_id, emoji=emoji
    ).first()

    if existing:
        db.session.delete(existing)
    else:
        reaction = Reaction(user_id=user.id, showtime_id=showtime_id, group_id=group_id, emoji=emoji)
        db.session.add(reaction)
    db.session.commit()

    if not group_id:
        return jsonify(public_reactions([_as_int(showtime_id)], user).get(_as_int(showtime_id), {}))
    # Return updated reactions for this showtime+group
    reactions = Reaction.query.filter_by(showtime_id=showtime_id, group_id=group_id).all()
    summary = {}
    for r in reactions:
        if r.emoji not in summary:
            summary[r.emoji] = {'count': 0, 'users': [], 'user_reacted': False}
        summary[r.emoji]['count'] += 1
        summary[r.emoji]['users'].append({'id': r.user.id, 'name': r.user.name})
        if r.user_id == user.id:
            summary[r.emoji]['user_reacted'] = True

    return jsonify(summary)


@app.route('/api/reactions')
@require_auth
def get_reactions():
    showtime_id = request.args.get('showtime_id', type=int)
    group_id = request.args.get('group_id', type=int)
    user = current_user()
    err = require_group_member(group_id)
    if err:
        return err

    if not showtime_id:
        return jsonify({'error': 'showtime_id required'}), 400

    reactions = Reaction.query.filter_by(showtime_id=showtime_id, group_id=group_id).all()
    summary = {}
    for r in reactions:
        if r.emoji not in summary:
            summary[r.emoji] = {'count': 0, 'users': [], 'user_reacted': False}
        summary[r.emoji]['count'] += 1
        summary[r.emoji]['users'].append({'id': r.user.id, 'name': r.user.name})
        if r.user_id == user.id:
            summary[r.emoji]['user_reacted'] = True

    return jsonify(summary)


# ─── Routes: Messages ─────────────────────────────────────────────────────────

@app.route('/api/messages')
@require_auth
def get_messages():
    showtime_id = request.args.get('showtime_id', type=int)
    group_id = request.args.get('group_id', type=int)
    since = request.args.get('since')
    err = require_group_member(group_id)
    if err:
        return err

    if not showtime_id:
        return jsonify({'error': 'showtime_id required'}), 400

    query = Message.query.filter_by(showtime_id=showtime_id, group_id=group_id)
    since_dt = parse_utc(since) if since else None
    if since_dt:
        query = query.filter(Message.created_at > since_dt)

    messages = query.order_by(Message.created_at.asc()).limit(100).all()
    viewer = current_user()
    return jsonify([_message_dict(m, viewer) for m in messages])


def _message_dict(m, viewer):
    return {
        'id': m.id,
        'user': {'id': m.user.id, 'name': m.user.name, **face(m.user)},
        'body': m.body,
        'created_at': utc_iso(m.created_at),
        'via_discord': m.source in ('discord', 'discord_bot'),
        'can_delete': m.user_id == viewer.id and m.deletable_on_site,
    }


@app.route('/api/messages', methods=['POST'])
@require_auth
def post_message():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    group_id = _as_int(data.get('group_id'))
    body = (data.get('body') or '').strip()
    _, err = require_role(user, group_id, 'member')
    if err:
        return err

    if not showtime_id or not body:
        return jsonify({'error': 'showtime_id and body required'}), 400

    if len(body) > 2000:
        return jsonify({'error': 'Message too long'}), 400

    if not db.session.get(Showtime, _as_int(showtime_id)):
        return jsonify({'error': 'Showtime not found'}), 404
    # source='site' queues it for the screening's Discord thread — only if it
    # has one, the writer is in the club's server, and they left "also post in
    # Discord" on (R3d).
    to_discord = data.get('to_discord')
    if not isinstance(to_discord, bool):
        to_discord = share_prefs(user)['comment'] != 'never'
    to_discord = to_discord and can_share(user, _as_int(group_id))
    msg = Message(user_id=user.id, showtime_id=showtime_id, group_id=group_id, body=body, source='site',
                  to_discord=to_discord)
    db.session.add(msg)
    db.session.commit()
    return jsonify(_message_dict(msg, user)), 201


@app.route('/api/messages/<int:message_id>', methods=['DELETE'])
@require_auth
def delete_message(message_id):
    """Delete your own comment. If it has a copy in the Discord thread, the bot
    removes that too. Comments typed in Discord are deleted there instead."""
    user = current_user()
    msg = db.session.get(Message, message_id)
    if not msg or msg.user_id != user.id:
        return jsonify({'error': 'Not found'}), 404
    if not msg.deletable_on_site:
        return jsonify({'error': 'This was posted in Discord — delete it there.'}), 400
    if msg.discord_message_id:
        thread = ShowtimeThread.query.filter_by(showtime_id=msg.showtime_id, group_id=msg.group_id).first()
        if thread:
            db.session.add(DiscordDeletion(thread_id=thread.thread_id, discord_message_id=msg.discord_message_id))
    db.session.delete(msg)
    db.session.commit()
    return jsonify({'deleted': message_id})

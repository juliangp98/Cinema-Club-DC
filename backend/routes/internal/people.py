"""People, for the bot: profiles, the server's members, kernels, the
leaderboard, comparing members, history and "did you go?".
"""
import taste
from app import (ATTENDANCE_LOOKBACK, Attendance, Group, IntegrityError, RSVP, Showtime, User,
    Watchlist, _as_int, _screening_item, _update_profile_fields, _utcnow_naive, app, build_leaderboard,
    compare_members, db, history_items, jsonify, on_discord, pending_attendance, present_user_ids, request,
    set_attendance, timedelta)
from routes.internal.common import _discord_member, request_group, require_internal, resolve_discord_user


@app.route('/api/internal/club')
@require_internal
def internal_club():
    """/club: the club at a glance (the Club page's Overview) — who's in it
    (members in the server by name; the rest counted), its theatres, and the
    month's numbers."""
    import club_stats
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    members = [m.user for m in group.memberships if m.status == 'active' and m.user and m.user.is_active]
    shown = present_user_ids(group.id)
    named = sorted((u.name for u in members if u.id in shown), key=str.lower)
    import places
    slugs = places.club_slugs(group)
    theatres = [t for t in places.theatres_in() if t.slug in slugs]
    o = club_stats.overview(group)
    o.pop('members', None)
    o['top'] = [{'name': r['user']['name'], 'kernels': r['kernels'], 'place': r['place']} for r in o['top'] if r['user']['id'] in shown]
    return jsonify({'name': group.name, 'emoji': group.emoji, 'description': group.description or '',
                    'members': len(members), 'named': named, 'on_site': len(members) - len(named),
                    'theatres': [{'slug': t.slug, 'name': t.name, 'short_name': t.short_name or t.name} for t in theatres],
                    **o})


@app.route('/api/internal/leaderboard')
@require_internal
def internal_leaderboard():
    """/leaderboard: members in the club's server, with their real place;
    `hidden` counts the members on the site."""
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    shown_ids = present_user_ids(group.id)
    board = build_leaderboard(group)
    rows = [{'user': {'name': r['user']['name']},
             **{k: r[k] for k in ('place', 'kernels', 'correct', 'attendance', 'breakdown')}}
            for r in board if r['user']['id'] in shown_ids]
    return jsonify({'rows': rows, 'hidden': len(board) - len(rows)})


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
               if m.status == 'active' and m.user and m.user.is_active and on_discord(m.user, group.id)]
    members.sort(key=lambda u: (u.name or '').lower())
    return jsonify([{'id': u.id, 'name': u.name} for u in members])


def _profile_payload(user, own=True):
    import kernels
    import places
    k = kernels.breakdown(user.id)
    upcoming = places.upcoming(RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
                               .filter(RSVP.user_id == user.id, RSVP.status == 'going')).count()
    return {
        'user': user.to_dict(),
        # someone else's taste only if they show it (R13)
        'genres': [{'key': k, 'label': taste.GENRE_LABELS[k]} for k in taste.genres(user)] if own or user.taste_public else [],
        'taste_hidden': not own and not user.taste_public,
        'genre_options': [{'key': k, 'label': label} for k, label in taste.GENRES],
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
        if not user or not user.is_active or not on_discord(user, request_group()):
            return jsonify({'error': 'no_account'}), 404
    else:
        user, err = resolve_discord_user(request.args)
        if err:
            return err
    return jsonify(_profile_payload(user, own=not other))


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


@app.route('/api/internal/kernels/cards')
@require_internal
def internal_kernel_cards():
    """Give kernels on /profile @member: the screenings they did something on
    lately (the feed's cards), what you've given each this week, and your
    allowance."""
    import kernels
    me, err = resolve_discord_user(request.args)
    if err:
        return err
    other = _discord_member(request.args.get('member_discord_id'), request_group())
    group_id = request.args.get('group_id', type=int)
    if not other:
        return jsonify({'error': 'unknown_member'}), 404
    cards = kernels.member_cards(group_id, other.id, me.id)
    return jsonify({'name': other.name, 'user_id': other.id, 'cards': cards, 'allowance': kernels.allowance(me.id)})


@app.route('/api/internal/kernels/toss', methods=['POST'])
@require_internal
def internal_kernel_toss():
    """A +1 / −1 under Give kernels: {discord ident, member_discord_id,
    showtime_id, delta} — the same rules as the feed's buttons."""
    import kernels
    data = request.json or {}
    me, err = resolve_discord_user(data)
    if err:
        return err
    other = _discord_member(data.get('member_discord_id'), request_group())
    if not other:
        return jsonify({'error': 'unknown_member'}), 404
    group_id, showtime_id = _as_int(data.get('group_id')), _as_int(data.get('showtime_id'))
    row, error = kernels.toss(me, other.id, group_id, showtime_id, _as_int(data.get('delta')))
    if error:
        return jsonify({'error': error}), 400
    try:
        db.session.commit()
    except IntegrityError:                  # two quick taps made the week's row twice
        db.session.rollback()
        return jsonify({'error': 'Try that again.'}), 409
    return jsonify({'name': other.name, 'user_id': other.id, 'cards': kernels.member_cards(group_id, other.id, me.id),
                    'allowance': kernels.allowance(me.id), 'showtime_id': showtime_id, 'mine': row.amount})


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


ATTENDANCE_DM_GAP = timedelta(hours=20)   # at most one "did you go?" DM per person per day


@app.route('/api/internal/attendance/prompts')
@require_internal
def internal_attendance_prompts():
    """Who the bot should DM "did you go?" now: members on Discord with
    screenings nobody has asked them about, skipping anyone DMed in the last 20
    hours (so it's at most a daily nudge). Up to 5 screenings each — one DM's
    worth of buttons. Quiet hours are the bot's call."""
    import places
    since = places.now_in() - ATTENDANCE_LOOKBACK - timedelta(days=1)    # pending_attendance trims it per person
    candidates = {r.user_id for r in places.started(RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id).filter(
        RSVP.status == 'going', Showtime.start_time >= since))}
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
            import letterboxd
            hints = letterboxd.suggestions(user, [s.id for s in pending])
            out.append({'discord_user_id': user.discord_user_id, 'name': user.name, 'tz': places.person_zone(user),
                        'screenings': [{**_screening_item(s), 'letterboxd': hints.get(s.id)} for s in pending]})
    return jsonify(out)


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
    """Watch history (History on /profile): someone else's (member_discord_id)
    or the caller's own. Only what they saw — RSVPs count from this group;
    your own also lists the ones you said you missed, to check in again."""
    group_id = request.args.get('group_id', type=int)
    other = request.args.get('member_discord_id')
    if other:
        user = User.query.filter_by(discord_user_id=str(other)).first()
        if not user or not user.is_active or not on_discord(user, request_group()):
            return jsonify({'error': 'no_account'}), 404
    else:
        user, err = resolve_discord_user(request.args)
        if err:
            return err
    own = not other                         # your own lists missed ones too, so you can fix them
    items = history_items(user, own, {group_id} if group_id else None)
    return jsonify({'name': user.name, 'user_id': user.id, 'own': own, 'items': items})


@app.route('/api/internal/compare')
@require_internal
def internal_compare():
    """Compare on /profile @member: where the caller and a member line up (this group's RSVPs)."""
    me, err = resolve_discord_user(request.args)
    if err:
        return err
    other = User.query.filter_by(discord_user_id=str(request.args.get('member_discord_id') or '')).first()
    if not other or not other.is_active or not on_discord(other, request_group()):
        return jsonify({'error': 'unknown_member'}), 404
    if other.id == me.id:
        return jsonify({'error': 'same_person'}), 400
    group_id = request.args.get('group_id', type=int)
    return jsonify({**compare_members(me, other, {group_id} if group_id else set()), 'user_id': other.id})

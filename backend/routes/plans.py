"""Your plans: RSVPs, "did you go?", history, watchlists.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
import app as core
from app import (Movie, RSVP, Showtime, Watchlist, _active_membership, _as_int, _profile_target,
    _screening_item, _with_attendance, app, apply_rsvp, can_share, current_user, datetime, db, history_items,
    jsonify, pending_attendance, public_showtimes, queue_rsvp_share, request, require_auth, require_role,
    set_attendance, set_share_pref, share_prefs, watch_shared)


@app.route('/api/rsvp', methods=['POST'])
@require_auth
def rsvp():
    user = current_user()
    data = request.json or {}
    showtime_id = data.get('showtime_id')
    status = data.get('status')
    group_id = _as_int(data.get('group_id'))
    # No club: a personal RSVP (R5b) — only you ever see it.
    if group_id:
        _, err = require_role(user, group_id, 'member')
        if err:
            return err

    prev = RSVP.query.filter_by(user_id=user.id, showtime_id=showtime_id, group_id=group_id).first()
    prev_status = prev.status if prev else None

    showtime, err = apply_rsvp(user, showtime_id, status, group_id)
    if err:
        return err

    # Going / maybe (a real change) in the Discord server's group: share it if
    # they always do, or ask. (Discord's own /rsvp posts for itself.)
    prompt = False
    if status in ('going', 'maybe') and status != prev_status and showtime and can_share(user, group_id):
        pref = share_prefs(user)['rsvp']
        if pref == 'always':
            queue_rsvp_share(user, showtime.id, group_id)
        elif pref == 'ask':
            prompt = True

    import notify
    ask_attendance = status == 'going' and bool(user.discord_user_id) and notify.ask_once(user, 'attendance')
    if ask_attendance:
        db.session.commit()
    if not group_id:
        return jsonify({**public_showtimes([showtime], user)[0], 'attendance_prompt': ask_attendance})
    d = _with_attendance(user, [showtime], [
        showtime.to_dict(user_id=user.id, group_id=group_id, user_genres=user.favorite_genres)], group_id)[0]
    if prompt and d.get('discord') and not d['discord']['my_share']:
        d['discord']['prompt'] = True
    d['attendance_prompt'] = ask_attendance
    return jsonify(d)


@app.route('/api/attendance/pending')
@require_auth
def attendance_pending():
    """The signed-in member's "Did you make it?" list — each with what their
    Letterboxd diary says, when they connected it and chose "ask" (R10f)."""
    import letterboxd
    user = current_user()
    shows = pending_attendance(user)
    hints = letterboxd.suggestions(user, [s.id for s in shows])
    return jsonify([{**_screening_item(s), 'letterboxd': hints.get(s.id)} for s in shows])


@app.route('/api/attendance', methods=['POST'])
@require_auth
def attendance_set():
    data = request.json or {}
    showtime, err = set_attendance(current_user(), data.get('showtime_id'), data.get('status'), 'site')
    if err:
        return err
    return jsonify({'showtime_id': showtime.id, 'status': data.get('status')})


@app.route('/api/users/<int:user_id>/history')
@require_auth
def user_history(user_id):
    me, target, groups, err = _profile_target(user_id)
    if err:
        return err
    if me.id == target.id:
        return jsonify({'own': True, 'items': history_items(target, True)})
    # Others see RSVP-based attendance only from groups you share.
    return jsonify({'own': False, 'items': history_items(target, False, groups)})


# ─── Routes: Watchlist ────────────────────────────────────────────────────────

@app.route('/api/watchlist', methods=['POST'])
@require_auth
def toggle_watchlist():
    user = current_user()
    movie_id = (request.json or {}).get('movie_id')
    movie = db.session.get(Movie, movie_id) if movie_id else None
    if not movie:
        return jsonify({'error': 'Movie not found'}), 404

    existing = Watchlist.query.filter_by(user_id=user.id, movie_id=movie.id).first()
    prompt = False
    if existing:
        db.session.delete(existing)
        watching = False
    else:
        # The digest may mention it in Discord only if you say so: "always" /
        # "never" decide now; "ask" asks (members in the club's server only).
        pref = share_prefs(user)['watchlist']
        db.session.add(Watchlist(user_id=user.id, movie_id=movie.id,
                                 share_discord={'always': True, 'never': False}.get(pref)))
        prompt = pref == 'ask' and can_share(user, core.DISCORD_GROUP_ID) \
            and _active_membership(user, core.DISCORD_GROUP_ID) is not None
        watching = True
    # The first watchlist add is when to ask how (if at all) to hear about it.
    import notify
    alert_prompt = watching and not user.is_guest and notify.ask_once(user, 'alerts')
    db.session.commit()
    return jsonify({'movie_id': movie.id, 'watching': watching, 'discord_prompt': prompt,
                    'alert_prompt': alert_prompt})


@app.route('/api/watchlist/<int:movie_id>/discord', methods=['PUT'])
@require_auth
def watchlist_discord(movie_id):
    """Answer "mention you in the Discord digest when it's playing?" for one
    film: {share: bool, remember: bool} (remember makes it your choice for all)."""
    user = current_user()
    w = Watchlist.query.filter_by(user_id=user.id, movie_id=movie_id).first()
    if not w:
        return jsonify({'error': 'Not on your watchlist'}), 404
    data = request.json or {}
    w.share_discord = bool(data.get('share'))
    if data.get('remember'):
        set_share_pref(user, 'watchlist', 'always' if w.share_discord else 'never')
    db.session.commit()
    return jsonify({'movie_id': movie_id, 'discord_share': watch_shared(w), 'prefs': share_prefs(user)})


@app.route('/api/watchlist')
@require_auth
def get_watchlist():
    user = current_user()
    now = datetime.now()
    items = []
    for w in Watchlist.query.filter_by(user_id=user.id).all():
        next_st = (Showtime.query
                   .filter(Showtime.movie_id == w.movie_id,
                           Showtime.start_time > now,
                           Showtime.is_cancelled.isnot(True))
                   .order_by(Showtime.start_time).first())
        items.append({
            'movie': w.movie.to_dict() if w.movie else None,
            'added_at': w.created_at.isoformat() if w.created_at else None,
            'discord_share': watch_shared(w),       # may the Discord digest mention you about it
            # Public serializer: the old one listed every club's attendees here.
            'next_showtime': public_showtimes([next_st], user)[0] if next_st else None,
        })
    items.sort(key=lambda i: i['next_showtime']['start_time'] if i['next_showtime'] else '9999')
    return jsonify(items)

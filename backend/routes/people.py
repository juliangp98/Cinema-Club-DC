"""Profiles and pictures (avatars, club pictures).

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
from app import (GroupMembership, User, Watchlist, _profile_target, _screening_item, _upload, app,
    compare_members, current_user, db, guest_blocked, jsonify, next_showings, request, require_auth,
    role_at_least, send_from_directory, upcoming_rsvps)


@app.route('/api/media/<name>')
def get_media(name):
    """An uploaded picture. Names are random and never reused, so they're cached for good."""
    import media
    if not media.NAME_RE.match(name):
        return jsonify({'error': 'Not found'}), 404
    resp = send_from_directory(media.media_dir(app.instance_path), name, mimetype='image/webp', max_age=31536000)
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


def _set_picture(user, kind, url=None, emoji=None):
    """Switch your picture, removing an uploaded photo you no longer use."""
    import media
    old = user.avatar_url
    user.avatar_kind = kind
    user.avatar_url = url if kind == 'photo' else user.discord_avatar_url if kind == 'discord' else None
    user.avatar_emoji = emoji if kind == 'emoji' else None
    if old != user.avatar_url:
        media.delete(app.instance_path, old)


@app.route('/api/me/picture', methods=['POST'])
@require_auth
def upload_my_picture():
    """Upload a photo (multipart 'file'). Guests keep their profile first."""
    user = current_user()
    blocked = guest_blocked(user)
    if blocked:
        return blocked
    url, err = _upload('avatar')
    if err:
        return err
    _set_picture(user, 'photo', url=url)
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route('/api/me/picture', methods=['PUT'])
@require_auth
def choose_my_picture():
    """{kind: 'initials' | 'emoji' (+ emoji) | 'discord'}."""
    import media
    user = current_user()
    data = request.json or {}
    kind = data.get('kind')
    if kind == 'emoji':
        emoji = media.clean_emoji(data.get('emoji'))
        if not emoji:
            return jsonify({'error': 'Pick an emoji.'}), 400
        _set_picture(user, 'emoji', emoji=emoji)
    elif kind == 'discord':
        if not user.discord_avatar_url:
            return jsonify({'error': "There's no Discord picture to use."}), 400
        _set_picture(user, 'discord')
    elif kind == 'initials':
        _set_picture(user, 'initials')
    else:
        return jsonify({'error': 'Unknown choice'}), 400
    db.session.commit()
    return jsonify({'user': user.to_dict()})


@app.route('/api/users/<int:user_id>/profile')
@require_auth
def get_user_profile(user_id):
    target = db.session.get(User, user_id)
    if not target or not target.is_active:
        return jsonify({'error': 'User not found'}), 404

    me = current_user()
    if me.id == target.id:
        return jsonify(target.to_dict())

    # Privacy: must share at least one group with active membership
    mine = {m.group_id: m for m in GroupMembership.query.filter_by(user_id=me.id, status='active').all()}
    their_groups = {m.group_id for m in GroupMembership.query.filter_by(user_id=target.id, status='active').all()}
    shared = set(mine) & their_groups
    if not shared:
        return jsonify({'error': 'You do not share a group with this user'}), 403
    # Their email only for an admin of a club you share.
    return jsonify(target.public_dict(with_email=any(role_at_least(mine[g], 'admin') for g in shared)))


def watchlist_items(user):
    """A member's watchlist, newest first, each with its next showing (if any)."""
    rows = Watchlist.query.filter_by(user_id=user.id).order_by(Watchlist.created_at.desc()).all()
    nxt = next_showings({w.movie_id for w in rows})
    return [{'movie': {'id': w.movie.id, 'title': w.movie.title, 'release_year': w.movie.release_year,
                       'poster_url': w.movie.poster_url},
             'added_at': w.created_at.isoformat() if w.created_at else None,
             'next': _screening_item(nxt[w.movie_id]) if w.movie_id in nxt else None}
            for w in rows if w.movie]


@app.route('/api/users/<int:user_id>/watchlist')
@require_auth
def user_watchlist(user_id):
    me, target, _, err = _profile_target(user_id)
    if err:
        return err
    return jsonify({'own': me.id == target.id, 'items': watchlist_items(target)})


@app.route('/api/users/<int:user_id>/rsvps')
@require_auth
def user_rsvps(user_id):
    """Upcoming screenings a member is going to (or might), from groups you share."""
    me, target, groups, err = _profile_target(user_id)
    if err:
        return err
    own = me.id == target.id
    return jsonify({'own': own,
                    'items': [_screening_item(s, st) for s, st in upcoming_rsvps(target, groups, personal=own)]})


@app.route('/api/users/<int:user_id>/compare')
@require_auth
def user_compare(user_id):
    me, target, groups, err = _profile_target(user_id)
    if err:
        return err
    if me.id == target.id:
        return jsonify({'error': 'Pick someone else to compare with'}), 400
    return jsonify(compare_members(me, target, groups))


# ─── Letterboxd diary sync (R10f) ─────────────────────────────────────────────

@app.route('/api/me/letterboxd', methods=['GET', 'POST', 'PUT', 'DELETE'])
@require_auth
def my_letterboxd():
    """Your Letterboxd diary link. POST {username} connects it (the diary feed
    must exist; one site account per username) and reads it once; PUT
    {checkin: ask|always|never, ratings: bool} changes your choices; DELETE
    disconnects it (and forgets the username and what was read)."""
    import letterboxd
    from app import LetterboxdEntry
    user = current_user()
    if request.method == 'POST':
        if user.is_guest:
            return jsonify({'error': 'Make an account to connect Letterboxd.'}), 403
        name = letterboxd.clean_username((request.json or {}).get('username'))
        if not name:
            return jsonify({'error': 'Enter your Letterboxd username (letters, numbers and _).'}), 400
        taken = User.query.filter(User.id != user.id, User.letterboxd_sync.is_(True),
                                  db.func.lower(User.letterboxd_username) == name.lower()).first()
        if taken:
            return jsonify({'error': 'That Letterboxd account is already connected to another member. '
                                     'If it\'s yours, ask a club admin to clear it.'}), 409
        entries, error = letterboxd.fetch(name)
        if error == 'not_found':
            return jsonify({'error': f'There\'s no Letterboxd member called "{name}".'}), 400
        if error:
            return jsonify({'error': "Couldn't reach Letterboxd — try again in a bit."}), 502
        if (user.letterboxd_username or '').lower() != name.lower():
            LetterboxdEntry.query.filter_by(user_id=user.id).delete()
        user.letterboxd_username, user.letterboxd_sync = name, True
        db.session.commit()
        letterboxd.sync(user, entries)
    elif request.method == 'PUT':
        data = request.json or {}
        if data.get('checkin') in letterboxd.CHOICES:
            user.letterboxd_checkin = data['checkin']
        if isinstance(data.get('ratings'), bool):
            user.letterboxd_ratings = data['ratings']
        db.session.commit()
    elif request.method == 'DELETE':
        user.letterboxd_sync, user.letterboxd_ratings, user.letterboxd_username = False, False, None
        LetterboxdEntry.query.filter_by(user_id=user.id).delete()
        db.session.commit()
    return jsonify(letterboxd.status(user))


@app.route('/api/me/letterboxd/sync', methods=['POST'])
@require_auth
def sync_my_letterboxd():
    """Read your diary now (it's read every few hours anyway)."""
    import letterboxd
    user = current_user()
    if not user.letterboxd_sync:
        return jsonify({'error': 'Connect your Letterboxd diary first.'}), 400
    result = letterboxd.sync(user)
    if 'error' in result:
        return jsonify({'error': "Couldn't read your diary just now — try again in a bit."}), 502
    return jsonify({**letterboxd.status(user), **result})


@app.route('/api/me/tour', methods=['POST'])
@require_auth
def finish_tour():
    """The welcome tour was finished or skipped (R11): don't show it again
    on its own (it can always be replayed)."""
    from app import _utcnow_naive
    user = current_user()
    if not user.tour_seen_at:
        user.tour_seen_at = _utcnow_naive()
        db.session.commit()
    return jsonify({'tour_seen': True})

"""What goes to the club's Discord: shares, the bot's post queue, discussion threads.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
import app as core
from app import (DiscordPost, Poll, RSVP, Showtime, ShowtimeThread, _active_membership,
    _as_int, _live_post, _parse_post_at, app, current_user, datetime, db, discord_group, jsonify, on_discord,
    post_dict, queue_poll_post, queue_rsvp_share, request, require_auth, require_role, role_at_least,
    set_share_pref, share_prefs, unshare_rsvp)


def _can_manage_post(user, p):
    """Whoever shared it, an organizer for poll posts, or an admin."""
    if p.user_id == user.id:
        return True
    m = _active_membership(user, p.group_id)
    return role_at_least(m, 'organizer' if p.kind in ('poll', 'poll_results') else 'admin')


@app.route('/api/discord/prefs', methods=['GET', 'PUT'])
@require_auth
def discord_prefs():
    """Your "Ask / Always / Never" choice per kind, and whether sharing is
    available to you: in the club tied to the Discord server, with Discord
    linked, and in that server. `reason` says what's missing."""
    user = current_user()
    if request.method == 'PUT':
        for kind, value in (request.json or {}).items():
            set_share_pref(user, kind, value)
        db.session.commit()
    reason = ('no_club' if _active_membership(user, core.DISCORD_GROUP_ID) is None
              else 'not_linked' if not user.discord_user_id
              else 'not_in_server' if not on_discord(user) else None)
    return jsonify({'prefs': share_prefs(user), 'available': reason is None, 'reason': reason})


@app.route('/api/discord/shares', methods=['POST'])
@require_auth
def create_share():
    """Share to #movies: kind rsvp (your going/maybe), invite ("who's in?"),
    poll / poll_results (group admins), or thread (start a screening's
    thread). Optional post_at (local time) schedules invites and polls;
    remember=true makes "always" your choice for that kind."""
    user = current_user()
    data = request.json or {}
    kind, group_id = data.get('kind'), _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'member')
    if err:
        return err
    if not discord_group(group_id):
        return jsonify({'error': 'This group has no Discord server'}), 400
    if not on_discord(user):
        return jsonify({'error': "Only members in the club's Discord server (with Discord linked) can share there",
                        'code': 'not_on_discord'}), 403
    now = datetime.now()
    post_at = _parse_post_at(data.get('post_at'), now)
    if post_at is None:
        return jsonify({'error': 'Pick a time in the next 60 days'}), 400

    if kind in ('rsvp', 'invite', 'thread'):
        showtime = db.session.get(Showtime, _as_int(data.get('showtime_id')) or 0)
        if not showtime:
            return jsonify({'error': 'Showtime not found'}), 404
        if kind == 'rsvp':
            r = RSVP.query.filter_by(user_id=user.id, showtime_id=showtime.id, group_id=group_id).first()
            if not r or r.status not in ('going', 'maybe'):
                return jsonify({'error': 'RSVP going or maybe first'}), 400
            if data.get('remember'):
                set_share_pref(user, 'rsvp', 'always')
            return jsonify(post_dict(queue_rsvp_share(user, showtime.id, group_id, now))), 201
        if kind == 'thread':
            t = ShowtimeThread.query.filter_by(showtime_id=showtime.id, group_id=group_id).first()
            if t:
                return jsonify({'thread_url': t.url}), 200
            post_at = now
        existing = _live_post(kind, showtime.id, group_id)
        # A finished thread request doesn't count: the thread itself (checked
        # above) does, and it may have been deleted in Discord since.
        if existing and (kind == 'invite' or existing.status == 'pending'):
            return jsonify(post_dict(existing)), 200
        post = DiscordPost(group_id=group_id, kind=kind, user_id=user.id, ref_id=showtime.id, post_at=post_at,
                           note=(data.get('note') or '').strip()[:200] or None)
    elif kind in ('poll', 'poll_results'):
        poll = db.session.get(Poll, _as_int(data.get('poll_id')) or 0)
        if not poll or poll.group_id != group_id:
            return jsonify({'error': 'Poll not found'}), 404
        if not role_at_least(_active_membership(user, group_id), 'organizer'):
            return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403
        if kind == 'poll_results' and poll.status != 'scored':
            return jsonify({'error': 'Score the poll first'}), 400
        if data.get('remember'):
            set_share_pref(user, 'poll', 'always')
            db.session.commit()
        return jsonify(post_dict(queue_poll_post(poll, user, kind, post_at))), 201
    else:
        return jsonify({'error': 'Unknown kind'}), 400
    db.session.add(post)
    db.session.commit()
    return jsonify(post_dict(post)), 201


def _manageable_post(post_id):
    user = current_user()
    p = db.session.get(DiscordPost, post_id)
    if not p or not _active_membership(user, p.group_id):
        return None, (jsonify({'error': 'Not found'}), 404)
    if not _can_manage_post(user, p):
        return None, (jsonify({'error': 'Only whoever shared it (or a group admin) can change it'}), 403)
    return p, None


@app.route('/api/discord/shares/<int:post_id>/now', methods=['POST'])
@require_auth
def share_now(post_id):
    """Post a scheduled share right away."""
    p, err = _manageable_post(post_id)
    if err:
        return err
    if p.status == 'pending':
        p.post_at = datetime.now()
        db.session.commit()
    return jsonify(post_dict(p))


@app.route('/api/discord/shares/<int:post_id>', methods=['DELETE'])
@require_auth
def unshare(post_id):
    """Cancel a share that hasn't gone out, or take a posted one down. For an
    RSVP post, ?showtime_id= takes out just that screening."""
    p, err = _manageable_post(post_id)
    if err:
        return err
    showtime_id = request.args.get('showtime_id', type=int)
    if p.kind == 'rsvp' and showtime_id:
        unshare_rsvp(p.user_id, showtime_id, p.group_id)
    elif p.status == 'pending':
        p.status = 'cancelled'
    elif p.status == 'posted':
        p.status, p.dirty = 'removing', True
    db.session.commit()
    return jsonify(post_dict(p))

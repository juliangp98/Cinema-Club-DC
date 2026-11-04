"""Tournaments, for the bot (/play tournament start and list, the buttons on a tournament,
invite DMs). The rules are tournaments.py's — the same as the site's; each
match is a challenge, played with the challenge buttons."""
import tournaments
from app import Tournament, _active_membership, _as_int, app, close_due_polls, db, jsonify, request
from routes.internal.challenges import _who
from routes.internal.common import require_internal, resolve_discord_user


@app.route('/api/internal/tournaments/<int:tournament_id>')
@require_internal
def internal_tournament(tournament_id):
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    t = db.session.get(Tournament, tournament_id)
    if not t or not tournaments.can_see(t, user.id):
        return jsonify({'error': 'not_found'}), 404
    close_due_polls(force=True)
    db.session.refresh(t)
    return jsonify(tournaments.as_dict(t, user.id))


@app.route('/api/internal/tournaments', methods=['POST'])
@require_internal
def internal_tournament_action():
    """{action: create | respond | join | back | start | cancel, …} — create
    takes `players` as [{discord_user_id, discord_name}] (members of the
    server: their account is made like any first command's)."""
    data = request.json or {}
    action = data.get('action')
    if action == 'create':
        user, group, err = _who(data)
        if err:
            return err
        invited = []
        for o in data.get('players') or []:
            u, err = resolve_discord_user({**o, 'create': '1', 'group_id': group.id})
            if err:
                return jsonify({'error': "Couldn't find one of those members."}), 400
            invited.append(u.id)
        db.session.commit()
        t, err = tournaments.create(group, user, {**data, 'players': invited})
        if err:
            return jsonify({'error': err}), 400
        posted = tournaments.announce(t, user, data.get('announce'))
        return jsonify({**tournaments.as_dict(t, user.id), 'posted': posted}), 201

    user, err = resolve_discord_user(data)
    if err:
        return err
    t = db.session.get(Tournament, _as_int(data.get('tournament_id')) or 0)
    if not t or not _active_membership(user, t.group_id) or not tournaments.can_see(t, user.id):
        return jsonify({'error': 'not_found'}), 404
    close_due_polls(force=True)
    db.session.refresh(t)
    err = {'respond': lambda: tournaments.respond(t, user, bool(data.get('accept'))),
           'join': lambda: tournaments.join(t, user),
           'back': lambda: tournaments.back(t, user, _as_int(data.get('user_id')), data.get('amount')),
           'start': lambda: tournaments.start_now(t, user),
           'cancel': lambda: tournaments.cancel(t, user)}.get(action, lambda: 'Unknown action')()
    if err:
        return jsonify({'error': err}), 400
    db.session.refresh(t)
    return jsonify(tournaments.as_dict(t, user.id))

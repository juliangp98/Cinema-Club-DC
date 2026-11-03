"""Tournaments on the site (tournaments.py has the rules; each match is played
on its challenge page; the bot's routes are routes/internal/tournaments.py)."""
import challenges
import tournaments
from app import (Group, Tournament, _active_membership, _as_int, app, close_due_polls, current_user, db, jsonify,
                 request, require_auth, require_group_member)


def _mine(tournament_id):
    """(tournament, user, error) — a tournament the signed-in member may see."""
    user = current_user()
    t = db.session.get(Tournament, tournament_id)
    if not t or not _active_membership(user, t.group_id) or not tournaments.can_see(t, user.id):
        return None, user, (jsonify({'error': 'Tournament not found'}), 404)
    close_due_polls(force=True)
    db.session.refresh(t)
    return t, user, None


def _done(t, user, err=None, status=200):
    if err:
        return jsonify({'error': err}), 400
    db.session.refresh(t)
    return jsonify({**tournaments.as_dict(t, user.id), 'available': challenges.available(user.id, t.group_id)}), status


@app.route('/api/tournaments')
@require_auth
def list_tournaments():
    """Play's tournaments: the options for a new one, and the ones you can see."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    close_due_polls(force=True)
    user = current_user()
    return jsonify({'formats': tournaments.FORMATS, 'players': tournaments.PLAYERS, 'payouts': tournaments.PAYOUT_LABELS,
                    'match_times': tournaments.MATCH_TIMES, 'seedings': tournaments.SEEDINGS,
                    'max_seats': tournaments.MAX_SEATS,
                    'tournaments': [tournaments.as_dict(t, user.id) for t in tournaments.visible(group_id, user.id)]})


@app.route('/api/tournaments', methods=['POST'])
@require_auth
def create_tournament():
    data = request.json or {}
    group_id = _as_int(data.get('group_id'))
    err = require_group_member(group_id)
    if err:
        return err
    user = current_user()
    t, err = tournaments.create(db.session.get(Group, group_id), user, data)
    if err:
        return jsonify({'error': err}), 400
    tournaments.announce(t, user, data.get('announce'))
    return _done(t, user, status=201)


@app.route('/api/tournaments/<int:tournament_id>')
@require_auth
def get_tournament(tournament_id):
    t, user, err = _mine(tournament_id)
    return err or _done(t, user)


@app.route('/api/tournaments/<int:tournament_id>/<action>', methods=['POST'])
@require_auth
def tournament_action(tournament_id, action):
    """respond {accept} · join · back {user_id, amount} · start · cancel —
    each returns the tournament as you now see it."""
    t, user, err = _mine(tournament_id)
    if err:
        return err
    data = request.json or {}
    run = {'respond': lambda: tournaments.respond(t, user, bool(data.get('accept'))),
           'join': lambda: tournaments.join(t, user),
           'back': lambda: tournaments.back(t, user, _as_int(data.get('user_id')), data.get('amount')),
           'start': lambda: tournaments.start_now(t, user),
           'cancel': lambda: tournaments.cancel(t, user)}.get(action)
    if not run:
        return jsonify({'error': 'Unknown action'}), 404
    return _done(t, user, run())

"""Challenges on the site (challenges.py has the rules; the bot's routes are
routes/internal/challenges.py and call the same functions)."""
import challenges
from app import (Challenge, ChallengePlayer, DiscordPost, Group, _active_membership, _as_int, app, close_due_polls,
                 current_user, db, jsonify, request, require_auth, require_group_member)


def _mine(challenge_id):
    """(challenge, user, error) — a challenge the signed-in member may see."""
    user = current_user()
    ch = db.session.get(Challenge, challenge_id)
    if not ch or not _active_membership(user, ch.group_id) or not challenges.can_see(ch, user.id):
        return None, user, (jsonify({'error': 'Challenge not found'}), 404)
    if ch.status == 'open' and ch.closes_at <= challenges._now():
        challenges.settle(ch)
    return ch, user, None


def _done(ch, user, err=None, status=200):
    if err:
        return jsonify({'error': err}), 400
    db.session.refresh(ch)
    return jsonify(challenges.as_dict(ch, user.id)), status


@app.route('/api/challenges')
@require_auth
def list_challenges():
    """Play's Challenges: the club's settings and games, what you have to put
    in, and the challenges you can see (open, and recently decided)."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    close_due_polls(force=True)
    user, group = current_user(), db.session.get(Group, group_id)
    return jsonify({'enabled': bool(group.challenges_enabled), 'games': challenges.games(group),
                    'max_stake': group.challenge_max_stake or 10, 'backing': group.challenge_backing is not False,
                    'max_bet': challenges.MAX_BET, 'max_players': challenges.MAX_PLAYERS, 'max_seats': challenges.MAX_SEATS,
                    'lengths': challenges.LENGTHS, 'deadlines': challenges.DEADLINES,
                    'available': challenges.available(user.id, group_id),
                    'on_the_line': challenges.on_the_line(user.id, group_id),
                    'challenges': [challenges.as_dict(c, user.id) for c in challenges.visible(group_id, user.id)]})


@app.route('/api/challenges', methods=['POST'])
@require_auth
def create_challenge():
    data = request.json or {}
    group_id = _as_int(data.get('group_id'))
    err = require_group_member(group_id)
    if err:
        return err
    user = current_user()
    ch, err = challenges.create(db.session.get(Group, group_id), user, data)
    if err:
        return jsonify({'error': err}), 400
    challenges.announce(ch, user, data.get('announce'))
    return _done(ch, user, status=201)


@app.route('/api/challenges/<int:challenge_id>')
@require_auth
def get_challenge(challenge_id):
    ch, user, err = _mine(challenge_id)
    return err or _done(ch, user)


@app.route('/api/challenges/<int:challenge_id>/<action>', methods=['POST'])
@require_auth
def challenge_action(challenge_id, action):
    """respond {accept} · join · back {user_id, amount} · cancel · end ·
    rematch {double} — each returns the challenge as you now see it."""
    ch, user, err = _mine(challenge_id)
    if err:
        return err
    data = request.json or {}
    if action == 'respond':
        return _done(ch, user, challenges.respond(ch, user, bool(data.get('accept'))))
    if action == 'join':
        return _done(ch, user, challenges.join(ch, user))
    if action == 'back':
        return _done(ch, user, challenges.back(ch, user, _as_int(data.get('user_id')), data.get('amount')))
    if action == 'cancel':
        return _done(ch, user, challenges.cancel(ch, user))
    if action == 'end':
        return _done(ch, user, challenges.end_now(ch, user))
    if action == 'rematch':
        new, err = challenges.rematch(ch, user, bool(data.get('double')))
        if err:
            return jsonify({'error': err}), 400
        posted = DiscordPost.query.filter_by(kind='challenge', ref_id=ch.id).first() is not None
        challenges.announce(new, user, 'now' if posted else None)          # posted like the first one was
        return _done(new, user, status=201)
    return jsonify({'error': 'Unknown action'}), 404


@app.route('/api/challenges/<int:challenge_id>/play', methods=['GET', 'POST'])
@require_auth
def play_challenge(challenge_id):
    """Your question now (GET; its 30 seconds start the first time) or your
    answer to it (POST {choice}; 'more' to see more of a still or reviews)."""
    ch, user, err = _mine(challenge_id)
    if err:
        return err
    p = challenges.player(ch, user.id)
    if not p or p.status not in ('accepted', 'finished', 'forfeit'):
        return jsonify({'error': "You're not playing this one."}), 400
    if request.method == 'GET':
        q = challenges.current(ch, p) if ch.status == 'open' else None
        return jsonify({'question': q, 'challenge': challenges.as_dict(ch, user.id)})
    choice = (request.json or {}).get('choice')
    shown, err = challenges.answer(ch, p, choice)
    if err:
        return jsonify({'error': err}), 400
    db.session.refresh(ch)
    nxt = challenges.current(ch, p) if ch.status == 'open' and p.status == 'accepted' else None
    return jsonify({'answered': shown, 'question': nxt, 'challenge': challenges.as_dict(ch, user.id)})


@app.route('/api/challenges/still/<int:player_id>/<int:i>/<token_step>.jpg')
def challenge_still(player_id, i, token_step):
    """A challenge's still for one player at a step (quizzes.crop_still): their
    own token is the key — Discord fetches these too, without a session."""
    import json
    import quizzes
    from flask import Response
    p = db.session.get(ChallengePlayer, player_id)
    ch = p.challenge if p else None
    if not ch or ch.kind != 'still':
        return jsonify({'error': 'Not found'}), 404
    prog = json.loads(p.progress_json or '{}')
    token, _, step = token_step.rpartition('-')
    answered = i < prog.get('i', 0) or ch.status == 'done'
    if (not token or token != prog.get('tokens', {}).get(str(i)) or step not in ('1', '2', '3')
            or (not answered and (i != prog.get('i', 0) or int(step) > prog.get('step', 1)))):
        return jsonify({'error': 'Not found'}), 404
    qs = json.loads(ch.state_json or '{}').get('questions', [])
    if i >= len(qs):
        return jsonify({'error': 'Not found'}), 404
    data = quizzes.crop_still(qs[i], int(step))
    return Response(data, mimetype='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})


@app.route('/api/challenges/rivals')
@require_auth
def challenge_rivals():
    """?group_id=&user_id= — a member's challenge record and their rivals
    (the members they've played most); with you, head to head."""
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    viewer = current_user()
    uid = request.args.get('user_id', type=int) or viewer.id
    return jsonify({'record': challenges.records([uid], group_id)[uid], 'rivals': challenges.rivals(group_id, uid),
                    'versus_you': challenges.head_to_head(group_id, uid, viewer.id) if uid != viewer.id else None})

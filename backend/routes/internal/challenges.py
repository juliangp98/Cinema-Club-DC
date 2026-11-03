"""Challenges, for the bot (/play versus: and challenges:, the buttons on a
challenge, invite DMs). The rules are challenges.py's — the same as the site's."""
import challenges
from app import Challenge, Group, _active_membership, _as_int, app, close_due_polls, db, jsonify, request
from routes.internal.common import require_internal, resolve_discord_user


def _who(data):
    """(user, group, error) for the member acting and their club."""
    user, err = resolve_discord_user(data)
    if err:
        return None, None, err
    group = db.session.get(Group, _as_int(data.get('group_id')) or 0)
    if not group or not _active_membership(user, group.id):
        return None, None, (jsonify({'error': 'not_member'}), 403)
    return user, group, None


@app.route('/api/internal/challenges')
@require_internal
def internal_challenges():
    """The club's challenge settings and games, and the challenges you can see."""
    user, group, err = _who(request.args)
    if err:
        return err
    close_due_polls(force=True)
    return jsonify({'enabled': bool(group.challenges_enabled), 'games': challenges.games(group),
                    'max_stake': group.challenge_max_stake or 10, 'available': challenges.available(user.id, group.id),
                    'challenges': [challenges.as_dict(c, user.id) for c in challenges.visible(group.id, user.id)]})


@app.route('/api/internal/challenges/<int:challenge_id>')
@require_internal
def internal_challenge(challenge_id):
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    ch = db.session.get(Challenge, challenge_id)
    if not ch or not challenges.can_see(ch, user.id):
        return jsonify({'error': 'not_found'}), 404
    if ch.status == 'open' and ch.closes_at <= challenges._now():
        challenges.settle(ch)
    return jsonify(challenges.as_dict(ch, user.id))


@app.route('/api/internal/challenges', methods=['POST'])
@require_internal
def internal_challenge_action():
    """{action: create | respond | join | back | cancel | end | games | rematch | play | answer, …} —
    create takes `opponents` as [{discord_user_id, discord_name}] (members of the
    server: their account is made like any first command's)."""
    data = request.json or {}
    action = data.get('action')
    if action == 'create':
        user, group, err = _who(data)
        if err:
            return err
        opponents = []
        for o in data.get('opponents') or []:
            u, err = resolve_discord_user({**o, 'create': '1', 'group_id': group.id})
            if err:
                return jsonify({'error': "Couldn't find one of those members."}), 400
            opponents.append(u.id)
        db.session.commit()
        ch, err = challenges.create(group, user, {**data, 'opponents': opponents})
        if err:
            return jsonify({'error': err}), 400
        posted = challenges.announce(ch, user, data.get('announce'))
        return jsonify({**challenges.as_dict(ch, user.id), 'posted': posted}), 201

    user, err = resolve_discord_user(data)
    if err:
        return err
    ch = db.session.get(Challenge, _as_int(data.get('challenge_id')) or 0)
    if not ch or not _active_membership(user, ch.group_id) or not challenges.can_see(ch, user.id):
        return jsonify({'error': 'not_found'}), 404
    if ch.status == 'open' and ch.closes_at <= challenges._now():
        challenges.settle(ch)

    if action in ('play', 'answer'):
        p = challenges.player(ch, user.id)
        if not p or p.status not in ('accepted', 'finished', 'forfeit'):
            return jsonify({'error': "You're not playing this one."}), 400
        answered = None
        if action == 'answer':
            choice = data.get('choice')
            answered, err = challenges.answer(ch, p, int(choice) if str(choice).isdigit() else choice)
            if err:
                return jsonify({'error': err}), 400
            db.session.refresh(ch)
        q = challenges.current(ch, p) if ch.status == 'open' and p.status == 'accepted' else None
        return jsonify({'answered': answered, 'question': q, 'challenge': challenges.as_dict(ch, user.id)})

    if action == 'rematch':
        new, err = challenges.rematch(ch, user, bool(data.get('double')))
        if err:
            return jsonify({'error': err}), 400
        from app import DiscordPost
        posted = DiscordPost.query.filter_by(kind='challenge', ref_id=ch.id).first() is not None
        challenges.announce(new, user, 'now' if posted else None)
        return jsonify(challenges.as_dict(new, user.id)), 201
    err = {'respond': lambda: challenges.respond(ch, user, bool(data.get('accept'))),
           'join': lambda: challenges.join(ch, user),
           'back': lambda: challenges.back(ch, user, _as_int(data.get('user_id')), data.get('amount')),
           'cancel': lambda: challenges.cancel(ch, user),
           'end': lambda: challenges.end_now(ch, user),
           'games': lambda: challenges.set_games(ch, user, data)}.get(action, lambda: 'Unknown action')()
    if err:
        return jsonify({'error': err}), 400
    db.session.refresh(ch)
    return jsonify(challenges.as_dict(ch, user.id))

"""The quiz games (R15, quizzes.py): what a club has on, starting a round,
answering it — on the site and, through the internal API, in Discord."""
from app import Group, _as_int, app, current_user, db, jsonify, request, require_auth, require_group_member
from routes.internal import require_internal, resolve_discord_user


def _group(data):
    return db.session.get(Group, _as_int(data.get('group_id')) or 0)


def _round(r, err):
    import quizzes
    if err:
        return jsonify({'error': err}), 400
    return jsonify(quizzes.as_dict(r))


@app.route('/api/quizzes')
@require_auth
def quiz_games():
    """{games: [...]}: the club's quiz games that are on, with your round in each."""
    import quizzes
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    return jsonify({'games': quizzes.summary(db.session.get(Group, group_id), current_user())})


@app.route('/api/quizzes/start', methods=['POST'])
@require_auth
def quiz_start():
    """{group_id, kind}: your round of a game (the open one, or a new one)."""
    import quizzes
    data = request.json or {}
    return _round(*quizzes.start(_group(data), current_user(), data.get('kind')))


@app.route('/api/quizzes/answer', methods=['POST'])
@require_auth
def quiz_answer():
    """{group_id, round_id, choice}: answer your round."""
    import quizzes
    data = request.json or {}
    return _round(*quizzes.answer(_group(data), current_user(), _as_int(data.get('round_id')), data.get('choice')))


@app.route('/api/internal/quizzes', methods=['GET', 'POST'])
@require_internal
def internal_quizzes():
    """The bot's /games: GET the club's games (with your rounds); POST
    {action: start, kind} or {action: answer, round_id, choice}."""
    import quizzes
    data = (request.json or {}) if request.method == 'POST' else request.args
    user, err = resolve_discord_user(data)
    if err:
        return err
    group = _group(data)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    if request.method == 'GET':
        return jsonify({'games': quizzes.summary(group, user)})
    if data.get('action') == 'start':
        return _round(*quizzes.start(group, user, data.get('kind'), source='discord'))
    return _round(*quizzes.answer(group, user, _as_int(data.get('round_id')), data.get('choice')))

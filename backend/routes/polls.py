"""Polls: creating (and AI drafts), voting, scoring.

Routes (and their own helpers) moved out of app.py in R9b; shared helpers
and the models are imported from app."""
import json as _json
from app import (DiscordPost, Group, Poll, PollCategory, PollDraft, PollOption, PollVote,
    _active_membership, _as_int, _draft_poll, _live_post, announce_new_poll, app, apply_votes, build_leaderboard,
    build_poll, can_share, current_user, datetime, db, jsonify, os, poll_scores,
    post_dict, queue_poll_post, request, require_auth, require_group_member, require_role, role_at_least,
    share_prefs, timezone)


def poll_posts_changed(poll_id):
    """A poll was edited, closed, scored, un-scored or deleted: refresh (or
    remove) its announcement and results posts."""
    DiscordPost.query.filter(DiscordPost.kind.in_(('poll', 'poll_results')), DiscordPost.ref_id == poll_id,
                             DiscordPost.status == 'posted').update({'dirty': True}, synchronize_session=False)

def _require_group_member(group_id):
    """Return (user, membership) or abort with JSON error."""
    user = current_user()
    return user, _active_membership(user, group_id)


@app.route('/api/groups/<int:group_id>/polls', methods=['GET'])
@require_auth
def get_group_polls(group_id):
    user, membership = _require_group_member(group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403
    polls = Poll.query.filter_by(group_id=group_id).order_by(Poll.created_at.desc()).all()
    # For the list (R6a): how many voted, and how far you've got.
    cat_poll = {c.id: c.poll_id for c in PollCategory.query.filter(PollCategory.poll_id.in_([p.id for p in polls]))} if polls else {}
    voters, mine = {}, {}
    for cat_id, uid in (db.session.query(PollVote.category_id, PollVote.user_id)
                        .filter(PollVote.category_id.in_(cat_poll)).distinct() if cat_poll else []):
        pid = cat_poll[cat_id]
        voters.setdefault(pid, set()).add(uid)
        if uid == user.id:
            mine.setdefault(pid, set()).add(cat_id)
    return jsonify([{**p.to_dict(), 'voters': len(voters.get(p.id, ())), 'you_picked': len(mine.get(p.id, ()))}
                    for p in polls])


@app.route('/api/groups/<int:group_id>/polls', methods=['POST'])
@require_auth
def create_poll(group_id):
    user, membership = _require_group_member(group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403
    data = request.json or {}
    poll, err = build_poll(group_id, user, data)
    if err:
        return err
    draft = db.session.get(PollDraft, _as_int(data.get('draft_id')) or 0)
    if draft and draft.group_id == group_id:          # made from an AI draft (R6a)
        draft.poll_id = poll.id
        db.session.commit()
    announce_new_poll(poll, user, data)
    return jsonify(poll.to_dict(include_categories=True)), 201


@app.route('/api/groups/<int:group_id>/polls/draft', methods=['POST'])
@require_auth
def draft_poll(group_id):
    """{prompt} → an editable draft (not a poll yet). Organizers and admins."""
    user = current_user()
    _, err = require_role(user, group_id, 'organizer')
    if err:
        return err
    data = request.json or {}
    body, status = _draft_poll(user, db.session.get(Group, group_id), data.get('prompt'), data.get('scope') or 'playing')
    return jsonify(body), status


@app.route('/api/poll-drafts/<int:draft_id>')
@require_auth
def get_poll_draft(draft_id):
    """A saved draft for the editor (e.g. "Open in editor" from Discord)."""
    user = current_user()
    d = db.session.get(PollDraft, draft_id)
    if not d:
        return jsonify({'error': 'Draft not found'}), 404
    _, err = require_role(user, d.group_id, 'organizer')
    if err:
        return err
    return jsonify({'id': d.id, 'group_id': d.group_id, 'prompt': d.prompt, 'poll_id': d.poll_id, **_json.loads(d.data_json)})


@app.route('/api/groups/<int:group_id>/polls/oscars', methods=['POST'])
@require_auth
def create_oscars_poll(group_id):
    user, membership = _require_group_member(group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    # Load template
    template_path = os.path.join(os.path.dirname(__file__), 'oscars_2026.json')
    if not os.path.exists(template_path):
        return jsonify({'error': 'Oscars template not found'}), 404

    with open(template_path) as f:
        tmpl = _json.load(f)

    data = request.json or {}
    scoring_mode = data.get('scoring_mode', 'confidence')

    poll = Poll(
        group_id=group_id,
        created_by=user.id,
        title=tmpl.get('title', 'Oscar Predictions'),
        description=tmpl.get('description', ''),
        poll_type='prediction',
        scoring_mode=scoring_mode,
    )
    db.session.add(poll)
    db.session.flush()

    for i, cat_data in enumerate(tmpl.get('categories', [])):
        cat = PollCategory(
            poll_id=poll.id,
            title=cat_data['title'],
            sort_order=i,
        )
        db.session.add(cat)
        db.session.flush()
        for j, nom in enumerate(cat_data.get('nominees', [])):
            extra = nom.get('extra')
            opt = PollOption(
                category_id=cat.id,
                text=nom['text'],
                sort_order=j,
                extra_data=_json.dumps(extra) if extra else None,
            )
            db.session.add(opt)

    db.session.commit()
    announce_new_poll(poll, user, data)
    return jsonify(poll.to_dict(include_categories=True)), 201


@app.route('/api/polls/<int:poll_id>', methods=['GET'])
@require_auth
def get_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403
    d = poll.to_dict(include_categories=True, user_id=user.id)
    if can_share(user, poll.group_id):
        live = {k: _live_post(k, poll.id, poll.group_id) for k in ('poll', 'poll_results')}
        d['discord'] = {'announce': post_dict(live['poll']) if live['poll'] else None,
                        'results': post_dict(live['poll_results']) if live['poll_results'] else None}
    return jsonify(d)


@app.route('/api/polls/<int:poll_id>', methods=['PUT'])
@require_auth
def update_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    data = request.json
    if 'title' in data:
        poll.title = data['title'].strip()
    if 'description' in data:
        poll.description = data['description']
    if 'poll_type' in data and data['poll_type'] in ('standard', 'prediction'):
        poll.poll_type = data['poll_type']
    if 'scoring_mode' in data and data['scoring_mode'] in ('none', 'single', 'ranked', 'confidence'):
        poll.scoring_mode = data['scoring_mode']
    if 'status' in data and data['status'] in ('open', 'closed'):
        poll.status = data['status']
        if data['status'] == 'closed':
            poll.closed_at = datetime.now(timezone.utc)
    poll_posts_changed(poll.id)
    db.session.commit()
    return jsonify(poll.to_dict())


@app.route('/api/polls/<int:poll_id>', methods=['DELETE'])
@require_auth
def delete_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    poll_posts_changed(poll.id)            # its Discord posts come down
    DiscordPost.query.filter(DiscordPost.kind.in_(('poll', 'poll_results')), DiscordPost.ref_id == poll.id,
                             DiscordPost.status == 'pending').update({'status': 'cancelled'}, synchronize_session=False)
    db.session.delete(poll)
    db.session.commit()
    return jsonify({'message': 'Poll deleted'})


@app.route('/api/polls/<int:poll_id>/vote', methods=['POST'])
@require_auth
def submit_votes(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    if poll.status != 'open':
        return jsonify({'error': 'Poll is not open for voting'}), 400
    user, membership = _require_group_member(poll.group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403
    _, err = require_role(user, poll.group_id, 'member')
    if err:
        return err

    # { votes: [{ category_id, option_id, confidence?, rank? }], clear: [category_id] }
    data = request.json or {}
    count = apply_votes(user, poll, data.get('votes'), data.get('clear'))
    return jsonify({'message': 'Votes submitted', 'count': count})


@app.route('/api/polls/<int:poll_id>/categories/<int:cat_id>/winner', methods=['PUT'])
@require_auth
def set_category_winner(poll_id, cat_id):
    """Set (or clear) the correct answer for a single category – used for live scoring."""
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    cat = db.session.get(PollCategory, cat_id)
    if not cat or cat.poll_id != poll.id:
        return jsonify({'error': 'Category not found'}), 404

    data = request.json  # { option_id: int | null }
    opt_id = data.get('option_id')
    if opt_id:
        opt = db.session.get(PollOption, opt_id)
        if not opt or opt.category_id != cat_id:
            return jsonify({'error': 'Invalid option'}), 400
        cat.correct_option_id = opt_id
    else:
        cat.correct_option_id = None

    poll_posts_changed(poll.id)            # posted results follow corrections
    db.session.commit()
    return jsonify({'category_id': cat_id, 'correct_option_id': cat.correct_option_id})


@app.route('/api/polls/<int:poll_id>/score', methods=['POST'])
@require_auth
def score_poll(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not role_at_least(membership, 'organizer'):
        return jsonify({'error': 'Organizer access required', 'code': 'role'}), 403

    data = request.json  # { winners: { category_id: option_id } }
    winners = data.get('winners', {})

    for cat_id_str, opt_id in winners.items():
        cat_id = int(cat_id_str)
        cat = db.session.get(PollCategory, cat_id)
        if cat and cat.poll_id == poll.id:
            cat.correct_option_id = opt_id

    first_scoring = poll.status != 'scored'
    poll.status = 'scored'
    poll.closed_at = poll.closed_at or datetime.now(timezone.utc)
    poll.scored_at = datetime.now(timezone.utc)
    poll_posts_changed(poll.id)            # a correction updates results already posted
    db.session.commit()
    # Results go to Discord when asked for, or right away for "always" sharers.
    if can_share(user, poll.group_id) and (data.get('post_results') is True or (
            first_scoring and data.get('post_results') is None and share_prefs(user)['poll'] == 'always')):
        queue_poll_post(poll, user, 'poll_results', datetime.now())

    return jsonify(poll.to_dict(include_categories=True))


@app.route('/api/polls/<int:poll_id>/leaderboard', methods=['GET'])
@require_auth
def poll_leaderboard(poll_id):
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return jsonify({'error': 'Poll not found'}), 404
    user, membership = _require_group_member(poll.group_id)
    if not membership:
        return jsonify({'error': 'Not a group member'}), 403

    return jsonify([{**s, 'user': s['user'].public_dict()} for s in poll_scores(poll)])


@app.route('/api/users/<int:user_id>/kernels', methods=['GET'])
@require_auth
def user_kernels(user_id):
    """Someone's kernels across their clubs (R10b): the total, and where it
    came from (polls · going out · from members)."""
    import kernels
    k = kernels.breakdown(user_id)
    return jsonify({'user_id': user_id, 'kernels': k['kernels'],
                    'breakdown': {part: k[part] for part in kernels.PARTS}})


@app.route('/api/groups/<int:group_id>/leaderboard')
@require_auth
def group_leaderboard(group_id):
    """Season-long standings: kernels across all scored polls + attendance."""
    group = db.session.get(Group, group_id)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    err = require_group_member(group_id)
    if err:
        return err
    return jsonify(build_leaderboard(group))


# ─── Daily trivia (R10d) ──────────────────────────────────────────────────────

@app.route('/api/trivia/today')
@require_auth
def trivia_today():
    """Trivia for the card: the club's question of the day (if it's on), your
    answer if you've given one, yesterday's with its answer, and your
    unanswered anytime question (if anytime is on)."""
    import trivia
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    return jsonify(trivia.today_for(db.session.get(Group, group_id), current_user()))


@app.route('/api/trivia/another', methods=['POST'])
@require_auth
def trivia_another():
    """{group_id}: an anytime question for you (if the club has them on) —
    your unanswered one if you have one."""
    import trivia
    group_id = _as_int((request.json or {}).get('group_id'))
    err = require_group_member(group_id)
    if err:
        return err
    user = current_user()
    q, error = trivia.another(db.session.get(Group, group_id), user)
    if error:
        return jsonify({'error': error}), 400
    return jsonify(trivia.as_dict(q, user))


@app.route('/api/trivia/answer', methods=['POST'])
@require_auth
def trivia_answer():
    """{group_id, question_id, choice}: your one answer to a question."""
    import trivia
    data = request.json or {}
    group_id = _as_int(data.get('group_id'))
    err = require_group_member(group_id)
    if err:
        return err
    result, error = trivia.answer(db.session.get(Group, group_id), current_user(), _as_int(data.get('question_id')),
                                  data.get('choice') if isinstance(data.get('choice'), int) else None)
    if error:
        return jsonify({'error': error}), 400
    return jsonify(result)


# ─── Repertory bingo (R10e) ───────────────────────────────────────────────────

@app.route('/api/bingo')
@require_auth
def bingo_card():
    """This month's club card (if the club turned bingo on): your squares, the
    screenings that filled them, your lines, and how the club is doing."""
    import bingo
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    return jsonify(bingo.view(db.session.get(Group, group_id), current_user()))


# ─── Play (R10) ───────────────────────────────────────────────────────────────

@app.route('/api/play')
@require_auth
def play_summary():
    """What there is to play today: trivia, bingo, polls waiting for your vote,
    your kernels (for the feed's rail and strip, the Club page and Play)."""
    import play
    group_id = request.args.get('group_id', type=int)
    err = require_group_member(group_id)
    if err:
        return err
    return jsonify(play.summary(db.session.get(Group, group_id), current_user()))

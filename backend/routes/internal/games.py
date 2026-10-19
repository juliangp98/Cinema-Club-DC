"""Games and polls, for the bot: trivia, bingo, /play, game posts, polls and
poll drafts, quotes.
"""
import json as _json
from app import (Group, HOME_GROUP_ID, Poll, PollCategory, PollDraft, PollVote, Quote, RANKED_PICKS, GamePost, discord_group,
    role_at_least, _active_membership, _as_int, _draft_poll, _utcnow_naive, announce_new_poll, app, apply_votes,
    build_poll, db, jsonify, poll_scores, request, require_role, timedelta, vote_kernels)
from routes.internal.common import require_internal, resolve_discord_user


@app.route('/api/internal/polls/draft', methods=['POST'])
@require_internal
def internal_draft_poll():
    """The bot's /poll make: — organizers only, same rules as the site."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group_id = _as_int(data.get('group_id'))
    _, err = require_role(user, group_id, 'organizer')
    if err:
        return err
    body, status = _draft_poll(user, db.session.get(Group, group_id), data.get('prompt'), data.get('scope') or 'playing')
    return jsonify(body), status


@app.route('/api/internal/poll-drafts/<int:draft_id>/create', methods=['POST'])
@require_internal
def internal_create_from_draft(draft_id):
    """Discord's "Create now": the draft becomes an open poll, announced in #movies."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    d = db.session.get(PollDraft, draft_id)
    if not d:
        return jsonify({'error': 'draft_not_found'}), 404
    _, err = require_role(user, d.group_id, 'organizer')
    if err:
        return err
    if d.poll_id and db.session.get(Poll, d.poll_id):
        return jsonify({'error': 'already_created', 'poll_id': d.poll_id}), 409
    draft = _json.loads(d.data_json)
    poll, err = build_poll(d.group_id, user, draft)
    if err:
        return err
    d.poll_id = poll.id
    db.session.commit()
    announce_new_poll(poll, user, {'announce': 'now'})
    return jsonify(poll.to_dict(include_categories=True)), 201


def poll_ballot(user, poll):
    """Everything a Discord ballot shows, for one member: each category's
    nominees, their picks, the vote split (once they've picked, or voting has
    closed), and — once scored — the winners, their kernels and their place."""
    mine = {}
    for v in PollVote.query.join(PollCategory).filter(PollCategory.poll_id == poll.id,
                                                       PollVote.user_id == user.id):
        mine.setdefault(v.category_id, []).append(v)
    scored = poll.status == 'scored'
    cats = []
    for c in poll.categories:
        votes = sorted(mine.get(c.id, []), key=lambda v: v.rank or 0)
        d = {'id': c.id, 'title': c.title,
             'options': [{'id': o.id, 'text': o.text} for o in c.options],
             'picks': [{'option_id': v.option_id, 'confidence': v.confidence, 'rank': v.rank} for v in votes],
             'correct_option_id': c.correct_option_id if scored else None}
        if votes or poll.status != 'open':
            # Picks per nominee (ranked: any rank), out of the members who voted here.
            d['voters'] = len({v.user_id for v in c.votes})
            d['split'] = {}
            for v in c.votes:
                d['split'][str(v.option_id)] = d['split'].get(str(v.option_id), 0) + 1
        if scored and c.correct_option_id and votes:
            d['kernels'] = sum(vote_kernels(poll.scoring_mode, v, c.correct_option_id) for v in votes)
        cats.append(d)
    out = {'poll': {'id': poll.id, 'title': poll.title, 'status': poll.status,
                    'scoring_mode': poll.scoring_mode, 'poll_type': poll.poll_type,
                    'ranked_picks': RANKED_PICKS},
           'categories': cats, 'answered': sum(1 for c in cats if c['picks'])}
    if scored:
        board = poll_scores(poll)
        place = next((i for i, s in enumerate(board) if s['user'].id == user.id), None)
        out['score'] = ({'kernels': board[place]['kernels'], 'correct': board[place]['correct'],
                         'place': place + 1, 'of': len(board)} if place is not None else None)
    return out


@app.route('/api/internal/polls')
@require_internal
def internal_polls():
    group_id = request.args.get('group_id', type=int)
    if not group_id:
        return jsonify({'error': 'group_id required'}), 400
    q = Poll.query.filter_by(group_id=group_id)
    if request.args.get('include_closed'):
        # /poll vote's picker: open polls, then ones that closed in the last 60 days
        # (to check your picks and results).
        recent = _utcnow_naive() - timedelta(days=60)
        ended = db.func.coalesce(Poll.scored_at, Poll.closed_at, Poll.created_at)
        polls = q.filter(db.or_(Poll.status == 'open', ended >= recent)).all()
        polls.sort(key=lambda p: (p.status != 'open', -(p.scored_at or p.closed_at or p.created_at).timestamp()))
    else:
        polls = q.filter_by(status='open').all()
    return jsonify([p.to_dict() for p in polls])


def _internal_poll_voter(poll_id, data):
    """(user, poll, error) for a Discord member acting on a poll of a group
    they belong to."""
    poll = db.session.get(Poll, poll_id)
    if not poll:
        return None, None, (jsonify({'error': 'poll_not_found'}), 404)
    user, err = resolve_discord_user(data)
    if err:
        return None, None, err
    if not _active_membership(user, poll.group_id):
        return None, None, (jsonify({'error': 'not_member'}), 403)
    return user, poll, None


@app.route('/api/internal/polls/<int:poll_id>/ballot')
@require_internal
def internal_poll_ballot(poll_id):
    user, poll, err = _internal_poll_voter(poll_id, request.args)
    if err:
        return err
    return jsonify(poll_ballot(user, poll))


@app.route('/api/internal/polls/<int:poll_id>/vote', methods=['POST'])
@require_internal
def internal_poll_vote(poll_id):
    """Save picks from a Discord ballot; returns the refreshed ballot."""
    data = request.json or {}
    user, poll, err = _internal_poll_voter(poll_id, data)
    if err:
        return err
    _, err = require_role(user, poll.group_id, 'member')
    if err:
        return err
    if poll.status != 'open':
        return jsonify({'error': 'poll_closed', **poll_ballot(user, poll)}), 409
    apply_votes(user, poll, data.get('votes'), data.get('clear'))
    return jsonify(poll_ballot(user, poll))


# ─── Daily trivia (R10d) ──────────────────────────────────────────────────────

@app.route('/api/internal/trivia/today')
@require_internal
def internal_trivia_today():
    """/trivia: the club's question of the day for this member."""
    import trivia
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    return jsonify(trivia.today_for(group, user))


@app.route('/api/internal/trivia/answer', methods=['POST'])
@require_internal
def internal_trivia_answer():
    """A trivia button in Discord: {discord ident, question_id, choice}."""
    import trivia
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group = db.session.get(Group, _as_int(data.get('group_id')) or 0)
    result, error = trivia.answer(group, user, _as_int(data.get('question_id')),
                                  data.get('choice') if isinstance(data.get('choice'), int) else None, source='discord')
    if error:
        return jsonify({'error': error}), 400
    return jsonify(result)


@app.route('/api/internal/trivia/another', methods=['POST'])
@require_internal
def internal_trivia_another():
    """Play trivia on /play or "🎲 Another one" in Discord: an anytime question for this member."""
    import trivia
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    q, error = trivia.another(db.session.get(Group, _as_int(data.get('group_id')) or 0), user)
    if error:
        return jsonify({'error': error}), 400
    return jsonify(trivia.as_dict(q, user))


@app.route('/api/internal/play')
@require_internal
def internal_play():
    """/play: this member's day in the club — trivia, bingo, the quiz games
    the club has on, polls, kernels."""
    import play
    import quizzes
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group:
        return jsonify({'error': 'Group not found'}), 404
    games = [{k: g[k] for k in ('kind', 'emoji', 'label', 'each', 'cap', 'by_step', 'earned_today')}
             for g in quizzes.summary(group, user)]
    return jsonify({'club': group.name, **play.summary(group, user), 'games': games})


@app.route('/api/internal/bingo')
@require_internal
def internal_bingo():
    """/bingo: this member's card for the month."""
    import bingo
    user, err = resolve_discord_user(request.args)
    if err:
        return err
    return jsonify(bingo.view(db.session.get(Group, request.args.get('group_id', type=int) or 0), user))


# ─── Game posts in #movies (R14, game_posts.py) ────────────────────────────────

@app.route('/api/internal/games/posts')
@require_internal
def internal_game_posts():
    """What the bot should post in #movies now (the question of the day, the
    month's card, wins) — after bringing everything due up to date."""
    import game_posts
    game_posts.tick_if_due()
    group = db.session.get(Group, request.args.get('group_id', type=int) or 0)
    if not group or not discord_group(group.id):
        return jsonify({'posts': []})
    return jsonify({'posts': game_posts.ready_to_post(group)})


@app.route('/api/internal/games/posted', methods=['POST'])
@require_internal
def internal_game_posted():
    import game_posts
    data = request.json or {}
    post = db.session.get(GamePost, _as_int(data.get('post_id')) or 0)
    if not post:
        return jsonify({'error': 'Not found'}), 404
    game_posts.posted(post, data.get('message_id'))
    return jsonify({'ok': True})


@app.route('/api/internal/games/post/<int:post_id>', methods=['GET', 'POST'])
@require_internal
def internal_game_review(post_id):
    """An admin's review in their DM: GET the post as it'll look; POST
    {action: post | skip | another | reshuffle}."""
    import game_posts
    data = (request.json or {}) if request.method == 'POST' else request.args
    user, err = resolve_discord_user(data)
    if err:
        return err
    post = db.session.get(GamePost, post_id)
    if not post:
        return jsonify({'error': 'That post is gone.'}), 404
    if request.method == 'GET':
        if not role_at_least(_active_membership(user, post.group_id), 'organizer'):
            return jsonify({'error': 'Only club organizers and admins can do that.'}), 403
        return jsonify(game_posts.preview(post))
    view, err = game_posts.decide(post, user, data.get('action'))
    if view is None:
        return jsonify({'error': err}), 403
    return jsonify({**view, 'error': err})


# ─── Quotes (/quote, /quote random) ───────────────────────────────────────────
# The classics (the bot's original list, group None) show in every server;
# quotes a club adds show only in its server. Any member corrects their club's
# quotes; whoever added one, or that server's admins, remove it. The classics
# change everywhere, so they're corrected and removed only from the home server.

def _quote_fields(data):
    """Validated text/movie/character from a request. Returns (fields, error)."""
    text = (data.get('text') or '').strip()
    if not text:
        return None, (jsonify({'error': 'The quote is empty'}), 400)
    if len(text) > 2000:   # Discord's message limit — the bot posts the line as-is
        return None, (jsonify({'error': "Quotes can't be longer than a Discord message (2,000 characters)"}), 400)
    return {'text': text,
            'movie': (data.get('movie') or '').strip()[:200] or None,
            'character': (data.get('character') or '').strip()[:200] or None}, None


def _visible(query, group_id):
    """Quotes a club's server sees: the classics, and its own."""
    return query.filter(Quote.deleted_at.is_(None),
                        db.or_(Quote.group_id.is_(None), Quote.group_id == group_id) if group_id
                        else Quote.group_id.is_(None))


def _duplicate_quote(text, group_id, exclude_id=None):
    q = _visible(Quote.query, group_id).filter(db.func.lower(Quote.text) == text.lower())
    if exclude_id:
        q = q.filter(Quote.id != exclude_id)
    return q.first()


def _quote_group():
    """The club a quote request is for (none in a server not connected to a club)."""
    body = request.get_json(silent=True) if request.method != 'GET' else None
    return _as_int((body or {}).get('group_id')) or request.args.get('group_id', type=int)


def _may_change(quote, group_id):
    """A club's quote from its own server; a classic only from the home server."""
    return quote.group_id == group_id if quote.group_id else group_id == HOME_GROUP_ID


@app.route('/api/internal/quotes')
@require_internal
def internal_quotes():
    """The quotes a club's server sees (group_id: the classics and its own).
    With `q`: a search over text, movie and character (for /quote find and
    autocomplete). Without: the whole list, which the bot caches per club.
    `newest=1` puts recent additions first."""
    q = (request.args.get('q') or '').strip()
    limit = min(request.args.get('limit', 5000, type=int), 5000)
    query = _visible(Quote.query, _quote_group())
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Quote.text.ilike(like), Quote.movie.ilike(like),
                                    Quote.character.ilike(like)))
    order = Quote.id.desc() if request.args.get('newest') else Quote.id
    return jsonify([row.to_dict() for row in query.order_by(order).limit(limit)])


@app.route('/api/internal/quotes/<int:quote_id>')
@require_internal
def internal_quote(quote_id):
    quote = _visible(Quote.query, _quote_group()).filter(Quote.id == quote_id).first()
    if not quote:
        return jsonify({'error': 'Quote not found'}), 404
    return jsonify(quote.to_dict())


@app.route('/api/internal/quotes', methods=['POST'])
@require_internal
def internal_quote_add():
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    fields, err = _quote_fields(data)
    if err:
        return err
    group_id = _quote_group()
    if not group_id or not discord_group(group_id):
        return jsonify({'error': 'no_club'}), 400            # quotes are added in a club's server
    dupe = _duplicate_quote(fields['text'], group_id)
    if dupe:
        return jsonify({'error': 'duplicate', 'id': dupe.id}), 409
    quote = Quote(**fields, added_by=user.id, group_id=group_id)
    db.session.add(quote)
    db.session.commit()
    return jsonify(quote.to_dict()), 201


@app.route('/api/internal/quotes/<int:quote_id>', methods=['PUT'])
@require_internal
def internal_quote_edit(quote_id):
    """Any member can correct their club's quote or its source (a classic: in
    the home server); the last editor is kept."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group_id = _quote_group()
    quote = _visible(Quote.query, group_id).filter(Quote.id == quote_id).first()
    if not quote:
        return jsonify({'error': 'Quote not found'}), 404
    if not _may_change(quote, group_id):
        return jsonify({'error': 'classic'}), 403
    fields, err = _quote_fields(data)
    if err:
        return err
    dupe = _duplicate_quote(fields['text'], group_id, exclude_id=quote.id)
    if dupe:
        return jsonify({'error': 'duplicate', 'id': dupe.id}), 409
    for key, value in fields.items():
        setattr(quote, key, value)
    quote.updated_by, quote.updated_at = user.id, _utcnow_naive()
    db.session.commit()
    return jsonify(quote.to_dict())


@app.route('/api/internal/quotes/<int:quote_id>', methods=['DELETE'])
@require_internal
def internal_quote_remove(quote_id):
    """Removable by whoever added it, or that server's admins (the bot sends
    is_admin for members with Manage Server) — so nobody can wipe the list on a
    whim; a classic only by the home server's admins. Soft delete: the row
    stays, recoverable."""
    data = request.json or {}
    user, err = resolve_discord_user(data)
    if err:
        return err
    group_id = _quote_group()
    quote = _visible(Quote.query, group_id).filter(Quote.id == quote_id).first()
    if not quote:
        return jsonify({'error': 'Quote not found'}), 404
    if not _may_change(quote, group_id):
        return jsonify({'error': 'classic'}), 403
    if quote.added_by != user.id and not data.get('is_admin'):
        owner = quote.author.name if quote.author else 'the original list'
        return jsonify({'error': 'not_yours', 'added_by': owner}), 403
    quote.deleted_at, quote.deleted_by = _utcnow_naive(), user.id
    db.session.commit()
    return jsonify({'removed': quote.id})


@app.route('/api/internal/quotes/seed', methods=['POST'])
@require_internal
def internal_quotes_seed():
    """One-time import of the bot's built-in list (bot/quotes.py), sent by the
    bot at startup. It only runs while the table is completely empty, so it can
    never resurrect removed quotes or duplicate edited ones."""
    if Quote.query.first():
        return jsonify({'seeded': 0, 'skipped': []})
    seen, skipped = set(), []
    for item in (request.json or {}).get('quotes') or []:
        fields, err = _quote_fields(item)
        if not fields or fields['text'].lower() in seen:
            skipped.append((item.get('text') or '')[:60])
            continue
        seen.add(fields['text'].lower())
        db.session.add(Quote(**fields))
    db.session.commit()
    return jsonify({'seeded': len(seen), 'skipped': skipped})

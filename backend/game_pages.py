"""Play's game pages (Phase 3): Trivia, Higher or lower and Bingo each get a
page with your numbers for a period (this month, this year, all time), your
history, the club's board and the game's modes. The numbers come from the
games' own modules (trivia, quizzes, bingo) and club_stats, so the pages,
Records and the leaderboard count the same way."""
import json

import club_stats
import places

HISTORY = 15                    # the latest answers / runs a page lists
BINGO_HISTORY = 12              # past cards on the bingo page


def _since(group, period):
    return club_stats.since_of(period if period in club_stats.PERIODS else 'month', places.club_now(group))


def _members(group):
    from app import GroupMembership
    return [m.user for m in GroupMembership.query.filter_by(group_id=group.id, status='active') if m.user]


# ─── Trivia ───────────────────────────────────────────────────────────────────

def _current_streak(daily, mine, today):
    """Daily questions in a row answered right, back from the latest one
    (today's doesn't break it until the day is over)."""
    run = 0
    for q in sorted(daily, key=lambda x: x.day, reverse=True):
        if q.day == today and q.id not in mine:
            continue
        if not mine.get(q.id):
            break
        run += 1
    return run


def trivia(group, user, period='month'):
    """Your trivia (answered, right, streaks, by difficulty), your latest
    answers, and the club's board, for a period."""
    import trivia as t
    from app import TriviaAnswer, TriviaQuestion
    since = _since(group, period)
    q = TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id)
    if since:
        q = q.filter(TriviaQuestion.day >= since.date())
    questions = {x.id: x for x in q}
    mine = {a.question_id: a for a in TriviaAnswer.query.filter(TriviaAnswer.user_id == user.id,
                                                                 TriviaAnswer.question_id.in_(list(questions) or [0]))}
    levels = {lv: {'answered': 0, 'correct': 0} for lv in t.LEVELS}
    for qid, a in mine.items():
        lv = levels[questions[qid].difficulty or 'medium']
        lv['answered'] += 1
        lv['correct'] += bool(a.correct)
    daily = [x for x in questions.values() if x.slot == 'daily']
    stats = club_stats._trivia(group, [user.id], since)[user.id]
    you = {**stats, 'best_streak': stats['streak'],
           'streak': _current_streak(daily, {k: a.correct for k, a in mine.items()}, t.today(group)),
           'levels': levels, 'kernels': t.kernels_for([user.id], group.id, since).get(user.id, 0)}
    history = []
    for a in (TriviaAnswer.query.join(TriviaQuestion, TriviaAnswer.question_id == TriviaQuestion.id)
              .filter(TriviaAnswer.user_id == user.id, TriviaQuestion.group_id == group.id)
              .order_by(TriviaAnswer.answered_at.desc(), TriviaAnswer.id.desc()).limit(HISTORY)):
        x, options = a.question, json.loads(a.question.options_json)
        history.append({'id': x.id, 'day': x.day.isoformat(), 'prompt': x.prompt, 'daily': x.slot == 'daily',
                        'difficulty': x.difficulty or 'medium', 'correct': a.correct,
                        'yours': options[a.choice] if 0 <= a.choice < len(options) else None,
                        'answer': options[x.answer]})
    people = _members(group)
    board_stats = club_stats._trivia(group, [u.id for u in people], since)
    board = sorted(({'user': u.public_dict(), **board_stats[u.id]} for u in people if board_stats[u.id]['answered']),
                   key=lambda r: (-r['correct'], -(r['accuracy'] or 0), r['user']['name']))
    return {'enabled': bool(group.trivia_enabled or group.trivia_anytime), 'anytime': bool(group.trivia_anytime),
            'period': period, 'you': you, 'history': history, 'board': board}


# ─── Higher or lower ──────────────────────────────────────────────────────────

def higher_lower(group, user, period='month'):
    """Your runs (best, average, by decade), your latest, the club's best
    streaks, and the decades you can play, for a period."""
    import quizzes
    from app import QuizRound
    since = _since(group, period)
    q = QuizRound.query.filter(QuizRound.group_id == group.id, QuizRound.kind == 'higher_lower',
                               QuizRound.status == 'done')
    if since:
        q = q.filter(QuizRound.day >= since.date())
    runs = q.order_by(QuizRound.id.desc()).all()
    decade = lambda r: json.loads(r.state_json or '{}').get('decade')
    mine = [r for r in runs if r.user_id == user.id]
    by_mode = {}
    for r in mine:
        label = f'{decade(r)}s' if decade(r) else 'Classic'
        by_mode[label] = max(by_mode.get(label, 0), r.score)
    you = {'runs': len(mine), 'best': max((r.score for r in mine), default=0),
           'average': round(sum(r.score for r in mine) / len(mine), 1) if mine else None,
           'right': sum(r.score for r in mine), 'kernels': sum(r.earned for r in mine),
           'by_mode': [{'label': k, 'best': v} for k, v in sorted(by_mode.items(), key=lambda kv: (kv[0] != 'Classic', kv[0]))]}
    history = [{'id': r.id, 'day': r.day.isoformat(), 'score': r.score, 'earned': r.earned,
                'mode': f'{decade(r)}s' if decade(r) else 'Classic'} for r in mine[:HISTORY]]
    best = {}
    for r in runs:
        b = best.setdefault(r.user_id, {'best': 0, 'runs': 0})
        b['best'], b['runs'] = max(b['best'], r.score), b['runs'] + 1
    board = sorted(({'user': u.public_dict(), **best[u.id]} for u in _members(group) if u.id in best),
                   key=lambda r: (-r['best'], -r['runs'], r['user']['name']))
    return {'enabled': quizzes.on(group, 'higher_lower'), 'period': period, 'modes': quizzes.decades(group),
            'you': you, 'history': history, 'board': board,
            'left_today': max(0, quizzes.DAILY_CAP - quizzes.earned_today(user.id, group.id, 'higher_lower'))}


# ─── Bingo ────────────────────────────────────────────────────────────────────

def bingo(group, user, period='month'):
    """Your bingo (cards played, lines, full cards, kernels, your best month
    and the square you fill most), your past cards, and the club's board."""
    import bingo as b
    from app import BingoCard
    since = _since(group, period)
    first = b.month_of(since) if since else None
    cards = [c for c in BingoCard.query.filter_by(group_id=group.id).order_by(BingoCard.month.desc())
             if not first or c.month >= first]
    people = _members(group)
    totals = {u.id: {'lines': 0, 'cards': 0, 'kernels': 0, 'played': 0} for u in people}
    you = {'played': 0, 'lines': 0, 'cards': 0, 'kernels': 0, 'best': None, 'favorite': None}
    fills = {}
    for card in cards:
        for u in people:
            p = b.progress(card, u.id)
            row = totals[u.id]
            row['played'] += p['filled'] > 0
            row['lines'] += bool(p['line_at'])
            row['cards'] += bool(p['full_at'])
            row['kernels'] += p['kernels']
            if u.id != user.id:
                continue
            if p['filled'] and (not you['best'] or p['filled'] > you['best']['filled']):
                you['best'] = {'month': card.month, 'label': b.month_bounds(card.month)[0].strftime('%B %Y'),
                               'filled': p['filled']}
            for s in b.squares_of(p):
                if s['done'] and s['key'] != 'free':
                    fills[s['label']] = fills.get(s['label'], 0) + 1
    you.update({k: totals[user.id][k] for k in ('played', 'lines', 'cards', 'kernels')} if user.id in totals else {})
    if fills:
        label = max(sorted(fills), key=fills.get)
        you['favorite'] = {'label': label, 'count': fills[label]}
    this = b.month_of(places.club_now(group))
    history = [{'month': c.month, 'month_label': b.month_bounds(c.month)[0].strftime('%B %Y'), **b.mini(b.progress(c, user.id))}
               for c in BingoCard.query.filter(BingoCard.group_id == group.id, BingoCard.month < this)
               .order_by(BingoCard.month.desc()).limit(BINGO_HISTORY)]
    board = sorted(({'user': u.public_dict(), **totals[u.id]} for u in people if totals[u.id]['played']),
                   key=lambda r: (-r['cards'], -r['lines'], -r['kernels'], r['user']['name']))
    return {'enabled': bool(group.bingo_enabled), 'period': period, 'you': you, 'history': history, 'board': board}

"""Quiz games (R15), each its own switch in Club settings, all off to start
(Group.quizzes_json). One frame for all of them: a member starts a round, it
shows something, they answer, it pays kernels (within the game's daily cap)
and it's done — or, for a streak game, it goes on until a miss.

  higher_lower  a film and its year; the next film: before or after?
                +1 for each right call, a miss ends the run
  who_said      a line from a film, and four of its characters: who says it?
                +1 for a right answer

Rounds are private to the member playing (site or Discord). Films come from
the club's trivia source (film_pool: ours, TMDB's best known, or both).
"""
import json
import random
from datetime import datetime

import film_pool

# key: (emoji, label, what it is, kernels per right answer)
GAMES = {
    'higher_lower': ('↕️', 'Higher or lower', 'A film and its year — did the next one come out before or after? '
                     'Keep the streak going.', 1),
    'who_said': ('🗣️', 'Who said it', 'A line from a film and four of its characters: who says it?', 1),
}
DAILY_CAP = 5                       # kernels a day from each game
SPREAD = 30                         # higher or lower: the next film is within this many years


def today():
    return datetime.now().date()


def switches(group):
    """{game: on} for a club (all off until someone turns one on)."""
    try:
        raw = json.loads(group.quizzes_json or '{}')
    except ValueError:
        raw = {}
    return {k: bool(raw.get(k)) for k in GAMES}


def set_switches(group, data):
    """Turn games on or off from {game: bool} (unknown games are ignored)."""
    now = switches(group)
    for k, v in (data or {}).items():
        if k in GAMES and isinstance(v, bool):
            now[k] = v
    group.quizzes_json = json.dumps(now)


def on(group, kind):
    return bool(group) and switches(group).get(kind, False)


def earned_today(user_id, group_id, kind):
    from app import QuizRound
    return sum(r.earned for r in QuizRound.query.filter_by(user_id=user_id, group_id=group_id, kind=kind, day=today()))


def kernels_for(user_ids, group_id=None, since=None):
    """{uid: kernels from the quiz games} (one club's, or all; since a date)."""
    from app import db, QuizRound
    if not user_ids:
        return {}
    q = db.session.query(QuizRound.user_id, db.func.sum(QuizRound.earned)).filter(QuizRound.user_id.in_(list(user_ids)))
    if group_id:
        q = q.filter(QuizRound.group_id == group_id)
    if since:
        q = q.filter(QuizRound.day >= since.date())
    return {uid: int(n or 0) for uid, n in q.group_by(QuizRound.user_id)}


def _films(group):
    source = group.trivia_source if group.trivia_source in film_pool.SOURCES else 'both'
    subjects, everyone = film_pool.films(source)
    return (subjects or film_pool.films('local')[0]), everyone


def _brief(f, year=True):
    """What a round shows of a film."""
    return {'key': f.key, 'title': f.title, 'year': f.year if year else None, 'poster_url': f.poster_url,
            'movie_id': f.movie_id}


# ─── Higher or lower ──────────────────────────────────────────────────────────

def _next_film(rng, films, current, seen):
    near = [f for f in films if f.year and f.year != current['year'] and f.key not in seen
            and abs(f.year - current['year']) <= SPREAD]
    return rng.choice(near) if near else None


def _hl_start(group, rng):
    films = [f for f in _films(group)[0] if f.year]
    if len(films) < 2:
        return None
    first = rng.choice(films)
    nxt = _next_film(rng, films, {'year': first.year}, {first.key})
    return nxt and {'chain': [_brief(first), _brief(nxt)]}


def _hl_answer(group, state, choice, rng):
    """choice: 'before' | 'after'. Returns (right, done)."""
    cur, nxt = state['chain'][-2], state['chain'][-1]
    right = (choice == 'before') == (nxt['year'] < cur['year'])
    if not right:
        return False, True
    films = [f for f in _films(group)[0] if f.year]
    new = _next_film(rng, films, nxt, {c['key'] for c in state['chain']})
    if not new:
        return True, True                                  # out of films: a perfect run
    state['chain'].append(_brief(new))
    return True, False


def _hl_view(state, done):
    chain = state['chain']
    shown = [*chain[:-1], {**chain[-1], 'year': chain[-1]['year'] if done else None}]
    return {'current': shown[-2], 'next': shown[-1], 'history': shown[:-2]}


# ─── Who said it ──────────────────────────────────────────────────────────────

def _same_person(a, b):
    """'Rick Blaine' and 'Rick' are the same character."""
    wa = {w for w in a.lower().replace('.', '').split() if len(w) > 2}
    wb = {w for w in b.lower().replace('.', '').split() if len(w) > 2}
    return bool(wa & wb) or a.lower() == b.lower()


def _ws_start(group, rng):
    import discover
    from app import Quote
    quotes = [q for q in Quote.query.filter(Quote.deleted_at.is_(None)) if q.movie and q.character]
    if not quotes:
        return None
    _, everyone = _films(group)
    by_title = {}
    for f in everyone:
        by_title.setdefault(discover.normalize(f.title), []).append(f)
    for q in rng.sample(quotes, len(quotes)):
        films = by_title.get(discover.normalize(q.movie))
        if not films:
            continue
        f = film_pool.ensure_details(max(films, key=lambda x: x.votes))
        right = next((ch for ch in f.characters if _same_person(ch, q.character)), None)
        if not right:                   # the film's own name for them, so the answer doesn't stand out
            continue
        others = []
        for ch in f.characters:
            if not _same_person(ch, q.character) and not any(_same_person(ch, o) for o in others):
                others.append(ch)
        if len(others) < 3:
            continue
        options = [right, *rng.sample(others[:8], 3)]
        rng.shuffle(options)
        return {'quote': q.text, 'film': _brief(f), 'options': options, 'answer': options.index(right)}
    return None


def _ws_answer(group, state, choice, rng):
    return choice == state['answer'], True


def _ws_view(state, done):
    out = {'quote': state['quote'], 'film': state['film'], 'options': state['options']}
    if done:
        out['answer'] = state['answer']
    return out


RULES = {
    'higher_lower': (_hl_start, _hl_answer, _hl_view),
    'who_said': (_ws_start, _ws_answer, _ws_view),
}


# ─── Playing ──────────────────────────────────────────────────────────────────

def as_dict(r):
    """A round as its player sees it — answers only once it's over."""
    emoji, label, _, each = GAMES[r.kind]
    state = json.loads(r.state_json)
    done = r.status == 'done'
    return {'id': r.id, 'kind': r.kind, 'label': label, 'emoji': emoji, 'done': done, 'score': r.score,
            'earned': r.earned, 'each': each, 'left_today': max(0, DAILY_CAP - earned_today(r.user_id, r.group_id, r.kind)),
            'last': state.get('last'), **RULES[r.kind][2](state, done)}


def _check(group, user, kind):
    from app import require_role
    if kind not in GAMES:
        return "There's no such game."
    if not on(group, kind):
        return f'{GAMES[kind][1]} is off for this club.'
    _, err = require_role(user, group.id, 'member')
    return "Only club members can play." if err else None


def start(group, user, kind, source='site', rng=None):
    """Your round of `kind`: the one you're in the middle of, or a new one.
    Returns (round, error)."""
    from app import db, QuizRound
    err = _check(group, user, kind)
    if err:
        return None, err
    r = QuizRound.query.filter_by(group_id=group.id, user_id=user.id, kind=kind, status='open').first()
    if r:
        return r, None
    state = RULES[kind][0](group, rng or random.Random())
    if not state:
        return None, "There's nothing to play with yet — try again later."
    r = QuizRound(group_id=group.id, user_id=user.id, kind=kind, day=today(), state_json=json.dumps(state), source=source)
    db.session.add(r)
    db.session.commit()
    return r, None


def answer(group, user, round_id, choice, rng=None):
    """Answer your open round. Returns (round, error); the round says whether
    it was right ('last'), what it paid, and whether it's over."""
    from app import db, QuizRound
    r = db.session.get(QuizRound, round_id) if isinstance(round_id, int) else None
    if not r or r.group_id != getattr(group, 'id', None) or r.user_id != user.id:
        return None, "That round isn't yours."
    err = _check(group, user, r.kind)
    if err:
        return None, err
    if r.status == 'done':
        return None, "That round is over — start another."
    state = json.loads(r.state_json)
    right, done = RULES[r.kind][1](group, state, choice, rng or random.Random())
    pay = 0
    if right:
        r.score += 1
        pay = min(GAMES[r.kind][3], max(0, DAILY_CAP - earned_today(user.id, group.id, r.kind)))
        r.earned += pay
    state['last'] = {'right': right, 'paid': pay}
    r.state_json = json.dumps(state)
    if done:
        r.status, r.finished_at = 'done', datetime.utcnow()
    db.session.commit()
    return r, None


def summary(group, user):
    """Play's "More games": each game the club has on, what you've earned from
    it today, and the round you're in the middle of."""
    from app import QuizRound
    out = []
    for kind, (emoji, label, blurb, each) in GAMES.items():
        if not on(group, kind):
            continue
        r = QuizRound.query.filter_by(group_id=group.id, user_id=user.id, kind=kind, status='open').first()
        best = max((x.score for x in QuizRound.query.filter_by(group_id=group.id, user_id=user.id, kind=kind)), default=0)
        out.append({'kind': kind, 'emoji': emoji, 'label': label, 'blurb': blurb, 'each': each, 'cap': DAILY_CAP,
                    'earned_today': earned_today(user.id, group.id, kind), 'best': best,
                    'round': as_dict(r) if r else None})
    return out

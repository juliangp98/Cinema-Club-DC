"""Daily trivia (R10d): one question a day for each club that turned it on
(off by default — a club admin switches it on; posting it in Discord is a
second switch). Questions come from what we already know, so the answer is
always right: the films (who directed it, who's in it, which came first,
whose tagline — favoring films on the club's calendar) and the bot's quote
collection. One try each; a right answer is worth TRIVIA_KERNELS (kernels.py).
"""
import json
import random
from datetime import datetime, timedelta

TRIVIA_KERNELS = 2
REPEAT_AFTER = timedelta(days=90)      # the same film / quote isn't asked again for this long
CALENDAR_DAYS = 21                     # "on the calendar": playing at the club's theatres this soon
FAVOR_CALENDAR = 0.7


def today():
    return datetime.now().date()


def _label(m, year=True):
    y = (m.release_year or '')[:4]
    return f'{m.title} ({y})' if year and y else m.title


def _cast(m, n=6):
    try:
        return [c['name'] for c in json.loads(m.cast_json or '[]')[:n] if c.get('name')]
    except (ValueError, TypeError):
        return []


def _year(m):
    try:
        return int((m.release_year or '')[:4])
    except ValueError:
        return None


def _distinct(rng, values, exclude, k):
    """k different values (case-insensitive), none of them in `exclude`."""
    seen = {v.lower() for v in exclude}
    out = []
    for v in rng.sample(values, len(values)):
        if v and v.lower() not in seen:
            seen.add(v.lower())
            out.append(v)
            if len(out) == k:
                return out
    return None


def _choose(rng, candidates, on_calendar, recent, ref):
    """A candidate not asked recently, from the calendar most of the time."""
    fresh = [c for c in candidates if ref(c) not in recent]
    playing = [c for c in fresh if getattr(c, 'id', None) in on_calendar]
    pool = playing if playing and rng.random() < FAVOR_CALENDAR else fresh
    return rng.choice(pool) if pool else None


def _question(rng, kind, prompt, right, wrong, ref, movie_id=None):
    options = [right, *wrong]
    rng.shuffle(options)
    return {'kind': kind, 'prompt': prompt, 'options': options, 'answer': options.index(right),
            'ref': ref, 'movie_id': movie_id}


def _director(rng, films, on_calendar, recent, quotes):
    m = _choose(rng, [f for f in films if f.director], on_calendar, recent, lambda f: f'film:{f.id}')
    if not m:
        return None
    wrong = _distinct(rng, sorted({f.director for f in films if f.director}), [m.director], 3)
    return wrong and _question(rng, 'director', f'Who directed {_label(m)}?', m.director, wrong, f'film:{m.id}', m.id)


def _cast_q(rng, films, on_calendar, recent, quotes):
    m = _choose(rng, [f for f in films if len(_cast(f)) >= 3], on_calendar, recent, lambda f: f'film:{f.id}')
    if not m:
        return None
    right = rng.choice(_cast(m, 4))
    others = sorted({name for f in films if f.id != m.id for name in _cast(f, 4)})
    wrong = _distinct(rng, others, _cast(m, 50), 3)
    return wrong and _question(rng, 'cast', f'Who’s in {_label(m)}?', right, wrong, f'film:{m.id}', m.id)


def _first(rng, films, on_calendar, recent, quotes):
    dated = [f for f in films if _year(f)]
    m = _choose(rng, dated, on_calendar, recent, lambda f: f'film:{f.id}')
    if not m:
        return None
    by_year = {}
    for f in rng.sample(dated, len(dated)):
        if f.id != m.id and _year(f) != _year(m):
            by_year.setdefault(_year(f), f)
    if len(by_year) < 3:
        return None
    picks = [m, *rng.sample(list(by_year.values()), 3)]
    if len({_year(f) for f in picks}) < 4 or len({f.title.lower() for f in picks}) < 4:
        return None
    oldest = min(picks, key=_year)
    return _question(rng, 'first', 'Which came out first?', _label(oldest, year=False),
                     [_label(f, year=False) for f in picks if f is not oldest], f'film:{m.id}', oldest.id)


def _tagline(rng, films, on_calendar, recent, quotes):
    def usable(f):
        words = {w for w in f.title.lower().split() if len(w) > 3}
        return f.tagline and not any(w in f.tagline.lower() for w in words)
    m = _choose(rng, [f for f in films if usable(f)], on_calendar, recent, lambda f: f'film:{f.id}')
    if not m:
        return None
    wrong = _distinct(rng, sorted({_label(f) for f in films if f.id != m.id}), [_label(m)], 3)
    return wrong and _question(rng, 'tagline', f'Which film’s tagline is “{m.tagline}”?', _label(m), wrong,
                               f'film:{m.id}', m.id)


def _quote(rng, films, on_calendar, recent, quotes):
    q = _choose(rng, [q for q in quotes if q.movie], set(), recent, lambda q: f'quote:{q.id}')
    if not q:
        return None
    wrong = _distinct(rng, sorted({x.movie for x in quotes if x.movie}), [q.movie], 3)
    return wrong and _question(rng, 'quote', f'Which film is this line from? “{q.text}”', q.movie, wrong, f'quote:{q.id}')


BUILDERS = (_director, _cast_q, _first, _tagline, _quote)


def make_question(group, day):
    """Today's question for a club (not saved): the same club and day always
    give the same question; nothing about the same film or quote twice in
    REPEAT_AFTER."""
    from app import Movie, Quote, Showtime, TriviaQuestion, _group_showtime_query
    rng = random.Random(f'{group.id}:{day.isoformat()}')
    recent = {q.ref for q in TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id,
                                                         TriviaQuestion.day >= day - REPEAT_AFTER)}
    now = datetime.now()
    on_calendar = {mid for (mid,) in _group_showtime_query(group).with_entities(Showtime.movie_id).filter(
        Showtime.start_time >= now, Showtime.start_time < now + timedelta(days=CALENDAR_DAYS)).distinct()}
    films = Movie.query.filter(Movie.tmdb_id.isnot(None)).order_by(Movie.id).all()
    quotes = Quote.query.filter(Quote.deleted_at.is_(None)).order_by(Quote.id).all()
    builders = list(BUILDERS)
    rng.shuffle(builders)
    for build in builders:
        q = build(rng, films, on_calendar, recent, quotes)
        if q:
            return q
    return None


def question_for(group, day=None):
    """The club's question for `day` (today), made and saved on first ask.
    None if trivia's off, or there's nothing to ask about."""
    from sqlalchemy.exc import IntegrityError
    from app import db, TriviaQuestion
    if not group or not group.trivia_enabled:
        return None
    day = day or today()
    q = TriviaQuestion.query.filter_by(group_id=group.id, day=day).first()
    if q:
        return q
    made = make_question(group, day)
    if not made:
        return None
    q = TriviaQuestion(group_id=group.id, day=day, kind=made['kind'], prompt=made['prompt'],
                       options_json=json.dumps(made['options']), answer=made['answer'],
                       movie_id=made['movie_id'], ref=made['ref'])
    db.session.add(q)
    try:
        db.session.commit()
    except IntegrityError:                     # someone else asked at the same moment
        db.session.rollback()
        q = TriviaQuestion.query.filter_by(group_id=group.id, day=day).first()
    return q


def as_dict(q, user=None, reveal=False):
    """A question for showing: the right answer, the tally and the film only
    once you've answered (or it's an earlier day's)."""
    from app import db, Movie, TriviaAnswer
    out = {'id': q.id, 'day': q.day.isoformat(), 'kind': q.kind, 'prompt': q.prompt,
           'options': json.loads(q.options_json), 'kernels': TRIVIA_KERNELS}
    mine = TriviaAnswer.query.filter_by(question_id=q.id, user_id=user.id).first() if user else None
    if mine:
        out['mine'] = {'choice': mine.choice, 'correct': mine.correct}
    if mine or reveal:
        answers = TriviaAnswer.query.filter_by(question_id=q.id).all()
        out['answer'] = q.answer
        out['stats'] = {'answered': len(answers), 'correct': sum(a.correct for a in answers)}
        m = db.session.get(Movie, q.movie_id) if q.movie_id else None
        if m:
            out['movie'] = {'id': m.id, 'title': m.title, 'poster_url': m.poster_url}
    return out


def today_for(group, user):
    """{'enabled', 'question', 'yesterday'} for the trivia card / /trivia."""
    from app import TriviaQuestion
    if not group or not group.trivia_enabled:
        return {'enabled': False}
    q = question_for(group)
    prev = (TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id, TriviaQuestion.day < today())
            .order_by(TriviaQuestion.day.desc()).first())
    return {'enabled': True, 'question': as_dict(q, user) if q else None,
            'yesterday': as_dict(prev, user, reveal=True) if prev and prev.day == today() - timedelta(days=1) else None}


def answer(group, user, question_id, choice, source='site'):
    """Record `user`'s one answer to today's question. Returns (result, error)."""
    from sqlalchemy.exc import IntegrityError
    from app import db, TriviaAnswer, TriviaQuestion, require_role
    if not group or not group.trivia_enabled:
        return None, "Trivia is off for this club."
    _, err = require_role(user, group.id, 'member')
    if err:
        return None, "Only club members can answer."
    q = db.session.get(TriviaQuestion, question_id) if isinstance(question_id, int) else None
    if not q or q.group_id != group.id:
        return None, "That question isn't this club's."
    if q.day != today():
        return None, "That was an earlier day's question — try today's."
    if not isinstance(choice, int) or not 0 <= choice < len(json.loads(q.options_json)):
        return None, 'Pick one of the answers.'
    if TriviaAnswer.query.filter_by(question_id=q.id, user_id=user.id).first():
        return None, 'You already answered today’s question.'
    db.session.add(TriviaAnswer(question_id=q.id, user_id=user.id, choice=choice, correct=choice == q.answer,
                                source=source))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, 'You already answered today’s question.'
    return as_dict(q, user), None


def correct_counts(user_ids, group_id=None):
    """{uid: right answers} (for kernels)."""
    from app import db, TriviaAnswer, TriviaQuestion
    if not user_ids:
        return {}
    q = (db.session.query(TriviaAnswer.user_id, db.func.count(TriviaAnswer.id))
         .join(TriviaQuestion, TriviaAnswer.question_id == TriviaQuestion.id)
         .filter(TriviaAnswer.user_id.in_(list(user_ids)), TriviaAnswer.correct.is_(True)))
    if group_id:
        q = q.filter(TriviaQuestion.group_id == group_id)
    return dict(q.group_by(TriviaAnswer.user_id).all())

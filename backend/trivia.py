"""Trivia (R10d), all off until a club admin turns it on:

  question of the day   one a day for the club, the same for everyone
                        (group.trivia_enabled; posting it in Discord is
                        group.trivia_discord, a second yes); right = +2
  anytime               extra questions whenever a member asks
                        (group.trivia_anytime), private to them, one
                        unanswered at a time; right = +1, at most 5 a day

Questions come from what we already know, so the answer is always right:
the films (who directed it, who's in it, which came first, whose tagline —
favoring films on the club's calendar) and the bot's quote collection.
One try each.
"""
import json
import random
from datetime import datetime, timedelta

TRIVIA_KERNELS = 2                     # a right answer to the question of the day
ANYTIME_KERNELS, ANYTIME_DAILY_CAP = 1, 5   # anytime questions: +1 each, at most 5 kernels a day
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


def make_question(group, day, rng=None, recent=None):
    """A question for a club (not saved). The question of the day: the same
    club and day always give the same one, and nothing about the same film or
    quote as the club's other recent daily questions (REPEAT_AFTER). Anytime
    questions pass their own `rng` and `recent`."""
    from app import Movie, Quote, Showtime, TriviaQuestion, _group_showtime_query
    rng = rng or random.Random(f'{group.id}:{day.isoformat()}')
    if recent is None:
        recent = {q.ref for q in TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id,
                                                             TriviaQuestion.slot == 'daily',
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
    q = TriviaQuestion.query.filter_by(group_id=group.id, day=day, slot='daily').first()
    if q:
        return q
    made = make_question(group, day)
    if not made:
        return None
    q = _save(group, day, 'daily', made)
    try:
        db.session.commit()
    except IntegrityError:                     # someone else asked at the same moment
        db.session.rollback()
        q = TriviaQuestion.query.filter_by(group_id=group.id, day=day, slot='daily').first()
    return q


def swap(q):
    """A different question of the day (R14: an admin's "Try another" before
    it's posted) — only while nobody has answered it. Returns an error or None."""
    from app import db, Group, TriviaAnswer, TriviaQuestion
    if TriviaAnswer.query.filter_by(question_id=q.id).first():
        return "Someone has answered it already, so it can't be swapped now."
    group = db.session.get(Group, q.group_id)
    recent = {x.ref for x in TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id,
                                                         TriviaQuestion.day >= q.day - REPEAT_AFTER)}
    made = make_question(group, q.day, rng=random.Random(), recent=recent | {q.ref})
    if not made:
        return "There isn't another question to ask today."
    q.kind, q.prompt, q.options_json, q.answer = made['kind'], made['prompt'], json.dumps(made['options']), made['answer']
    q.movie_id, q.ref = made['movie_id'], made['ref']
    db.session.commit()
    return None


def _save(group, day, slot, made, asked_by=None):
    from app import db, TriviaQuestion
    q = TriviaQuestion(group_id=group.id, day=day, slot=slot, asked_by=asked_by, kind=made['kind'],
                       prompt=made['prompt'], options_json=json.dumps(made['options']), answer=made['answer'],
                       movie_id=made['movie_id'], ref=made['ref'])
    db.session.add(q)
    return q


def waiting_anytime(group, user):
    """The anytime question this member asked for and hasn't answered yet."""
    from app import TriviaAnswer, TriviaQuestion
    answered = TriviaAnswer.query.filter(TriviaAnswer.user_id == user.id).with_entities(TriviaAnswer.question_id)
    return (TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id, TriviaQuestion.asked_by == user.id,
                                        TriviaQuestion.day == today(), ~TriviaQuestion.id.in_(answered))
            .order_by(TriviaQuestion.id.desc()).first())


def another(group, user):
    """An anytime question for `user` (R10d): their unanswered one if there is
    one (no skipping to an easier one), else a new one about something they
    haven't been asked lately. Returns (question, error)."""
    from sqlalchemy.exc import IntegrityError
    from app import db, TriviaQuestion, require_role
    if not group or not group.trivia_anytime:
        return None, "Anytime trivia is off for this club."
    _, err = require_role(user, group.id, 'member')
    if err:
        return None, "Only club members can play."
    waiting = waiting_anytime(group, user)
    if waiting:
        return waiting, None
    day = today()
    mine = TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id, TriviaQuestion.day >= day - REPEAT_AFTER,
                                       (TriviaQuestion.asked_by == user.id) | (TriviaQuestion.slot == 'daily')).all()
    n = sum(1 for q in mine if q.asked_by == user.id and q.day == day) + 1
    made = make_question(group, day, rng=random.Random(f'{group.id}:{user.id}:{day.isoformat()}:{n}'),
                         recent={q.ref for q in mine})
    if not made:
        return None, "We're out of questions for now — try again tomorrow."
    q = _save(group, day, f'{user.id}:{n}', made, asked_by=user.id)
    try:
        db.session.commit()
    except IntegrityError:                     # a double tap
        db.session.rollback()
        return waiting_anytime(group, user), None
    return q, None


def as_dict(q, user=None, reveal=False):
    """A question for showing: the right answer, the tally and the film only
    once you've answered (or it's an earlier day's)."""
    from app import db, Movie, TriviaAnswer
    anytime = q.slot != 'daily'
    out = {'id': q.id, 'day': q.day.isoformat(), 'kind': q.kind, 'prompt': q.prompt, 'anytime': anytime,
           'options': json.loads(q.options_json), 'kernels': ANYTIME_KERNELS if anytime else TRIVIA_KERNELS}
    if anytime and user:
        out['kernels_left_today'] = max(0, ANYTIME_DAILY_CAP - _anytime_today(user.id, q.group_id))
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
    """For the trivia card / /trivia: {'enabled' (either kind is on), 'daily'
    and 'anytime' (which are), 'question' (the question of the day),
    'yesterday' (with its answer), 'waiting' (your unanswered anytime one)}."""
    from app import TriviaQuestion
    daily, anytime = bool(group and group.trivia_enabled), bool(group and group.trivia_anytime)
    if not (daily or anytime):
        return {'enabled': False}
    out = {'enabled': True, 'daily': daily, 'anytime': anytime, 'question': None, 'yesterday': None, 'waiting': None}
    if daily:
        q = question_for(group)
        prev = (TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id, TriviaQuestion.slot == 'daily',
                                            TriviaQuestion.day < today())
                .order_by(TriviaQuestion.day.desc()).first())
        out['question'] = as_dict(q, user) if q else None
        out['yesterday'] = as_dict(prev, user, reveal=True) if prev and prev.day == today() - timedelta(days=1) else None
    if anytime and user:
        w = waiting_anytime(group, user)
        out['waiting'] = as_dict(w, user) if w else None
    return out


def answer(group, user, question_id, choice, source='site'):
    """Record `user`'s one answer to today's question. Returns (result, error)."""
    from sqlalchemy.exc import IntegrityError
    from app import db, TriviaAnswer, TriviaQuestion, require_role
    q = db.session.get(TriviaQuestion, question_id) if isinstance(question_id, int) else None
    if not group or not (group.trivia_anytime if q and q.slot != 'daily' else group.trivia_enabled):
        return None, "Trivia is off for this club."
    _, err = require_role(user, group.id, 'member')
    if err:
        return None, "Only club members can answer."
    if not q or q.group_id != group.id or (q.asked_by and q.asked_by != user.id):
        return None, "That question isn't yours to answer."
    if q.day != today():
        return None, "That was an earlier day's question — try today's."
    if not isinstance(choice, int) or not 0 <= choice < len(json.loads(q.options_json)):
        return None, 'Pick one of the answers.'
    if TriviaAnswer.query.filter_by(question_id=q.id, user_id=user.id).first():
        return None, 'You already answered that one.'
    right = choice == q.answer
    if not right:
        earned = 0
    elif q.slot == 'daily':
        earned = TRIVIA_KERNELS
    else:
        earned = max(0, min(ANYTIME_KERNELS, ANYTIME_DAILY_CAP - _anytime_today(user.id, group.id)))
    db.session.add(TriviaAnswer(question_id=q.id, user_id=user.id, choice=choice, correct=right, source=source))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, 'You already answered that one.'
    return {**as_dict(q, user), 'earned': earned, 'anytime_on': bool(group.trivia_anytime)}, None


def kernels_for(user_ids, group_id=None):
    """{uid: trivia kernels}: +2 per right answer to a question of the day,
    +1 per right anytime answer up to ANYTIME_DAILY_CAP a day (per club)."""
    from app import db, TriviaAnswer, TriviaQuestion
    if not user_ids:
        return {}
    q = (db.session.query(TriviaAnswer.user_id, TriviaQuestion.group_id, TriviaQuestion.day, TriviaQuestion.slot)
         .join(TriviaQuestion, TriviaAnswer.question_id == TriviaQuestion.id)
         .filter(TriviaAnswer.user_id.in_(list(user_ids)), TriviaAnswer.correct.is_(True)))
    if group_id:
        q = q.filter(TriviaQuestion.group_id == group_id)
    out, anytime = {}, {}
    for uid, gid, day, slot in q:
        if slot == 'daily':
            out[uid] = out.get(uid, 0) + TRIVIA_KERNELS
        else:
            anytime[(uid, gid, day)] = anytime.get((uid, gid, day), 0) + ANYTIME_KERNELS
    for (uid, _, _), k in anytime.items():
        out[uid] = out.get(uid, 0) + min(k, ANYTIME_DAILY_CAP)
    return out


def _anytime_today(user_id, group_id):
    """Kernels from anytime questions today (toward the daily cap)."""
    from app import TriviaAnswer, TriviaQuestion
    n = (TriviaAnswer.query.join(TriviaQuestion, TriviaAnswer.question_id == TriviaQuestion.id)
         .filter(TriviaAnswer.user_id == user_id, TriviaAnswer.correct.is_(True), TriviaQuestion.group_id == group_id,
                 TriviaQuestion.slot != 'daily', TriviaQuestion.day == today()).count())
    return min(n * ANYTIME_KERNELS, ANYTIME_DAILY_CAP)

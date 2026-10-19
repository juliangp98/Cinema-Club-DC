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
from datetime import timedelta

import film_pool
import places

# Kernels for a right answer by difficulty (R15; questions from before it count as medium).
DAILY_KERNELS = {'easy': 1, 'medium': 2, 'hard': 3}        # the question of the day
ANYTIME_KERNEL_TABLE = {'easy': 1, 'medium': 1, 'hard': 2}  # anytime questions…
ANYTIME_DAILY_CAP = 5                                       # …at most this many kernels a day
TRIVIA_KERNELS = DAILY_KERNELS['medium']                    # what the question of the day is usually worth
ANYTIME_KERNELS = ANYTIME_KERNEL_TABLE['medium']


def worth(slot, difficulty):
    """Kernels a right answer earns (before the anytime cap)."""
    table = DAILY_KERNELS if slot == 'daily' else ANYTIME_KERNEL_TABLE
    return table.get(difficulty or 'medium', table['medium'])
REPEAT_AFTER = timedelta(days=90)      # the same film / quote isn't asked again for this long
CALENDAR_DAYS = 21                     # "on the calendar": playing at the club's theatres this soon
FAVOR_CALENDAR = 0.7


def today(group=None):
    """The club's day (its city's clock)."""
    import places
    return places.club_now(group).date()


def _choose(rng, subjects, c, ok=lambda f: True):
    """A film not asked about recently (and passing `ok`): from the club's
    calendar most of the time when the club asks about its own films, a
    third of the time when it asks about both, never for the TMDB pool."""
    fresh = [f for f in subjects if f.key not in c['recent'] and ok(f)]
    playing = [f for f in fresh if f.movie_id in c['on_calendar']]
    favor = {'local': FAVOR_CALENDAR, 'both': 0.35}.get(c['source'], 0)
    pool = playing if playing and rng.random() < favor else fresh
    return rng.choice(pool) if pool else None


def _choose_detailed(rng, c, has):
    """A film with the people a question needs (`has`): pool films' are
    looked up (a few tries at most) when one comes up without them."""
    tried = set()
    for _ in range(film_pool.DETAILS_PER_QUESTION + 1):
        f = _choose(rng, c['subjects'], c, ok=lambda x: x.key not in tried and (has(x) or (x.pool and not x.pool.details_at
                                                                                          and not x.movie_id)))
        if not f:
            return None
        film_pool.ensure_details(f)
        if has(f):
            return f
        tried.add(f.key)
    return None


def _alike_people(rng, f, c, people_of, exclude, k=3, top=15):
    """k different people (directors, actors) from the films most like `f` —
    none of them in `exclude` — each with the film they're from."""
    seen = {p.lower() for p in exclude}
    ranked = sorted((x for x in c['everyone'] if x.key != f.key and people_of(x)),
                    key=lambda x: -film_pool.similarity(f, x))
    order = rng.sample(ranked[:top], min(top, len(ranked))) + ranked[top:]
    picks = []
    for x in order:
        for p in people_of(x):
            if p and p.lower() not in seen:
                seen.add(p.lower())
                picks.append((p, x))
                break
        if len(picks) == k:
            return picks
    return None


def _known(f, c):
    """-1 for a film on the club's calendar (members have seen it listed: a step easier)."""
    return -1 if f.movie_id and f.movie_id in c['on_calendar'] else 0


def _question(rng, kind, prompt, right, wrong, film=None, ref=None, difficulty=film_pool.MEDIUM):
    options = [right, *wrong]
    rng.shuffle(options)
    return {'kind': kind, 'prompt': prompt, 'options': options, 'answer': options.index(right),
            'ref': ref or film.key, 'movie_id': film.movie_id if film else None,
            'tmdb_id': film.tmdb_id if film and not film.movie_id else None, 'difficulty': difficulty}


def _director(rng, c):
    f = _choose_detailed(rng, c, lambda x: bool(x.director))
    picks = f and _alike_people(rng, f, c, lambda x: [x.director] if x.director else [], [f.director])
    return picks and _question(rng, 'director', f'Who directed {f.label}?', f.director, [p for p, _ in picks], f,
                               difficulty=film_pool.difficulty(f, [x for _, x in picks], _known(f, c)))


def _cast_q(rng, c):
    f = _choose_detailed(rng, c, lambda x: len(x.cast) >= 3)
    if not f:
        return None
    right = rng.choice(f.cast[:3])                                # the top billed: fair to know
    picks = _alike_people(rng, f, c, lambda x: x.cast[:3], f.cast)
    return picks and _question(rng, 'cast', f'Who’s in {f.label}?', right, [p for p, _ in picks], f,
                               difficulty=film_pool.difficulty(f, [x for _, x in picks], _known(f, c)))


def _first(rng, c, top=20):
    f = _choose(rng, c['subjects'], c, ok=lambda x: bool(x.year))
    if not f:
        return None
    ranked = sorted((x for x in c['everyone'] if x.year and x.key != f.key), key=lambda x: -film_pool.similarity(f, x))
    picks, years, titles = [f], {f.year}, {f.title.lower()}
    for x in rng.sample(ranked[:top], min(top, len(ranked))) + ranked[top:]:
        if x.year not in years and x.title.lower() not in titles:
            picks.append(x)
            years.add(x.year)
            titles.add(x.title.lower())
            if len(picks) == 4:
                break
    if len(picks) < 4:
        return None
    oldest = min(picks, key=lambda x: x.year)
    close = 1 if max(years) - min(years) <= 8 else 0              # years this close are hard to call
    return _question(rng, 'first', 'Which came out first?', oldest.title, [x.title for x in picks if x is not oldest],
                     oldest, ref=f.key, difficulty=film_pool.difficulty(f, picks[1:], extra=close + _known(f, c)))


def _tagline(rng, c):
    def usable(x):
        words = {w for w in x.title.lower().split() if len(w) > 3}
        return bool(x.tagline) and not any(w in x.tagline.lower() for w in words)
    f = _choose_detailed(rng, c, usable)
    others = f and film_pool.lookalikes(f, c['everyone'], rng)
    return others and _question(rng, 'tagline', f'Which film’s tagline is “{f.tagline}”?', f.label,
                                [x.label for x in others], f, difficulty=film_pool.difficulty(f, others, _known(f, c)))


def _quote(rng, c):
    import discover
    fresh = [x for x in c['quotes'] if x.movie and f'quote:{x.id}' not in c['recent']]
    if not fresh:
        return None
    q = rng.choice(fresh)
    want = discover.normalize(q.movie)
    films = [x for x in c['everyone'] if discover.normalize(x.title) == want]
    f = max(films, key=lambda x: x.votes) if films else None
    prompt = f'Which film is this line from? “{q.text}”'
    if f:
        others = film_pool.lookalikes(f, c['everyone'], rng)
        return others and _question(rng, 'quote', prompt, f.label, [x.label for x in others], f, ref=f'quote:{q.id}',
                                    difficulty=film_pool.difficulty(f, others))
    names = sorted({x.movie for x in c['quotes'] if x.movie and x.movie.lower() != q.movie.lower()})
    wrong = rng.sample(names, 3) if len(names) >= 3 else None
    return wrong and _question(rng, 'quote', prompt, q.movie, wrong, ref=f'quote:{q.id}')


BUILDERS = (_director, _cast_q, _first, _tagline, _quote)


def make_question(group, day, rng=None, recent=None):
    """A question for a club (not saved). The question of the day: the same
    club and day always give the same one, and nothing about the same film or
    quote as the club's other recent daily questions (REPEAT_AFTER). Anytime
    questions pass their own `rng` and `recent`. Its film comes from the
    club's source (film_pool: our films, TMDB's best known, or both); its
    wrong answers are look-alikes from both, and it carries a difficulty."""
    from app import Quote, Showtime, TriviaQuestion, _group_showtime_query
    rng = rng or random.Random(f'{group.id}:{day.isoformat()}')
    if recent is None:
        recent = {q.ref for q in TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id,
                                                             TriviaQuestion.slot == 'daily',
                                                             TriviaQuestion.day >= day - REPEAT_AFTER)}
    now = places.club_now(group)
    on_calendar = {mid for (mid,) in _group_showtime_query(group).with_entities(Showtime.movie_id).filter(
        Showtime.start_time >= now, Showtime.start_time < now + timedelta(days=CALENDAR_DAYS)).distinct()}
    source = group.trivia_source if group.trivia_source in film_pool.SOURCES else 'both'
    subjects, everyone = film_pool.films(source)
    if not subjects:                                          # the pool isn't filled yet: our films for now
        source = 'local'
        subjects, everyone = film_pool.films('local')
    c = {'subjects': subjects, 'everyone': everyone, 'on_calendar': on_calendar, 'recent': recent, 'source': source,
         'quotes': Quote.query.filter(Quote.deleted_at.is_(None)).order_by(Quote.id).all()}
    builders = list(BUILDERS)
    rng.shuffle(builders)
    for build in builders:
        q = build(rng, c)
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
    day = day or today(group)
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
    q.tmdb_id, q.difficulty = made.get('tmdb_id'), made.get('difficulty')
    db.session.commit()
    return None


def _save(group, day, slot, made, asked_by=None):
    from app import db, TriviaQuestion
    q = TriviaQuestion(group_id=group.id, day=day, slot=slot, asked_by=asked_by, kind=made['kind'],
                       prompt=made['prompt'], options_json=json.dumps(made['options']), answer=made['answer'],
                       movie_id=made['movie_id'], ref=made['ref'], tmdb_id=made.get('tmdb_id'),
                       difficulty=made.get('difficulty'))
    db.session.add(q)
    return q


def waiting_anytime(group, user):
    """The anytime question this member asked for and hasn't answered yet."""
    from app import TriviaAnswer, TriviaQuestion
    answered = TriviaAnswer.query.filter(TriviaAnswer.user_id == user.id).with_entities(TriviaAnswer.question_id)
    return (TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id, TriviaQuestion.asked_by == user.id,
                                        TriviaQuestion.day == today(group), ~TriviaQuestion.id.in_(answered))
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
    day = today(group)
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
    """A question for showing: how hard it is and what it's worth; the right
    answer, the tally and the film only once you've answered (or it's an
    earlier day's)."""
    from app import db, Movie, PoolFilm, TriviaAnswer
    anytime = q.slot != 'daily'
    out = {'id': q.id, 'day': q.day.isoformat(), 'kind': q.kind, 'prompt': q.prompt, 'anytime': anytime,
           'options': json.loads(q.options_json), 'kernels': worth(q.slot, q.difficulty),
           'difficulty': q.difficulty or film_pool.MEDIUM}
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
        p = PoolFilm.query.filter_by(tmdb_id=q.tmdb_id).first() if q.tmdb_id and not m else None
        if m:
            out['movie'] = {'id': m.id, 'title': film_pool.nice_title(m.title), 'poster_url': m.poster_url}
        elif p:                                               # a TMDB pool film (no page of ours yet)
            out['movie'] = {'id': None, 'tmdb_id': p.tmdb_id, 'title': p.title, 'poster_url': p.poster_url}
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
                                            TriviaQuestion.day < today(group))
                .order_by(TriviaQuestion.day.desc()).first())
        out['question'] = as_dict(q, user) if q else None
        out['yesterday'] = as_dict(prev, user, reveal=True) if prev and prev.day == today(group) - timedelta(days=1) else None
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
    if q.day != today(group):
        return None, "That was an earlier day's question — try today's."
    if not isinstance(choice, int) or not 0 <= choice < len(json.loads(q.options_json)):
        return None, 'Pick one of the answers.'
    if TriviaAnswer.query.filter_by(question_id=q.id, user_id=user.id).first():
        return None, 'You already answered that one.'
    right = choice == q.answer
    if not right:
        earned = 0
    elif q.slot == 'daily':
        earned = worth('daily', q.difficulty)
    else:
        earned = max(0, min(worth(q.slot, q.difficulty), ANYTIME_DAILY_CAP - _anytime_today(user.id, group.id)))
    db.session.add(TriviaAnswer(question_id=q.id, user_id=user.id, choice=choice, correct=right, source=source))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return None, 'You already answered that one.'
    return {**as_dict(q, user), 'earned': earned, 'anytime_on': bool(group.trivia_anytime)}, None


def kernels_for(user_ids, group_id=None, since=None):
    """{uid: trivia kernels}: a right answer to a question of the day is
    worth its difficulty (DAILY_KERNELS), anytime ones too (ANYTIME_KERNEL_TABLE)
    up to ANYTIME_DAILY_CAP a day (per club); with `since`, only questions
    from that day on."""
    from app import db, TriviaAnswer, TriviaQuestion
    if not user_ids:
        return {}
    q = (db.session.query(TriviaAnswer.user_id, TriviaQuestion.group_id, TriviaQuestion.day, TriviaQuestion.slot,
                          TriviaQuestion.difficulty)
         .join(TriviaQuestion, TriviaAnswer.question_id == TriviaQuestion.id)
         .filter(TriviaAnswer.user_id.in_(list(user_ids)), TriviaAnswer.correct.is_(True)))
    if group_id:
        q = q.filter(TriviaQuestion.group_id == group_id)
    if since:
        q = q.filter(TriviaQuestion.day >= since.date())
    out, anytime = {}, {}
    for uid, gid, day, slot, level in q:
        if slot == 'daily':
            out[uid] = out.get(uid, 0) + worth('daily', level)
        else:
            anytime[(uid, gid, day)] = anytime.get((uid, gid, day), 0) + worth(slot, level)
    for (uid, _, _), k in anytime.items():
        out[uid] = out.get(uid, 0) + min(k, ANYTIME_DAILY_CAP)
    return out


def _anytime_today(user_id, group_id):
    """Kernels from anytime questions today (toward the daily cap)."""
    from app import db, Group, TriviaAnswer, TriviaQuestion
    day = today(db.session.get(Group, group_id))
    rows = (TriviaQuestion.query.join(TriviaAnswer, TriviaAnswer.question_id == TriviaQuestion.id)
            .filter(TriviaAnswer.user_id == user_id, TriviaAnswer.correct.is_(True), TriviaQuestion.group_id == group_id,
                    TriviaQuestion.slot != 'daily', TriviaQuestion.day == day).all())
    return min(sum(worth(q.slot, q.difficulty) for q in rows), ANYTIME_DAILY_CAP)

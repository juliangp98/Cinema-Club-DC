"""Quiz games (R15), each its own switch in Club settings, all off to start
(Group.quizzes_json). One frame for all of them: a member starts a round, it
shows something, they answer, it pays kernels (within the game's daily cap)
and it's done — or, for a streak game, it goes on until a miss.

  higher_lower  a film and its year; the next film: before or after?
                +1 for each right call, a miss ends the run
  who_said      a line from a film, and four of its characters: who says it?
                +1 for a right answer
  still         a still from a film, close up, then wider, then whole:
                3 / 2 / 1 kernels by how much you needed to see
  reviews       a line from three reviews (club members' diaries first —
                never named — then TMDB's), revealed one at a time: 3 / 2 / 1
  emoji         a film's plot told in emojis (the AI's, made once per film
                and kept): which film? +1

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
    'still': ('🖼️', 'Guess the still', 'A still from a film, close up — zoom out if you need to. '
              'The less you see, the more it pays.', 3),
    'reviews': ('📝', 'Guess from the reviews', 'A line from a review — another if you need it. '
                'The fewer it takes, the more it pays.', 3),
    'emoji': ('🎭', 'Emoji plot', "A film's story told in emojis: which film is it?", 1),
}
STEP_PAY = {1: 3, 2: 2, 3: 1}       # still / reviews: kernels for a right answer at each reveal
BY_STEP = ('still', 'reviews')      # the games that pay by how much you needed to see
STILL_ZOOM = {1: 4, 2: 2, 3: 1}     # how close the still is at each step
DAILY_CAP = 5                       # kernels a day from each game
SPREAD = 30                         # higher or lower: the next film is within this many years


def today(group=None):
    """The club's day (its city's clock)."""
    import places
    return places.club_now(group).date()


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
    from app import db, Group
    day = today(db.session.get(Group, group_id))
    return sum(r.earned for r in QuizRound.query.filter_by(user_id=user_id, group_id=group_id, kind=kind, day=day))


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


# ─── Guess the still ──────────────────────────────────────────────────────────

def _backdrops(tmdb_id):
    """TMDB's stills for a film (no text on them first), best voted first."""
    import enrich
    try:
        r = enrich._http.get(f'{enrich.TMDB_BASE}/movie/{tmdb_id}/images', headers=enrich._tmdb_headers(), timeout=10,
                             params={'include_image_language': 'null'})
        r.raise_for_status()
        rows = r.json().get('backdrops') or []
    except Exception as e:
        print(f'  still: TMDB images for {tmdb_id} failed: {e}')
        return []
    return [b['file_path'] for b in sorted(rows, key=lambda b: -(b.get('vote_count') or 0)) if b.get('file_path')]


def _options(rng, f, everyone):
    others = film_pool.lookalikes(f, everyone, rng)
    if not others:
        return None
    options = [f.label, *[o.label for o in others]]
    rng.shuffle(options)
    return options


def _still_start(group, rng, tries=4):
    import secrets
    subjects, everyone = _films(group)
    films = [f for f in subjects if f.tmdb_id]
    for f in rng.sample(films, min(tries, len(films))):
        stills = _backdrops(f.tmdb_id)
        options = stills and _options(rng, f, everyone)
        if options:
            return {'path': rng.choice(stills[:5]), 'focus': [rng.uniform(0.3, 0.7), rng.uniform(0.3, 0.7)],
                    'token': secrets.token_hex(8), 'step': 1, 'film': _brief(f), 'options': options,
                    'answer': options.index(f.label)}
    return None


def _pick_answer(group, state, choice, rng):
    return choice == state['answer'], True


def _still_view(state, done, round_id=None):
    step = 3 if done else state['step']
    out = {'image': f"/api/quizzes/still/{round_id}/{state['token']}-{step}.jpg", 'step': step, 'steps': 3,
           'worth': STEP_PAY[step], 'options': state['options']}
    if done:
        out.update(answer=state['answer'], film=state['film'])
    return out


def still_image(r, token_step):
    """The still for a round at a step, cropped around its focus — the whole
    picture never reaches the browser before the round is over. JPEG bytes,
    or None for a wrong token."""
    import io
    import enrich
    from PIL import Image
    state = json.loads(r.state_json)
    token, _, step = token_step.rpartition('-')
    if token != state.get('token') or step not in ('1', '2', '3'):
        return None
    step = int(step)
    if r.status != 'done' and step > state['step']:            # no peeking ahead
        return None
    raw = _image_cache.get(state['path'])
    if raw is None:
        resp = enrich._http.get(f"https://image.tmdb.org/t/p/w1280{state['path']}", timeout=15)
        resp.raise_for_status()
        raw = _image_cache[state['path']] = resp.content
        while len(_image_cache) > 40:
            _image_cache.pop(next(iter(_image_cache)))
    img = Image.open(io.BytesIO(raw)).convert('RGB')
    zoom = STILL_ZOOM[step]
    w, h = img.size
    cw, ch = w / zoom, h / zoom
    fx, fy = state['focus']
    left = min(max(0, fx * w - cw / 2), w - cw)
    top = min(max(0, fy * h - ch / 2), h - ch)
    img = img.crop((int(left), int(top), int(left + cw), int(top + ch))).resize((768, int(768 * h / w)))
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=82)
    return out.getvalue()


_image_cache = {}


# ─── Guess from the reviews ───────────────────────────────────────────────────

STOP = {'with', 'from', 'that', 'this', 'there', 'their', 'into', 'about', 'than', 'then', 'they', 'have', 'what',
        'when', 'were', 'will', 'your', 'film', 'movie'}


def _banned_words(f):
    """Words a clue can't contain: the title's, the year, the people's names."""
    import discover
    words = {w for w in discover.normalize(f.title).split() if len(w) >= 4 and w not in STOP}
    for name in [f.director or '', *f.cast[:6], *f.characters[:6]]:
        words |= {w for w in discover.normalize(name).split() if len(w) >= 3}
    if f.year:
        words.add(str(f.year))
    return words


def clue(text, banned):
    """One sentence of a review that hints without giving the film away (none
    of `banned`), 25–220 characters — or None when the review is mostly
    names and plot."""
    import discover
    import re as _re
    sentences = [x.strip() for x in _re.split(r'(?<=[.!?])\s+|\n+', text or '') if x.strip()]
    if not sentences:
        return None
    ok = [x for x in sentences if not set(discover.normalize(x).split()) & banned]
    if len(ok) < len(sentences) * 0.4:                          # mostly giveaways: skip the review
        return None
    fits = [x for x in ok if 25 <= len(x) <= 220]
    return max(fits, key=len) if fits else None


def _tmdb_reviews(tmdb_id):
    import enrich
    try:
        r = enrich._http.get(f'{enrich.TMDB_BASE}/movie/{tmdb_id}/reviews', headers=enrich._tmdb_headers(), timeout=10)
        r.raise_for_status()
        return [x.get('content') or '' for x in r.json().get('results', [])]
    except Exception as e:
        print(f'  reviews: TMDB reviews for {tmdb_id} failed: {e}')
        return []


def _club_reviews(group):
    """{tmdb id: [review]} from the diaries of members who allow it."""
    from app import LetterboxdEntry, User, member_ids
    ids = member_ids(group.id)
    out = {}
    for e in (LetterboxdEntry.query.join(User, User.id == LetterboxdEntry.user_id)
              .filter(LetterboxdEntry.user_id.in_(list(ids)), LetterboxdEntry.review.isnot(None),
                      LetterboxdEntry.tmdb_id.isnot(None), User.letterboxd_clues.isnot(False))):
        out.setdefault(e.tmdb_id, []).append(e.review)
    return out


def _reviews_start(group, rng, tries=5):
    subjects, everyone = _films(group)
    by_tmdb = {f.tmdb_id: f for f in everyone if f.tmdb_id}
    club = _club_reviews(group)
    known = [by_tmdb[t] for t in club if t in by_tmdb]
    famous = [f for f in subjects if f.tmdb_id and f.votes >= film_pool.KNOWN]
    picks = rng.sample(known, len(known)) + rng.sample(famous, min(tries, len(famous)))
    for f in picks[:tries + len(known)]:
        film_pool.ensure_details(f)
        banned = _banned_words(f)
        clues = [(c, 'club') for c in (clue(t, banned) for t in club.get(f.tmdb_id, [])) if c]
        if len(clues) < 3:
            clues += [(c, 'tmdb') for c in (clue(t, banned) for t in _tmdb_reviews(f.tmdb_id)) if c]
        seen, unique = set(), []
        for c, src in clues:
            if c.lower() not in seen:
                seen.add(c.lower())
                unique.append({'text': c, 'from': src})
        options = len(unique) >= 3 and _options(rng, f, everyone)
        if options:
            return {'clues': rng.sample(unique, 3), 'step': 1, 'film': _brief(f), 'options': options,
                    'answer': options.index(f.label)}
    return None


def _reviews_view(state, done, round_id=None):
    step = 3 if done else state['step']
    out = {'clues': state['clues'][:step], 'step': step, 'steps': 3, 'worth': STEP_PAY[step], 'options': state['options']}
    if done:
        out.update(answer=state['answer'], film=state['film'])
    return out


# ─── Emoji plot ───────────────────────────────────────────────────────────────

EMOJI_SYSTEM = ("You turn film plots into emoji puzzles. Reply with 4 to 7 emojis and nothing else: no words, "
                "letters, numbers or flags that spell out the title. Hint at the story — its people, places and "
                "what happens — not the title itself.")


def clean_emojis(text):
    """Only the emojis of an answer (letters, digits and punctuation dropped
    so nothing can spell the title); None unless 3–10 are left."""
    import re as _re
    left = _re.sub(r'[\w\s.,;:!?\'"()\[\]{}\-–—*#/\\|<>+=~`@$%^&]', '', text or '')
    marks = [c for c in left if ord(c) > 0x2000]
    joined = ''.join(marks)
    singles = [c for c in marks if ord(c) not in range(0xFE00, 0xFE10) and ord(c) != 0x200D
               and not 0x1F3FB <= ord(c) <= 0x1F3FF]
    return joined[:80] if 3 <= len(singles) <= 10 else None


def emoji_for(f):
    """A film's emoji plot: the saved one, or the AI's (saved). None when
    there's no plot to tell or the AI can't answer."""
    import ai
    from app import db, EmojiPlot
    row = EmojiPlot.query.filter_by(key=f.key).first()
    if row:
        return row.emojis
    if not f.overview:
        return None
    try:
        raw = ai.chat([{'role': 'system', 'content': EMOJI_SYSTEM},
                       {'role': 'user', 'content': f'Film: {f.title} ({f.year})\nPlot: {f.overview[:700]}'}], max_tokens=60)
    except Exception as e:
        print(f'  emoji plot: the AI failed for {f.key}: {e}')
        return None
    emojis = clean_emojis(raw)
    if emojis:
        db.session.add(EmojiPlot(key=f.key, emojis=emojis))
        db.session.commit()
    return emojis


def _emoji_start(group, rng, tries=4):
    subjects, everyone = _films(group)
    films = [f for f in subjects if f.overview or (f.pool and not f.movie_id and not f.pool.details_at)]
    famous = [f for f in films if f.votes >= film_pool.KNOWN] or films         # a story people may know
    for f in rng.sample(famous, min(tries, len(famous))):
        film_pool.ensure_details(f)
        emojis = emoji_for(f)
        options = emojis and _options(rng, f, everyone)
        if options:
            return {'emojis': emojis, 'film': _brief(f), 'options': options, 'answer': options.index(f.label)}
    return None


def _emoji_view(state, done):
    out = {'emojis': state['emojis'], 'options': state['options']}
    if done:
        out.update(answer=state['answer'], film=state['film'])
    return out


RULES = {
    'higher_lower': (_hl_start, _hl_answer, _hl_view),
    'who_said': (_ws_start, _ws_answer, _ws_view),
    'still': (_still_start, _pick_answer, _still_view),
    'reviews': (_reviews_start, _pick_answer, _reviews_view),
    'emoji': (_emoji_start, _pick_answer, _emoji_view),
}


# ─── Playing ──────────────────────────────────────────────────────────────────

def as_dict(r):
    """A round as its player sees it — answers only once it's over."""
    emoji, label, _, each = GAMES[r.kind]
    state = json.loads(r.state_json)
    done = r.status == 'done'
    return {'id': r.id, 'kind': r.kind, 'label': label, 'emoji': emoji, 'done': done, 'score': r.score,
            'earned': r.earned, 'each': each, 'by_step': r.kind in BY_STEP, 'left_today': max(0, DAILY_CAP - earned_today(r.user_id, r.group_id, r.kind)),
            'last': state.get('last'), **_view(r.kind, state, done, r.id)}


def _view(kind, state, done, round_id):
    view = RULES[kind][2]
    return view(state, done, round_id) if kind in BY_STEP else view(state, done)


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
    r = QuizRound(group_id=group.id, user_id=user.id, kind=kind, day=today(group), state_json=json.dumps(state), source=source)
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
    if choice == 'more':                                       # still / reviews: show more instead of answering
        if r.kind not in BY_STEP or state['step'] >= 3:
            return None, "That's everything there is to see."
        state['step'] += 1
        r.state_json = json.dumps(state)
        db.session.commit()
        return r, None
    right, done = RULES[r.kind][1](group, state, choice, rng or random.Random())
    pay = 0
    if right:
        r.score += 1
        worth = STEP_PAY[state['step']] if r.kind in BY_STEP else GAMES[r.kind][3]
        pay = min(worth, max(0, DAILY_CAP - earned_today(user.id, group.id, r.kind)))
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
                    'by_step': kind in BY_STEP,
                    'earned_today': earned_today(user.id, group.id, kind), 'best': best,
                    'round': as_dict(r) if r else None})
    return out

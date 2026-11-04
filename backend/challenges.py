"""Challenges: club members play the same set of a game against each other,
with kernels on the line — and members who aren't playing can back one.

  * A challenge is a set of games the club has on (quiz games, trivia): one
    game for a versus, several for a gauntlet — each picked or random, each
    1–10 questions (higher or lower: one run; a miss ends that game). Plus a
    stake each player puts in the pot (0: for bragging rights), named
    opponents and/or open seats anyone in the club can take, and a deadline.
  * Everyone gets the identical set: each question is made the first time a
    player reaches it (quizzes.RULES / trivia.make_question) and kept, so the
    others get the same one. 30 seconds a question (QUESTION_SECONDS); running
    out counts as a miss. Scored in kernels like the solo game: 1 a right
    call, 3/2/1 by how much of a still or the reviews you needed, trivia by
    difficulty. They decide the winner; the pot (and backing) is what changes
    hands — scoring alone doesn't add to anyone's total.
  * Scores show as each player finishes (`reveal` live) or only once everyone
    has (sealed) — the creator's choice, like a poll's answers.
  * Decided when every player has played (and nobody's left to answer an
    invite or take a seat), when the creator ends it after everyone in has
    played, or at the deadline: anyone who accepted and didn't play scores 0.
    One game: the top score takes the pot (a tie splits it; an odd kernel
    goes to the first to finish). A gauntlet: each game's top scorer wins
    that game; most games won takes it, then kernels scored, then the least
    time. Fewer than two players in: cancelled, nothing changes.
  * Backing (club-visible challenges, if the club allows it): back one player
    with 1–MAX_BET kernels until the first player finishes. Whoever backed
    the winner splits the backing pot by what they put in; if nobody did,
    everyone gets theirs back.
  * Kernels: the "challenges" part of everyone's total (kernels.py), from
    `net` once decided. Stakes and bets on open challenges are "on the line"
    — you can only put in what you have.

Rivalries: each member's challenge record (won, lost, streak, tournaments
won) and head-to-head against another member, from decided challenges.

Tournaments (tournaments.py) play each match as a challenge with
tournament_id: both players in from the start, no stake or backing of its
own, one winner (ties go to the faster player, then the higher seed).
"""
import json
import random
import secrets
from datetime import datetime, timedelta

import places

QUESTION_SECONDS = 30
GRACE_SECONDS = 3            # the network's share of the 30 seconds
MAX_PLAYERS = 8
MAX_SEATS = 6
MAX_BET = 10
QUESTIONS = (1, 10)          # how many questions a game can have (higher or lower: one run)
MAX_ROUNDS = 6               # games in a gauntlet
HL_CHAIN = 30                # higher or lower: films lined up for a run
RECENT_DAYS = 14             # decided challenges listed this long
DEADLINES = {'hour': 'In an hour', 'tonight': 'Tonight', 'days': 'In 3 days'}
TRIVIA = ('🧠', 'Trivia', 'Movie trivia questions: easy, medium and hard.')
GAUNTLET = ('🧩', 'Gauntlet')


# ─── Games ────────────────────────────────────────────────────────────────────

def games(group):
    """[{kind, emoji, label}] — the games this club can challenge in: its quiz
    games that are on, and trivia if either kind is on."""
    import quizzes
    out = [{'kind': k, 'emoji': g[0], 'label': g[1]} for k, g in quizzes.GAMES.items() if quizzes.on(group, k)]
    if group.trivia_enabled or group.trivia_anytime:
        out.append({'kind': 'trivia', 'emoji': TRIVIA[0], 'label': TRIVIA[1]})
    return out


def label(kind):
    import quizzes
    if kind == 'gauntlet':
        return GAUNTLET
    return TRIVIA[:2] if kind == 'trivia' else quizzes.GAMES[kind][:2]


def _now():
    return datetime.utcnow()


def _state(ch):
    return json.loads(ch.state_json or '{}')


def _progress(p):
    return json.loads(p.progress_json or '{}')


def _deadline(group, key, now=None):
    now = now or _now()
    if key == 'hour':
        return now + timedelta(hours=1)
    if key == 'days':
        return now + timedelta(days=3)
    city = places.club_city(group)                        # tonight: the club's midnight (at least an hour away)
    local = places.from_utc(now, city)
    midnight = places.to_utc(datetime.combine(local.date() + timedelta(days=1), datetime.min.time()), city)
    return max(midnight, now + timedelta(hours=1))


# ─── Rounds and their questions: the same for everyone ────────────────────────

def rounds(ch):
    """[{kind, questions}] — the games in order (one: a versus; more: a gauntlet)."""
    return _state(ch).get('rounds') or [{'kind': ch.kind, 'questions': ch.questions}]


def _hl_chain(group, rng):
    import quizzes
    films = [f for f in quizzes._films(group)[0] if f.year]
    if len(films) < 2:
        return None
    chain, seen = [rng.choice(films)], set()
    seen.add(chain[0].key)
    while len(chain) < HL_CHAIN:
        nxt = quizzes._next_film(rng, films, {'year': chain[-1].year}, seen)
        if not nxt:
            break
        chain.append(nxt)
        seen.add(nxt.key)
    return [quizzes._brief(f) for f in chain] if len(chain) >= 2 else None


def _key(kind, q):
    if kind == 'trivia':
        return q.get('ref')
    return (q.get('film') or {}).get('key') or q.get('quote')


def _made(state, r):
    return state.get('sets', {}).get(str(r), [])


def _make(ch, group, r, i):
    """Question `i` of round `r`, made fresh (not yet saved) — nothing the
    challenge has already asked in that game."""
    import quizzes
    import trivia
    kind = rounds(ch)[r]['kind']
    state = _state(ch)
    used = {_key(kind, q) for rr, rd in enumerate(rounds(ch)) if rd['kind'] == kind for q in _made(state, rr)} - {None}
    rng = random.Random(f'{ch.id}:{r}:{i}:{secrets.token_hex(4)}')
    if kind == 'trivia':
        return trivia.make_question(group, places.today_in(places.club_city(group)), rng=rng, recent=used)
    return quizzes.RULES[kind][0](group, rng, avoid=used) or quizzes.RULES[kind][0](group, rng)


def question(ch, r, i):
    """Question `i` of round `r`: the one already made, or made now and kept —
    if two players get there at once, the first one saved is everyone's."""
    from app import db, Group
    if rounds(ch)[r]['kind'] == 'higher_lower':
        return {'i': i}
    state = _state(ch)
    have = _made(state, r)
    if i < len(have):
        return have[i]
    made = _make(ch, db.session.get(Group, ch.group_id), r, i)
    if not made:
        return None
    new = json.dumps({**state, 'sets': {**state.get('sets', {}), str(r): [*have, made]}})
    done = db.session.execute(db.text('UPDATE challenge SET state_json = :new WHERE id = :id AND state_json = :old'),
                              {'new': new, 'old': ch.state_json, 'id': ch.id}).rowcount
    db.session.commit()
    db.session.refresh(ch)
    return question(ch, r, i) if not done else _made(_state(ch), r)[i]


# ─── What a player sees ───────────────────────────────────────────────────────

def _points(kind, q, step):
    import quizzes
    import trivia
    if kind == 'trivia':
        return trivia.worth('daily', q.get('difficulty'))
    return quizzes.STEP_PAY[step] if kind in quizzes.BY_STEP else 1


def _round_len(ch, r):
    rd = rounds(ch)[r]
    if rd['kind'] == 'higher_lower':
        return len(_state(ch).get('chains', {}).get(str(r), [])) - 1
    return rd['questions']


def round_points(p):
    """{round: kernels scored} from a player's answers."""
    out = {}
    for a in _progress(p).get('answers', []):
        out[a.get('r', 0)] = out.get(a.get('r', 0), 0) + a['points']
    return out


def _view(ch, p, r, i, q, step, answered, last):
    """Question `i` of round `r`, shaped like a solo round (quizzes.as_dict), so
    the site's and the bot's round displays show it as they are."""
    import quizzes
    kind = rounds(ch)[r]['kind']
    emoji, name = label(kind)
    out = {'id': ch.id, 'challenge': True, 'kind': kind, 'emoji': emoji, 'label': name, 'done': answered,
           'round': r, 'rounds': len(rounds(ch)), 'q': i, 'of': _round_len(ch, r), 'score': p.score,
           'round_score': round_points(p).get(r, 0), 'last': last, 'each': 1,
           'by_step': kind in quizzes.BY_STEP, 'left_today': None}
    if kind == 'higher_lower':
        chain = _state(ch)['chains'][str(r)]
        nxt = chain[i + 1]
        return {**out, 'current': chain[i], 'next': {**nxt, 'year': nxt['year'] if answered else None},
                'history': chain[:i]}
    if kind == 'trivia':
        out.update(prompt=q['prompt'], options=q['options'], difficulty=q.get('difficulty'), worth=_points(kind, q, 1))
        if answered:
            out['answer'] = q['answer']
        return out
    view = quizzes.RULES[kind][2]
    shown = {**q, 'step': step}
    out.update(view(shown, answered, None) if kind in quizzes.BY_STEP else view(shown, answered))
    if kind == 'still':
        token = _progress(p).get('tokens', {}).get(f'{r}:{i}', '')
        out['image'] = f"/api/challenges/still/{p.id}/{r}/{i}/{token}-{out['step']}.jpg"
    return out


def _next_round(p, prog):
    from app import db
    prog.update(r=prog.get('r', 0) + 1, i=0, step=1, shown_at=None)
    p.progress_json = json.dumps(prog)
    db.session.commit()


def current(ch, p, now=None):
    """The player's question now (starting its 30 seconds the first time it's
    shown), or None once they've finished. Questions whose time ran out while
    they were away count as misses; a game with nothing left to ask moves on."""
    from app import db
    now = now or _now()
    while p.status == 'accepted':
        prog = _progress(p)
        r, i = prog.get('r', 0), prog.get('i', 0)
        if r >= len(rounds(ch)):
            _finish(ch, p, now)
            break
        if i >= _round_len(ch, r):
            _next_round(p, prog)
            continue
        q = question(ch, r, i)
        if q is None:                                          # nothing left to ask in this game: on to the next
            _next_round(p, prog)
            continue
        if not prog.get('shown_at'):
            prog['shown_at'] = now.isoformat()
            prog.setdefault('step', 1)
            if rounds(ch)[r]['kind'] == 'still':
                prog.setdefault('tokens', {})[f'{r}:{i}'] = secrets.token_hex(8)
            p.progress_json = json.dumps(prog)
            db.session.commit()
        if _expired(prog, now):
            _record(ch, p, prog, q, None, now, timeout=True)
            continue
        last = (prog.get('answers') or [None])[-1]
        view = _view(ch, p, r, i, q, prog.get('step', 1), False, last)
        view['ends_at'] = (datetime.fromisoformat(prog['shown_at']) + timedelta(seconds=QUESTION_SECONDS)).isoformat() + 'Z'
        return view
    return None


def _expired(prog, now):
    shown = prog.get('shown_at')
    return bool(shown) and (now - datetime.fromisoformat(shown)).total_seconds() > QUESTION_SECONDS + GRACE_SECONDS


def _record(ch, p, prog, q, choice, now, timeout=False):
    """An answer (or the clock running out) to the player's current question.
    A higher-or-lower miss, or a game's last question, moves on to the next game."""
    from app import db
    r, i, step = prog.get('r', 0), prog.get('i', 0), prog.get('step', 1)
    kind = rounds(ch)[r]['kind']
    if kind == 'higher_lower':
        chain = _state(ch)['chains'][str(r)]
        right = not timeout and (choice == 'before') == (chain[i + 1]['year'] < chain[i]['year'])
    else:
        right = not timeout and choice == q['answer']
    points = _points(kind, q, step) if right else 0
    shown = datetime.fromisoformat(prog['shown_at']) if prog.get('shown_at') else now
    ms = min(int((now - shown).total_seconds() * 1000), (QUESTION_SECONDS + GRACE_SECONDS) * 1000)
    answer = {'r': r, 'q': i, 'choice': choice, 'right': right, 'points': points, 'ms': ms, 'step': step,
              'timeout': timeout, 'paid': points}
    prog.setdefault('answers', []).append(answer)
    p.score += points
    p.took_ms += ms
    prog.update(i=i + 1, step=1, shown_at=None)
    if (kind == 'higher_lower' and not right) or prog['i'] >= _round_len(ch, r):
        prog.update(r=r + 1, i=0)
    p.progress_json = json.dumps(prog)
    if prog.get('r', 0) >= len(rounds(ch)):
        _finish(ch, p, now)
    db.session.commit()
    return answer


def answer(ch, p, choice, now=None):
    """Answer the current question ('more': see more of a still or the
    reviews). Returns (view of the answered question, error)."""
    import quizzes
    from app import db
    now = now or _now()
    if ch.status != 'open' or p.status != 'accepted':
        return None, "You're not playing this challenge right now."
    if current(ch, p, now) is None:                          # also catches a question that ran out
        return None, "You've played all your questions."
    prog = _progress(p)
    r, i = prog.get('r', 0), prog.get('i', 0)
    kind = rounds(ch)[r]['kind']
    q = question(ch, r, i)
    if choice == 'more':
        if kind not in quizzes.BY_STEP or prog.get('step', 1) >= 3:
            return None, "That's everything there is to see."
        prog['step'] = prog.get('step', 1) + 1
        p.progress_json = json.dumps(prog)
        db.session.commit()
        return current(ch, p, now), None
    if kind == 'higher_lower':
        if choice not in ('before', 'after'):
            return None, 'Before or after?'
    elif not isinstance(choice, int) or not 0 <= choice < len(q['options']):
        return None, 'Pick one of the answers.'
    step = prog.get('step', 1)
    late = _expired(prog, now)
    got = _record(ch, p, prog, q, None if late else choice, now, timeout=late)
    shown = _view(ch, p, r, i, q, step, True, got)
    shown['over'] = p.status != 'accepted'
    return shown, None


def _finish(ch, p, now):
    """A player is done: by their last answer, or (current()) the clock running
    out while they were away. If nobody's left to play, that decides it."""
    from app import db
    if p.status == 'accepted':
        p.status, p.finished_at = 'finished', now
        db.session.commit()
        posts_changed(ch)
        maybe_settle(ch, now)


# ─── Who can do what ──────────────────────────────────────────────────────────

def player(ch, user_id):
    return next((p for p in ch.players if p.user_id == user_id), None)


def in_game(ch):
    """Players who accepted (playing, finished or forfeited)."""
    return [p for p in ch.players if p.status in ('accepted', 'finished', 'forfeit')]


def seats_left(ch):
    return max(0, ch.seats - sum(1 for p in ch.players if p.seat))


def can_see(ch, user_id):
    from app import _active_membership, User, db
    if player(ch, user_id):
        return True
    return ch.visibility == 'club' and bool(_active_membership(db.session.get(User, user_id), ch.group_id))


def betting_open(ch):
    from app import db, Group
    group = db.session.get(Group, ch.group_id)
    return (ch.status == 'open' and ch.visibility == 'club' and group.challenge_backing is not False
            and not ch.tournament_id and not any(p.status == 'finished' for p in ch.players))


def on_the_line(user_id, group_id):
    """Kernels held in open challenges and tournaments: stakes you're in for, bets you've made."""
    import tournaments
    from app import db, Challenge, ChallengeBet, ChallengePlayer
    stakes = (db.session.query(db.func.coalesce(db.func.sum(Challenge.stake), 0)).join(ChallengePlayer)
              .filter(Challenge.group_id == group_id, Challenge.status == 'open', ChallengePlayer.user_id == user_id,
                      ChallengePlayer.status.in_(('accepted', 'finished'))).scalar())
    bets = (db.session.query(db.func.coalesce(db.func.sum(ChallengeBet.amount), 0)).join(Challenge)
            .filter(Challenge.group_id == group_id, Challenge.status == 'open', ChallengeBet.user_id == user_id).scalar())
    return int(stakes or 0) + int(bets or 0) + tournaments.on_the_line(user_id, group_id)


def available(user_id, group_id):
    """What you can put in: your kernels in the club, less what's on the line."""
    import kernels
    return max(0, kernels.breakdown(user_id, group_id)['kernels'] - on_the_line(user_id, group_id))


def _afford(user_id, group_id, amount):
    if amount and available(user_id, group_id) < amount:
        return f"You have {available(user_id, group_id)} 🍿 to put in right now."
    return None


# ─── Making and joining ───────────────────────────────────────────────────────

def _int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _clamp(v, lo, hi, default):
    return max(lo, min(hi, _int(v, default)))


def plan_rounds(group, data, rng=None):
    """The games for a challenge, from {rounds: [{kind, questions}]} (each
    kind a game or 'random'), or {kind: game | 'random' | 'gauntlet', games,
    questions}. Random games come from the club's, none twice until each has
    had a turn. Returns (rounds, error)."""
    rng = rng or random.Random()
    choices = [g['kind'] for g in games(group)]
    if not choices:
        return None, "The club doesn't have any games on yet."
    spec = data.get('rounds')
    if not isinstance(spec, list) or not spec:
        kind = data.get('kind')
        n = _clamp(data.get('games'), 2, MAX_ROUNDS, 3) if kind == 'gauntlet' else 1
        spec = [{'kind': 'random' if kind == 'gauntlet' else kind, 'questions': data.get('questions')}] * n
    if len(spec) > MAX_ROUNDS:
        return None, f'At most {MAX_ROUNDS} games.'
    out, pool = [], []
    for item in spec:
        kind = item.get('kind') if isinstance(item, dict) else None
        if kind == 'random':
            if not pool:
                pool = rng.sample(choices, len(choices))
            kind = pool.pop()
        elif kind not in choices:
            return None, "Pick from the club's games."
        q = _clamp(item.get('questions', data.get('questions')), QUESTIONS[0], QUESTIONS[1], 5)
        out.append({'kind': kind, 'questions': None if kind == 'higher_lower' else q})
    return out, None


def _fresh_state(group, plan):
    """A challenge's starting state for its games (each higher-or-lower run lined up)."""
    chains = {}
    for r, rd in enumerate(plan):
        if rd['kind'] == 'higher_lower':
            chain = _hl_chain(group, random.Random())
            if not chain:
                return None, "There aren't enough films for Higher or lower yet."
            chains[str(r)] = chain
    return {'rounds': plan, 'chains': chains}, None


def create(group, user, data, now=None, rematch_of=None):
    """A new challenge: its games (plan_rounds), opponents (user ids), seats,
    stake, deadline, visibility and reveal. The creator is in from the start.
    Returns (challenge, error)."""
    from app import db, Challenge, ChallengePlayer, User, _active_membership, require_role
    now = now or _now()
    if not group.challenges_enabled:
        return None, 'Challenges are off in this club.'
    _, err = require_role(user, group.id, 'member')
    if err:
        return None, 'Only club members can start a challenge.'
    plan, err = plan_rounds(group, data)
    if err:
        return None, err
    opponents = []
    for uid in dict.fromkeys(_int(x) for x in data.get('opponents') or []):
        u = db.session.get(User, uid) if uid else None
        if not u or u.id == user.id or not _active_membership(u, group.id):
            return None, 'Challenge members of this club.'
        opponents.append(u)
    seats = max(0, min(MAX_SEATS, _int(data.get('seats'))))
    if not opponents and not seats:
        return None, 'Name someone to challenge, or leave a seat open.'
    if 1 + len(opponents) + seats > MAX_PLAYERS:
        return None, f'At most {MAX_PLAYERS} players.'
    stake = _int(data.get('stake'))
    top = group.challenge_max_stake or 10
    if not 0 <= stake <= top:
        return None, f'Stakes run from 0 to {top} 🍿 in this club.'
    err = _afford(user.id, group.id, stake)
    if err:
        return None, err
    state, err = _fresh_state(group, plan)
    if err:
        return None, err
    ch = Challenge(group_id=group.id, created_by=user.id, kind=plan[0]['kind'] if len(plan) == 1 else 'gauntlet',
                   questions=plan[0]['questions'] or 0, stake=stake, seats=seats, state_json=json.dumps(state),
                   visibility='club' if data.get('visibility') == 'club' else 'players',
                   reveal='live' if data.get('reveal') == 'live' else 'sealed',
                   closes_at=_deadline(group, data.get('deadline') if data.get('deadline') in DEADLINES else 'tonight', now),
                   rematch_of=rematch_of)
    db.session.add(ch)
    db.session.flush()
    db.session.add(ChallengePlayer(challenge_id=ch.id, user_id=user.id, status='accepted'))
    for u in opponents:
        db.session.add(ChallengePlayer(challenge_id=ch.id, user_id=u.id, status='invited'))
    db.session.commit()
    if question(ch, 0, 0) is None:                              # nothing to ask about: don't leave it hanging
        db.session.delete(ch)
        db.session.commit()
        return None, "There's nothing to play that with yet. Try another game."
    notify_invites(ch, opponents)
    if ch.visibility == 'club':
        notify_open(ch)
    return ch, None


def open_match(group, t, user_ids, spec, closes_at, now=None):
    """A tournament's match: both players in already, no stake of its own (the
    entry is the tournament's), its games drawn now — random ones fresh for
    each match. Returns (challenge, error)."""
    from app import db, Challenge, ChallengePlayer
    tries = 4 if any(s.get('kind') == 'random' for s in spec) else 1      # a random game with nothing to ask: draw again
    for _ in range(tries):
        plan, err = plan_rounds(group, {'rounds': spec})
        if err:
            return None, err
        state, err = _fresh_state(group, plan)
        if err:
            continue
        ch = Challenge(group_id=group.id, created_by=t.created_by, kind=plan[0]['kind'] if len(plan) == 1 else 'gauntlet',
                       questions=plan[0]['questions'] or 0, stake=0, seats=0, state_json=json.dumps(state),
                       visibility=t.visibility, reveal=t.reveal, closes_at=closes_at, tournament_id=t.id)
        db.session.add(ch)
        db.session.flush()
        for uid in user_ids:
            db.session.add(ChallengePlayer(challenge_id=ch.id, user_id=uid, status='accepted'))
        db.session.commit()
        if question(ch, 0, 0) is not None:
            return ch, None
        db.session.delete(ch)
        db.session.commit()
    return None, "There's nothing to play that with yet."


def set_games(ch, user, data):
    """The creator picks the games again (Discord's gauntlet picker) — only
    before anyone has seen a question."""
    from app import db, Group
    if ch.created_by != user.id or ch.status != 'open' or ch.tournament_id:
        return 'Only whoever started it can change the games.'
    if any(_progress(p).get('shown_at') or _progress(p).get('answers') for p in ch.players):
        return 'Someone has started playing, so the games stay as they are.'
    group = db.session.get(Group, ch.group_id)
    plan, err = plan_rounds(group, data)
    if err:
        return err
    state, err = _fresh_state(group, plan)
    if err:
        return err
    ch.state_json = json.dumps(state)
    ch.kind = plan[0]['kind'] if len(plan) == 1 else 'gauntlet'
    ch.questions = plan[0]['questions'] or 0
    db.session.commit()
    if question(ch, 0, 0) is None:
        return "There's nothing to play that with yet. Try another game."
    posts_changed(ch)
    return None


def respond(ch, user, accept, now=None):
    """An invitee says yes (their stake goes in) or no."""
    from app import db
    p = player(ch, user.id)
    if ch.status != 'open' or not p or p.status != 'invited':
        return "That invite isn't open anymore."
    if accept:
        err = _afford(user.id, ch.group_id, ch.stake)
        if err:
            return err
        p.status = 'accepted'
    else:
        p.status = 'declined'
    db.session.commit()
    clear_invite(ch, user.id)
    posts_changed(ch)
    maybe_settle(ch, now)
    return None


def join(ch, user, now=None):
    """Take an open seat."""
    from app import db, ChallengePlayer, _active_membership, require_role
    if ch.status != 'open' or not seats_left(ch):
        return 'No seats left in that one.'
    if player(ch, user.id):
        return "You're already in it."
    if not _active_membership(user, ch.group_id):
        return 'Only club members can join.'
    _, err = require_role(user, ch.group_id, 'member')
    if err:
        return 'Only club members can join.'
    if any(b.user_id == user.id for b in ch.bets):
        return "You've backed a player in this one, so you can't play in it too."
    err = _afford(user.id, ch.group_id, ch.stake)
    if err:
        return err
    db.session.add(ChallengePlayer(challenge_id=ch.id, user_id=user.id, status='accepted', seat=True))
    db.session.commit()
    posts_changed(ch)
    return None


def back(ch, user, backing_id, amount):
    """Back a player in a club-visible challenge."""
    from app import db, ChallengeBet, _active_membership
    if not betting_open(ch):
        return 'Backing is closed for this one.'
    if player(ch, user.id):
        return "You're in this one, so you can't back a player too."
    if not _active_membership(user, ch.group_id):
        return 'Only club members can back a player.'
    if not any(p.user_id == backing_id and p.status in ('accepted', 'invited') for p in ch.players):
        return 'Back one of the players.'
    amount = _int(amount)
    if not 1 <= amount <= MAX_BET:
        return f'Back a player with 1 to {MAX_BET} 🍿.'
    if any(b.user_id == user.id for b in ch.bets):
        return "You've backed a player in this one already."
    err = _afford(user.id, ch.group_id, amount)
    if err:
        return err
    db.session.add(ChallengeBet(challenge_id=ch.id, user_id=user.id, backing_id=backing_id, amount=amount))
    db.session.commit()
    notify_backed(ch, user, backing_id, amount)
    posts_changed(ch)
    return None


def cancel(ch, user):
    """The creator calls it off before anyone has answered a question."""
    from app import db
    if ch.created_by != user.id or ch.status != 'open' or ch.tournament_id:
        return 'Only whoever started it can call it off.'
    if any(_progress(p).get('answers') or _progress(p).get('shown_at') for p in ch.players):
        return 'Someone has started playing, so it runs to the end.'
    ch.status, ch.decided_at = 'cancelled', _now()
    db.session.commit()
    clear_invite(ch)
    posts_changed(ch)
    return None


def end_now(ch, user, now=None):
    """The creator settles it once everyone in has played (no waiting for
    unanswered invites or open seats)."""
    if ch.created_by != user.id or ch.status != 'open' or ch.tournament_id:
        return 'Only whoever started it can end it.'
    if any(p.status == 'accepted' for p in ch.players):
        return 'Not everyone in has played yet.'
    settle(ch, now)
    return None


def rematch(ch, user, double=False, now=None):
    """The same challenge again — same game, same players (invited again),
    the same stake or double it (up to the club's limit)."""
    from app import db, Group
    if ch.status != 'done' or not player(ch, user.id) or ch.tournament_id:
        return None, 'Only players can ask for a rematch once it’s decided.'
    group = db.session.get(Group, ch.group_id)
    stake = min(ch.stake * 2 if double else ch.stake, group.challenge_max_stake or 10)
    others = [p.user_id for p in in_game(ch) if p.user_id != user.id]
    return create(group, user, {'rounds': rounds(ch), 'opponents': others, 'seats': 0, 'stake': stake,
                                'deadline': 'tonight', 'visibility': ch.visibility, 'reveal': ch.reveal},
                  now, rematch_of=ch.id)


# ─── Deciding ─────────────────────────────────────────────────────────────────

def maybe_settle(ch, now=None):
    """Decide it as soon as nobody's left to play — or call it off as soon as
    there's no one left to play against."""
    if ch.status != 'open' or seats_left(ch):
        return
    if all(p.status not in ('invited', 'accepted') for p in ch.players) or \
            (not any(p.status == 'invited' for p in ch.players) and len(in_game(ch)) < 2):
        settle(ch, now)


def settle(ch, now=None):
    """Pay out: the pot to the top score, the backing pot to its backers."""
    from app import db
    now = now or _now()
    if ch.status != 'open':
        return
    for p in ch.players:
        if p.status == 'invited':
            p.status = 'expired'
        elif p.status == 'accepted':
            p.status = 'forfeit'
    players = in_game(ch)
    state = _state(ch)
    if len(players) < 2:
        ch.status, ch.decided_at = 'cancelled', now
        db.session.commit()
        clear_invite(ch)
        posts_changed(ch)
        notify_results(ch)
        return
    # Each game's top scorer wins it (a tie shares it). One game: the top
    # score wins (a tie splits the pot); a gauntlet: most games won, then
    # kernels scored, then the least time.
    pts = {p.user_id: round_points(p) for p in players}
    round_winners = []
    for r in range(len(rounds(ch))):
        top = max(pts[p.user_id].get(r, 0) for p in players)
        round_winners.append(sorted(p.user_id for p in players if top > 0 and pts[p.user_id].get(r, 0) == top))
    won_rounds = {p.user_id: sum(p.user_id in w for w in round_winners) for p in players}
    state['round_winners'] = round_winners
    state['standing'] = {str(p.user_id): {'rounds_won': won_rounds[p.user_id], 'score': p.score, 'ms': p.took_ms}
                         for p in players}
    rank = lambda p: _rank(ch, state, p.user_id)
    played = [p for p in players if p.status == 'finished']    # someone who played beats someone who didn't
    if played:
        best = max(rank(p) for p in played)
        winners = sorted((p for p in played if rank(p) == best), key=lambda p: p.finished_at or now)
    else:                                                     # nobody played: everyone's stake comes back
        winners = sorted(players, key=lambda p: p.id)
    if ch.tournament_id:                                      # a tournament match has one winner
        import tournaments
        winners = [tournaments.match_winner(ch, players, rank)]
    pot = ch.stake * len(players)
    share, extra = divmod(pot, len(winners))
    for p in players:
        p.net = -ch.stake
    for n, p in enumerate(winners):
        p.net += share + (1 if n < extra else 0)
    won = {p.user_id for p in winners}
    backing = sum(b.amount for b in ch.bets)
    right = [b for b in ch.bets if b.backing_id in won]
    for b in ch.bets:
        b.net = 0 if not right else -b.amount
    if right:
        total = sum(b.amount for b in right)
        paid = [backing * b.amount // total for b in right]
        for n in range(backing - sum(paid)):            # what rounding leaves, to the earliest backers
            paid[n % len(paid)] += 1
        for b, got in zip(right, paid):
            b.net = got - b.amount
    state['winners'] = sorted(won)
    ch.state_json = json.dumps(state)
    ch.status, ch.decided_at = 'done', now
    db.session.commit()
    clear_invite(ch)
    posts_changed(ch)
    if ch.tournament_id:                                      # the bracket moves on (and tells the players)
        import tournaments
        tournaments.match_decided(ch, now)
    else:
        notify_results(ch)


def _rank(ch, state, uid):
    """What decides between players: kernels scored (one game) or games won, kernels scored, time (a gauntlet)."""
    s = state.get('standing', {}).get(str(uid), {'rounds_won': 0, 'score': 0, 'ms': 0})
    return (s['score'],) if len(rounds(ch)) == 1 else (s['rounds_won'], s['score'], -s['ms'])


def settle_due(now=None):
    """Challenges past their deadline are decided (the API's sweep runs this)."""
    from app import Challenge
    now = now or _now()
    for ch in Challenge.query.filter(Challenge.status == 'open', Challenge.closes_at <= now).all():
        settle(ch, now)


# ─── Kernels and records ──────────────────────────────────────────────────────

def kernels_for(user_ids, group_id=None, since=None):
    """{uid: net kernels from decided challenges and tournaments} (decided since `since`)."""
    import tournaments
    from app import db, Challenge, ChallengeBet, ChallengePlayer
    out = tournaments.kernels_for(user_ids, group_id, since)
    for model in (ChallengePlayer, ChallengeBet):
        q = (db.session.query(model.user_id, db.func.sum(model.net)).join(Challenge, Challenge.id == model.challenge_id)
             .filter(model.user_id.in_(list(user_ids)), model.net.isnot(None), Challenge.status == 'done'))
        if group_id:
            q = q.filter(Challenge.group_id == group_id)
        if since:
            q = q.filter(Challenge.decided_at >= since)
        for uid, n in q.group_by(model.user_id):
            out[uid] = out.get(uid, 0) + int(n or 0)
    return out


def _decided(group_id, user_ids=None, since=None):
    from app import Challenge, ChallengePlayer
    q = Challenge.query.filter(Challenge.group_id == group_id, Challenge.status == 'done')
    if user_ids is not None:
        q = q.join(ChallengePlayer).filter(ChallengePlayer.user_id.in_(list(user_ids))).distinct()
    if since:
        q = q.filter(Challenge.decided_at >= since)
    return q.order_by(Challenge.decided_at.desc()).all()


def records(user_ids, group_id, since=None):
    """{uid: {played, won, lost, streak, titles}} — a shared win counts as a
    win (tournament matches count too); `streak`: wins in a row, most recent
    first; `titles`: tournaments won."""
    import tournaments
    won_it = tournaments.titles(user_ids, group_id, since)
    out = {uid: {'played': 0, 'won': 0, 'lost': 0, 'streak': 0, 'titles': won_it.get(uid, 0), '_open': True}
           for uid in user_ids}
    for ch in _decided(group_id, user_ids, since):
        winners = set(_state(ch).get('winners', []))
        for p in in_game(ch):
            r = out.get(p.user_id)
            if r is None:
                continue
            r['played'] += 1
            won = p.user_id in winners
            r['won' if won else 'lost'] += 1
            if r['_open']:
                if won:
                    r['streak'] += 1
                else:
                    r['_open'] = False
    for r in out.values():
        r.pop('_open')
    return out


def head_to_head(group_id, a, b):
    """{won, lost, tied, played} for `a` against `b`: the challenges they both
    played, by who came out ahead (as the challenge was decided)."""
    out = {'won': 0, 'lost': 0, 'tied': 0, 'played': 0}
    for ch in _decided(group_id, [a]):
        pa, pb = player(ch, a), player(ch, b)
        if not pa or not pb or pa.status not in ('finished', 'forfeit') or pb.status not in ('finished', 'forfeit'):
            continue
        state = _state(ch)
        ra, rb = _rank(ch, state, a), _rank(ch, state, b)
        out['played'] += 1
        out['won' if ra > rb else 'lost' if ra < rb else 'tied'] += 1
    return out


def rivals(group_id, user_id, limit=5):
    """The members you've played most, with your record against each."""
    from app import db, User
    seen = {}
    for ch in _decided(group_id, [user_id]):
        for p in in_game(ch):
            if p.user_id != user_id:
                seen[p.user_id] = seen.get(p.user_id, 0) + 1
    out = []
    for uid, _ in sorted(seen.items(), key=lambda kv: -kv[1])[:limit]:
        u = db.session.get(User, uid)
        if u:
            out.append({'user': u.public_dict(), **head_to_head(group_id, user_id, uid)})
    return out


# ─── Showing it ───────────────────────────────────────────────────────────────

def _show_scores(ch, p, viewer_id):
    return ch.status == 'done' or (p.status == 'finished' and (ch.reveal == 'live' or p.user_id == viewer_id))


def games_line(ch):
    """'🗣️ Who said it' — or '🧩 Gauntlet: Who said it, Trivia, Emoji plot'."""
    rs = rounds(ch)
    if len(rs) == 1:
        return ' '.join(label(rs[0]['kind']))
    return f"{' '.join(GAUNTLET)}: " + ', '.join(label(rd['kind'])[1] for rd in rs)


def _summary(ch, r, q, i):
    """One question in a line, for the results ("Casablanca (1942)")."""
    kind = rounds(ch)[r]['kind']
    if kind == 'higher_lower':
        f = _state(ch)['chains'][str(r)][i + 1]
        return f"{f['title']} ({f['year']})"
    if kind == 'trivia':
        return f"{q['prompt']} — {q['options'][q['answer']]}"
    f = q.get('film') or {}
    year = f" ({f['year']})" if f.get('year') else ''
    return f"{f.get('title', '?')}{year}"


def as_dict(ch, viewer_id):
    """A challenge as `viewer_id` sees it."""
    from app import db, Group
    group = db.session.get(Group, ch.group_id)
    emoji, name = label(ch.kind)
    me = player(ch, viewer_id)
    state = _state(ch)
    winners = set(state.get('winners', []))
    mine = next((b for b in ch.bets if b.user_id == viewer_id), None)
    rs = rounds(ch)
    standing = state.get('standing', {})
    players = [{'user': p.user.public_dict(), 'status': p.status, 'seat': bool(p.seat),
                'score': p.score if _show_scores(ch, p, viewer_id) else None,
                'round_scores': [round_points(p).get(r, 0) for r in range(len(rs))] if _show_scores(ch, p, viewer_id) else None,
                'rounds_won': standing.get(str(p.user_id), {}).get('rounds_won') if ch.status == 'done' else None,
                'took_ms': p.took_ms if _show_scores(ch, p, viewer_id) else None,
                'net': p.net if ch.status == 'done' else None, 'winner': p.user_id in winners,
                'backers': sum(1 for b in ch.bets if b.backing_id == p.user_id)} for p in ch.players]
    out = {'id': ch.id, 'group_id': ch.group_id, 'kind': ch.kind, 'emoji': emoji, 'label': name,
           'games_line': games_line(ch), 'gauntlet': len(rs) > 1,
           'rounds': [{'kind': rd['kind'], 'emoji': label(rd['kind'])[0], 'label': label(rd['kind'])[1],
                       'questions': rd['questions']} for rd in rs],
           'questions': rs[0]['questions'] if len(rs) == 1 else None, 'stake': ch.stake,
           'pot': ch.stake * len(in_game(ch)), 'seats': ch.seats, 'seats_left': seats_left(ch),
           'visibility': ch.visibility, 'reveal': ch.reveal, 'status': ch.status,
           'closes_at': ch.closes_at.isoformat() + 'Z', 'created_at': ch.created_at.isoformat() + 'Z',
           'decided_at': ch.decided_at.isoformat() + 'Z' if ch.decided_at else None,
           'created_by': {'id': ch.created_by, 'name': ch.creator.name if ch.creator else None},
           'players': players, 'rematch_of': ch.rematch_of,
           'backing': {'open': betting_open(ch), 'total': sum(b.amount for b in ch.bets), 'count': len(ch.bets),
                       'allowed': ch.visibility == 'club' and group.challenge_backing is not False,
                       'mine': {'backing_id': mine.backing_id, 'amount': mine.amount, 'net': mine.net} if mine else None,
                       'max': MAX_BET},
           'you': {'status': me.status if me else None,
                   'can_accept': bool(me and me.status == 'invited' and ch.status == 'open'),
                   'can_join': bool(not me and ch.status == 'open' and seats_left(ch) and not mine),
                   'can_play': bool(me and me.status == 'accepted' and ch.status == 'open'),
                   'can_back': bool(not me and not mine and betting_open(ch)),
                   'can_cancel': ch.created_by == viewer_id and ch.status == 'open' and not ch.tournament_id
                                 and not any(_progress(p).get('shown_at') or _progress(p).get('answers') for p in ch.players),
                   'can_set_games': ch.created_by == viewer_id and ch.status == 'open' and not ch.tournament_id
                                    and not any(_progress(p).get('shown_at') or _progress(p).get('answers') for p in ch.players),
                   'can_end': ch.created_by == viewer_id and ch.status == 'open' and not ch.tournament_id
                              and not any(p.status == 'accepted' for p in ch.players),
                   'can_rematch': bool(me and ch.status == 'done' and me.status in ('finished', 'forfeit')
                                       and not ch.tournament_id)}}
    out['tournament'] = _tournament_of(ch)
    newer = db.session.execute(db.text('SELECT id FROM challenge WHERE rematch_of = :id ORDER BY id DESC LIMIT 1'),
                               {'id': ch.id}).scalar()
    out['rematch'] = newer
    out['game_choices'] = games(group) if out['you']['can_set_games'] else None
    if ch.status == 'done':
        answers = {p.user_id: {(a.get('r', 0), a['q']): a for a in _progress(p).get('answers', [])} for p in in_game(ch)}
        round_winners = state.get('round_winners', [])
        out['results'] = []
        for r, rd in enumerate(rs):
            qs = _made(state, r)
            asked = sorted({q for by in answers.values() for (rr, q) in by if rr == r})
            out['results'].append({
                'round': r, 'kind': rd['kind'], 'emoji': label(rd['kind'])[0], 'label': label(rd['kind'])[1],
                'winners': round_winners[r] if r < len(round_winners) else [],
                'questions': [{'q': i, 'summary': _summary(ch, r, qs[i] if i < len(qs) else {}, i),
                               'answers': {str(uid): {k: a[k] for k in ('right', 'points', 'ms', 'timeout')}
                                           for uid, by in answers.items() if (a := by.get((r, i)))}}
                              for i in asked if rd['kind'] == 'higher_lower' or i < len(qs)]})
    return out


def _tournament_of(ch):
    """For a tournament's match: {id, title, match} ("Winners' round 1")."""
    if not ch.tournament_id:
        return None
    import tournaments
    from app import db, Tournament
    t = db.session.get(Tournament, ch.tournament_id)
    m = next((x for x in t.matches if x.challenge_id == ch.id), None) if t else None
    return {'id': t.id, 'title': tournaments.title(t), 'match': tournaments.match_label(t, m) if m else None} if t else None


def visible(group_id, viewer_id, now=None):
    """The challenges a member sees on Play: open ones they're in or that the
    club can see, and ones decided in the last RECENT_DAYS days. A
    tournament's matches show on its bracket — here, only to their players
    while they're open."""
    from app import Challenge
    now = now or _now()
    rows = (Challenge.query.filter(Challenge.group_id == group_id)
            .filter((Challenge.status == 'open') | (Challenge.decided_at >= now - timedelta(days=RECENT_DAYS)))
            .order_by(Challenge.created_at.desc()).all())
    return [c for c in rows if can_see(c, viewer_id) and (c.status != 'cancelled' or player(c, viewer_id))
            and (not c.tournament_id or (c.status == 'open' and player(c, viewer_id)))][:40]


# ─── Telling people ───────────────────────────────────────────────────────────

def _notify(user, kind, type_, payload, channels=None):
    import notify
    from app import db, Notification
    if user and notify.wants(user, type_):
        notify._make(db, Notification, user, kind, None, None, payload, ready=True, channels=channels)


def _about(ch):
    n = len(rounds(ch))
    game = ' '.join(label(ch.kind)) + (f' ({n} games)' if n > 1 else '')
    return {'challenge_id': ch.id, 'group_id': ch.group_id, 'game': game, 'stake': ch.stake,
            'by': ch.creator.name if ch.creator else None}


def notify_invites(ch, users):
    """Invites: the bell (it waits for your answer) — and, if you chose them,
    Discord / email / push."""
    from app import db
    for u in users:
        _notify(u, 'challenge_invite', 'challenge_invite', _about(ch))
    db.session.commit()


def notify_open(ch):
    """A club-visible challenge opened: members not in it hear about it if they asked to."""
    from app import db, User, member_ids
    playing = {p.user_id for p in ch.players}
    for uid in member_ids(ch.group_id) - playing:
        _notify(db.session.get(User, uid), 'challenge_open', 'challenge_open', _about(ch), channels=())
    db.session.commit()


def notify_backed(ch, backer, backing_id, amount):
    from app import db, User
    _notify(db.session.get(User, backing_id), 'challenge_backed', 'challenge_result',
            {**_about(ch), 'backer': backer.name, 'amount': amount}, channels=())
    db.session.commit()


def notify_results(ch):
    """Decided (or called off): each player and backer, with how they did."""
    from app import db, User
    state = _state(ch)
    winners = [db.session.get(User, uid) for uid in state.get('winners', [])]
    players = in_game(ch)
    ranked = sorted(players, key=lambda p: -p.score)
    for p in ch.players:
        if p.status not in ('finished', 'forfeit'):
            continue
        place = 1 + sum(1 for x in players if x.score > p.score)
        _notify(p.user, 'challenge_result', 'challenge_result',
                {**_about(ch), 'status': ch.status, 'net': p.net or 0, 'score': p.score, 'place': place, 'of': len(ranked),
                 'winners': [w.name for w in winners if w]}, channels=())
    for b in ch.bets:
        _notify(b.user, 'challenge_result', 'challenge_result',
                {**_about(ch), 'status': ch.status, 'net': b.net or 0, 'backed': b.backing.name if b.backing else None,
                 'amount': b.amount, 'winners': [w.name for w in winners if w]}, channels=())
    db.session.commit()


def clear_invite(ch, user_id=None):
    """Answered (or no longer open): the invite stops waiting in the bell."""
    from app import db, Notification
    for n in Notification.query.filter_by(kind='challenge_invite'):
        p = json.loads(n.payload_json or '{}')
        if p.get('challenge_id') == ch.id and (user_id is None or n.user_id == user_id) and n.read_at is None:
            n.read_at = _now()
    db.session.commit()


def needs_answer(user_id, payload):
    from app import db, Challenge
    ch = db.session.get(Challenge, payload.get('challenge_id') or 0)
    p = player(ch, user_id) if ch else None
    return bool(ch and ch.status == 'open' and p and p.status == 'invited')


# ─── Discord ──────────────────────────────────────────────────────────────────

def posts_changed(ch):
    """Its post in the club's Discord (if any) follows — a match's, its tournament's."""
    from app import db, DiscordPost
    kind, ref = ('tournament', ch.tournament_id) if ch.tournament_id else ('challenge', ch.id)
    DiscordPost.query.filter(DiscordPost.kind == kind, DiscordPost.ref_id == ref,
                             DiscordPost.status == 'posted').update({'dirty': True}, synchronize_session=False)
    db.session.commit()


def _named(u, group_id):
    """A name for the channel: only members in its server who don't say Never."""
    from app import on_discord, share_prefs
    return u.name if u and on_discord(u, group_id) and share_prefs(u)['challenge'] != 'never' else None


def post_payload(ch):
    """What the challenge's post in the club's Discord shows right now (names only — never pings)."""
    state = _state(ch)
    winners = set(state.get('winners', []))
    from app import on_discord
    # Whoever posted it chose to: their name shows (others' follow their own setting).
    by = ch.creator.name if ch.creator and on_discord(ch.creator, ch.group_id) else None
    rs = rounds(ch)
    standing = state.get('standing', {})
    return {'challenge_id': ch.id, 'game': games_line(ch), 'kind': ch.kind, 'status': ch.status, 'stake': ch.stake,
            'pot': ch.stake * len(in_game(ch)), 'seats_left': seats_left(ch), 'reveal': ch.reveal,
            'questions': rs[0]['questions'] if len(rs) == 1 else None, 'games': len(rs),
            'closes_at': ch.closes_at.isoformat() + '+00:00', 'by': by,
            'backing': {'open': betting_open(ch), 'total': sum(b.amount for b in ch.bets), 'count': len(ch.bets)},
            'players': [{'name': by if p.user_id == ch.created_by else _named(p.user, ch.group_id), 'status': p.status,
                         'score': p.score if (ch.status == 'done' or (ch.reveal == 'live' and p.status == 'finished')) else None,
                         'winner': p.user_id in winners, 'net': p.net if ch.status == 'done' else None,
                         'rounds_won': standing.get(str(p.user_id), {}).get('rounds_won') if len(rs) > 1 else None}
                        for p in ch.players if p.status not in ('declined', 'expired')]}


def announce(ch, user, choice=None):
    """Post a club-visible challenge in the club's Discord. The creator's
    choice on the spot ('now' / 'none') wins, whatever their "Challenges I
    start or play" setting; without one, the setting decides (Always posts)."""
    from app import DiscordPost, can_share, db, share_prefs
    if ch.visibility != 'club' or not can_share(user, ch.group_id):
        return False
    if choice not in ('now', 'none'):
        choice = 'now' if share_prefs(user)['challenge'] == 'always' else 'none'
    if choice == 'none':
        return False
    db.session.add(DiscordPost(group_id=ch.group_id, kind='challenge', user_id=user.id, ref_id=ch.id,
                               post_at=places.server_now()))
    db.session.commit()
    return True

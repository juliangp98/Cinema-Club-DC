"""Tournaments: three or more club members, a bracket of 1-v-1 challenges, and
a prize pot (challenges.py plays each match).

  * Formats (the creator picks):
      - Double elimination (3–16): seeded, the bracket filled to the next
        power of two with byes for the top seeds; one loss drops you to the
        losers' bracket, two put you out. One grand final between the two
        brackets' champions (no reset match).
      - Round robin + final (3–6): everyone plays everyone once; the top two
        meet in a final. Standings: matches won, then kernels scored, then seed.
  * Every match is a challenge with tournament_id: the same game set for both
    players (each picked, or random — drawn fresh for each match), the 30-
    second clock, sealed or live scores. No stake of its own: the entry stake
    is the tournament's. A match opens as soon as both players are known and
    closes `match_time` later; a tie goes to the faster player, then the
    higher seed. Someone who doesn't play forfeits; if neither plays, the
    higher seed goes through.
  * Entries: named members are invited (they accept, putting in the entry
    stake, or decline) and/or open seats anyone in the club can take. It
    starts when nobody's left to answer and the seats are filled, when the
    creator starts it (3 or more in), or when entries close — with fewer than
    three in, it's called off and nothing changes hands.
  * Prizes: the pot (entry × entrants) to the champion, or 60 / 30 / 10 to the
    top three (an odd kernel to the higher place). Third: the losers' final's
    loser, or the round robin's third place.
  * Backing: members not in it back an entrant to win it all, until the first
    match is decided. Whoever backed the champion splits the backing pot by
    what they put in; if nobody did, everyone gets theirs back.
  * Kernels: the "challenges" part of everyone's total; entry stakes and bets
    are "on the line" until it's decided (challenges.on_the_line).
"""
import json
import random
from datetime import timedelta

import challenges
import places

FORMATS = {'double': 'Double elimination', 'round_robin': 'Round robin + final'}
PLAYERS = {'double': (3, 16), 'round_robin': (3, 6)}
PAYOUTS = {'all': (100,), 'top3': (60, 30, 10)}
PAYOUT_LABELS = {'all': 'Winner takes all', 'top3': '60 / 30 / 10'}
MATCH_TIMES = {'hour': 'An hour', 'tonight': 'Till tonight', 'day': 'A day'}
SEEDINGS = {'random': 'Random', 'record': 'By challenge record'}
MAX_SEATS = 8
EMOJI = '🏆'


def _now():
    return challenges._now()


def rounds(t):
    """The game set every match plays: [{kind | 'random', questions}]."""
    return json.loads(t.rounds_json or '[]')


# ─── The bracket ──────────────────────────────────────────────────────────────

def _order(size):
    """Seed positions for a bracket of `size`, so the top seeds meet last:
    4 → 1 4 2 3; 8 → 1 8 4 5 2 7 3 6."""
    order = [1]
    while len(order) < size:
        m = len(order) * 2 + 1
        order = [x for s in order for x in (s, m - s)]
    return order


def _match(section, rnd, slot, a, b, key=None):
    prefix = {'winners': 'W', 'losers': 'L', 'league': 'R'}.get(section)
    return {'key': key or f'{prefix}{rnd}-{slot}', 'section': section, 'round': rnd, 'slot': slot, 'a_from': a, 'b_from': b}


def double_bracket(n):
    """The matches of a double-elimination bracket for `n` players. Seeds
    past `n` are nobody: their matches are byes."""
    size = 1 << (n - 1).bit_length()
    k = size.bit_length() - 1                       # winners' rounds
    order = _order(size)
    out = [_match('winners', 1, j, f'seed:{order[2 * j]}', f'seed:{order[2 * j + 1]}') for j in range(size // 2)]
    for r in range(2, k + 1):
        out += [_match('winners', r, j, f'winner:W{r - 1}-{2 * j}', f'winner:W{r - 1}-{2 * j + 1}') for j in range(size >> r)]
    # Losers' bracket: round 1 pairs the winners' first-round losers; then each
    # winners' round's losers drop in (in reverse order every other round, so
    # nobody meets the player who just beat them), and the survivors pair off.
    out += [_match('losers', 1, j, f'loser:W1-{2 * j}', f'loser:W1-{2 * j + 1}') for j in range(size // 4)]
    lb, alive = 1, size // 4
    for r in range(2, k + 1):
        lb += 1
        out += [_match('losers', lb, j, f'winner:L{lb - 1}-{j}', f'loser:W{r}-{alive - 1 - j if r % 2 == 0 else j}')
                for j in range(alive)]
        if alive > 1:
            lb += 1
            out += [_match('losers', lb, j, f'winner:L{lb - 1}-{2 * j}', f'winner:L{lb - 1}-{2 * j + 1}') for j in range(alive // 2)]
            alive //= 2
    out.append(_match('final', 1, 0, f'winner:W{k}-0', f'winner:L{lb}-0', key='GF'))
    return out


def league(n):
    """Round robin for `n` players (the circle method: one match each per
    round; with an odd number, one sits out), then the final."""
    ids = list(range(1, n + 1)) + ([0] if n % 2 else [])
    out = []
    for r in range(len(ids) - 1):
        pairs = [(ids[i], ids[-1 - i]) for i in range(len(ids) // 2)]
        out += [_match('league', r + 1, j, f'seed:{a}', f'seed:{b}') for j, (a, b) in enumerate(p for p in pairs if 0 not in p)]
        ids = [ids[0], ids[-1], *ids[1:-1]]
    out.append(_match('final', 1, 0, 'place:1', 'place:2', key='F'))
    return out


def match_label(t, m):
    """"Winners' round 1", "Losers' final", "Grand final", "Round 2"…"""
    if m.section == 'final':
        return 'Grand final' if t.format == 'double' else 'Final'
    if m.section == 'league':
        return f'Round {m.round}'
    last = max(x.round for x in t.matches if x.section == m.section)
    side = "Winners'" if m.section == 'winners' else "Losers'"
    return f'{side} final' if m.round == last else f'{side} round {m.round}'


# ─── Who's in ─────────────────────────────────────────────────────────────────

def player(t, user_id):
    return next((p for p in t.players if p.user_id == user_id), None)


def entrants(t):
    return [p for p in t.players if p.status == 'accepted']


def seats_left(t):
    return max(0, t.seats - sum(1 for p in t.players if p.seat))


def can_see(t, user_id):
    from app import _active_membership, User, db
    if player(t, user_id):
        return True
    return t.visibility == 'club' and bool(_active_membership(db.session.get(User, user_id), t.group_id))


def betting_open(t):
    """Until the first match is decided (byes don't count)."""
    from app import db, Group
    group = db.session.get(Group, t.group_id)
    return (t.status in ('open', 'running') and t.visibility == 'club' and group.challenge_backing is not False
            and not any(m.decided_at and m.challenge_id for m in t.matches))


def _int(v, default=0):
    return challenges._int(v, default)


# ─── Making and joining ───────────────────────────────────────────────────────

def _match_deadline(group, key, now):
    if key == 'tonight':
        return challenges._deadline(group, 'tonight', now)
    return now + (timedelta(hours=1) if key == 'hour' else timedelta(days=1))


def _keep_random(data, plan):
    """plan_rounds draws random games; a tournament keeps them random, so each match draws its own."""
    spec = data.get('rounds') if isinstance(data.get('rounds'), list) and data.get('rounds') else \
        [{'kind': 'random' if data.get('kind') in ('random', 'gauntlet') else data.get('kind')}] * len(plan)
    out = []
    for s, p in zip(spec, plan):
        s = s if isinstance(s, dict) else {}
        if s.get('kind') == 'random':
            out.append({'kind': 'random', 'questions': challenges._clamp(s.get('questions', data.get('questions')),
                                                                         *challenges.QUESTIONS, 5)})
        else:
            out.append(p)
    return out


def create(group, user, data, now=None):
    """A new tournament: format, the game set (challenges.plan_rounds — kept
    as given, so random games are drawn for each match), invitees and open
    seats, entry stake, payout, seeding, entries' deadline, each match's time,
    who sees it and how scores show. The creator is in from the start.
    Returns (tournament, error)."""
    from app import db, Tournament, TournamentPlayer, User, _active_membership, require_role
    now = now or _now()
    if not group.challenges_enabled:
        return None, 'Challenges are off in this club.'
    _, err = require_role(user, group.id, 'member')
    if err:
        return None, 'Only club members can start a tournament.'
    fmt = data.get('format') if data.get('format') in FORMATS else 'double'
    plan, err = challenges.plan_rounds(group, data)             # checks the games are the club's
    if err:
        return None, err
    plan = _keep_random(data, plan)
    invitees = []
    for uid in dict.fromkeys(_int(x) for x in data.get('players') or data.get('opponents') or []):
        u = db.session.get(User, uid) if uid else None
        if not u or u.id == user.id or not _active_membership(u, group.id):
            return None, 'Invite members of this club.'
        invitees.append(u)
    lo, hi = PLAYERS[fmt]
    seats = max(0, min(MAX_SEATS, _int(data.get('seats'))))
    if 1 + len(invitees) + seats < lo:
        return None, f'A tournament needs at least {lo} players: invite more, or leave seats open.'
    if 1 + len(invitees) + seats > hi:
        return None, f"{FORMATS[fmt]} takes at most {hi} players."
    stake = _int(data.get('stake'))
    top = group.challenge_max_stake or 10
    if not 0 <= stake <= top:
        return None, f'Entry runs from 0 to {top} 🍿 in this club.'
    err = challenges._afford(user.id, group.id, stake)
    if err:
        return None, err
    t = Tournament(group_id=group.id, created_by=user.id, format=fmt, rounds_json=json.dumps(plan), stake=stake,
                   payout=data.get('payout') if data.get('payout') in PAYOUTS else 'all', seats=seats,
                   seeding=data.get('seeding') if data.get('seeding') in SEEDINGS else 'random',
                   match_time=data.get('match_time') if data.get('match_time') in MATCH_TIMES else 'day',
                   visibility='players' if data.get('visibility') == 'players' else 'club',
                   reveal='live' if data.get('reveal') == 'live' else 'sealed',
                   closes_at=challenges._deadline(group, data.get('deadline') if data.get('deadline') in challenges.DEADLINES
                                                  else 'tonight', now))
    db.session.add(t)
    db.session.flush()
    db.session.add(TournamentPlayer(tournament_id=t.id, user_id=user.id, status='accepted'))
    for u in invitees:
        db.session.add(TournamentPlayer(tournament_id=t.id, user_id=u.id, status='invited'))
    db.session.commit()
    notify_invites(t, invitees)
    if t.visibility == 'club':
        notify_open(t)
    return t, None


def respond(t, user, accept, now=None):
    """An invitee says yes (their entry goes in) or no."""
    from app import db
    p = player(t, user.id)
    if t.status != 'open' or not p or p.status != 'invited':
        return "That invite isn't open anymore."
    if accept:
        err = challenges._afford(user.id, t.group_id, t.stake)
        if err:
            return err
        if len(entrants(t)) >= PLAYERS[t.format][1]:
            return "It's full."
    p.status = 'accepted' if accept else 'declined'
    db.session.commit()
    clear_invite(t, user.id)
    posts_changed(t)
    maybe_start(t, now)
    return None


def join(t, user, now=None):
    """Take an open seat."""
    from app import db, TournamentPlayer, _active_membership, require_role
    if t.status != 'open' or not seats_left(t):
        return 'No seats left in that one.'
    if player(t, user.id):
        return "You're already in it."
    if not _active_membership(user, t.group_id) or require_role(user, t.group_id, 'member')[1]:
        return 'Only club members can join.'
    if any(b.user_id == user.id for b in t.bets):
        return "You've backed someone in this one, so you can't play in it too."
    if len(entrants(t)) >= PLAYERS[t.format][1]:
        return "It's full."
    err = challenges._afford(user.id, t.group_id, t.stake)
    if err:
        return err
    db.session.add(TournamentPlayer(tournament_id=t.id, user_id=user.id, status='accepted', seat=True))
    db.session.commit()
    posts_changed(t)
    maybe_start(t, now)
    return None


def back(t, user, backing_id, amount):
    """Back an entrant to win it all."""
    from app import db, TournamentBet, User, _active_membership
    if not betting_open(t):
        return 'Backing is closed for this one.'
    if player(t, user.id):
        return "You're in this one, so you can't back someone too."
    if not _active_membership(user, t.group_id):
        return 'Only club members can back a player.'
    if not any(p.user_id == backing_id and p.status == 'accepted' for p in t.players):
        return 'Back one of the players.'
    amount = _int(amount)
    if not 1 <= amount <= challenges.MAX_BET:
        return f'Back a player with 1 to {challenges.MAX_BET} 🍿.'
    if any(b.user_id == user.id for b in t.bets):
        return "You've backed someone in this one already."
    err = challenges._afford(user.id, t.group_id, amount)
    if err:
        return err
    db.session.add(TournamentBet(tournament_id=t.id, user_id=user.id, backing_id=backing_id, amount=amount))
    db.session.commit()
    challenges._notify(db.session.get(User, backing_id), 'tournament_backed', 'challenge_result',
                       {**_about(t), 'backer': user.name, 'amount': amount}, channels=())
    db.session.commit()
    posts_changed(t)
    return None


def cancel(t, user):
    """The creator calls it off before it starts."""
    if t.created_by != user.id or t.status != 'open':
        return 'Only whoever started it can call it off, before it starts.'
    _call_off(t)
    return None


def _call_off(t):
    from app import db
    t.status, t.decided_at = 'cancelled', _now()
    for b in t.bets:
        b.net = 0
    db.session.commit()
    clear_invite(t)
    posts_changed(t)


def start_now(t, user, now=None):
    """The creator starts it with whoever's in (at least three)."""
    if t.created_by != user.id or t.status != 'open':
        return 'Only whoever started it can start it.'
    lo = PLAYERS[t.format][0]
    if len(entrants(t)) < lo:
        return f'It needs at least {lo} players in.'
    start(t, now)
    return None


def maybe_start(t, now=None):
    """Nobody's left to answer and every seat is taken: it starts."""
    if t.status == 'open' and not seats_left(t) and not any(p.status == 'invited' for p in t.players):
        if len(entrants(t)) >= PLAYERS[t.format][0]:
            start(t, now)
        else:
            _call_off(t)


def start_due(now=None):
    """Tournaments whose entries have closed start — or, short of players,
    are called off (the API's sweep runs this)."""
    from app import Tournament
    now = now or _now()
    for t in Tournament.query.filter(Tournament.status == 'open', Tournament.closes_at <= now).all():
        if len(entrants(t)) >= PLAYERS[t.format][0]:
            start(t, now)
        else:
            _call_off(t)


def _seed(t, rng):
    """Entrants in seed order: random, or by challenge record (most wins
    over losses first; ties drawn at random)."""
    people = entrants(t)
    rng.shuffle(people)
    if t.seeding == 'record':
        rec = challenges.records([p.user_id for p in people], t.group_id)
        people.sort(key=lambda p: -(rec[p.user_id]['won'] - rec[p.user_id]['lost']))
    return people


def start(t, now=None, rng=None):
    """Entries close: seeds, the bracket, and the first matches open."""
    from app import db, TournamentMatch
    now = now or _now()
    if t.status != 'open':
        return
    for p in t.players:
        if p.status == 'invited':
            p.status = 'expired'
    people = _seed(t, rng or random.Random())
    for n, p in enumerate(people, 1):
        p.seed = n
    for b in list(t.bets):                                 # backing someone who never got in: it comes back
        if not any(p.user_id == b.backing_id for p in people):
            db.session.delete(b)
    matches = double_bracket(len(people)) if t.format == 'double' else league(len(people))
    for m in matches:
        db.session.add(TournamentMatch(tournament_id=t.id, **m))
    t.status, t.started_at = 'running', now
    db.session.commit()
    clear_invite(t)
    advance(t, now)
    posts_changed(t)


# ─── Playing it out ───────────────────────────────────────────────────────────

def _seeds(t):
    return {p.seed: p.user_id for p in t.players if p.seed}


def _by_key(t):
    return {m.key: m for m in t.matches}


def _side(t, src, by_key, seeds):
    """Who a side's source names now: a user id, 0 (nobody: a bye) or None
    (not known yet)."""
    kind, _, ref = src.partition(':')
    if kind == 'seed':
        return seeds.get(int(ref), 0)
    if kind == 'place':
        table = standings(t)
        if not table or any(not m.decided_at for m in t.matches if m.section == 'league'):
            return None
        return table[int(ref) - 1]['user_id'] if int(ref) <= len(table) else 0
    m = by_key[ref]
    if not m.decided_at:
        return None
    return m.winner_id if kind == 'winner' else m.loser_id


def advance(t, now=None):
    """Fill in every match whose players are now known: a bye goes straight
    through; a real one opens as a challenge. Then, once the final's
    decided, pay out."""
    from app import db, Group
    now = now or _now()
    if t.status != 'running':
        return
    group = db.session.get(Group, t.group_id)
    moved = True
    while moved:
        moved = False
        by_key, seeds = _by_key(t), _seeds(t)
        for m in t.matches:
            if m.decided_at:
                continue
            a = m.a_id if m.a_id is not None else _side(t, m.a_from, by_key, seeds)
            b = m.b_id if m.b_id is not None else _side(t, m.b_from, by_key, seeds)
            if (a, b) != (m.a_id, m.b_id):
                m.a_id, m.b_id, moved = a, b, True
            if a is None or b is None:
                continue
            if not a or not b:                             # a bye (or nobody at all): straight through
                m.winner_id, m.loser_id, m.decided_at, moved = a or b, 0, now, True
                continue
            if m.challenge_id is None:
                db.session.commit()
                if _claim(m):
                    _open(t, group, m, now)
                    moved = True
        db.session.commit()
    final = next(m for m in t.matches if m.section == 'final')
    if final.decided_at:
        settle(t, now)


def _claim(m):
    """Only one request makes a match's challenge."""
    from app import db
    got = db.session.execute(db.text('UPDATE tournament_match SET challenge_id = 0 WHERE id = :id AND challenge_id IS NULL'),
                             {'id': m.id}).rowcount
    db.session.commit()
    db.session.refresh(m)
    return bool(got)


def _seed_of(t, uid):
    p = player(t, uid)
    return p.seed if p and p.seed else 99


def _open(t, group, m, now):
    """A match's challenge: the two players, in already; its games drawn now."""
    from app import db, User
    ch, err = challenges.open_match(group, t, [m.a_id, m.b_id], rounds(t), _match_deadline(group, t.match_time, now), now)
    if err:                                                 # nothing to play it with: the higher seed goes through
        hi, lo = sorted((m.a_id, m.b_id), key=lambda u: _seed_of(t, u))
        m.challenge_id, m.winner_id, m.loser_id, m.decided_at = None, hi, lo, now
        db.session.commit()
        return
    m.challenge_id = ch.id
    db.session.commit()
    for uid, other in ((m.a_id, m.b_id), (m.b_id, m.a_id)):
        challenges._notify(db.session.get(User, uid), 'tournament_match', 'challenge_invite',
                           {**_about(t), 'challenge_id': ch.id, 'match': match_label(t, m),
                            'opponent': db.session.get(User, other).name,
                            'closes_at': ch.closes_at.isoformat() + 'Z'})
    db.session.commit()


def match_winner(ch, players, rank):
    """A match's one winner: whoever played (if only one did), then the
    challenge's rank, then less time, then the higher seed; if neither
    played, the higher seed."""
    from app import db, Tournament
    t = db.session.get(Tournament, ch.tournament_id)
    played = [p for p in players if p.status == 'finished']
    if not played:
        return min(players, key=lambda p: _seed_of(t, p.user_id))
    return max(played, key=lambda p: (rank(p), -p.took_ms, -_seed_of(t, p.user_id)))


def match_decided(ch, now=None):
    """A match's challenge was decided: its winner goes on, and the bracket moves."""
    from app import db, Tournament
    t = db.session.get(Tournament, ch.tournament_id or 0)
    m = next((x for x in t.matches if x.challenge_id == ch.id), None) if t else None
    if not m or m.decided_at:
        return
    winners = challenges._state(ch).get('winners') or []
    ids = [m.a_id, m.b_id]
    win = winners[0] if winners and winners[0] in ids else min(ids, key=lambda u: _seed_of(t, u))
    m.winner_id, m.loser_id, m.decided_at = win, ids[1] if ids[0] == win else ids[0], now or _now()
    db.session.commit()
    advance(t, now)
    posts_changed(t)


def standings(t):
    """The round robin's table: [{user_id, played, won, lost, score}] —
    matches won, then kernels scored, then seed."""
    from app import db, Challenge
    rows = {p.user_id: {'user_id': p.user_id, 'played': 0, 'won': 0, 'lost': 0, 'score': 0}
            for p in t.players if p.seed}
    for m in t.matches:
        if m.section != 'league' or not m.decided_at:
            continue
        ch = db.session.get(Challenge, m.challenge_id) if m.challenge_id else None
        for uid in (m.a_id, m.b_id):
            if uid in rows:
                rows[uid]['played'] += 1
                rows[uid]['won' if uid == m.winner_id else 'lost'] += 1
        for p in (ch.players if ch else []):
            if p.user_id in rows:
                rows[p.user_id]['score'] += p.score
    return sorted(rows.values(), key=lambda r: (-r['won'], -r['score'], _seed_of(t, r['user_id'])))


def places_of(t):
    """[first, second, third] user ids (None where there isn't one yet)."""
    by_key = _by_key(t)
    final = next(m for m in t.matches if m.section == 'final')
    first = final.winner_id if final.decided_at else None
    second = final.loser_id if final.decided_at else None
    third = None
    if t.format == 'double':
        lf = by_key.get(final.b_from.partition(':')[2])            # the losers' final
        third = lf.loser_id if lf and lf.decided_at else None
    else:
        table = standings(t)
        third = next((r['user_id'] for r in table if r['user_id'] not in (first, second)), None) if first else None
    return [first, second, third or None]


def prizes(pot, payout):
    """The pot split by place — what rounding leaves goes to the champion."""
    shares = [pot * pct // 100 for pct in PAYOUTS[payout]]
    shares[0] += pot - sum(shares)
    return shares


def settle(t, now=None):
    """The final's decided: prizes from the pot, the backing pot to the champion's backers."""
    from app import db
    now = now or _now()
    if t.status != 'running':
        return
    people = [p for p in t.players if p.seed]
    pot = t.stake * len(people)
    top = places_of(t)
    shares = prizes(pot, t.payout)
    for p in people:
        p.net = -t.stake
        p.place = top.index(p.user_id) + 1 if p.user_id in top else None
    for uid, prize in zip(top, shares):
        p = player(t, uid) if uid else None
        (p or player(t, top[0])).net += prize                    # a place nobody holds: to the champion
    champ = top[0]
    backing = sum(b.amount for b in t.bets)
    right = [b for b in t.bets if b.backing_id == champ]
    for b in t.bets:
        b.net = 0 if not right else -b.amount
    if right:
        total = sum(b.amount for b in right)
        paid = [backing * b.amount // total for b in right]
        for n in range(backing - sum(paid)):
            paid[n % len(paid)] += 1
        for b, got in zip(right, paid):
            b.net = got - b.amount
    t.status, t.decided_at = 'done', now
    db.session.commit()
    posts_changed(t)
    notify_results(t)


# ─── Kernels and records ──────────────────────────────────────────────────────

def kernels_for(user_ids, group_id=None, since=None):
    """{uid: net kernels from decided tournaments: prizes and backing}."""
    from app import db, Tournament, TournamentBet, TournamentPlayer
    out = {}
    for model in (TournamentPlayer, TournamentBet):
        q = (db.session.query(model.user_id, db.func.sum(model.net)).join(Tournament, Tournament.id == model.tournament_id)
             .filter(model.user_id.in_(list(user_ids)), model.net.isnot(None), Tournament.status == 'done'))
        if group_id:
            q = q.filter(Tournament.group_id == group_id)
        if since:
            q = q.filter(Tournament.decided_at >= since)
        for uid, n in q.group_by(model.user_id):
            out[uid] = out.get(uid, 0) + int(n or 0)
    return out


def on_the_line(user_id, group_id):
    """Entry stakes and bets in tournaments not yet decided."""
    from app import db, Tournament, TournamentBet, TournamentPlayer
    live = Tournament.status.in_(('open', 'running'))
    stakes = (db.session.query(db.func.coalesce(db.func.sum(Tournament.stake), 0)).join(TournamentPlayer)
              .filter(Tournament.group_id == group_id, live, TournamentPlayer.user_id == user_id,
                      TournamentPlayer.status == 'accepted').scalar())
    bets = (db.session.query(db.func.coalesce(db.func.sum(TournamentBet.amount), 0)).join(Tournament)
            .filter(Tournament.group_id == group_id, live, TournamentBet.user_id == user_id).scalar())
    return int(stakes or 0) + int(bets or 0)


def titles(user_ids, group_id, since=None):
    """{uid: tournaments won}."""
    from app import Tournament, TournamentPlayer
    q = (TournamentPlayer.query.join(Tournament)
         .filter(Tournament.group_id == group_id, Tournament.status == 'done', TournamentPlayer.place == 1,
                 TournamentPlayer.user_id.in_(list(user_ids))))
    if since:
        q = q.filter(Tournament.decided_at >= since)
    out = {uid: 0 for uid in user_ids}
    for p in q:
        out[p.user_id] += 1
    return out


# ─── Showing it ───────────────────────────────────────────────────────────────

def games_line(t):
    """'🗣️ Who said it' · '🎲 Random' · '🧩 3 games: Who said it, Random, Trivia'."""
    rs = rounds(t)
    name = lambda k: ('🎲', 'Random') if k == 'random' else challenges.label(k)
    if len(rs) == 1:
        return ' '.join(name(rs[0]['kind']))
    return f"🧩 {len(rs)} games: " + ', '.join(name(r['kind'])[1] for r in rs)


def title(t):
    return f"{EMOJI} {FORMATS[t.format]}"


def _side_dict(t, uid, users):
    if uid is None:
        return None
    if uid == 0:
        return {'bye': True}
    u = users.get(uid)
    return {'user': u.public_dict() if u else {'id': uid, 'name': '?'}, 'seed': _seed_of(t, uid)}


def match_dict(t, m, viewer_id, users):
    """One match as the bracket shows it: its two sides, who won, and — once
    shown — the kernels each scored."""
    from app import db, Challenge
    ch = db.session.get(Challenge, m.challenge_id) if m.challenge_id else None
    scores = {}
    if ch:
        for p in ch.players:
            if challenges._show_scores(ch, p, viewer_id):
                scores[str(p.user_id)] = p.score
    status = ('bye' if m.decided_at and not ch else 'done' if m.decided_at
              else 'open' if ch else 'waiting')
    played = {str(p.user_id): p.status for p in ch.players} if ch else {}
    return {'key': m.key, 'section': m.section, 'round': m.round, 'slot': m.slot, 'label': match_label(t, m),
            'a': _side_dict(t, m.a_id, users), 'b': _side_dict(t, m.b_id, users),
            'from': [m.a_from, m.b_from], 'challenge_id': ch.id if ch else None, 'status': status,
            'winner_id': m.winner_id or None, 'scores': scores, 'played': played,
            'games': challenges.games_line(ch) if ch else None,
            'closes_at': ch.closes_at.isoformat() + 'Z' if ch and ch.status == 'open' else None}


def your_match(t, viewer_id):
    """The match you have to play now: its challenge id, or None."""
    from app import db, Challenge
    for m in t.matches:
        if m.challenge_id and not m.decided_at and viewer_id in (m.a_id, m.b_id):
            ch = db.session.get(Challenge, m.challenge_id)
            p = challenges.player(ch, viewer_id) if ch else None
            if p and p.status == 'accepted' and ch.status == 'open':
                return ch.id
    return None


def as_dict(t, viewer_id):
    """A tournament as `viewer_id` sees it: entrants, the bracket, the pot."""
    from app import db, Group, User
    group = db.session.get(Group, t.group_id)
    me = player(t, viewer_id)
    mine = next((b for b in t.bets if b.user_id == viewer_id), None)
    ids = {p.user_id for p in t.players} | {x for m in t.matches for x in (m.a_id, m.b_id) if x}
    users = {u.id: u for u in User.query.filter(User.id.in_(ids))} if ids else {}
    rs = rounds(t)
    people = entrants(t)
    sections = {}
    for m in t.matches:
        sections.setdefault(m.section, []).append(match_dict(t, m, viewer_id, users))
    alive = None
    if t.status == 'running':
        losses = {}
        for m in t.matches:
            if m.decided_at and m.loser_id:
                losses[m.loser_id] = losses.get(m.loser_id, 0) + 1
        out_after = 2 if t.format == 'double' else None
        alive = [p.user_id for p in people if out_after is None or losses.get(p.user_id, 0) < out_after]
    lo, hi = PLAYERS[t.format]
    return {
        'id': t.id, 'group_id': t.group_id, 'title': title(t), 'format': t.format, 'format_label': FORMATS[t.format],
        'emoji': EMOJI, 'games_line': games_line(t),
        'rounds': [{'kind': r['kind'], 'emoji': '🎲' if r['kind'] == 'random' else challenges.label(r['kind'])[0],
                    'label': 'Random' if r['kind'] == 'random' else challenges.label(r['kind'])[1], 'questions': r['questions']}
                   for r in rs],
        'stake': t.stake, 'pot': t.stake * len(people), 'payout': t.payout, 'payout_label': PAYOUT_LABELS[t.payout],
        'prizes': prizes(t.stake * len(people), t.payout),
        'seats': t.seats, 'seats_left': seats_left(t), 'seeding': t.seeding, 'match_time': t.match_time,
        'match_time_label': MATCH_TIMES[t.match_time], 'visibility': t.visibility, 'reveal': t.reveal, 'status': t.status,
        'min_players': lo, 'max_players': hi,
        'closes_at': t.closes_at.isoformat() + 'Z', 'created_at': t.created_at.isoformat() + 'Z',
        'started_at': t.started_at.isoformat() + 'Z' if t.started_at else None,
        'decided_at': t.decided_at.isoformat() + 'Z' if t.decided_at else None,
        'created_by': {'id': t.created_by, 'name': t.creator.name if t.creator else None},
        'players': [{'user': p.user.public_dict(), 'status': p.status, 'seat': bool(p.seat), 'seed': p.seed,
                     'place': p.place, 'net': p.net if t.status == 'done' else None,
                     'alive': alive is not None and p.user_id in alive,
                     'backers': sum(1 for b in t.bets if b.backing_id == p.user_id)} for p in t.players],
        'bracket': {'winners': sections.get('winners', []), 'losers': sections.get('losers', []),
                    'league': sections.get('league', []), 'final': sections.get('final', [])},
        'standings': [{**r, 'user': users[r['user_id']].public_dict() if r['user_id'] in users else None}
                      for r in standings(t)] if t.format == 'round_robin' and t.status != 'open' else None,
        'places': places_of(t) if t.status == 'done' else None,
        'backing': {'open': betting_open(t), 'total': sum(b.amount for b in t.bets), 'count': len(t.bets),
                    'allowed': t.visibility == 'club' and group.challenge_backing is not False,
                    'mine': {'backing_id': mine.backing_id, 'amount': mine.amount, 'net': mine.net} if mine else None,
                    'max': challenges.MAX_BET},
        'you': {'status': me.status if me else None,
                'can_accept': bool(me and me.status == 'invited' and t.status == 'open'),
                'can_join': bool(not me and t.status == 'open' and seats_left(t) and not mine),
                'can_back': bool(not me and not mine and betting_open(t)),
                'can_start': t.created_by == viewer_id and t.status == 'open' and len(people) >= lo,
                'can_cancel': t.created_by == viewer_id and t.status == 'open',
                'match': your_match(t, viewer_id)},
    }


def visible(group_id, viewer_id, now=None):
    """Tournaments a member sees on Play: not yet decided ones they're in or
    the club can see, and ones decided in the last RECENT_DAYS days."""
    from app import Tournament
    now = now or _now()
    rows = (Tournament.query.filter(Tournament.group_id == group_id)
            .filter(Tournament.status.in_(('open', 'running'))
                    | (Tournament.decided_at >= now - timedelta(days=challenges.RECENT_DAYS)))
            .order_by(Tournament.created_at.desc()).all())
    return [t for t in rows if can_see(t, viewer_id) and (t.status != 'cancelled' or player(t, viewer_id))][:20]


# ─── Telling people ───────────────────────────────────────────────────────────

def _about(t):
    return {'tournament_id': t.id, 'group_id': t.group_id, 'format': FORMATS[t.format], 'game': games_line(t),
            'stake': t.stake, 'by': t.creator.name if t.creator else None}


def notify_invites(t, users):
    from app import db
    for u in users:
        challenges._notify(u, 'tournament_invite', 'challenge_invite', _about(t))
    db.session.commit()


def notify_open(t):
    from app import db, User, member_ids
    playing = {p.user_id for p in t.players}
    for uid in member_ids(t.group_id) - playing:
        challenges._notify(db.session.get(User, uid), 'tournament_open', 'challenge_open', _about(t), channels=())
    db.session.commit()


def notify_results(t):
    """Decided: every entrant and backer, with where they finished."""
    from app import db, User
    champ = db.session.get(User, places_of(t)[0] or 0)
    for p in t.players:
        if p.seed:
            challenges._notify(p.user, 'tournament_result', 'challenge_result',
                               {**_about(t), 'place': p.place, 'of': len([x for x in t.players if x.seed]), 'net': p.net or 0,
                                'winner': champ.name if champ else None}, channels=())
    for b in t.bets:
        challenges._notify(b.user, 'tournament_result', 'challenge_result',
                           {**_about(t), 'backed': b.backing.name if b.backing else None, 'amount': b.amount,
                            'net': b.net or 0, 'winner': champ.name if champ else None}, channels=())
    db.session.commit()


def clear_invite(t, user_id=None):
    from app import db, Notification
    for n in Notification.query.filter_by(kind='tournament_invite'):
        p = json.loads(n.payload_json or '{}')
        if p.get('tournament_id') == t.id and (user_id is None or n.user_id == user_id) and n.read_at is None:
            n.read_at = _now()
    db.session.commit()


def needs_answer(kind, user_id, payload):
    """An invite still waiting for a yes or no; a match still waiting to be played."""
    from app import db, Challenge, Tournament
    if kind == 'tournament_match':
        ch = db.session.get(Challenge, payload.get('challenge_id') or 0)
        p = challenges.player(ch, user_id) if ch else None
        return bool(ch and ch.status == 'open' and p and p.status == 'accepted')
    t = db.session.get(Tournament, payload.get('tournament_id') or 0)
    p = player(t, user_id) if t else None
    return bool(t and t.status == 'open' and p and p.status == 'invited')


# ─── Discord ──────────────────────────────────────────────────────────────────

def posts_changed(t):
    from app import db, DiscordPost
    DiscordPost.query.filter(DiscordPost.kind == 'tournament', DiscordPost.ref_id == t.id,
                             DiscordPost.status == 'posted').update({'dirty': True}, synchronize_session=False)
    db.session.commit()


def post_payload(t):
    """The tournament's post in the club's Discord: the bracket so far and
    each open match — names only, never pings."""
    from app import User, db, on_discord
    by = t.creator.name if t.creator and on_discord(t.creator, t.group_id) else None
    name = lambda uid: (by if uid == t.created_by else challenges._named(db.session.get(User, uid), t.group_id)) if uid else None
    top = places_of(t) if t.status == 'done' else [None, None, None]
    matches = []
    for m in t.matches:
        if m.a_id and m.b_id:
            matches.append({'key': m.key, 'label': match_label(t, m), 'a': name(m.a_id), 'b': name(m.b_id),
                            'winner': 'a' if m.winner_id == m.a_id else 'b' if m.winner_id == m.b_id else None,
                            'status': 'done' if m.decided_at else 'open' if m.challenge_id else 'waiting'})
    people = entrants(t)
    return {'tournament_id': t.id, 'title': title(t), 'format': t.format, 'game': games_line(t), 'status': t.status,
            'stake': t.stake, 'pot': t.stake * len(people), 'payout': PAYOUT_LABELS[t.payout], 'seats_left': seats_left(t),
            'closes_at': t.closes_at.isoformat() + '+00:00', 'by': by,
            'players': [{'name': name(p.user_id), 'status': p.status, 'seed': p.seed, 'place': p.place}
                        for p in t.players if p.status not in ('declined', 'expired')],
            'matches': matches, 'places': [name(uid) for uid in top],
            'backing': {'open': betting_open(t), 'total': sum(b.amount for b in t.bets), 'count': len(t.bets)}}


def announce(t, user, choice=None):
    """Post a club-visible tournament in the club's Discord — the creator's
    choice on the spot, or their "Challenges I start or play" setting."""
    from app import DiscordPost, can_share, db, share_prefs
    if t.visibility != 'club' or not can_share(user, t.group_id):
        return False
    if choice not in ('now', 'none'):
        choice = 'now' if share_prefs(user)['challenge'] == 'always' else 'none'
    if choice == 'none':
        return False
    db.session.add(DiscordPost(group_id=t.group_id, kind='tournament', user_id=user.id, ref_id=t.id,
                               post_at=places.server_now()))
    db.session.commit()
    return True

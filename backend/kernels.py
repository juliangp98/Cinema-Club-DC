"""Kernels 🍿 (R10b): one total per member, from three places —

  polls      picks in scored polls (app.vote_kernels)
  going_out  checking in to a screening (+5), +2 more if you'd said you were
             going; trailblazer: +1 for each member who joined a screening you
             were going to first (up to +5); crew night: +3 each when 3+
             members checked in to the same screening
  trivia     right trivia answers (trivia.py; off unless the club turned it
             on): +2 for the question of the day, +1 anytime (up to 5 a day)
  bingo      repertory bingo (bingo.py; off unless the club turned it on):
             +5 for a first line on the month's card, +15 for the full card
  games      the quiz games (quizzes.py; each off unless the club turned it
             on): +1 a right call, at most 5 a day from each game
  members    what other members gave you (or took) for your activity

Everything but the gifts is worked out from the source tables, like poll
kernels, so un-RSVPing or changing a check-in changes the count with it.
Gifts live in KernelGift, one row per giver, recipient, screening and week.

Check-ins are personal (not per club), so "went" counts in every club, as
the leaderboard's attendance always has; RSVP-based kernels count in the club
the RSVP was made in.
"""
from datetime import datetime, timedelta

WENT, PLANNED = 5, 2
TRAIL_EACH, TRAIL_MAX = 1, 5
CREW_MIN, CREW = 3, 3
GIVE_PER_WEEK, TAKE_PER_WEEK = 10, 3       # each member's weekly allowance
GIVE_PER_CARD, TAKE_PER_CARD = 3, 1        # per person, per screening, per week
MAX_TAKEN_PER_WEEK = 5                     # the most anyone loses to takes in a week
ACTIVITY = ('went', 'going', 'maybe', 'commented', 'reacted')


def week_start(now=None):
    """The Monday a give or take counts against (allowances reset then)."""
    d = (now or datetime.now()).date()
    return d - timedelta(days=d.weekday())


def _groups_of(user_ids):
    from app import GroupMembership
    return sorted({m.group_id for m in GroupMembership.query.filter(GroupMembership.user_id.in_(list(user_ids)),
                                                                  GroupMembership.status == 'active')})


def _since_filter(since):
    """showtime id -> whether it screened since `since` (everything when None)."""
    from app import db, Showtime
    if since is None:
        return lambda sid: True
    cache = {}

    def ok(sid):
        if sid not in cache:
            s = db.session.get(Showtime, sid)
            cache[sid] = bool(s and s.start_time >= since)
        return cache[sid]
    return ok


def going_out(user_ids, group_id=None, since=None):
    """{uid: {'went', 'planned', 'trailblazer', 'crew'}} — kernels from going
    to screenings, in one club (or overall: each screening counted once);
    with `since`, only screenings since then."""
    from app import Attendance, RSVP, member_ids
    out = {u: {'went': 0, 'planned': 0, 'trailblazer': 0, 'crew': 0} for u in user_ids}
    if not out:
        return out
    in_period = _since_filter(since)
    answers = Attendance.query.filter(Attendance.user_id.in_(list(out)), Attendance.status.isnot(None)).all()
    went = {(a.user_id, a.showtime_id) for a in answers if a.status == 'went' and in_period(a.showtime_id)}
    missed = {(a.user_id, a.showtime_id) for a in answers if a.status == 'missed'}
    for uid, _ in went:
        out[uid]['went'] += WENT
    q = RSVP.query.filter(RSVP.user_id.in_(list(out)), RSVP.status == 'going')
    if group_id:
        q = q.filter(RSVP.group_id == group_id)
    for uid, _ in {(r.user_id, r.showtime_id) for r in q} & went:
        out[uid]['planned'] += PLANNED

    trail, crew = {}, {}                     # (uid, showtime) -> kernels; a screening counts once overall
    for gid in ([group_id] if group_id else _groups_of(out)):
        members = member_ids(gid)
        if not members:
            continue
        going = {}
        for r in RSVP.query.filter(RSVP.group_id == gid, RSVP.status == 'going').order_by(RSVP.created_at, RSVP.id):
            if r.user_id in members:
                going.setdefault(r.showtime_id, []).append(r.user_id)
        for sid, uids in going.items():
            if not in_period(sid):
                continue
            lead = uids[0]
            if lead in out and len(uids) > 1 and (lead, sid) not in missed:
                trail[(lead, sid)] = max(trail.get((lead, sid), 0), min(TRAIL_MAX, (len(uids) - 1) * TRAIL_EACH))
        checked_in = {}
        for a in Attendance.query.filter(Attendance.user_id.in_(list(members)), Attendance.status == 'went'):
            checked_in.setdefault(a.showtime_id, set()).add(a.user_id)
        for sid, uids in checked_in.items():
            if len(uids) >= CREW_MIN and in_period(sid):
                for uid in uids & set(out):
                    crew[(uid, sid)] = CREW
    for (uid, _), k in trail.items():
        out[uid]['trailblazer'] += k
    for (uid, _), k in crew.items():
        out[uid]['crew'] += k
    return out


def from_members(user_ids, group_id=None, since=None):
    """{uid: net kernels other members gave (minus took)} (given since `since`)."""
    from app import db, KernelGift
    if not user_ids:
        return {}
    q = (db.session.query(KernelGift.recipient_id, db.func.sum(KernelGift.amount))
         .filter(KernelGift.recipient_id.in_(list(user_ids))))
    if group_id:
        q = q.filter(KernelGift.group_id == group_id)
    if since:
        q = q.filter(KernelGift.created_at >= since)
    return {uid: int(n or 0) for uid, n in q.group_by(KernelGift.recipient_id)}


def breakdowns(user_ids, group_id=None, since=None):
    """{uid: {kernels, correct, polls, going_out, trivia, members, detail}} —
    `kernels` is the one total; the rest say where it came from. `since` (a
    local datetime): only what was earned since then — screenings by their
    date, polls by when they were scored, trivia by the question's day, bingo
    by the card's month, gifts by when they were given."""
    import bingo
    import trivia
    from app import calc_user_kernels
    user_ids = list(dict.fromkeys(user_ids))
    out_k, gifts = going_out(user_ids, group_id, since), from_members(user_ids, group_id, since)
    quizzes = trivia.kernels_for(user_ids, group_id, since)
    games = __import__('quizzes').kernels_for(user_ids, group_id, since)
    cards = bingo.kernels_for(user_ids, group_id, since)
    result = {}
    for uid in user_ids:
        polls, correct = calc_user_kernels(uid, group_id=group_id, since=since)
        go, quiz = sum(out_k[uid].values()), quizzes.get(uid, 0)
        card, game = cards.get(uid, 0), games.get(uid, 0)
        result[uid] = {'kernels': polls + go + quiz + card + game + gifts.get(uid, 0), 'correct': correct,
                       'polls': polls, 'going_out': go, 'trivia': quiz, 'bingo': card, 'games': game,
                       'members': gifts.get(uid, 0),
                       'detail': out_k[uid]}
    return result


PARTS = ('polls', 'going_out', 'trivia', 'bingo', 'games', 'members')   # a breakdown's parts, in the order they're shown


def rules(group_id=None):
    """How kernels are earned, for /play's My kernels and the site (trivia: only when
    the club has it on)."""
    import bingo
    import quizzes
    import trivia
    from app import db, Group
    group = db.session.get(Group, group_id) if group_id else None
    return {'went': WENT, 'planned': PLANNED, 'trailblazer_max': TRAIL_MAX, 'crew_min': CREW_MIN, 'crew': CREW,
            'give': GIVE_PER_WEEK, 'take': TAKE_PER_WEEK,
            'trivia': trivia.DAILY_KERNELS if group and group.trivia_enabled else None,      # by difficulty (R15)
            'trivia_anytime': {'each': trivia.ANYTIME_KERNEL_TABLE, 'per_day': trivia.ANYTIME_DAILY_CAP}
            if group and group.trivia_anytime else None,
            'bingo': {'line': bingo.LINE_KERNELS, 'full': bingo.FULL_KERNELS} if group and group.bingo_enabled else None,
            'games': [{'label': quizzes.GAMES[k][1], 'each': quizzes.GAMES[k][3], 'per_day': quizzes.DAILY_CAP,
                       'by_step': k in quizzes.BY_STEP}
                      for k, v in quizzes.switches(group).items() if v] if group else []}


def breakdown(user_id, group_id=None):
    return breakdowns([user_id], group_id)[user_id]


# ─── Giving and taking ────────────────────────────────────────────────────────

def card_people(group_id, showtime_id):
    """{uid: what they did} — the club's members with activity on a screening
    (the people you can give kernels to, or take from, on its card)."""
    from app import Attendance, Message, RSVP, Reaction, member_ids, went_visible_in
    members = member_ids(group_id)
    did = {}
    went = [a for a in Attendance.query.filter_by(showtime_id=showtime_id, status='went') if a.user_id in members]
    for a in went_visible_in(group_id, went):
        did.setdefault(a.user_id, 'went')
    for r in RSVP.query.filter(RSVP.group_id == group_id, RSVP.showtime_id == showtime_id,
                               RSVP.status.in_(('going', 'maybe'))):
        did.setdefault(r.user_id, r.status)
    for m in Message.query.filter_by(group_id=group_id, showtime_id=showtime_id):
        did.setdefault(m.user_id, 'commented')
    for r in Reaction.query.filter_by(group_id=group_id, showtime_id=showtime_id):
        did.setdefault(r.user_id, 'reacted')
    return {uid: d for uid, d in did.items() if uid in members}


def allowance(giver_id, now=None):
    """What's left of this week's allowance: {give_left, take_left, resets}."""
    from app import KernelGift
    rows = KernelGift.query.filter_by(giver_id=giver_id, week=week_start(now)).all()
    given = sum(max(r.amount, 0) for r in rows)
    taken = sum(max(-r.amount, 0) for r in rows)
    return {'give_left': max(0, GIVE_PER_WEEK - given), 'take_left': max(0, TAKE_PER_WEEK - taken),
            'resets': (week_start(now) + timedelta(days=7)).isoformat()}


def card_kernels(group_id, showtime_id, viewer_id, now=None):
    """{'net': {uid: kernels from members on this screening}, 'mine': {uid:
    what you've given (or taken) this week}}."""
    from app import KernelGift
    net, mine = {}, {}
    for g in KernelGift.query.filter_by(group_id=group_id, showtime_id=showtime_id):
        net[g.recipient_id] = net.get(g.recipient_id, 0) + g.amount
        if g.giver_id == viewer_id and g.week == week_start(now):
            mine[g.recipient_id] = g.amount
    return {'net': net, 'mine': mine}


CARD_DAYS = 30                             # Give kernels in Discord: screenings this close either side


def member_cards(group_id, user_id, viewer_id, now=None, limit=10):
    """The screenings `user_id` did something on lately (the ones you could
    give them kernels for on the feed), newest first: [{screening, did,
    mine, net}] — `mine` is what you've given (or taken) this week."""
    from app import Attendance, Message, RSVP, Reaction, Showtime, _screening_item
    now = now or datetime.now()
    ids = {a.showtime_id for a in Attendance.query.filter_by(user_id=user_id, status='went')}
    ids |= {r.showtime_id for r in RSVP.query.filter(RSVP.group_id == group_id, RSVP.user_id == user_id,
                                                     RSVP.status.in_(('going', 'maybe')))}
    ids |= {m.showtime_id for m in Message.query.filter_by(group_id=group_id, user_id=user_id) if m.showtime_id}
    ids |= {r.showtime_id for r in Reaction.query.filter_by(group_id=group_id, user_id=user_id) if r.showtime_id}
    shows = (Showtime.query.filter(Showtime.id.in_(list(ids)), Showtime.start_time >= now - timedelta(days=CARD_DAYS),
                                   Showtime.start_time <= now + timedelta(days=CARD_DAYS))
             .order_by(Showtime.start_time.desc()).all() if ids else [])
    out = []
    for s in shows:
        did = card_people(group_id, s.id).get(user_id)
        if not did:
            continue                        # e.g. a check-in the club can't see
        k = card_kernels(group_id, s.id, viewer_id, now)
        out.append({'screening': _screening_item(s), 'did': did, 'mine': k['mine'].get(user_id, 0),
                    'net': k['net'].get(user_id, 0)})
        if len(out) == limit:
            break
    return out


def toss(giver, recipient_id, group_id, showtime_id, delta, now=None):
    """Give (+1) or take (−1) a kernel for someone's activity on a screening,
    or undo one. Returns (KernelGift, error)."""
    from app import db, KernelGift, _active_membership, _utcnow_naive
    if delta not in (1, -1):
        return None, 'Give or take one kernel at a time.'
    if giver.is_guest:
        return None, 'Make an account to give kernels.'
    if recipient_id == giver.id:
        return None, "You can't give yourself kernels."
    if not _active_membership(giver, group_id):
        return None, 'Not a club member.'
    if recipient_id not in card_people(group_id, showtime_id):
        return None, "They haven't done anything on this screening yet."
    week = week_start(now)
    row = KernelGift.query.filter_by(giver_id=giver.id, recipient_id=recipient_id, group_id=group_id,
                                     showtime_id=showtime_id, week=week).first()
    before = row.amount if row else 0
    after = before + delta
    if after > GIVE_PER_CARD:
        return None, f'Up to {GIVE_PER_CARD} kernels per person per screening.'
    if after < -TAKE_PER_CARD:
        return None, f'You can only take {TAKE_PER_CARD} per person per screening.'
    left = allowance(giver.id, now)
    if after > 0 and after > before and left['give_left'] < 1:
        return None, f"You've given all {GIVE_PER_WEEK} this week — more on Monday."
    if after < 0 and after < before:
        if left['take_left'] < 1:
            return None, f"You've taken all {TAKE_PER_WEEK} this week — more on Monday."
        lost = sum(max(-r.amount, 0) for r in KernelGift.query.filter_by(recipient_id=recipient_id, week=week))
        if lost >= MAX_TAKEN_PER_WEEK:
            return None, "They've lost enough kernels this week."
        if breakdown(recipient_id, group_id)['kernels'] < 1:
            return None, "They don't have any kernels to take."
    if not row:
        row = KernelGift(giver_id=giver.id, recipient_id=recipient_id, group_id=group_id,
                         showtime_id=showtime_id, week=week, amount=0)
        db.session.add(row)
    row.amount, row.updated_at = after, _utcnow_naive()
    return row, None

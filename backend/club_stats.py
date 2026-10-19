"""The club's numbers (R15): each member's stats for a period (the
leaderboard's details, the member tiles), the leaderboard's superlatives, and
the Overview's club stats.

Periods: this month, this year, all time. Kernels count by when they were
earned (kernels.breakdowns `since`); everything else by when it happened — a
screening by its date, a comment when it was posted, trivia by the
question's day, bingo by the card's month.

Screenings are the leaderboard's "attended" (app.attended_showtime_ids):
confirmed check-ins, plus past "going" RSVPs in this club nobody took back.
"""
import re
from datetime import datetime, timedelta

PERIODS = ('week', 'month', 'year', 'all')     # week: Play's "this week's movers"
FILM_PRINT = re.compile(r'\b(16|35|70)\s*mm\b|nitrate', re.I)
LATE = (21, 30)                  # a Night owl screening starts at 9:30 PM or later
SHARPSHOOTER_MIN = 10            # trivia answers before accuracy can win anything
CREW_MIN = 3                     # members at one screening for a crew night (as kernels.CREW_MIN)

# (key, emoji, title, what it counts, stat, the least that can win)
SUPERLATIVES = (
    ('night_owl', '🦉', 'Night owl', 'screenings at 9:30 PM or later', 'late', 2),
    ('purist', '🎞️', 'Purist', 'film-print screenings', 'film_prints', 2),
    ('explorer', '🧭', 'Explorer', 'different theatres', 'theatres', 3),
    ('early_bird', '🐦', 'Early bird', "times first to say they're going", 'first_going', 2),
    ('critic', '✍️', 'Critic', 'comments on screenings', 'comments', 3),
    ('sharpshooter', '🎯', 'Sharpshooter', 'trivia accuracy', 'trivia_accuracy', 1),
    ('regular', '🔥', 'Regular', 'weeks in a row with a screening', 'week_streak', 2),
)


def since_of(period, now=None):
    """The local datetime a period starts (None: all time)."""
    now = now or datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == 'week':
        return start - timedelta(days=start.weekday())
    if period == 'month':
        return start.replace(day=1)
    if period == 'year':
        return start.replace(month=1, day=1)
    return None


def _longest_run(weeks):
    """The longest run of consecutive Mondays in a set of them."""
    best = run = 0
    prev = None
    for w in sorted(weeks):
        run = run + 1 if prev and w - prev == timedelta(days=7) else 1
        best, prev = max(best, run), w
    return best


def _club_screenings(group, user_ids, since, now):
    """{uid: [Showtime]} — the screenings each member saw in the period."""
    from app import db, Showtime, attended_showtime_ids
    out = {}
    for uid in user_ids:
        ids = attended_showtime_ids(uid, {group.id})
        shows = [s for s in (db.session.get(Showtime, i) for i in ids) if s and s.start_time < now
                 and (since is None or s.start_time >= since)]
        out[uid] = sorted(shows, key=lambda s: s.start_time)
    return out


def _first_going(group, members, since):
    """{uid: screenings where they said "going" first and another member joined}."""
    from app import RSVP, Showtime
    going = {}
    q = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
         .filter(RSVP.group_id == group.id, RSVP.status == 'going'))
    if since:
        q = q.filter(Showtime.start_time >= since)
    for r in q.order_by(RSVP.created_at, RSVP.id):
        if r.user_id in members:
            going.setdefault(r.showtime_id, []).append(r.user_id)
    out = {}
    for uids in going.values():
        if len(set(uids)) > 1:
            out[uids[0]] = out.get(uids[0], 0) + 1
    return out


def _trivia(group, user_ids, since):
    """{uid: {answered, correct, accuracy, streak}} — questions of the day
    (and anytime ones) in the club; the streak is the most daily questions in
    a row answered right."""
    from app import TriviaAnswer, TriviaQuestion
    q = TriviaQuestion.query.filter(TriviaQuestion.group_id == group.id)
    if since:
        q = q.filter(TriviaQuestion.day >= since.date())
    questions = q.all()
    by_id = {x.id: x for x in questions}
    daily = sorted((x for x in questions if x.slot == 'daily'), key=lambda x: x.day)
    answers = {}
    if by_id:
        for a in TriviaAnswer.query.filter(TriviaAnswer.question_id.in_(list(by_id)),
                                           TriviaAnswer.user_id.in_(list(user_ids))):
            answers.setdefault(a.user_id, {})[a.question_id] = a.correct
    out = {}
    for uid in user_ids:
        mine = answers.get(uid, {})
        best = run = 0
        for x in daily:
            run = run + 1 if mine.get(x.id) else 0
            best = max(best, run)
        n, right = len(mine), sum(1 for c in mine.values() if c)
        out[uid] = {'answered': n, 'correct': right, 'accuracy': round(100 * right / n) if n else None, 'streak': best}
    return out


def _bingo(group, user_ids, since):
    """{uid: {lines, cards}} — first lines and full cards on the club's cards."""
    import bingo
    from app import BingoCard
    first = bingo.month_of(since) if since else None
    out = {uid: {'lines': 0, 'cards': 0} for uid in user_ids}
    for card in BingoCard.query.filter_by(group_id=group.id):
        if first and card.month < first:
            continue
        for uid in user_ids:
            p = bingo.progress(card, uid)
            out[uid]['lines'] += bool(p['line_at'])
            out[uid]['cards'] += bool(p['full_at'])
    return out


def _quizzes(group, user_ids, since):
    """{uid: {rounds, best_streak, right}} — quiz games played (R15), the
    longest higher-or-lower run, and the other games' rounds got right (7g,
    Records)."""
    from app import QuizRound
    q = QuizRound.query.filter(QuizRound.group_id == group.id, QuizRound.user_id.in_(list(user_ids)))
    if since:
        q = q.filter(QuizRound.day >= since.date())
    out = {uid: {'rounds': 0, 'best_streak': 0, 'right': 0} for uid in user_ids}
    for r in q:
        out[r.user_id]['rounds'] += 1
        if r.kind == 'higher_lower':
            out[r.user_id]['best_streak'] = max(out[r.user_id]['best_streak'], r.score)
        elif r.score:
            out[r.user_id]['right'] += 1
    return out


def _comments(group, user_ids, since):
    from app import db, Message
    q = (db.session.query(Message.user_id, db.func.count(Message.id))
         .filter(Message.group_id == group.id, Message.user_id.in_(list(user_ids))))
    if since:
        q = q.filter(Message.created_at >= since)
    return dict(q.group_by(Message.user_id).all())


def member_stats(group, user_ids, since=None, now=None):
    """{uid: {screenings, film_prints, theatres, late, crew_nights,
    week_streak, first_going, comments, trivia {...}, bingo {...}, last_out}}."""
    from app import member_ids
    now = now or datetime.now()
    user_ids = list(dict.fromkeys(user_ids))
    shows = _club_screenings(group, member_ids(group.id), since, now)
    together = {}
    for uid, ss in shows.items():
        for s in ss:
            together.setdefault(s.id, set()).add(uid)
    first, quiz = _first_going(group, member_ids(group.id), since), _trivia(group, user_ids, since)
    cards, talk = _bingo(group, user_ids, since), _comments(group, user_ids, since)
    played = _quizzes(group, user_ids, since)
    out = {}
    for uid in user_ids:
        ss = shows.get(uid, [])
        out[uid] = {
            'screenings': len(ss),
            'film_prints': sum(1 for s in ss if FILM_PRINT.search(f'{s.format_label or ""} {s.event_label or ""}')),
            'theatres': len({s.theatre_id for s in ss}),
            'late': sum(1 for s in ss if (s.start_time.hour, s.start_time.minute) >= LATE),
            'crew_nights': sum(1 for s in ss if len(together.get(s.id, ())) >= CREW_MIN),
            'week_streak': _longest_run({(s.start_time - timedelta(days=s.start_time.weekday())).date() for s in ss}),
            'first_going': first.get(uid, 0),
            'comments': talk.get(uid, 0),
            'trivia': quiz[uid],
            'bingo': cards[uid],
            'quizzes': played[uid],
            'last_out': ss[-1].start_time.isoformat() if ss else None,
        }
    return out


def superlatives(rows):
    """The period's titles: who leads each (rows are in leaderboard order, so a
    tie goes to the higher place), if anyone reached the least it takes."""
    out = []
    for key, emoji, title, what, stat, least in SUPERLATIVES:
        def value(r):
            if stat == 'trivia_accuracy':
                t = r['stats']['trivia']
                return t['accuracy'] if t['answered'] >= SHARPSHOOTER_MIN else None
            return r['stats'][stat]
        best = None
        for r in rows:
            v = value(r)
            if v is not None and v >= least and (best is None or v > best[1]):
                best = (r, v)
        if best:
            out.append({'key': key, 'emoji': emoji, 'title': title, 'what': what, 'value': best[1],
                        'user': best[0]['user']})
    return out


def leaderboard(group, period='all', now=None):
    """{period, since, rows, superlatives}: the standings for a period — kernels
    (and where they came from), correct poll picks, screenings, and stats.
    Each row's `place` is shared by everyone on the same kernels."""
    import kernels
    since = since_of(period, now)
    members = [m for m in group.memberships if m.status == 'active' and m.user]
    uids = [m.user_id for m in members]
    counts = kernels.breakdowns(uids, group.id, since)
    stats = member_stats(group, uids, since, now)
    rows = [{'user': m.user.public_dict(), 'kernels': counts[m.user_id]['kernels'],
             'correct': counts[m.user_id]['correct'], 'attendance': stats[m.user_id]['screenings'],
             'breakdown': {part: counts[m.user_id][part] for part in kernels.PARTS},
             'stats': stats[m.user_id]} for m in members]
    rows.sort(key=lambda r: (-r['kernels'], -r['correct'], -r['attendance']))
    for r in rows:                     # ties share a place: 1, 1, 3
        r['place'] = 1 + sum(1 for x in rows if x['kernels'] > r['kernels'])
    return {'period': period, 'since': since.isoformat() if since else None, 'rows': rows,
            'superlatives': superlatives(rows)}


def overview(group, now=None):
    """The Overview's club stats: {month_label, screenings_together, member_screenings,
    most_wanted, busiest_theatre, top, members: {uid: {screenings, last_out}}}."""
    from app import db, Showtime, Theatre, Watchlist, _group_showtime_query, member_ids
    now = now or datetime.now()
    since = since_of('month', now)
    members = member_ids(group.id)
    month = _club_screenings(group, members, since, now)
    ever = _club_screenings(group, members, None, now)
    together, by_theatre = {}, {}
    for uid, ss in month.items():
        for s in ss:
            together.setdefault(s.id, set()).add(uid)
            by_theatre[s.theatre_id] = by_theatre.get(s.theatre_id, 0) + 1

    wanted = {}
    for w in Watchlist.query.filter(Watchlist.user_id.in_(list(members))) if members else []:
        wanted[w.movie_id] = wanted.get(w.movie_id, 0) + 1
    most_wanted = None
    for movie_id, n in sorted(wanted.items(), key=lambda kv: -kv[1]):
        nxt = (_group_showtime_query(group).filter(Showtime.movie_id == movie_id, Showtime.start_time >= now)
               .order_by(Showtime.start_time).first())
        if nxt:
            m = nxt.movie
            most_wanted = {'movie': {'id': m.id, 'title': m.title, 'poster_url': m.poster_url,
                                     'release_year': m.release_year},
                           'wanters': n, 'next': nxt.start_time.isoformat(), 'showtime_id': nxt.id}
            break
    busiest = None
    if by_theatre:
        tid, n = max(by_theatre.items(), key=lambda kv: kv[1])
        t = db.session.get(Theatre, tid)
        busiest = {'theatre': {'slug': t.slug, 'name': t.name, 'short_name': t.short_name, 'color': t.color},
                   'screenings': n}
    board = leaderboard(group, 'month', now)
    return {
        'month_label': since.strftime('%B'),
        'screenings_together': sum(1 for uids in together.values() if len(uids) >= 2),
        'member_screenings': sum(len(ss) for ss in month.values()),
        'most_wanted': most_wanted,
        'busiest_theatre': busiest,
        'top': [{'user': r['user'], 'kernels': r['kernels'], 'place': r['place']} for r in board['rows'][:3] if r['kernels'] > 0],
        'members': {uid: {'screenings': len(month.get(uid, [])),
                          'last_out': ever[uid][-1].start_time.isoformat() if ever.get(uid) else None}
                    for uid in members},
    }

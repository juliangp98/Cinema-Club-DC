"""Repertory bingo (R10e), off until a club admin turns it on: a 3×3 card a
month, the same for every member, with a free middle. It fills in by itself
from check-ins ("went") during the month — one screening can tick every
square it fits. A first line is worth LINE_KERNELS, the full card
FULL_KERNELS more.

A square goes on the card only if this month's calendar at the club's
theatres makes it possible (at least MIN_CHANCES showings fit), and the card
is kept once made, so it doesn't change as the calendar does.

Home viewing (R15, the club's own switch, off by default): Letterboxd diary
entries from the month fill the squares the film alone decides — its era,
genre, length — and "Off your watchlist", once nothing seen in person has.
A line that needs one is worth HOME_LINE_KERNELS, a full card that does
HOME_FULL_KERNELS. Entries that matched a screening count as that screening.
"""
import json
import random
import re
from datetime import datetime

LINE_KERNELS, FULL_KERNELS = 5, 15
HOME_LINE_KERNELS, HOME_FULL_KERNELS = 3, 10              # when a home-viewing square was needed (R15)
MIN_CHANCES = 2
FREE = 4                                                    # the middle of the 3×3 grid
LINES = ((0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6))
PER_CATEGORY = 2

# key: (emoji, label, category, how it's checked)
SQUARES = {
    'film': ('🎞️', 'On film', 'format', 'A 35mm, 16mm or 70mm print'),
    'big': ('🎬', 'Big screen', 'format', '70mm, IMAX or Dolby'),
    'pre1960': ('📼', 'Made before 1960', 'era', 'Released before 1960'),
    'seventies': ('🕺', "From the '70s or '80s", 'era', 'Released 1970–1989'),
    'new': ('🆕', 'A new release', 'era', 'Released this year or last'),
    'documentary': ('🎥', 'A documentary', 'genre', 'Listed as a documentary'),
    'horror': ('👻', 'A horror film', 'genre', 'Listed as horror'),
    'comedy': ('😂', 'A comedy', 'genre', 'Listed as a comedy'),
    'long': ('⏳', 'Over 2½ hours', 'length', 'Runs more than 150 minutes'),
    'matinee': ('☀️', 'A matinee', 'time', 'Starts before 5 PM'),
    'late': ('🌙', 'A late show', 'time', 'Starts 9:30 PM or later'),
    'event': ('🎤', 'A Q&A or special event', 'event', 'An intro, Q&A, premiere, anniversary…'),
    'new_theatre': ('🗺️', "A theatre you'd never been to", 'you', 'Your first check-in there'),
    'double': ('🍿', 'Two in one day', 'you', 'Two check-ins on the same day'),
    'watchlist': ('📋', 'Off your watchlist', 'you', 'A film on your watchlist'),
    'crew': ('👥', 'Crew night', 'club', '3+ members checked in'),
    'trailblazer': ('🚩', 'Trailblazer', 'club', 'You said you were going first'),
}
SHOW_SQUARES = [k for k, v in SQUARES.items() if v[2] not in ('you', 'club')]   # decided by the showing alone
FILM_SQUARES = [k for k, v in SQUARES.items() if v[2] in ('era', 'genre', 'length')]   # by the film alone
HOME_SQUARES = FILM_SQUARES + ['watchlist']                 # what a diary entry can fill (R15)


def month_of(d=None):
    return (d or datetime.now()).strftime('%Y-%m')


def month_bounds(month):
    y, m = map(int, month.split('-'))
    start = datetime(y, m, 1)
    return start, datetime(y + (m == 12), m % 12 + 1, 1)


def _year(m):
    try:
        return int((m.release_year or '')[:4])
    except ValueError:
        return None


def film_fits(key, year, genres, runtime, this_year=None):
    """Does a film (its year, genres text, runtime) fit square `key` — for
    the squares the film alone decides (a showing's, or a diary entry's)."""
    g = {x.strip() for x in (genres or '').lower().split(',')}
    this_year = this_year or datetime.now().year
    return {
        'pre1960': lambda: bool(year and year < 1960),
        'seventies': lambda: bool(year and 1970 <= year < 1990),
        'new': lambda: bool(year and year >= this_year - 1),
        'documentary': lambda: 'documentary' in g,
        'horror': lambda: 'horror' in g,
        'comedy': lambda: 'comedy' in g,
        'long': lambda: (runtime or 0) > 150,
    }.get(key, lambda: False)()


def show_fits(key, s, this_year=None):
    """Does showing `s` fit square `key` (for the squares the showing decides)?"""
    import discover
    from app import EVENT_WORDS
    if key in FILM_SQUARES:
        return film_fits(key, _year(s.movie), s.movie.genres, s.movie.runtime_minutes, this_year)
    return {
        'film': lambda: discover._show_ok(s, None, {'film'}, None),
        'big': lambda: discover._show_ok(s, None, {'big'}, None),
        'matinee': lambda: discover._show_ok(s, None, None, 'matinee'),
        'late': lambda: discover._show_ok(s, None, None, 'late'),
        'event': lambda: any(re.search(p, s.event_label or '', re.I) for p, _ in EVENT_WORDS),
    }.get(key, lambda: False)()


def card_for(group, month=None):
    """The club's card for `month` (this one): made on first ask, then kept."""
    from sqlalchemy.exc import IntegrityError
    from app import db, BingoCard
    month = month or month_of()
    card = BingoCard.query.filter_by(group_id=group.id, month=month).first()
    if card:
        return card
    squares = _pick(group, month, random.Random(f'{group.id}:{month}'))
    card = BingoCard(group_id=group.id, month=month, squares_json=json.dumps(squares))
    db.session.add(card)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        card = BingoCard.query.filter_by(group_id=group.id, month=month).first()
    return card


def reshuffle(card):
    """New squares for a card (R14: an admin's "Reshuffle" before it's posted);
    everyone's progress follows the new squares."""
    from app import db, Group
    group = db.session.get(Group, card.group_id)
    old = json.loads(card.squares_json)
    for _ in range(10):
        picked = _pick(group, card.month, random.Random())
        if picked != old:
            break
    card.squares_json = json.dumps(picked)
    db.session.commit()


def _pick(group, month, rng):
    """8 squares this month's calendar can fill (a few from each kind)."""
    from app import Showtime, _group_showtime_query
    start, end = month_bounds(month)
    shows = _group_showtime_query(group).filter(Showtime.start_time >= max(start, datetime.now()),
                                                Showtime.start_time < end).all()
    possible = [k for k in SHOW_SQUARES if sum(1 for s in shows if show_fits(k, s, start.year)) >= MIN_CHANCES]
    always = [k for k in SQUARES if k not in SHOW_SQUARES]
    pool = rng.sample(possible, len(possible)) + rng.sample(always, len(always))
    picked, per = [], {}
    for k in pool:
        cat = SQUARES[k][2]
        if per.get(cat, 0) < PER_CATEGORY:
            picked.append(k)
            per[cat] = per.get(cat, 0) + 1
        if len(picked) == 8:
            break
    for k in pool + rng.sample(SHOW_SQUARES, len(SHOW_SQUARES)):   # a thin calendar: fill up anyway
        if len(picked) == 8:
            break
        if k not in picked:
            picked.append(k)
    rng.shuffle(picked)
    return picked


def _grid(card):
    keys = json.loads(card.squares_json)
    return keys[:FREE] + [None] + keys[FREE:]


def progress(card, user_id, home=None):
    """Where a member is on a card: {squares: [(key, showtime, when, diary
    entry) or None for the free middle], filled, home, line_at, full_at,
    kernels}. A square is filled by the first check-in (in the order they
    were made) that fits; then, if the club counts home viewing (`home`, the
    club's switch when not given), by the month's diary entries."""
    from app import db, Attendance, Group, RSVP, Showtime, Watchlist, member_ids
    start, end = month_bounds(card.month)
    rows = (Attendance.query.join(Showtime, Attendance.showtime_id == Showtime.id)
            .filter(Attendance.user_id == user_id, Attendance.status == 'went',
                    Showtime.start_time >= start, Showtime.start_time < end)
            .order_by(Attendance.answered_at, Attendance.id).all())
    grid = _grid(card)
    keys = [k for k in grid if k]
    done = {}
    if rows:
        earlier = {(a.showtime.theatre_id) for a in Attendance.query.join(Showtime, Attendance.showtime_id == Showtime.id)
                   .filter(Attendance.user_id == user_id, Attendance.status == 'went', Showtime.start_time < start)}
        days = {}
        for a in rows:
            days.setdefault(a.showtime.start_time.date(), []).append(a)
        wanted = ({w.movie_id for w in Watchlist.query.filter_by(user_id=user_id)} if 'watchlist' in keys else set())
        members = (member_ids(card.group_id)
                   if {'crew', 'trailblazer'} & set(keys) else set())
        seen_theatres = set(earlier)
        for a in rows:
            s = a.showtime

            def fits(k):
                if k in SHOW_SQUARES:
                    return show_fits(k, s, start.year)
                if k == 'new_theatre':
                    return s.theatre_id not in seen_theatres
                if k == 'double':
                    return len(days[s.start_time.date()]) >= 2
                if k == 'watchlist':
                    return s.movie_id in wanted
                if k == 'crew':
                    return Attendance.query.filter(Attendance.showtime_id == s.id, Attendance.status == 'went',
                                                   Attendance.user_id.in_(members)).count() >= 3
                if k == 'trailblazer':
                    going = (RSVP.query.filter_by(group_id=card.group_id, showtime_id=s.id, status='going')
                             .order_by(RSVP.created_at, RSVP.id).all())
                    going = [r for r in going if r.user_id in members]
                    return len(going) >= 2 and going[0].user_id == user_id
                return False
            for k in keys:
                if k not in done and fits(k):
                    done[k] = (s, a.answered_at)
            seen_theatres.add(s.theatre_id)
    if home is None:
        home = bool(getattr(db.session.get(Group, card.group_id), 'bingo_home', False))
    at_home = _home_fill(card, user_id, [k for k in keys if k in HOME_SQUARES and k not in done], start, end) if home else {}
    squares = [None if k is None else (k, *done.get(k, (None, None)), None) if k in done
               else (k, None, *at_home.get(k, (None, None))) for k in grid]
    when = {i: (squares[i][2] if squares[i] and (squares[i][1] or squares[i][3]) else None) for i in range(9)}
    filled = {i for i in range(9) if i == FREE or when[i]}
    homes = {i for i in range(9) if squares[i] and squares[i][3] is not None}

    def finished(cells):
        times = [when[i] for i in cells if i != FREE]
        return max(times) if all(i in filled for i in cells) and times else None
    done_lines = [(t, line) for t, line in ((finished(line), line) for line in LINES) if t]
    line_at = min(t for t, _ in done_lines) if done_lines else None
    full_at = finished(range(9))
    in_person_line = any(not homes & set(line) for _, line in done_lines)
    kernels = ((LINE_KERNELS if in_person_line else HOME_LINE_KERNELS) if line_at else 0) + \
        ((HOME_FULL_KERNELS if homes else FULL_KERNELS) if full_at else 0)
    return {'squares': squares, 'filled': len(filled) - 1, 'home': len(homes), 'lines': len(done_lines),
            'line_at': line_at, 'full_at': full_at, 'kernels': kernels}


def _home_fill(card, user_id, keys, start, end):
    """{key: (when, diary entry)}: the squares the month's diary entries fill
    (R15) — entries that matched no screening, earliest first."""
    from app import LetterboxdEntry, Watchlist
    import letterboxd
    if not keys:
        return {}
    entries = (LetterboxdEntry.query.filter(LetterboxdEntry.user_id == user_id, LetterboxdEntry.showtime_id.is_(None),
                                            LetterboxdEntry.watched_on >= start.date(), LetterboxdEntry.watched_on < end.date())
               .order_by(LetterboxdEntry.watched_on, LetterboxdEntry.id).all())
    wanted = ([w.movie for w in Watchlist.query.filter_by(user_id=user_id) if w.movie] if 'watchlist' in keys else [])
    out = {}
    for e in entries:
        entry = {'tmdb_id': e.tmdb_id, 'title': e.title, 'year': e.year}
        for k in keys:
            if k in out:
                continue
            fits = (any(letterboxd.same_film(m, entry) for m in wanted) if k == 'watchlist'
                    else film_fits(k, e.year, e.genres, e.runtime, start.year))
            if fits:
                out[k] = (datetime.combine(e.watched_on, datetime.min.time()), e)
    return out


def kernels_for(user_ids, group_id=None, since=None):
    """{uid: bingo kernels} across the clubs' cards (one club's, or all;
    with `since`, cards from that month on)."""
    from app import BingoCard, GroupMembership
    out = {}
    first = month_of(since) if since else None
    for uid in user_ids:
        groups = [group_id] if group_id else [m.group_id for m in GroupMembership.query.filter_by(user_id=uid,
                                                                                               status='active')]
        for card in BingoCard.query.filter(BingoCard.group_id.in_(groups)) if groups else []:
            if first and card.month < first:
                continue
            k = progress(card, uid)['kernels']
            if k:
                out[uid] = out.get(uid, 0) + k
    return out


def feed_events(group_id, member_ids, since):
    """('bingo', 'b<month>', when, uid, 'line' | 'full') for the club feed."""
    from app import BingoCard
    since_month = month_of(since)
    ev = []
    for card in BingoCard.query.filter(BingoCard.group_id == group_id, BingoCard.month >= since_month):
        for uid in member_ids:
            p = progress(card, uid)
            for kind in ('line', 'full'):
                at = p[f'{kind}_at']
                if at and at >= since:
                    ev.append(('bingo', f'b{card.month}', at, uid, kind))
    return ev


def view(group, user, month=None):
    """The card as the site and /play (My bingo card) show it: every square (and the
    screening — or, R15, the diary entry — that filled it), your lines, and
    how the club is doing."""
    from app import GroupMembership, _screening_item
    if not group or not group.bingo_enabled:
        return {'enabled': False}
    card = card_for(group, month)
    mine = progress(card, user.id)
    squares = []
    for i, cell in enumerate(mine['squares']):
        if cell is None:
            squares.append({'key': 'free', 'emoji': '🍿', 'label': 'Free', 'hint': 'On the house', 'done': True})
            continue
        key, s, _, entry = cell
        emoji, label, _, hint = SQUARES[key]
        squares.append({'key': key, 'emoji': emoji, 'label': label, 'hint': hint, 'done': bool(s or entry),
                        'by': _screening_item(s) if s else None,
                        'home': {'title': entry.title, 'watched_on': entry.watched_on.isoformat(), 'link': entry.link}
                        if entry else None})
    club = []
    for m in GroupMembership.query.filter_by(group_id=group.id, status='active'):
        if m.user_id == user.id or not m.user:
            continue
        p = progress(card, m.user_id)
        if p['filled']:
            club.append({'user': {'id': m.user.id, 'name': m.user.name}, 'filled': p['filled'],
                         'line': bool(p['line_at']), 'full': bool(p['full_at'])})
    club.sort(key=lambda r: (-r['filled'], r['user']['name']))
    start, _ = month_bounds(card.month)
    return {'enabled': True, 'month': card.month, 'month_label': start.strftime('%B %Y'), 'squares': squares,
            'filled': mine['filled'], 'lines': mine['lines'], 'line': bool(mine['line_at']), 'full': bool(mine['full_at']),
            'kernels': mine['kernels'], 'club': club,
            'rules': {'line': LINE_KERNELS, 'full': FULL_KERNELS, 'home': bool(group.bingo_home),
                      'home_line': HOME_LINE_KERNELS, 'home_full': HOME_FULL_KERNELS}}


"""Challenge scouting: the club's challenge stats, who you should challenge
(and why), and a roast of their movie habits.

  * stats(): the club's — most wins, most kernels won, the hottest streak,
    the biggest pot, the fiercest rivalry, the favorite game, tournament
    titles — and yours: record, win rate, your nemesis (who's beaten you
    most), your favorite victim, your best game, your biggest win.
  * picks(): every other member, with the numbers that matter — their
    kernels next to yours, their record and win rate, how you've done against
    them, their best and worst game — a tag ("Grudge match", "Fresh meat"…),
    the reasons, and a suggested game and stake. Best challenges first.
  * habits(): someone's movie habits, only from what the club already sees:
    screenings they went to (and when, and where), their watchlist and how
    much of it they've seen, "going" and then missing it, trivia, their taste
    (if they show it), their Letterboxd diary (if they connected one; star
    ratings only if they share them). Members who turned off "roastable"
    (Me → Settings → Privacy) show only the numbers.
  * roast(): a playful jab from those habits. The AI writes it when it can —
    it's never told anyone's name (it writes about THEM and YOU) — kept for
    the day; otherwise a line from the facts.
"""
import random
import re
from collections import Counter
from datetime import datetime, timedelta

import challenges

ROASTS_A_DAY = 3
STAKES = (0, 1, 2, 3, 5, 10, 15, 20, 25, 50)      # the stakes the site's sheet offers
_roasts = {}                      # (viewer, target, day) → [roast, …]

TAGS = {
    'grudge': ('😤', 'Grudge match'), 'fresh': ('🆕', 'Fresh meat'), 'streak': ('🔥', 'Streak breaker'),
    'top': ('👑', 'Top dog'), 'fish': ('🐋', 'Big fish'), 'easy': ('🎯', 'Easy pickings'), 'even': ('⚖️', 'Dead even'),
    'wild': ('🎲', 'Wild card'),
}


def _now():
    return datetime.utcnow()


def _pct(n, d):
    return round(100 * n / d) if d else None


# ─── The challenges themselves ────────────────────────────────────────────────

def _games_by_member(group_id):
    """{uid: {kind: [games played, games won]}} — every game of every decided
    challenge (each game of a gauntlet counts)."""
    out = {}
    for ch in challenges._decided(group_id):
        state = challenges._state(ch)
        won = state.get('round_winners', [])
        for r, rd in enumerate(challenges.rounds(ch)):
            for p in challenges.in_game(ch):
                row = out.setdefault(p.user_id, {}).setdefault(rd['kind'], [0, 0])
                row[0] += 1
                row[1] += int(r < len(won) and p.user_id in won[r])
    return out


def _versus(group_id, viewer_id):
    """{uid: {won, lost, tied, played}} — your record against each member."""
    out = {}
    for ch in challenges._decided(group_id, [viewer_id]):
        me = challenges.player(ch, viewer_id)
        if not me or me.status not in ('finished', 'forfeit'):
            continue
        state = challenges._state(ch)
        mine = challenges._rank(ch, state, viewer_id)
        winners = set(state.get('winners', []))
        for p in challenges.in_game(ch):
            if p.user_id == viewer_id:
                continue
            row = out.setdefault(p.user_id, {'won': 0, 'lost': 0, 'tied': 0, 'played': 0})
            row['played'] += 1
            if ch.tournament_id:                              # a match: one winner
                row['won' if viewer_id in winners else 'lost'] += 1
            else:
                theirs = challenges._rank(ch, state, p.user_id)
                row['won' if mine > theirs else 'lost' if mine < theirs else 'tied'] += 1
    return out


def _best(kinds, worst=False, least=2):
    """The game someone wins most (or least) often, among those they've played `least` times."""
    rated = [(w / n, n, k) for k, (n, w) in kinds.items() if n >= least]
    if not rated:
        return None
    rate, n, kind = (min if worst else max)(rated)
    emoji, name = challenges.label(kind)
    return {'kind': kind, 'emoji': emoji, 'label': name, 'played': n, 'win_rate': round(100 * rate)}


def stats(group, viewer_id):
    """The club's challenge stats, and yours."""
    from app import User, db, member_ids
    ids = member_ids(group.id)
    rec = challenges.records(ids, group.id)
    nets = challenges.kernels_for(ids, group.id)
    decided = challenges._decided(group.id)
    name = lambda uid: (db.session.get(User, uid).public_dict() if uid and db.session.get(User, uid) else None)
    out = {'decided': len(decided), 'kernels_moved': 0, 'club': [], 'you': None}
    pairs, kinds, pot = Counter(), Counter(), None
    for ch in decided:
        people = sorted(p.user_id for p in challenges.in_game(ch))
        out['kernels_moved'] += sum(p.net for p in ch.players if p.net and p.net > 0)
        for i, a in enumerate(people):
            for b in people[i + 1:]:
                pairs[(a, b)] += 1
        for rd in challenges.rounds(ch):
            kinds[rd['kind']] += 1
        size = ch.stake * len(people)
        if size and (not pot or size > pot[0]):
            pot = (size, ch)
    club = out['club']
    wins = max(ids, key=lambda u: (rec[u]['won'], -rec[u]['lost']), default=None)
    if wins and rec[wins]['won']:
        r = rec[wins]
        club.append({'key': 'wins', 'icon': '👑', 'label': 'Most wins', 'user': name(wins),
                     'value': f"{r['won']}–{r['lost']} ({_pct(r['won'], r['played'])}%)"})
    rich = max(ids, key=lambda u: nets.get(u, 0), default=None)
    if rich and nets.get(rich, 0) > 0:
        club.append({'key': 'kernels', 'icon': '🍿', 'label': 'Kernels won', 'user': name(rich), 'value': f"+{nets[rich]} 🍿"})
    hot = max(ids, key=lambda u: rec[u]['streak'], default=None)
    if hot and rec[hot]['streak'] >= 2:
        club.append({'key': 'streak', 'icon': '🔥', 'label': 'On a streak', 'user': name(hot), 'value': f"{rec[hot]['streak']} wins in a row"})
    champ = max(ids, key=lambda u: rec[u]['titles'], default=None)
    if champ and rec[champ]['titles']:
        club.append({'key': 'titles', 'icon': '🏆', 'label': 'Tournament titles', 'user': name(champ), 'value': str(rec[champ]['titles'])})
    if pot:
        size, ch = pot
        won = challenges._state(ch).get('winners', [])
        club.append({'key': 'pot', 'icon': '💰', 'label': 'Biggest pot', 'user': name(won[0]) if won else None,
                     'value': f"{size} 🍿 · {challenges.games_line(ch)}"})
    if pairs:
        (a, b), n = pairs.most_common(1)[0]
        if n >= 2:
            h = challenges.head_to_head(group.id, a, b)
            tied = f"–{h['tied']}" if h['tied'] else ''
            club.append({'key': 'rivalry', 'icon': '⚔️', 'label': 'Fiercest rivalry', 'user': name(a), 'other': name(b),
                         'value': f"{n} meetings · {h['won']}–{h['lost']}{tied}"})
    if kinds:
        kind, n = kinds.most_common(1)[0]
        club.append({'key': 'game', 'icon': challenges.label(kind)[0], 'label': 'Favorite game', 'user': None,
                     'value': f"{challenges.label(kind)[1]} · {n} played"})
    if viewer_id in rec:
        mine, vs = rec[viewer_id], _versus(group.id, viewer_id)
        nemesis = max(vs, key=lambda u: (vs[u]['lost'], -vs[u]['won']), default=None)
        victim = max(vs, key=lambda u: (vs[u]['won'], -vs[u]['lost']), default=None)
        biggest = max((p.net or 0 for ch in decided for p in ch.players if p.user_id == viewer_id), default=0)
        games = _games_by_member(group.id).get(viewer_id, {})
        out['you'] = {**mine, 'win_rate': _pct(mine['won'], mine['played']), 'kernels': nets.get(viewer_id, 0),
                      'nemesis': {'user': name(nemesis), **vs[nemesis]} if nemesis and vs[nemesis]['lost'] else None,
                      'victim': {'user': name(victim), **vs[victim]} if victim and vs[victim]['won'] else None,
                      'best_game': _best(games), 'biggest_win': biggest or None}
    return out


# ─── Who to challenge ─────────────────────────────────────────────────────────

def picks(group, viewer):
    """Every other member, best challenge first, with why and what to play."""
    import kernels
    from app import GroupMembership, User, db
    rows = GroupMembership.query.filter_by(group_id=group.id, status='active').all()
    ids = [m.user_id for m in rows if m.user_id != viewer.id and not role_blocked(m)]
    if not ids:
        return []
    k = kernels.breakdowns([viewer.id, *ids], group.id)
    rec = challenges.records([viewer.id, *ids], group.id)
    vs = _versus(group.id, viewer.id)
    games = _games_by_member(group.id)
    club_games = [g['kind'] for g in challenges.games(group)]
    mine_free = challenges.available(viewer.id, group.id)
    my_habits = habits(viewer, group)
    rng = random.Random(f'{viewer.id}:{_now().date()}')            # the same suggestions all day
    top = group.challenge_max_stake or 10
    out = []
    for uid in ids:
        u = db.session.get(User, uid)
        if not u or u.is_guest:
            continue
        r, h = rec[uid], vs.get(uid, {'won': 0, 'lost': 0, 'tied': 0, 'played': 0})
        rate = _pct(r['won'], r['played'])
        gap = k[uid]['kernels'] - k[viewer.id]['kernels']
        why, score, tag = [], 0, 'wild'
        if h['played'] == 0:
            why.append("You've never played them.")
            score, tag = score + 2, 'fresh'
        elif h['lost'] > h['won']:
            why.append(f"They're {h['lost']}–{h['won']} up on you. Settle it.")
            score, tag = score + 3, 'grudge'
        elif h['won'] > h['lost']:
            why.append(f"You're {h['won']}–{h['lost']} up on them.")
            score, tag = score + 1, 'easy'
        else:
            why.append(f"You're dead even at {h['won']}–{h['lost']}.")
            score, tag = score + 2, 'even'
        if r['streak'] >= 2:
            why.append(f"They've won {r['streak']} in a row. Someone has to end it.")
            score += 2
            tag = 'streak' if tag in ('fresh', 'easy', 'wild') else tag
        if rate is not None and r['played'] >= 3 and rate >= 60:
            why.append(f"They win {rate}% of their challenges.")
            score += 1
            tag = 'top' if tag in ('fresh', 'wild') else tag
        if gap >= 15:
            why.append(f"They've got {gap} 🍿 more than you: a bigger pot is on the table.")
            score += 1
            tag = 'fish' if tag in ('fresh', 'wild') else tag
        elif gap <= -15:
            why.append(f"You've got {-gap} 🍿 more than them.")
        theirs, yours = games.get(uid, {}), games.get(viewer.id, {})
        best, worst = _best(theirs), _best(theirs, worst=True)
        # The game where you've done better than them; else their weakest; else any.
        edge = max(club_games, key=lambda kd: _rate(yours, kd) - _rate(theirs, kd), default=None)
        if edge and _rate(yours, edge) <= _rate(theirs, edge):
            edge = None
        suggest_kind = edge or (worst['kind'] if worst and worst['kind'] in club_games else
                                rng.choice(club_games) if club_games else None)
        if edge:
            why.append(f"You win {challenges.label(edge)[1]} more often than they do.")
        elif worst and worst['kind'] == suggest_kind:
            why.append(f"{worst['label']} is their weak spot ({worst['win_rate']}% won).")
        free = min(mine_free, challenges.available(uid, group.id), top)
        stake = max(n for n in STAKES if n <= max(0, min(10 if tag == 'fish' else 3, free)))
        emoji, label = TAGS[tag]
        out.append({'user': u.public_dict(), 'tag': {'key': tag, 'emoji': emoji, 'label': label}, 'score': score,
                    'why': why[:3], 'kernels': {'them': k[uid]['kernels'], 'you': k[viewer.id]['kernels']},
                    'record': {**r, 'win_rate': rate}, 'versus': h, 'best_game': best, 'worst_game': worst,
                    'suggest': {'kind': suggest_kind, 'emoji': challenges.label(suggest_kind)[0] if suggest_kind else None,
                                'label': challenges.label(suggest_kind)[1] if suggest_kind else None, 'stake': stake},
                    'roastable': u.roastable is not False,
                    'habits': compare(my_habits, habits(u, group)) if u.roastable is not False else []})
    out.sort(key=lambda p: (-p['score'], p['user']['name'].lower()))
    return out


def _rate(kinds, kind):
    n, w = kinds.get(kind, (0, 0))
    return w / n if n else 0.5


def role_blocked(m):
    """Read-only members can't play challenges."""
    from app import role_at_least
    return not role_at_least(m, 'member')


# ─── Movie habits ─────────────────────────────────────────────────────────────

def habits(user, group):
    """Someone's movie habits, from what the club already sees."""
    import taste
    from app import Attendance, LetterboxdEntry, Showtime, TriviaAnswer, Watchlist, attended_showtime_ids
    seen = attended_showtime_ids(user.id, [group.id])
    shows = Showtime.query.filter(Showtime.id.in_(list(seen))).all() if seen else []
    out = {'went': len(shows)}
    if shows:
        late = sum(1 for s in shows if s.start_time.hour >= 21)
        out['late_pct'] = _pct(late, len(shows))
        out['matinee_pct'] = _pct(sum(1 for s in shows if s.start_time.hour < 17), len(shows))
        where = Counter(s.theatre.name for s in shows if s.theatre)
        if where:
            out['usual_theatre'], out['usual_count'] = where.most_common(1)[0]
        recent = _now() - timedelta(days=90)
        out['went_90'] = sum(1 for s in shows if s.start_time >= recent)
    wl = [w.movie_id for w in Watchlist.query.filter_by(user_id=user.id)]
    out['watchlist'] = len(wl)
    if wl:
        watched = {s.movie_id for s in shows}
        out['watchlist_seen'] = sum(1 for m in wl if m in watched)
    att = Counter(a.status for a in Attendance.query.filter(Attendance.user_id == user.id, Attendance.status.isnot(None)))
    out['missed'] = att.get('missed', 0)
    answers = TriviaAnswer.query.filter_by(user_id=user.id).all()
    if len(answers) >= 3:
        out['trivia_pct'] = _pct(sum(1 for a in answers if a.correct), len(answers))
    if user.taste_public:
        out['genres'] = taste.summary(user)['genres'][:3]
    if user.letterboxd_sync:
        year_ago = (_now() - timedelta(days=365)).date()
        diary = LetterboxdEntry.query.filter(LetterboxdEntry.user_id == user.id, LetterboxdEntry.watched_on >= year_ago).all()
        out['diary'] = len(diary)
        if diary:
            years = sorted(e.year for e in diary if e.year)
            if years:
                out['diary_median_year'] = years[len(years) // 2]
                out['diary_oldest'] = years[0]
            out['rewatches'] = sum(1 for e in diary if e.rewatch)
            genres = Counter(g.strip() for e in diary for g in (e.genres or '').split(',') if g.strip())
            if genres:
                g, n = genres.most_common(1)[0]
                out['diary_genre'], out['diary_genre_pct'] = g.replace('_', ' '), _pct(n, len(diary))
            mins = sum(e.runtime or 0 for e in diary)
            if mins:
                out['diary_hours'] = round(mins / 60)
            if user.letterboxd_ratings:
                rated = [e.rating for e in diary if e.rating]
                if len(rated) >= 3:
                    out['avg_rating'] = round(sum(rated) / len(rated), 1)
                    out['five_stars'] = sum(1 for x in rated if x >= 5)
    return out


def _facts(h, who):
    """Lines about one person's habits ("you" or a name)."""
    lines = []
    if 'went' in h:
        lines.append(('🎟️', f"{who} went to {h['went']} club screening{'' if h['went'] == 1 else 's'}"
                             + (f" ({h['went_90']} in the last 90 days)" if h.get('went_90') is not None else '')))
    if h.get('watchlist'):
        lines.append(('📋', f"{who} has {h['watchlist']} films on the watchlist and saw {h.get('watchlist_seen', 0)} of them at a screening"))
    if h.get('missed'):
        lines.append(('👻', f"{who} said they'd go and then missed it {h['missed']} time{'' if h['missed'] == 1 else 's'}"))
    if h.get('late_pct') is not None and h['went'] >= 3:
        lines.append(('🌙', f"{h['late_pct']}% of {who}'s screenings started after 9 p.m.; {h['matinee_pct']}% before 5"))
    if h.get('usual_theatre'):
        lines.append(('🏛️', f"{who} is usually at {h['usual_theatre']} ({h['usual_count']} times)"))
    if h.get('trivia_pct') is not None:
        lines.append(('🧠', f"{who} gets {h['trivia_pct']}% of the trivia questions right"))
    if h.get('genres'):
        lines.append(('🎭', f"{who} says their favorite genres are {', '.join(h['genres'])}"))
    if h.get('diary') is not None:
        lines.append(('📓', f"{who} logged {h['diary']} films on Letterboxd in the last year"
                             + (f" (about {h['diary_hours']} hours)" if h.get('diary_hours') else '')))
        if h.get('diary_genre'):
            lines.append(('🎬', f"{h['diary_genre_pct']}% of {who}'s diary is {h['diary_genre']}"))
        if h.get('diary_median_year'):
            lines.append(('🕰️', f"the middle film in {who}'s diary came out in {h['diary_median_year']}; the oldest in {h['diary_oldest']}"))
        if h.get('rewatches'):
            lines.append(('🔁', f"{who} rewatched {h['rewatches']} films"))
        if h.get('avg_rating') is not None:
            lines.append(('⭐', f"{who} rates films {h['avg_rating']}★ on average, with {h['five_stars']} five-star{'' if h['five_stars'] == 1 else 's'}"))
    return lines


# The side-by-side lines a pick card shows: (icon, label, yours, theirs).
COMPARE = (('🎟️', 'Club screenings', 'went'), ('📋', 'On the watchlist', 'watchlist'), ('👻', 'Said going, missed it', 'missed'),
           ('🧠', 'Trivia right', 'trivia_pct'), ('🌙', 'Screenings after 9 p.m.', 'late_pct'),
           ('📓', 'Diary, last year', 'diary'), ('⭐', 'Average rating', 'avg_rating'), ('🕰️', 'Diary’s middle year', 'diary_median_year'))


def compare(mine, theirs):
    """[{icon, label, you, them}] — your habits next to theirs, wherever
    theirs show (habits() leaves out what they keep to themselves)."""
    pct = {'trivia_pct', 'late_pct'}
    fmt = lambda k, v: None if v is None else f'{v}%' if k in pct else f'{v}★' if k == 'avg_rating' else str(v)
    out = []
    for icon, label, key in COMPARE:
        if theirs.get(key) is not None:
            out.append({'icon': icon, 'label': label, 'you': fmt(key, mine.get(key)), 'them': fmt(key, theirs.get(key))})
    if theirs.get('usual_theatre'):
        out.append({'icon': '🏛️', 'label': 'Usual theatre', 'you': mine.get('usual_theatre'), 'them': theirs['usual_theatre']})
    if theirs.get('diary_genre'):
        out.append({'icon': '🎬', 'label': 'Most-logged genre', 'you': mine.get('diary_genre'), 'them': theirs['diary_genre']})
    return out


# ─── The roast ────────────────────────────────────────────────────────────────

ROAST_SYSTEM = (
    "You write ONE short, playful roast (one or two sentences, under 40 words) of a film-club member's movie habits, "
    "for a friend about to challenge them to a movie quiz. Call the rival THEM and the challenger YOU, exactly like that "
    "(capitals). Use only the facts given, and compare THEM with YOU where it's funny. Roast habits only — never looks, "
    "identity, health, money or anything not given. Affectionate trash talk: PG-13, no slurs, no swearing, at most one emoji. "
    "Reply with the roast only.")


def _fallback(h, n):
    """A roast from the facts, when the AI can't write one."""
    lines = []
    if h.get('watchlist', 0) >= 10 and h.get('watchlist_seen', 0) <= h['watchlist'] // 10:
        lines.append(f"THEM has {h['watchlist']} films on their watchlist and has seen {h.get('watchlist_seen', 0)} of them. "
                     "That's not a watchlist, that's a wish list.")
    if h.get('missed', 0) >= 2:
        lines.append(f"THEM has said “going” and then ghosted {h['missed']} screenings. At least this challenge comes to them.")
    if h.get('diary', 0) >= 150:
        lines.append(f"THEM logged {h['diary']} films in a year. Either a true cinephile or they haven't seen daylight since spring.")
    if h.get('avg_rating', 0) >= 4.2:
        lines.append(f"THEM rates films {h['avg_rating']}★ on average. Everything's a masterpiece when your standards are on vacation.")
    if 0 < h.get('avg_rating', 5) <= 2.8:
        lines.append(f"THEM averages {h['avg_rating']}★. A critic nobody asked for. Let's see them answer some questions instead.")
    if h.get('late_pct', 0) >= 60 and h.get('went', 0) >= 3:
        lines.append(f"{h['late_pct']}% of THEM's screenings start after 9 p.m. Challenge them early; they peak after dark.")
    if h.get('trivia_pct') is not None and h['trivia_pct'] < 50:
        lines.append(f"THEM gets {h['trivia_pct']}% of trivia right. Coin flips are getting nervous.")
    if h.get('diary_median_year') and h['diary_median_year'] < 1975:
        lines.append(f"The middle film in THEM's diary is from {h['diary_median_year']}. They think “new release” means color.")
    if h.get('diary_median_year', 0) >= 2019:
        lines.append(f"The middle film in THEM's diary is from {h['diary_median_year']}. Ask them about anything before streaming.")
    if h.get('diary_genre') and h.get('diary_genre_pct', 0) >= 30:
        lines.append(f"{h['diary_genre_pct']}% of THEM's diary is {h['diary_genre']}. Range? Never heard of her.")
    if h.get('went', 0) <= 1:
        lines.append("THEM has made it to a club screening about as often as a solar eclipse. Easy to find them home, though.")
    if h.get('usual_theatre') and h.get('usual_count', 0) >= 5:
        lines.append(f"THEM has been to {h['usual_theatre']} {h['usual_count']} times. They should be paying rent.")
    lines.append("THEM's movie habits are suspiciously normal. Only a challenge will reveal what they're hiding.")
    return lines[n % len(lines)]


def roast(viewer, other, group, again=False):
    """{'roast', 'by': 'ai' | 'facts'} — or None if they'd rather not be roasted."""
    import ai
    if other.roastable is False or other.id == viewer.id:
        return None
    key = (viewer.id, other.id, _now().date())
    have = _roasts.setdefault(key, [])
    if have and (not again or len(have) >= ROASTS_A_DAY):        # today's (out of new ones: one of them again)
        text, by = random.choice(have) if again else have[-1]
        return {'roast': _named(text, other.name), 'by': by, 'more': len(have) < ROASTS_A_DAY}
    theirs, mine = habits(other, group), habits(viewer, group)
    facts = [f'{i} {t}' for i, t in _facts(theirs, 'THEM')] + [f'{i} {t}' for i, t in _facts(mine, 'YOU')]
    text, by = None, 'facts'
    try:
        raw = ai.chat([{'role': 'system', 'content': ROAST_SYSTEM},
                       {'role': 'user', 'content': 'Facts:\n' + '\n'.join(facts[:16]) + (
                           f'\n(A different roast from: {have[-1][0]})' if have else '')}], max_tokens=120)
        text = re.sub(r'\s+', ' ', (raw or '').strip().strip('"“”')) or None
        if text and 'THEM' in text and len(text) <= 300:
            by = 'ai'
        else:
            text = None
    except Exception as e:
        print(f'scout: the AI roast failed: {e}')
    if not text:
        text = _fallback(theirs, len(have))
    have.append((text, by))
    if len(_roasts) > 500:                                   # yesterday's go
        for k in [k for k in _roasts if k[2] != key[2]]:
            _roasts.pop(k, None)
    return {'roast': _named(text, other.name), 'by': by, 'more': len(have) < ROASTS_A_DAY}


def _named(text, name):
    """THEM → their name; YOU / YOUR → you / your."""
    text = re.sub(r'\bTHEM\b', name, text)
    text = re.sub(r'\bYOU(R|RS|RSELF)?\b', lambda m: m.group(0).lower(), text)
    return re.sub(r'(^|[.!?]\s+)you', lambda m: m.group(1) + 'You', text)       # a sentence's first word

"""Personal alerts (R8): what they are, where each person gets them, and
sending them.

Every alert is a Notification row: the bell shows them all. Where else one
goes is decided when it's made, from the person's one notification setting:
Discord DM (the bot sends those), email (sent here) and push. All of those
are opt-in: nothing leaves the site until the person says so — they're asked
once, at the first moment it matters (`ask_once`). Alerts made
during a scrape wait for the run to finish (`release`), so a person gets one
DM / email per run listing everything new, not one per film.
"""
import json
from datetime import datetime, timedelta

# Alert types, in the order the settings list them.
TYPES = {
    'showings': ('A film on your watchlist is booked or announced', 'When a theatre books or announces it (not every new time in a run).'),
    'on_sale': ('Tickets go on sale', 'For announced films on your watchlist.'),
    'attendance': ('"Did you make it?" DMs', 'After screenings you said you were going to, a Discord DM to log it.'),
    'searches': ('A film fits a search you saved', 'When a theatre books a film that fits one of your saved searches.'),
    'favorites': ('A favorite’s film is booked', 'When a theatre books one of your favorite films, or one by a director, actor or writer in Your taste.'),
    # Games (R14, game_posts.py) — only in clubs with the game on
    'trivia_daily': ('Trivia: the question of the day is up', 'Once a day, around 11 AM.'),
    'trivia_result': ('Trivia: yesterday\u2019s answer', 'The answer, whether you got it, and how the club did.'),
    'bingo_card': ('Bingo: a new card', 'On the 1st, with this month\u2019s squares.'),
    'bingo_win': ('Bingo: your line or full card', 'When your check-ins complete a line or the card, with the kernels.'),
    'reviews': ('A game post is waiting for your OK', 'Club admins: the question of the day or the month\u2019s card, when Club settings say Ask first.'),
}
CHANNELS = ('discord', 'email', 'push')
REALERT_AFTER = timedelta(days=3)         # a theatre's listing flickering doesn't re-alert
RELEASE_AFTER = timedelta(minutes=30)     # a crashed scrape run still gets its alerts out


def _now():
    return datetime.utcnow()


def _raw(user):
    try:
        raw = json.loads(user.notify_prefs or '{}')
    except ValueError:
        raw = {}
    return raw if isinstance(raw, dict) else {}


def available(user):
    """Which channels this account can use at all (push: a device turned it on)."""
    from app import PushSubscription
    push = bool(user.id) and PushSubscription.query.filter_by(user_id=user.id).first() is not None
    return {'discord': bool(user.discord_user_id), 'email': bool(user.email), 'push': push}


# Off until chosen: no DM, email or push, and no "Did you make it?" DMs.
# Watchlist alerts still land in the site's bell (it never sends anything).
DEFAULT_TYPES = {'showings': True, 'on_sale': True, 'attendance': False, 'searches': True, 'favorites': True,
                 'trivia_daily': False, 'trivia_result': False, 'bingo_card': False, 'bingo_win': True, 'reviews': True}
ASKS = ('alerts', 'attendance')


def prefs(user):
    """{'channels': {discord, email, push}, 'types': {...}} — your choices;
    anything you haven't chosen is off (types: see DEFAULT_TYPES)."""
    raw, can = _raw(user), available(user)
    chosen = raw.get('channels') or {}
    channels = {c: bool(chosen.get(c, False)) and can[c] for c in CHANNELS}
    types = {t: bool((raw.get('types') or {}).get(t, DEFAULT_TYPES[t])) for t in TYPES}
    return {'channels': channels, 'types': types}


def ask_once(user, key):
    """True the first time something could notify this person about `key`
    ('alerts': watchlist news; 'attendance': "Did you make it?" DMs) — the
    moment to ask them. Remembered, so it's asked once; caller commits."""
    raw = _raw(user)
    if (raw.get('asked') or {}).get(key):
        return False
    raw.setdefault('asked', {})[key] = True
    user.notify_prefs = json.dumps(raw)
    return True


def set_prefs(user, data):
    """Save the parts of {'channels': {...}, 'types': {...}} that were sent."""
    raw = _raw(user)
    for key, allowed in (('channels', CHANNELS), ('types', tuple(TYPES))):
        for k, v in ((data or {}).get(key) or {}).items():
            if k in allowed and isinstance(v, bool):
                raw.setdefault(key, {})[k] = v
    user.notify_prefs = json.dumps(raw)


def wants(user, kind):
    return prefs(user)['types'].get(kind, True)


def wants_dm(user, kind):
    """May the bot DM this person about `kind`? "Did you make it?" is its own
    yes (it's only ever a DM); alerts follow the Discord DM channel."""
    p = prefs(user)
    if kind == 'attendance':
        return p['types']['attendance'] and bool(user.discord_user_id)
    return p['types'].get(kind, True) and p['channels']['discord']


def _make(db, Notification, user, kind, movie_id, theatre_id, payload, ready=False):
    """`ready`: send at once (games, R14) rather than with the scrape run's bundle."""
    p = prefs(user)
    db.session.add(Notification(user_id=user.id, kind=kind, movie_id=movie_id, theatre_id=theatre_id,
                                payload_json=json.dumps(payload), ready_at=_now() if ready else None,
                                channels=','.join(c for c in CHANNELS if p['channels'][c])))


def alert_new_showings(theatre, new_future, had_upcoming):
    """Called by the scraper's sync (before its commit): a film on someone's
    watchlist was just booked at `theatre` — it has new upcoming showings
    there and had none before (`had_upcoming`: movie ids already upcoming at
    this theatre). Its ongoing run adding more times isn't news."""
    from app import db, Notification, Watchlist
    booked = {}
    for s in new_future:
        if s.movie_id not in had_upcoming:
            booked.setdefault(s.movie_id, []).append(s)
    if not booked:
        return 0
    recent = {(n.user_id, n.movie_id) for n in Notification.query.filter(
        Notification.kind == 'showings', Notification.theatre_id == theatre.id,
        Notification.movie_id.in_(booked), Notification.created_at > _now() - REALERT_AFTER)}
    made = 0
    for w in Watchlist.query.filter(Watchlist.movie_id.in_(booked)).all():
        if not w.user or (w.user_id, w.movie_id) in recent or not wants(w.user, 'showings'):
            continue
        shows = sorted(booked[w.movie_id], key=lambda s: s.start_time)
        m = shows[0].movie
        formats = sorted({s.format_label for s in shows if s.format_label})
        _make(db, Notification, w.user, 'showings', w.movie_id, theatre.id, {
            'title': m.title, 'year': m.release_year, 'poster_url': m.poster_url,
            'theatre': theatre.name, 'theatre_slug': theatre.slug,
            'first': shows[0].start_time.isoformat(), 'count': len(shows), 'formats': formats[:3]})
        made += 1
    return made


def alert_favorites(theatre, new_future, had_upcoming):
    """R13: like alert_new_showings, for Your taste — a theatre just booked a
    favorite film of someone's, or one by a person they love. Not when the
    watchlist alert already told them (same film, same theatre)."""
    import taste
    from app import db, Notification, TasteItem
    booked = {}
    for s in new_future:
        if s.movie_id not in had_upcoming:
            booked.setdefault(s.movie_id, []).append(s)
    if not booked:
        return 0
    told = {(n.user_id, n.movie_id) for n in Notification.query.filter(
        Notification.kind.in_(('showings', 'favorite')), Notification.theatre_id == theatre.id,
        Notification.movie_id.in_(booked), Notification.created_at > _now() - REALERT_AFTER)}
    because = {}                                  # (user, movie) -> why
    for i in TasteItem.query.filter(TasteItem.kind == 'movie', TasteItem.movie_id.in_(booked)):
        because.setdefault((i.user_id, i.movie_id), 'a favorite of yours')
    credits = {}                                  # movie -> {(person, role): name} — one person can hold several roles
    for mid, shows in booked.items():
        credits[mid] = {(key, kind): label for key, label, kind in taste._people_of(shows[0].movie)}
    keys = {k for c in credits.values() for k, _ in c}
    for i in TasteItem.query.filter(TasteItem.kind.in_(taste.PEOPLE), TasteItem.key.in_(keys)) if keys else []:
        for mid, c in credits.items():
            if (i.key, i.kind) in c:
                because.setdefault((i.user_id, mid), f'{c[(i.key, i.kind)]} ({i.kind})')
    made = 0
    for (uid, mid), why in because.items():
        if (uid, mid) in told:
            continue
        user = db.session.get(__import__('app').User, uid)
        if not user or not user.is_active or not wants(user, 'favorites'):
            continue
        shows = sorted(booked[mid], key=lambda s: s.start_time)
        m = shows[0].movie
        _make(db, Notification, user, 'favorite', mid, theatre.id, {
            'title': m.title, 'year': m.release_year, 'poster_url': m.poster_url, 'because': why,
            'theatre': theatre.name, 'theatre_slug': theatre.slug, 'first': shows[0].start_time.isoformat(),
            'count': len(shows), 'formats': sorted({s.format_label for s in shows if s.format_label})[:3]})
        made += 1
    return made


def _watchers(Watchlist, movie_ids, kind):
    return [w for w in (Watchlist.query.filter(Watchlist.movie_id.in_(movie_ids)).all() if movie_ids else [])
            if w.user and wants(w.user, kind)]


def alert_announced(theatre, announcements):
    """R8b: a theatre announced films on people's watchlists (tickets later)."""
    from app import db, Notification, Watchlist
    by_movie = {a.movie_id: a for a in announcements}
    for w in _watchers(Watchlist, list(by_movie), 'showings'):
        a, m = by_movie[w.movie_id], by_movie[w.movie_id].movie
        _make(db, Notification, w.user, 'announced', w.movie_id, theatre.id, {
            'title': m.title, 'year': m.release_year, 'poster_url': m.poster_url,
            'theatre': theatre.name, 'theatre_slug': theatre.slug, 'date': a.expected_on.isoformat()})


def alert_on_sale(theatre, new_future):
    """R8b: announced films at `theatre` whose showtimes just appeared — mark
    them on sale and tell watchers. Returns those movie ids (they get this
    alert instead of "is playing")."""
    from app import db, Announcement, Notification, Watchlist
    shows = {}
    for s in new_future:
        shows.setdefault(s.movie_id, []).append(s)
    if not shows:
        return set()
    opened = Announcement.query.filter(Announcement.theatre_id == theatre.id, Announcement.on_sale_at.is_(None),
                                       Announcement.movie_id.in_(list(shows))).all()
    for a in opened:
        a.on_sale_at = _now()
    ids = {a.movie_id for a in opened}
    for w in _watchers(Watchlist, list(ids), 'on_sale'):
        ss = sorted(shows[w.movie_id], key=lambda s: s.start_time)
        m = ss[0].movie
        _make(db, Notification, w.user, 'on_sale', w.movie_id, theatre.id, {
            'title': m.title, 'year': m.release_year, 'poster_url': m.poster_url,
            'theatre': theatre.name, 'theatre_slug': theatre.slug,
            'first': ss[0].start_time.isoformat(), 'count': len(ss)})
    return ids


# ─── Saved searches (R10a) ────────────────────────────────────────────────────
# Any Browse search can be saved; after each scrape run every saved search is
# run over the coming months, and a film that newly fits it (at a theatre)
# makes one alert. What fits when it's saved counts as seen, so saving never
# sets off a burst of alerts.

SEARCH_KEYS = ('theatres', 'regions', 'genres', 'decade', 'format', 'time', 'rarity', 'runtime', 'mood', 'shelf',
               'q', 'person')                 # Browse's filters, minus the time window, "the club" and sort
SEARCH_LISTS = ('theatres', 'regions', 'genres', 'format')
SEARCH_AHEAD = timedelta(days=90)
MAX_SEARCHES = 10
_EXTRA_LABELS = {('format', 'big'): 'Big screen', ('time', 'matinee'): 'Matinees', ('time', 'evening'): 'Evenings',
                 ('time', 'late'): 'Late nights', ('rarity', 'rare'): 'Rare', ('rarity', 'repertory'): 'Repertory',
                 ('rarity', 'wide'): 'Wide releases', ('runtime', 'short'): 'Under 95 min',
                 ('runtime', 'long'): 'Over 2½ hours'}


def search_params(params):
    """A search's filters, tidied so the same search always looks the same
    (lists lowercased and sorted, blanks dropped, no window or sort)."""
    out = {}
    for k in SEARCH_KEYS:
        v = str((params or {}).get(k) or '').strip()
        if k in SEARCH_LISTS:
            v = ','.join(sorted({x.strip().lower() for x in v.split(',') if x.strip()}))
        if v:
            out[k] = v[:80]
    return out


def search_label(params):
    """'On film · Horror · AFI' — a saved search in words."""
    import discover
    from app import Theatre
    p = dict(params)
    if p.get('theatres'):
        names = {t.slug: t.short_name or t.name for t in Theatre.query.filter(Theatre.slug.in_(p['theatres'].split(',')))}
        p['_theatre_label'] = ', '.join(names.get(s, s) for s in p['theatres'].split(','))
    label = discover.describe(p, when=False)
    extra = [_EXTRA_LABELS[(k, p[k])] for k in ('format', 'time', 'rarity', 'runtime') if (k, p.get(k)) in _EXTRA_LABELS]
    return ' · '.join(b for b in [label, *extra] if b)[:200] or 'Everything new'


def search_dict(s):
    import discover
    params = json.loads(s.params_json)
    return {'id': s.id, 'label': s.label, 'params': params, 'group_id': s.group_id,
            'path': discover.browse_path({**params, 'when': 'month'})}


def _search_group(s):
    """The club whose theatres a search covers — if the person's still in it."""
    from app import db, Group, GroupMembership
    if not s.group_id or not GroupMembership.query.filter_by(user_id=s.user_id, group_id=s.group_id,
                                                              status='active').first():
        return None
    return db.session.get(Group, s.group_id)


def search_matches(s, now=None):
    """{(movie_id, theatre_id): [showtimes]} — what fits a saved search over
    the coming months."""
    import discover
    now = now or datetime.now()
    params = {**json.loads(s.params_json), 'from': now.isoformat(), 'to': (now + SEARCH_AHEAD).date().isoformat()}
    films = discover.select(_search_group(s), s.user, params, now)[0]
    out = {}
    for f in films:
        for show in f.shows:
            out.setdefault((f.movie.id, show.theatre_id), []).append(show)
    return out


def seed_search(s, now=None):
    """Mark what fits a new saved search as seen. Returns how many films."""
    from app import db, SavedSearchHit
    matches = search_matches(s, now)
    for movie_id, theatre_id in matches:
        db.session.add(SavedSearchHit(search_id=s.id, movie_id=movie_id, theatre_id=theatre_id))
    return len({m for m, _ in matches})


def save_search(user, params, group_id=None, now=None):
    """Save a search for `user` (the caller commits). Returns (search,
    films fitting it now, error) — the same search saved twice is one."""
    from app import db, GroupMembership, SavedSearch
    p = search_params(params)
    if not p:
        return None, 0, 'Pick at least one filter first.'
    if group_id and not GroupMembership.query.filter_by(user_id=user.id, group_id=group_id, status='active').first():
        group_id = None
    raw = json.dumps(p, sort_keys=True)
    same = SavedSearch.query.filter_by(user_id=user.id, group_id=group_id, params_json=raw).first()
    if same:
        return same, len({m for m, _ in search_matches(same, now)}), None
    if SavedSearch.query.filter_by(user_id=user.id).count() >= MAX_SEARCHES:
        return None, 0, f'You can save up to {MAX_SEARCHES} searches — remove one first.'
    s = SavedSearch(user_id=user.id, group_id=group_id, params_json=raw, label=search_label(p))
    db.session.add(s)
    db.session.flush()
    return s, seed_search(s, now), None


def alert_saved_searches(now=None):
    """After a scrape run: one alert per film that newly fits someone's saved
    search, per theatre (not when they've just been told about it — by their
    watchlist or another of their searches). Returns how many alerts."""
    from app import app, db, Notification, SavedSearch, SavedSearchHit
    utc = _now()
    made = 0
    with app.app_context():
        told = {(n.user_id, n.movie_id, n.theatre_id) for n in Notification.query.filter(
            Notification.kind.in_(('showings', 'on_sale', 'search')), Notification.created_at > utc - REALERT_AFTER)}
        for s in SavedSearch.query.order_by(SavedSearch.id).all():
            user = s.user
            if not user or not user.is_active or user.is_guest:
                continue
            matches = search_matches(s, now)
            hits = {(h.movie_id, h.theatre_id): h for h in s.hits}
            for key, h in hits.items():
                if key in matches:
                    h.seen_at = utc
                elif h.seen_at < utc - REALERT_AFTER:          # gone for days: a new booking is news again
                    db.session.delete(h)
            for (movie_id, theatre_id), shows in matches.items():
                if (movie_id, theatre_id) in hits:
                    continue
                db.session.add(SavedSearchHit(search_id=s.id, movie_id=movie_id, theatre_id=theatre_id, seen_at=utc))
                if (user.id, movie_id, theatre_id) in told or not wants(user, 'searches'):
                    continue
                told.add((user.id, movie_id, theatre_id))
                shows = sorted(shows, key=lambda x: x.start_time)
                m, theatre = shows[0].movie, shows[0].theatre
                _make(db, Notification, user, 'search', movie_id, theatre_id, {
                    'title': m.title, 'year': m.release_year, 'poster_url': m.poster_url,
                    'theatre': theatre.name, 'theatre_slug': theatre.slug, 'first': shows[0].start_time.isoformat(),
                    'count': len(shows), 'formats': sorted({x.format_label for x in shows if x.format_label})[:3],
                    'search': s.label, 'search_id': s.id})
                made += 1
        db.session.commit()
    return made


# ─── Showing them ─────────────────────────────────────────────────────────────

def _when(iso):
    d = datetime.fromisoformat(iso)
    return d.strftime('%a, %b %-d, %-I:%M %p').replace(':00 ', ' ')


def describe(n):
    """{headline, detail, link} for an alert, in words."""
    p = json.loads(n.payload_json or '{}')
    title = p.get('title') or (n.movie.title if n.movie else 'A film')
    link = f'/films/{n.movie_id}' if n.movie_id else '/'
    if n.kind == 'showings':
        more = p.get('count', 1) - 1
        bits = [p.get('theatre'), _when(p['first']) if p.get('first') else None,
                f'+{more} more' if more > 0 else None, ' · '.join(p.get('formats') or []) or None]
        return {'headline': f'{title} is playing', 'detail': ' · '.join(b for b in bits if b), 'link': link}
    if n.kind == 'on_sale':
        more = p.get('count', 1) - 1
        bits = [p.get('theatre'), _when(p['first']) if p.get('first') else None, f'+{more} more' if more > 0 else None]
        return {'headline': f'Tickets on sale: {title}', 'detail': ' · '.join(b for b in bits if b), 'link': link}
    if n.kind == 'announced':
        day = datetime.fromisoformat(p['date']).strftime('%a, %b %-d') if p.get('date') else None
        bits = [p.get('theatre'), day, 'tickets not on sale yet']
        return {'headline': f'{title} is coming', 'detail': ' · '.join(b for b in bits if b), 'link': link}
    if n.kind == 'search':
        more = p.get('count', 1) - 1
        bits = [f"Fits “{p['search']}”" if p.get('search') else None, p.get('theatre'),
                _when(p['first']) if p.get('first') else None, f'+{more} more' if more > 0 else None,
                ' · '.join(p.get('formats') or []) or None]
        return {'headline': f'New: {title}', 'detail': ' · '.join(b for b in bits if b), 'link': link}
    if n.kind == 'favorite':
        more = p.get('count', 1) - 1
        bits = [f"Because you love {p['because']}" if p.get('because') and p['because'] != 'a favorite of yours'
                else 'A favorite of yours', p.get('theatre'), _when(p['first']) if p.get('first') else None,
                f'+{more} more' if more > 0 else None]
        return {'headline': f'{title} is playing', 'detail': ' · '.join(b for b in bits if b), 'link': link}
    if n.kind in GAME_KINDS:
        return _describe_game(n.kind, p)
    return {'headline': title, 'detail': '', 'link': link}


GAME_KINDS = ('trivia_daily', 'trivia_result', 'bingo_card', 'bingo_win', 'game_review')


def _describe_game(kind, p):
    if kind == 'trivia_daily':
        return {'headline': 'Today’s trivia question is up', 'detail': p.get('prompt', ''), 'link': '/play#trivia'}
    if kind == 'trivia_result':
        you = {'right': 'You got it ✅', 'wrong': 'You missed this one', None: 'You didn’t answer'}[p.get('you')]
        return {'headline': f"Yesterday’s trivia: {p.get('answer', '')}",
                'detail': ' · '.join(b for b in (p.get('prompt'), you, f"{p.get('correct', 0)} of {p.get('answered', 0)} got it") if b),
                'link': '/play#trivia'}
    if kind == 'bingo_card':
        return {'headline': f"{p.get('month_label', 'This month')}’s bingo card is up",
                'detail': ' · '.join(p.get('squares') or []), 'link': '/play#bingo'}
    if kind == 'bingo_win':
        what = 'the full card 🎉🎉' if p.get('which') == 'full' else 'bingo 🎉'
        return {'headline': f'You got {what}', 'detail': f"+{p.get('kernels', 0)} kernels · {p.get('month_label', '')}",
                'link': '/play#bingo'}
    what = 'Today’s trivia question' if p.get('post_kind') == 'trivia' else f"{p.get('month_label', 'This month')}’s bingo card"
    return {'headline': f'{what} is waiting for your OK', 'detail': 'Look it over, then post it in Discord, skip it or change it.',
            'link': '/club?tab=settings#game-posts'}


WATCHLIST_KINDS = ('showings', 'on_sale', 'announced')


def bundle_title(ns):
    """What several alerts at once are called."""
    return (f'{len(ns)} updates on your watchlist' if all(n.kind in WATCHLIST_KINDS for n in ns)
            else f'{len(ns)} new alerts')


def item(n):
    """An alert for the bell."""
    p = json.loads(n.payload_json or '{}')
    return {'id': n.id, 'kind': n.kind, **describe(n), 'movie_id': n.movie_id,
            'poster_url': p.get('poster_url') or (n.movie.poster_url if n.movie else None),
            'title': p.get('title'), 'theatre_slug': p.get('theatre_slug'),
            'created_at': n.created_at.isoformat() + 'Z' if n.created_at else None,
            'read': n.read_at is not None}


# ─── Sending them ─────────────────────────────────────────────────────────────

def _ready(Notification, now):
    return (Notification.ready_at.isnot(None)) | (Notification.created_at < now - RELEASE_AFTER)


def release(now=None):
    """A scrape run finished: its alerts may go out. Sends the emails now; the
    bot picks up the DMs."""
    from app import app, db, Notification
    now = now or _now()
    with app.app_context():
        Notification.query.filter(Notification.ready_at.is_(None)).update({'ready_at': now})
        db.session.commit()
        emailed = send_emails(now)
        send_pushes(now)
        return emailed


def send_emails(now=None):
    """One email per person with everything ready for them."""
    from app import db, Notification, send_email, FRONTEND_URL
    now = now or _now()
    pending = Notification.query.filter(_ready(Notification, now), Notification.email_at.is_(None),
                                        Notification.channels.like('%email%')).order_by(Notification.created_at).all()
    by_user = {}
    for n in pending:
        by_user.setdefault(n.user_id, []).append(n)
    for ns in by_user.values():
        user = ns[0].user
        from html import escape as esc
        rows = ''.join(
            f'<li style="margin-bottom:10px;"><a href="{FRONTEND_URL}{d["link"]}" style="color:#e8a838;font-weight:bold;">'
            f'{esc(d["headline"])}</a><br><span style="color:#666;">{esc(d["detail"])}</span></li>'
            for d in map(describe, ns))
        subject = describe(ns[0])['headline'] if len(ns) == 1 else bundle_title(ns)
        send_email(user.email, subject,
                   f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
                   <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2><ul style="padding-left:18px;">{rows}</ul>
                   <p style="color:#888;font-size:12px;">Change where you get alerts in your profile menu →
                   Notifications on <a href="{FRONTEND_URL}" style="color:#888;">the site</a>.</p></div>""")
        for n in ns:
            n.email_at = now
    db.session.commit()
    return len(by_user)


def push_to(user, message):
    """Send `message` ({title, body, url, tag}) to every device `user` turned
    push on for; forget devices that are gone. Returns how many got it."""
    from app import db, PushSubscription, VAPID_PRIVATE_KEY, VAPID_SUBJECT
    if not VAPID_PRIVATE_KEY:
        return 0
    from pywebpush import webpush, WebPushException
    sent = 0
    for sub in PushSubscription.query.filter_by(user_id=user.id).all():
        try:
            webpush({'endpoint': sub.endpoint, 'keys': {'p256dh': sub.p256dh, 'auth': sub.auth}},
                    json.dumps(message), vapid_private_key=VAPID_PRIVATE_KEY,
                    vapid_claims={'sub': VAPID_SUBJECT}, ttl=12 * 3600)
            sent += 1
        except WebPushException as e:
            if getattr(e.response, 'status_code', None) in (404, 410):     # unsubscribed / expired
                db.session.delete(sub)
            else:
                print(f'push to user {user.id} failed: {e}')
        except Exception as e:
            print(f'push to user {user.id} failed: {e}')
    db.session.commit()
    return sent


def send_pushes(now=None):
    """One push per person with everything ready for them."""
    from app import db, Notification
    now = now or _now()
    pending = Notification.query.filter(_ready(Notification, now), Notification.push_at.is_(None),
                                        Notification.channels.like('%push%')).order_by(Notification.created_at).all()
    by_user = {}
    for n in pending:
        by_user.setdefault(n.user_id, []).append(n)
    for ns in by_user.values():
        first = describe(ns[0])
        message = ({'title': first['headline'], 'body': first['detail'], 'url': first['link']} if len(ns) == 1 else
                   {'title': bundle_title(ns),
                    'body': ' · '.join(describe(n)['headline'] for n in ns[:4]), 'url': '/?alerts=1'})
        push_to(ns[0].user, {**message, 'tag': f'alerts-{ns[-1].id}'})
        for n in ns:
            n.push_at = now
    db.session.commit()
    return len(by_user)


def pending_dms(now=None):
    """[{discord_user_id, ids, title, items: [{headline, detail, url, poster_url}]}] for the bot
    (`title`: what several at once are called)."""
    from app import Notification, FRONTEND_URL
    now = now or _now()
    pending = Notification.query.filter(_ready(Notification, now), Notification.discord_at.is_(None),
                                        Notification.channels.like('%discord%')).order_by(Notification.created_at).all()
    by_user = {}
    for n in pending:
        if n.user and n.user.discord_user_id:
            by_user.setdefault(n.user.discord_user_id, []).append(n)
    return [{'discord_user_id': uid, 'ids': [n.id for n in ns],
             'title': bundle_title(ns),
             'items': [{**{k: v for k, v in describe(n).items() if k != 'link'},
                        'url': FRONTEND_URL + describe(n)['link'], 'poster_url': item(n)['poster_url']} for n in ns],
             # admins' game posts waiting for an OK (R14): the bot DMs these with Post / Skip buttons
             'reviews': [json.loads(n.payload_json or '{}').get('post_id') for n in ns if n.kind == 'game_review']}
            for uid, ns in by_user.items()]

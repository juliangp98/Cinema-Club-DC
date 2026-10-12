"""Personal alerts (R8): what they are, where each person gets them, and
sending them.

Every alert is a Notification row: the bell shows them all. Where else one
goes is decided when it's made, from the person's one notification setting:
Discord DM (the bot sends those), email (sent here) and push. Alerts made
during a scrape wait for the run to finish (`release`), so a person gets one
DM / email per run listing everything new, not one per film.
"""
import json
from datetime import datetime, timedelta

# Alert types, in the order the settings list them.
TYPES = {
    'showings': ('A film on your watchlist is booked or announced', 'When a theatre books or announces it (not every new time in a run).'),
    'on_sale': ('Tickets go on sale', 'For announced films on your watchlist.'),
    'attendance': ('"Did you make it?"', 'After screenings you said you were going to (Discord DM).'),
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
    """Which channels this account can use at all."""
    return {'discord': bool(user.discord_user_id), 'email': bool(user.email), 'push': False}


def prefs(user):
    """{'channels': {discord, email, push}, 'types': {...}} — your choices,
    with defaults for anything you haven't set: Discord accounts get DMs,
    email-only accounts get email; every alert type is on."""
    raw, can = _raw(user), available(user)
    default = {'discord': can['discord'], 'email': can['email'] and not can['discord'], 'push': False}
    chosen = raw.get('channels') or {}
    channels = {c: bool(chosen.get(c, default[c])) and can[c] for c in CHANNELS}
    types = {t: bool((raw.get('types') or {}).get(t, True)) for t in TYPES}
    return {'channels': channels, 'types': types}


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
    p = prefs(user)
    return p['types'].get(kind, True) and p['channels']['discord']


def _make(db, Notification, user, kind, movie_id, theatre_id, payload):
    p = prefs(user)
    db.session.add(Notification(user_id=user.id, kind=kind, movie_id=movie_id, theatre_id=theatre_id,
                                payload_json=json.dumps(payload),
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
    return {'headline': title, 'detail': '', 'link': link}


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
        return send_emails(now)


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
        rows = ''.join(
            f'<li style="margin-bottom:10px;"><a href="{FRONTEND_URL}{d["link"]}" style="color:#e8a838;font-weight:bold;">'
            f'{d["headline"]}</a><br><span style="color:#666;">{d["detail"]}</span></li>'
            for d in map(describe, ns))
        subject = describe(ns[0])['headline'] if len(ns) == 1 else f'{len(ns)} updates on your watchlist'
        send_email(user.email, subject,
                   f"""<div style="font-family:sans-serif;max-width:480px;margin:auto;padding:24px;">
                   <h2 style="color:#e8a838;">🎬 Cinema Club DC</h2><ul style="padding-left:18px;">{rows}</ul>
                   <p style="color:#888;font-size:12px;">Change where you get alerts in your profile menu →
                   Notifications on <a href="{FRONTEND_URL}" style="color:#888;">the site</a>.</p></div>""")
        for n in ns:
            n.email_at = now
    db.session.commit()
    return len(by_user)


def pending_dms(now=None):
    """[{discord_user_id, ids, items: [{headline, detail, url, poster_url}]}] for the bot."""
    from app import Notification, FRONTEND_URL
    now = now or _now()
    pending = Notification.query.filter(_ready(Notification, now), Notification.discord_at.is_(None),
                                        Notification.channels.like('%discord%')).order_by(Notification.created_at).all()
    by_user = {}
    for n in pending:
        if n.user and n.user.discord_user_id:
            by_user.setdefault(n.user.discord_user_id, []).append(n)
    return [{'discord_user_id': uid, 'ids': [n.id for n in ns],
             'items': [{**{k: v for k, v in describe(n).items() if k != 'link'},
                        'url': FRONTEND_URL + describe(n)['link'], 'poster_url': item(n)['poster_url']} for n in ns]}
            for uid, ns in by_user.items()]

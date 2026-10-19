"""The Monday digest on the site: a club with it on (Club settings → Theatres)
gets the week's picks published Monday at 10 AM — a card in the Feed and an
item in members' bells — the same morning the bot posts it in the club's
Discord server. Each club's digest is published once a week and kept
(ClubDigest), so the Feed card says the same thing all week; the only part
made per person is "your watchlist", from the viewer's own list.

The picks come from discover.weekly (the Discover page's rules); the bot's
version (/api/internal/digest) adds who's going and names watchers, which
depend on who's in the club's server.
"""
import json
from datetime import datetime, timedelta

PUBLISH_HOUR = 10          # Monday, the club's clock — when the bot posts it too
YOURS_MAX = 5              # "your watchlist" lines on a card


def _local_now():
    """The club's clock (tests set it)."""
    return datetime.now()


def showtime_brief(s):
    return {'showtime_id': s.id, 'movie_id': s.movie_id, 'title': s.movie.title,
            'start_time': s.start_time.isoformat(),
            'theatre': s.theatre.short_name or s.theatre.name, 'format_label': s.format_label}


def new_on_calendar(days):
    """[{theatre, showtimes}] — new showtimes per theatre in the last `days`, most first."""
    from app import ScrapeEvent, _utcnow_naive
    counts = {}
    for e in (ScrapeEvent.query
              .filter(ScrapeEvent.event_type.in_(('new_drop', 'new_showtimes')),
                      ScrapeEvent.created_at > _utcnow_naive() - timedelta(days=days))):
        p = json.loads(e.payload_json or '{}')
        name = (e.theatre.short_name or e.theatre.name) if e.theatre else p.get('theatre_name', '')
        counts[name] = counts.get(name, 0) + (p.get('new_showtime_count') or 0)
    return [{'theatre': t, 'showtimes': n} for t, n in sorted(counts.items(), key=lambda kv: -kv[1]) if n]


def week_of(now):
    """The Monday a moment belongs to."""
    return (now - timedelta(days=now.weekday())).date()


def snapshot(group, now):
    """What a club's digest says this week (no names: those are the Feed's own cards)."""
    import discover
    from app import DIGEST_CAPS, PLAN_MIN_WATCHERS, Poll
    _, picks = discover.weekly(group, now, 7, DIGEST_CAPS, PLAN_MIN_WATCHERS)
    return {
        'plans': [{**showtime_brief(s), 'wanted': f.wanted} for f, s, _ in picks['plans']],
        'rare': [{**showtime_brief(s), 'reasons': why} for _, s, why in picks['rare']],
        'last_chance': [showtime_brief(s) for _, s, _ in picks['last_chance']],
        'opening': [{**showtime_brief(s), 'theatres': n} for _, s, n in picks['opening']],
        'new_on_calendar': new_on_calendar(7),
        'polls': [{'id': p.id, 'title': p.title} for p in Poll.query.filter_by(group_id=group.id, status='open')],
    }


def picks_count(payload):
    return sum(len(payload.get(k) or []) for k in ('plans', 'rare', 'last_chance', 'opening'))


def publish(group, now):
    """Publish `group`'s digest for this week and tell its members (the bell;
    elsewhere only for those who asked). False if it was already out."""
    import notify
    from sqlalchemy.exc import IntegrityError
    from app import db, ClubDigest, GroupMembership, Notification, _utcnow_naive
    monday = week_of(now)
    payload = snapshot(group, now)
    db.session.add(ClubDigest(group_id=group.id, week_of=monday, published_at=_utcnow_naive(),
                              payload_json=json.dumps(payload)))
    try:
        db.session.flush()
    except IntegrityError:            # the bot's check and a scrape run got here together
        db.session.rollback()
        return False
    note = {'group_id': group.id, 'group': group.name, 'week_of': monday.isoformat(), 'picks': picks_count(payload)}
    for m in GroupMembership.query.filter_by(group_id=group.id, status='active'):
        u = m.user
        if u and u.is_active and notify.wants(u, 'digest'):
            notify._make(db, Notification, u, 'digest', None, None, note, ready=True,
                         channels=None if notify.wants(u, 'digest_out') else ())
    db.session.commit()
    return True


def publish_due(now=None):
    """Publish every club's digest that's due (Monday from 10 AM, once a
    week). Returns how many. Safe to call often: the bot's checks and every
    scrape run call it."""
    from flask import has_app_context
    from app import app, db, ClubDigest, Group
    if not has_app_context():
        with app.app_context():
            return publish_due(now)
    now = now or _local_now()
    if now.weekday() != 0 or now.hour < PUBLISH_HOUR:
        return 0
    done = {d.group_id for d in db.session.query(ClubDigest.group_id).filter_by(week_of=week_of(now))}
    return sum(publish(g, now) for g in Group.query.filter(Group.digest_enabled.is_(True)) if g.id not in done)


def card(group, viewer, digest):
    """A published digest as a Feed card, with the viewer's watchlist films
    still to play that week."""
    from app import Showtime, Watchlist, _group_showtime_query
    payload = json.loads(digest.payload_json or '{}')
    start = datetime.combine(digest.week_of, datetime.min.time())
    wanted = [w.movie_id for w in Watchlist.query.filter_by(user_id=viewer.id)]
    yours = {}
    if wanted:
        for s in (_group_showtime_query(group)
                  .filter(Showtime.movie_id.in_(wanted),
                          Showtime.start_time >= max(start, _local_now()),
                          Showtime.start_time < start + timedelta(days=7))
                  .order_by(Showtime.start_time)):
            if s.movie_id in yours:
                yours[s.movie_id]['count'] += 1
            else:
                yours[s.movie_id] = {**showtime_brief(s), 'count': 1}
    return {'type': 'digest', 'digest': {'week_of': digest.week_of.isoformat(), **payload,
                                         'yours': list(yours.values())[:YOURS_MAX],
                                         'yours_more': max(0, len(yours) - YOURS_MAX)}}

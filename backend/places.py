"""Where and when: every "which theatres" and "what time is it there" goes
through here, so the site works the same for every city (cities.py).

- A showtime's start is its theatre's wall-clock time, so "now" depends on
  the city: `now_in(city)`, `now_at(theatre)`, and `upcoming()` / `started()`
  for showtimes across cities.
- A club runs on its home city's clock (`club_now`): the digest, trivia,
  bingo's month, the kernel week.
- Whose city a page is about: `viewer_city(user, group, asked)` — what the
  page asked for, else the club's, else the person's own, else the first city.
- Which theatres: `showtime_query(group, city)` — a club's chosen theatres
  (none chosen: its city's), or a city's.

Nothing else should call datetime.now() to compare with showtimes, or list
theatres without a city (tests/backend/test_cities.py checks the clock).
"""
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import cities


# ─── Cities ───────────────────────────────────────────────────────────────────

def active_cities():
    """Cities with at least one active theatre, in cities.CITIES order (never empty)."""
    from app import db, Theatre
    have = {c for (c,) in db.session.query(Theatre.city).filter(Theatre.is_active.isnot(False)).distinct()}
    return [c for c in cities.CITIES if c.slug in have] or [cities.get(cities.DEFAULT_CITY)]


def multi_city():
    """More than one city has theatres: the city menu, headings and tags show."""
    return len(active_cities()) > 1


class CityScope:
    """No club, one city — what a visitor's pages are about. It stands where
    a club would (`group`), and is falsy, so `if group:` still means "a club"."""
    id = name = slug = None
    theatres = ''

    def __init__(self, city=None):
        self.city = cities.clean(city) or cities.DEFAULT_CITY

    def __bool__(self):
        return False

    def __repr__(self):
        return f'<CityScope {self.city}>'


def asked_city():
    """The city a request names (?city=, which the site adds to every call), or None."""
    from flask import has_request_context, request
    return cities.clean(request.args.get('city')) if has_request_context() else None


def scope(group=None, user=None, asked=None):
    """The club, or (no club) the viewer's city as a CityScope."""
    return group if group else CityScope(viewer_city(user, None, asked or asked_city()))


def theatre_areas(city=None):
    """{theatre slug: area label} — for grouping theatres in filters."""
    return {t.slug: cities.area_label(t.city, t.area) for t in theatres_in(city)}


def city_of(theatre):
    return cities.clean(getattr(theatre, 'city', None)) or cities.DEFAULT_CITY


def club_city(group):
    return (cities.clean(group.city) if group is not None else None) or cities.DEFAULT_CITY


def person_city(user):
    """Someone's city: the one they chose, else their first club's, else the first city."""
    if user is None:
        return cities.DEFAULT_CITY
    own = cities.clean(getattr(user, 'city', None))
    if own:
        return own
    from app import Group, GroupMembership
    club = (Group.query.join(GroupMembership, GroupMembership.group_id == Group.id)
            .filter(GroupMembership.user_id == user.id, GroupMembership.status == 'active')
            .order_by(GroupMembership.id).first()) if getattr(user, 'id', None) else None
    return club_city(club) if club else cities.DEFAULT_CITY


def viewer_city(user=None, group=None, asked=None):
    """The city a page is about: what it asked for, the club's, or the person's."""
    return cities.clean(asked) or (club_city(group) if group is not None else None) or person_city(user)


def user_cities(user):
    """The cities someone hears about (alerts): their clubs' and their own."""
    from app import Group, GroupMembership
    out = {club_city(g) for g in Group.query.join(GroupMembership, GroupMembership.group_id == Group.id)
           .filter(GroupMembership.user_id == user.id, GroupMembership.status == 'active')}
    own = cities.clean(getattr(user, 'city', None))
    if own:
        out.add(own)
    return out or {cities.DEFAULT_CITY}


# ─── Clocks ───────────────────────────────────────────────────────────────────

def now_in(city=None):
    """The wall-clock time in a city (naive, like showtimes)."""
    return datetime.now(cities.zone(cities.clean(city) or cities.DEFAULT_CITY)).replace(tzinfo=None)


def server_now():
    """The server's own clock — for bookkeeping that never meets a showtime
    (the Discord post queue, rate limits, last seen). Never compare it with
    a showtime."""
    return datetime.now()


def to_utc(local, city):
    """A wall-clock time in a city, as naive UTC (how the database keeps activity times)."""
    zone = cities.zone(cities.clean(city) or cities.DEFAULT_CITY)
    return local.replace(tzinfo=zone).astimezone(timezone.utc).replace(tzinfo=None)


def to_server(local, city):
    """A wall-clock time someone typed in a city, on the server's clock (the post queue)."""
    zone = cities.zone(cities.clean(city) or cities.DEFAULT_CITY)
    return local.replace(tzinfo=zone).astimezone().replace(tzinfo=None)


def today_in(city=None):
    return now_in(city).date()


def now_at(theatre):
    return now_in(city_of(theatre))


def club_now(group):
    """A club's clock: its home city's."""
    return now_in(club_city(group))


def person_zone(user):
    """Someone's time zone name (the bot keeps its DMs to their daytime)."""
    return cities.get(person_city(user)).tz


def person_now(user_or_id):
    """Someone's clock (their kernel week): their city's."""
    from app import db, User
    user = db.session.get(User, user_or_id) if isinstance(user_or_id, int) else user_or_id
    return now_in(person_city(user))


def starts_at(showtime):
    """A showtime's start with its city's offset (ISO) — for relative times and calendars."""
    zone = cities.zone(city_of(showtime.theatre))
    return showtime.start_time.replace(tzinfo=zone).isoformat()


def utc_offset(showtime):
    """'-05:00' style offset of a showtime's start in its city."""
    return starts_at(showtime)[-6:]


# ─── Theatres ─────────────────────────────────────────────────────────────────

def theatres_in(city=None):
    """Active theatres, in one city (or all), by name."""
    from app import Theatre
    q = Theatre.query.filter(Theatre.is_active.isnot(False))
    if city:
        q = q.filter(Theatre.city == city)
    return q.order_by(Theatre.name).all()


def theatre_slugs(city):
    return {t.slug for t in theatres_in(city)}


def area_slugs(areas, city=None):
    """Theatres in any of these areas (Browse's ?regions=), within a city if given."""
    keys = {a.strip().lower() for a in areas if a and a.strip()}
    return {t.slug for t in theatres_in(city) if (t.area or '') in keys} if keys else set()


@lru_cache(maxsize=1)
def _flags():
    from scrapers import THEATRE_REGISTRY
    return ({c.slug for c in THEATRE_REGISTRY if c.arthouse}, {c.slug for c in THEATRE_REGISTRY if c.big_screen})


def arthouse_slugs():
    """Independent and repertory houses (the registry's `arthouse`)."""
    return _flags()[0]


def big_screen_slugs():
    """Giant screens even without a format label (the registry's `big_screen`)."""
    return _flags()[1]


def club_slugs(group):
    """The theatres a club follows (none chosen: every theatre in its city)."""
    chosen = [t.strip() for t in (group.theatres or '').split(',') if t.strip()] if group is not None else []
    return set(chosen) or theatre_slugs(club_city(group))


def showtime_query(group=None, city=None):
    """Showtimes (with Movie and Theatre joined, not cancelled, active theatres):
    a club's theatres, or one city's (the club's city if it chose none)."""
    from app import Movie, Showtime, Theatre
    q = Showtime.query.join(Movie).join(Theatre).filter(
        Showtime.is_cancelled.isnot(True), Theatre.is_active.isnot(False))
    if group is not None:
        return q.filter(Theatre.slug.in_(club_slugs(group)))
    return q.filter(Theatre.city == (cities.clean(city) or cities.DEFAULT_CITY))


def _by_city():
    """{city: [theatre ids]} for the active cities."""
    from app import Theatre
    out = {}
    for t in Theatre.query.filter(Theatre.is_active.isnot(False)):
        out.setdefault(city_of(t), []).append(t.id)
    return out


def upcoming(query, ahead=timedelta(0)):
    """Showtimes that haven't started (by their own city's clock), on any query of Showtime."""
    return query.filter(_since(ahead, later=True))


def started(query, ago=timedelta(0)):
    """Showtimes that have started (by their own city's clock)."""
    return query.filter(_since(ago, later=False))


def _since(offset, later):
    from sqlalchemy import and_, or_
    from app import Showtime
    groups = _by_city()

    def cond(city, ids=None):
        at = now_in(city) + (offset if later else -offset)
        c = Showtime.start_time >= at if later else Showtime.start_time < at
        return c if ids is None else and_(Showtime.theatre_id.in_(ids), c)
    if len(groups) <= 1:
        return cond(next(iter(groups), cities.DEFAULT_CITY))
    return or_(*[cond(city, ids) for city, ids in groups.items()])


def has_started(showtime):
    return showtime.start_time <= now_at(showtime.theatre)

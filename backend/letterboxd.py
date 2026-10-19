"""Letterboxd: the diary sync (R10f) and the watchlist import (below).

The diary sync is only for members who connect their diary in
their profile. Letterboxd has no sign-in we can use and blocks profile-page
fetches, but every member's diary is a public RSS feed
(https://letterboxd.com/<username>/rss/): we confirm it exists, allow one
site account per username (a club admin can clear a wrong claim), and read
it every few hours.

A diary entry matches a screening you said you were going to when it's the
same film (TMDB id, or the title tidied of "in 70mm" and the like, plus the
year) watched that day or the day after (late shows logged past midnight).
What happens then is your choice, like the Discord sharing ones:
  ask     the "Did you make it?" prompt for it says your diary has it (default)
  always  you're checked in ("Went") automatically
  never   the diary isn't used for check-ins
Entries that match nothing are kept so they're not read twice — and (R15)
in clubs that turn it on, the month's entries fill bingo's film squares
("home viewing"), so each recent one gets its film's genres and runtime
(fill_details: from our films, or TMDB by id).
"""
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

FEED = 'https://letterboxd.com/{}/rss/'
NS = {'lb': 'https://letterboxd.com', 'tmdb': 'https://themoviedb.org'}
USER_AGENT = 'Mozilla/5.0 (compatible; CinemaClubDC/1.0; +https://cinemaclubdc.com)'
SYNC_EVERY = timedelta(hours=3)
MATCH_WINDOW = timedelta(days=30)        # only recent diary entries are matched to screenings
DETAILS_WINDOW = timedelta(days=62)      # entries this recent get their film's details (this card and last)
DETAILS_PER_SYNC = 25                    # TMDB lookups per sync, at most
MAX_FEED_BYTES = 3_000_000
CHOICES = ('ask', 'always', 'never')
USERNAME_RE = re.compile(r'^[A-Za-z0-9_]{1,60}$')


def clean_username(raw):
    name = (raw or '').strip().lstrip('@')
    name = re.sub(r'^https?://(www\.)?letterboxd\.com/', '', name).strip('/').split('/')[0]
    return name if USERNAME_RE.match(name) else None


def fetch(username):
    """(diary entries, error). error: 'not_found' | 'unreachable'."""
    import requests
    try:
        r = requests.get(FEED.format(username), headers={'User-Agent': USER_AGENT}, timeout=15)
    except requests.RequestException:
        return None, 'unreachable'
    if r.status_code == 404:
        return None, 'not_found'
    if r.status_code != 200 or len(r.content) > MAX_FEED_BYTES:
        return None, 'unreachable'
    return parse(r.content), None


def parse(xml_bytes):
    """Diary entries (lists and other items are skipped):
    [{guid, watched_on, title, year, tmdb_id, rating, rewatch, link}]."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter('item'):
        watched = it.findtext('lb:watchedDate', namespaces=NS)
        if not watched:
            continue
        try:
            watched_on = date.fromisoformat(watched.strip())
        except ValueError:
            continue
        rating = it.findtext('lb:memberRating', namespaces=NS)
        tmdb = it.findtext('tmdb:movieId', namespaces=NS)
        year = it.findtext('lb:filmYear', namespaces=NS)
        out.append({
            'guid': (it.findtext('guid') or '').strip()[:80],
            'watched_on': watched_on,
            'title': (it.findtext('lb:filmTitle', namespaces=NS) or '').strip()[:200],
            'year': int(year) if year and year.strip().isdigit() else None,
            'tmdb_id': int(tmdb) if tmdb and tmdb.strip().isdigit() else None,
            'rating': float(rating) if rating and re.fullmatch(r'\d(\.\d)?', rating.strip()) else None,
            'rewatch': (it.findtext('lb:rewatch', namespaces=NS) or '').strip().lower() == 'yes',
            'link': (it.findtext('link') or '').strip()[:300],
            'review': review_text(it.findtext('description')),
        })
    return [e for e in out if e['guid'] and e['title']]


def review_text(html):
    """A diary entry's review in plain words (R15, for quiz clues): no poster,
    no "Watched on…" line; None when there's no review or Letterboxd marks it
    as having spoilers."""
    import html as htmllib
    if not html or 'may contain spoilers' in html.lower():
        return None
    text = re.sub(r'<img[^>]*>', ' ', html)
    text = re.sub(r'</p>\s*<p>', '\n', text)
    text = htmllib.unescape(re.sub(r'<[^>]+>', ' ', text))
    lines = [re.sub(r'\s+', ' ', ln).strip() for ln in text.split('\n')]
    lines = [ln for ln in lines if ln and not re.match(r'^Watched on ', ln)]
    return '\n'.join(lines)[:4000] or None


_NOISE = re.compile(r"\b(in\s+)?(70|35|16)\s*mm\b|\b(4k|imax|digital|restoration|restored|director'?s cut|"
                    r"anniversary|double feature)\b|\(\d{4}\)|^.*\bpresents\b", re.I)


def clean_title(title):
    """'NORTH BY NORTHWEST in 70mm' → 'north by northwest', 'VERTIGO (Digital)'
    → 'vertigo', "Schindler’s List" → 'schindlers list' (to match diary and
    watchlist titles): no format notes, no punctuation."""
    import discover
    t = _NOISE.sub(' ', title or '')
    t = re.sub(r'\s+-\s+.*$', '', t)            # "BRAZIL - DIRECTOR'S CUT"
    t = re.sub(r"['’]", '', discover.normalize(t))
    return re.sub(r'\s+', ' ', re.sub(r'[^\w\s]', ' ', t)).strip()


def _year(m):
    try:
        return int((m.release_year or '')[:4])
    except ValueError:
        return None


def same_film(movie, entry):
    if movie.tmdb_id and entry['tmdb_id']:
        return movie.tmdb_id == entry['tmdb_id']
    if clean_title(movie.title) != clean_title(entry['title']):
        return False
    y = _year(movie)
    return not y or not entry['year'] or abs(y - entry['year']) <= 1


def match(user, entry):
    """The screening this diary entry is — one `user` said they were going to,
    that day or the day before — or None."""
    from app import RSVP, Showtime
    day = entry['watched_on']
    start = datetime.combine(day - timedelta(days=1), datetime.min.time())
    end = datetime.combine(day + timedelta(days=1), datetime.min.time())
    rows = (RSVP.query.join(Showtime, RSVP.showtime_id == Showtime.id)
            .filter(RSVP.user_id == user.id, RSVP.status == 'going', Showtime.start_time >= start,
                    Showtime.start_time < end, Showtime.start_time <= datetime.now())
            .order_by(Showtime.start_time.desc()).all())
    return next((r.showtime for r in rows if r.showtime.movie and same_film(r.showtime.movie, entry)), None)


def fill_details(user, now=None):
    """Genres and runtime for `user`'s recent diary entries (home bingo, R15):
    from the film when it's one of ours (same TMDB id, or same title and
    year), else TMDB by id. Entries without either keep None (only the era
    squares, from the diary's year, can use them). Caller commits."""
    import enrich
    from app import LetterboxdEntry, Movie, _utcnow_naive
    now = now or datetime.now()
    todo = (LetterboxdEntry.query.filter(LetterboxdEntry.user_id == user.id, LetterboxdEntry.details_at.is_(None),
                                         LetterboxdEntry.watched_on >= (now - DETAILS_WINDOW).date())
            .order_by(LetterboxdEntry.watched_on.desc()).all())
    looked_up = 0
    for e in todo:
        entry = {'tmdb_id': e.tmdb_id, 'title': e.title, 'year': e.year}
        m = Movie.query.filter_by(tmdb_id=e.tmdb_id).first() if e.tmdb_id else None
        if not m and e.year:                              # no TMDB match: the same title from that year
            m = next((x for x in Movie.query.filter(Movie.release_year.like(f'{e.year}%')) if same_film(x, entry)), None)
        if m:
            e.genres, e.runtime = m.genres or '', m.runtime_minutes
        elif e.tmdb_id and looked_up < DETAILS_PER_SYNC:
            looked_up += 1
            d = enrich.tmdb_details(e.tmdb_id)
            if d is None:
                continue                                  # TMDB didn't answer: try again next sync
            e.genres, e.runtime = d.get('genres') or '', d.get('runtime_minutes')
        elif e.tmdb_id:
            continue                                      # over this sync's lookups: next time
        e.details_at = _utcnow_naive()


def sync(user, entries=None, now=None):
    """Read `user`'s diary (or the given entries) and act on new matches by
    their choice. Returns {'new', 'checked_in', 'suggested'} (or {'error'})."""
    from app import db, Attendance, LetterboxdEntry, _utcnow_naive, set_attendance
    if entries is None:
        entries, error = fetch(user.letterboxd_username)
        if error:
            user.letterboxd_synced_at = _utcnow_naive()
            db.session.commit()
            return {'error': error}
    now = now or datetime.now()
    seen = {e.guid for e in LetterboxdEntry.query.filter_by(user_id=user.id)}
    counts = {'new': 0, 'checked_in': 0, 'suggested': 0}
    choice = user.letterboxd_checkin if user.letterboxd_checkin in CHOICES else 'ask'
    for e in entries:
        if e['guid'] in seen:
            continue
        seen.add(e['guid'])
        s = match(user, e) if e['watched_on'] >= (now - MATCH_WINDOW).date() else None
        status = 'unmatched'
        if s:
            answered = Attendance.query.filter(Attendance.user_id == user.id, Attendance.showtime_id == s.id,
                                               Attendance.status.isnot(None)).first()
            if answered:
                status = 'already'
            elif choice == 'always':
                status = 'checked_in'
            elif choice == 'ask':
                status = 'suggested'
            else:
                status = 'ignored'
        db.session.add(LetterboxdEntry(user_id=user.id, guid=e['guid'], watched_on=e['watched_on'], title=e['title'],
                                       year=e['year'], tmdb_id=e['tmdb_id'], rating=e['rating'], rewatch=e['rewatch'],
                                       link=e['link'], review=e.get('review'), showtime_id=s.id if s else None,
                                       status=status))
        counts['new'] += 1
        if status == 'checked_in':
            db.session.flush()
            set_attendance(user, s.id, 'went', 'letterboxd')      # commits
            counts['checked_in'] += 1
        elif status == 'suggested':
            counts['suggested'] += 1
    fill_details(user, now)
    user.letterboxd_synced_at = _utcnow_naive()
    db.session.commit()
    return counts


def sync_due(now=None):
    """After a scrape run: sync every connected diary that's due."""
    from app import app, User, _utcnow_naive
    done = 0
    with app.app_context():
        cutoff = _utcnow_naive() - SYNC_EVERY
        for user in User.query.filter(User.letterboxd_sync.is_(True), User.is_active.is_(True)).all():
            if user.letterboxd_synced_at and user.letterboxd_synced_at > cutoff:
                continue
            try:
                if 'error' not in sync(user, now=now):
                    done += 1
            except Exception as e:                    # one bad feed never stops the rest
                print(f'letterboxd sync for user {user.id} failed: {e}')
    return done


def suggestions(user, showtime_ids):
    """{showtime_id: {rating, link}} — diary entries waiting on "Did you make it?"."""
    from app import LetterboxdEntry
    if not showtime_ids or not user.letterboxd_sync or user.letterboxd_checkin != 'ask':
        return {}
    rows = LetterboxdEntry.query.filter(LetterboxdEntry.user_id == user.id, LetterboxdEntry.status == 'suggested',
                                        LetterboxdEntry.showtime_id.in_(list(showtime_ids))).all()
    return {r.showtime_id: {'rating': r.rating, 'link': r.link} for r in rows}


def ratings(user_ids, showtime_id):
    """{uid: {rating, link}} for members who chose to show their Letterboxd
    ratings with their check-ins."""
    from app import LetterboxdEntry, User
    if not user_ids:
        return {}
    sharing = {u.id for u in User.query.filter(User.id.in_(list(user_ids)), User.letterboxd_sync.is_(True),
                                               User.letterboxd_ratings.is_(True))}
    if not sharing:
        return {}
    rows = LetterboxdEntry.query.filter(LetterboxdEntry.showtime_id == showtime_id,
                                        LetterboxdEntry.user_id.in_(sharing)).all()
    return {r.user_id: {'rating': r.rating, 'link': r.link} for r in rows if r.rating or r.link}


def status(user):
    """For the profile: connected?, the username, last sync, your choices."""
    return {'username': user.letterboxd_username or '', 'connected': bool(user.letterboxd_sync),
            'synced_at': user.letterboxd_synced_at.isoformat() + 'Z' if user.letterboxd_synced_at else None,
            'checkin': user.letterboxd_checkin if user.letterboxd_checkin in CHOICES else 'ask',
            'ratings': bool(user.letterboxd_ratings), 'clues': user.letterboxd_clues is not False,
            'watchlist': watch_status(user)}


# ─── The watchlist, from Letterboxd's export ──────────────────────────────────
# Letterboxd has no watchlist feed (and its pages sit behind a bot check), so
# members upload the export it gives them (Settings → Import & Export): the
# whole zip, or the watchlist.csv inside. Each import replaces the stored
# list and mirrors it: films from Letterboxd that are gone from the file leave
# the watchlist; films added here never do. A film joins the watchlist once
# it's in our catalog — now, or when a scrape or a TMDB search adds it later
# (match_films) — so a long list costs no lookups up front.

MAX_WATCHLIST = 10_000                   # rows read from one file
MAX_CSV_BYTES = 5_000_000                # the CSV inside a zip, unpacked


def read_export(data):
    """([{title, year, uri, added_on}], error) from the export's bytes — the
    zip or the CSV. error: 'not_export' (not Letterboxd's watchlist) | 'empty'."""
    import csv
    import io
    import zipfile
    if data[:4] == b'PK\x03\x04':
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                names = [n for n in z.namelist() if n.rsplit('/', 1)[-1].lower() == 'watchlist.csv']
                if not names:
                    return None, 'not_export'
                info = z.getinfo(min(names, key=lambda n: n.count('/')))    # the top one, not deleted/
                if info.file_size > MAX_CSV_BYTES:
                    return None, 'not_export'
                text = z.read(info).decode('utf-8-sig', 'replace')
        except zipfile.BadZipFile:
            return None, 'not_export'
    else:
        text = data.decode('utf-8-sig', 'replace')
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().lower() for h in next(reader, [])]
    if 'name' not in header or 'letterboxd uri' not in header:
        return None, 'not_export'
    col = {h: i for i, h in enumerate(header)}
    cell = lambda row, h: row[col[h]].strip() if h in col and col[h] < len(row) else ''
    rows, seen = [], set()
    for row in reader:
        title = cell(row, 'name')[:255]
        if not title:
            continue
        year = int(cell(row, 'year')) if cell(row, 'year').isdigit() else None
        key = (clean_title(title), year)
        if not key[0] or key in seen:
            continue
        seen.add(key)
        try:
            added = date.fromisoformat(cell(row, 'date'))
        except ValueError:
            added = None
        rows.append({'title': title, 'year': year, 'uri': cell(row, 'letterboxd uri')[:200], 'added_on': added})
        if len(rows) >= MAX_WATCHLIST:
            break
    return (rows, None) if rows else (None, 'empty')


def watch_match(year, films):
    """Which of `films` (ones with the entry's clean title) the entry is: the
    year must agree within one (re-release dates) — a film whose year we don't
    know isn't guessed at; with no year, only when there's just one."""
    if year:
        hits = [m for m in films if _year(m) and abs(_year(m) - year) <= 1]
        hits.sort(key=lambda m: abs(_year(m) - year))
        return hits[0] if hits else None
    return films[0] if len(films) == 1 else None


def import_watchlist(user, rows):
    """Replace `user`'s imported list with `rows` and mirror their watchlist.
    Returns {films, matched, added, removed}. Commits."""
    from app import db, LetterboxdWatch, Movie, Watchlist, _utcnow_naive
    old = {(w.title_key, w.year): w for w in LetterboxdWatch.query.filter_by(user_id=user.id)}
    index = {}
    for m in Movie.query.all():
        index.setdefault(clean_title(m.title), []).append(m)
    now, keep = _utcnow_naive(), set()
    for r in rows:
        key = (clean_title(r['title']), r['year'])
        lw = old.get(key)
        if lw is None:
            lw = LetterboxdWatch(user_id=user.id, title_key=key[0], year=r['year'])
            db.session.add(lw)
        lw.title, lw.uri, lw.added_on, lw.imported_at = r['title'], r['uri'], r['added_on'], now
        if lw.movie_id is None:
            m = watch_match(r['year'], index.get(key[0], []))
            lw.movie_id = m.id if m else None
        keep.add(key)
    for key, lw in old.items():
        if key not in keep:                                  # gone from Letterboxd
            db.session.delete(lw)
    db.session.flush()
    wanted = {lw.movie_id for lw in LetterboxdWatch.query.filter_by(user_id=user.id)
              if lw.movie_id and not lw.dismissed}
    current = {w.movie_id: w for w in Watchlist.query.filter_by(user_id=user.id)}
    added = removed = 0
    for mid in wanted - set(current):
        # share_discord stays unset: the digest follows your "watchlist" sharing choice (never asks per film)
        db.session.add(Watchlist(user_id=user.id, movie_id=mid, source='letterboxd'))
        added += 1
    for mid, w in current.items():
        if w.source == 'letterboxd' and mid not in wanted:
            db.session.delete(w)
            removed += 1
    user.letterboxd_watch_on, user.letterboxd_watch_imported_at = True, now
    db.session.commit()
    return {'films': len(keep), 'matched': len(wanted), 'added': added, 'removed': removed}


def remove_import(user):
    """Watchlist off: the imported films leave (films added here stay). Commits."""
    from app import db, LetterboxdWatch, Watchlist
    Watchlist.query.filter_by(user_id=user.id, source='letterboxd').delete()
    LetterboxdWatch.query.filter_by(user_id=user.id).delete()
    user.letterboxd_watch_on, user.letterboxd_watch_imported_at = False, None
    db.session.commit()


def match_films(movies):
    """Films just added to the catalog (or newly identified): put them on the
    watchlist of everyone whose imported list has them. Before the caller
    commits — the scraper calls this before that run's alerts, so a film
    booked the day it's matched alerts its watchers."""
    from app import db, LetterboxdWatch, User, Watchlist
    added = 0
    for m in movies:
        key = clean_title(m.title)
        for lw in (LetterboxdWatch.query.join(User, User.id == LetterboxdWatch.user_id)
                   .filter(LetterboxdWatch.title_key == key, LetterboxdWatch.movie_id.is_(None),
                           LetterboxdWatch.dismissed.isnot(True), User.letterboxd_watch_on.is_(True))):
            if watch_match(lw.year, [m]) is None:
                continue
            lw.movie_id = m.id
            if not Watchlist.query.filter_by(user_id=lw.user_id, movie_id=m.id).first():
                db.session.add(Watchlist(user_id=lw.user_id, movie_id=m.id, source='letterboxd'))
                added += 1
    if added:
        db.session.flush()
    return added


def removed_here(user_id, movie_id):
    """A film taken off the watchlist here (the site or /watch): if it's on
    their Letterboxd list, the next import leaves it out."""
    from app import LetterboxdWatch
    LetterboxdWatch.query.filter_by(user_id=user_id, movie_id=movie_id).update({'dismissed': True})


def watch_status(user):
    from app import LetterboxdWatch
    rows = LetterboxdWatch.query.filter_by(user_id=user.id).filter(LetterboxdWatch.dismissed.isnot(True))
    return {'on': bool(user.letterboxd_watch_on),
            'imported_at': user.letterboxd_watch_imported_at.isoformat() + 'Z' if user.letterboxd_watch_imported_at else None,
            'films': rows.count(), 'matched': rows.filter(LetterboxdWatch.movie_id.isnot(None)).count(),
            'alerts': user.letterboxd_watch_alerts}

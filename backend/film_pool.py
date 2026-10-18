"""The films trivia and the quiz games ask about (R15).

Two sources, chosen per club (Group.trivia_source):
  local   our films — what's played at the theatres we follow
  tmdb    TMDB's SIZE most-voted films (PoolFilm), refreshed weekly by the
          scraper (refresh_if_due), so questions reach films people know
  both    either (the default)

Wrong answers come from both, whatever the source: the films most like the
answer — the same era, a shared genre, about as well known (similarity) —
so a 1926 swashbuckler isn't up against a 2026 cartoon. A question's
difficulty (EASY / MEDIUM / HARD) follows how well known the answer is and
how close the wrong answers are.

Every film is shown by its TMDB title ("The Black Pirate", not the
theatre's "THE BLACK PIRATE").
"""
import json
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

SOURCES = ('local', 'tmdb', 'both')
SIZE = 5000                                  # TMDB's most-voted films in the pool
PER_PAGE = 20                                # TMDB's discover page size
REFRESH_EVERY = timedelta(days=7)
DETAILS_PER_QUESTION = 3                     # TMDB lookups a question may make for a pool film's people
EASY, MEDIUM, HARD = 'easy', 'medium', 'hard'
WELL_KNOWN, KNOWN = 6000, 1500               # TMDB votes: famous (pool's top ~15%), known (top ~75%); below: a deep cut
CLOSE = 0.95                                 # look-alikes this close make it harder (the median is ~0.9)
ROMAN = re.compile(r'(?=[ivxlc])(x{0,3})(ix|iv|v?i{0,3})', re.I)          # II, III, IV… stay capitals
SMALL_WORDS = {'a', 'an', 'and', 'as', 'at', 'by', 'for', 'from', 'in', 'into', 'of', 'on', 'or', 'the', 'to',
               'vs', 'vs.', 'with'}


@dataclass
class Film:
    key: str                                  # 'film:<movie id>' (ours) | 'tmdb:<tmdb id>' (the pool)
    title: str
    year: int | None
    genres: frozenset
    votes: int
    movie_id: int | None = None
    tmdb_id: int | None = None
    director: str | None = None
    tagline: str | None = None
    cast: list = field(default_factory=list)
    characters: list = field(default_factory=list)            # who the top billed play (who said it, R15)
    overview: str | None = None                               # the plot (emoji plot, R15)
    poster_url: str | None = None
    pool: object = None                       # its PoolFilm row, if it has one

    @property
    def label(self):
        return f'{self.title} ({self.year})' if self.year else self.title


def nice_title(title):
    """A theatre's ALL-CAPS title in title case ("THE BLACK PIRATE" →
    "The Black Pirate"); anything else as it is."""
    t = (title or '').strip()
    if not t or t != t.upper() or not re.search('[A-Z]', t):
        return t
    words, out = t.lower().split(), []
    for i, w in enumerate(words):
        starts = i == 0 or words[i - 1].endswith(':')          # a title, or a subtitle after a colon
        out.append(w.upper() if ROMAN.fullmatch(w.strip(':,.')) else w if w in SMALL_WORDS and not starts
                   else w[:1].upper() + w[1:])
    return ' '.join(out)


def _genres(text):
    return frozenset(g.strip().lower() for g in (text or '').split(',') if g.strip())


def _year(text):
    m = re.match(r'\d{4}', str(text or ''))
    return int(m.group()) if m else None


def _cast(cast_json, n=6):
    try:
        rows = json.loads(cast_json or '[]')
    except ValueError:
        return []
    return [r['name'] if isinstance(r, dict) else r for r in rows[:n] if (r.get('name') if isinstance(r, dict) else r)]


def _characters(cast_json, n=10):
    try:
        rows = json.loads(cast_json or '[]')
    except ValueError:
        return []
    return [r['character'].split(' / ')[0].strip() for r in rows[:n]
            if isinstance(r, dict) and (r.get('character') or '').strip()]


def from_pool(p):
    return Film(key=f'tmdb:{p.tmdb_id}', title=p.title, year=p.year, genres=_genres(p.genres), votes=p.vote_count or 0,
                tmdb_id=p.tmdb_id, director=p.director, tagline=p.tagline, cast=_cast(p.cast_json),
                characters=_characters(p.cast_json), overview=p.overview, poster_url=p.poster_url, pool=p)


def from_movie(m, pool_row=None):
    """One of our films, with the pool's title and fame when it's in the pool."""
    return Film(key=f'film:{m.id}', title=pool_row.title if pool_row else nice_title(m.title),
                year=_year(m.release_year), genres=_genres(m.genres), votes=(pool_row.vote_count or 0) if pool_row else 0,
                movie_id=m.id, tmdb_id=m.tmdb_id, director=m.director, tagline=m.tagline, cast=_cast(m.cast_json),
                characters=_characters(m.cast_json), overview=m.description, poster_url=m.poster_url, pool=pool_row)


def films(source='both'):
    """(subjects, everyone): the films a question may be about (by `source`)
    and every film a wrong answer may come from (ours and the pool, once each)."""
    from app import Movie, PoolFilm
    pool = {p.tmdb_id: p for p in PoolFilm.query.all()}
    ours = [from_movie(m, pool.get(m.tmdb_id)) for m in Movie.query.filter(Movie.tmdb_id.isnot(None)).order_by(Movie.id)]
    have = {f.tmdb_id for f in ours}
    wider = [from_pool(p) for p in sorted(pool.values(), key=lambda p: p.tmdb_id) if p.tmdb_id not in have]
    subjects = ours if source == 'local' else wider if source == 'tmdb' else ours + wider
    return subjects, ours + wider


# ─── Look-alikes and difficulty ───────────────────────────────────────────────

def similarity(a, b):
    """0–1: how easily `b` passes for `a` — a shared genre, a close year,
    about as well known."""
    genre = len(a.genres & b.genres) / len(a.genres | b.genres) if a.genres and b.genres else 0
    era = max(0.0, 1 - abs(a.year - b.year) / 25) if a.year and b.year else 0.3
    fame = 1 - min(1.0, abs(math.log10(a.votes + 10) - math.log10(b.votes + 10)) / 2)
    return (2 * genre + 2 * era + fame) / 5


def lookalikes(subject, candidates, rng, k=3, ok=lambda f: True, top=12):
    """k films most like `subject` (picked at random among the closest `top`),
    different titles, none the subject, each passing `ok`."""
    seen = {subject.title.lower()}
    ranked = sorted((c for c in candidates if c.key != subject.key and c.title.lower() not in seen and ok(c)),
                    key=lambda c: -similarity(subject, c))
    pool = ranked[:top]
    out = []
    for c in rng.sample(pool, len(pool)):
        if c.title.lower() not in seen:
            seen.add(c.title.lower())
            out.append(c)
            if len(out) == k:
                break
    return out if len(out) == k else None


def fame(f):
    return EASY if f.votes >= WELL_KNOWN else MEDIUM if f.votes >= KNOWN else HARD


def difficulty(subject, others, extra=0):
    """How hard: a famous answer is easy, a deep cut hard, and very close
    look-alikes make it a step harder. `extra` moves it (+1: years within eight of
    each other for "which came first"; -1: a film on the club's calendar,
    which members have seen listed)."""
    score = {EASY: 0, MEDIUM: 1, HARD: 2}[fame(subject)] + extra
    close = sum(similarity(subject, o) for o in others) / len(others) if others else 0.9
    score += 1 if close >= CLOSE else 0
    return EASY if score <= 0 else MEDIUM if score == 1 else HARD


def ensure_details(f):
    """A pool film's director, tagline and cast, looked up once (TMDB) and kept.
    Our own films have them already. Returns `f` (filled in when it could be)."""
    import enrich
    from app import db, _utcnow_naive
    if not f.pool or f.movie_id or f.pool.details_at:
        return f
    d = enrich.tmdb_details(f.tmdb_id)
    if d is None:
        return f
    p = f.pool
    p.director, p.tagline, p.overview = d.get('director'), d.get('tagline'), d.get('description')
    p.cast_json = json.dumps([{'name': c['name'], 'character': c.get('character') or ''}
                              for c in json.loads(d.get('cast_json') or '[]') if c.get('name')])
    p.details_at = _utcnow_naive()
    db.session.commit()
    f.director, f.tagline, f.cast, f.characters = p.director, p.tagline, _cast(p.cast_json), _characters(p.cast_json)
    f.overview = p.overview
    return f


# ─── Keeping the pool ─────────────────────────────────────────────────────────

def _genre_names():
    """TMDB's genre ids → names."""
    import enrich
    r = enrich._http.get(f'{enrich.TMDB_BASE}/genre/movie/list', headers=enrich._tmdb_headers(), timeout=10)
    r.raise_for_status()
    return {g['id']: g['name'] for g in r.json().get('genres', [])}


def refresh(size=SIZE, now=None):
    """Fetch TMDB's `size` most-voted films into the pool (new ones added,
    the rest updated). Returns how many it saw; stops quietly at an error."""
    import enrich
    import taste
    from app import db, PoolFilm, _utcnow_naive
    try:
        names = _genre_names()
    except Exception as e:
        print(f'  film pool: TMDB genres failed: {e}')
        return 0
    have = {p.tmdb_id: p for p in PoolFilm.query.all()}
    seen = 0
    for page in range(1, size // PER_PAGE + 1):
        try:
            r = enrich._http.get(f'{enrich.TMDB_BASE}/discover/movie', headers=enrich._tmdb_headers(), timeout=10,
                                 params={'sort_by': 'vote_count.desc', 'include_adult': 'false', 'page': page})
            r.raise_for_status()
            results = r.json().get('results', [])
        except Exception as e:
            print(f'  film pool: TMDB page {page} failed: {e}')
            break
        for row in results:
            tid = row.get('id')
            if not tid or not row.get('title'):
                continue
            p = have.get(tid)
            if not p:
                p = have[tid] = PoolFilm(tmdb_id=tid, title=row['title'][:200])
                db.session.add(p)
            p.title = row['title'][:200]
            p.year = _year(row.get('release_date'))
            p.genres = taste.merge_genres([names.get(g) for g in row.get('genre_ids', []) if names.get(g)])
            p.popularity, p.vote_count = row.get('popularity'), row.get('vote_count')
            p.poster_url = f"{enrich.TMDB_IMG_POSTER}{row['poster_path']}" if row.get('poster_path') else None
            p.refreshed_at = _utcnow_naive()
            seen += 1
        db.session.commit()
        if len(results) < PER_PAGE:
            break
    return seen


def refresh_if_due(now=None):
    """refresh() when the pool is empty or a week old (after a scrape run)."""
    from app import db, BotSetting
    row = db.session.get(BotSetting, 'film_pool_at')
    last = datetime.fromisoformat(row.value) if row and row.value else None
    utc = datetime.utcnow()
    if last and utc - last < REFRESH_EVERY:
        return None
    n = refresh()
    if n:
        if not row:
            row = BotSetting(key='film_pool_at')
            db.session.add(row)
        row.value = utc.isoformat()
        db.session.commit()
    return n

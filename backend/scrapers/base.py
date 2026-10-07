"""Shared helpers for all theatre scrapers."""

import datetime
import random
import re
import time
import unicodedata

import requests
from bs4 import BeautifulSoup

# Some venues (Regal's Cloudflare, si.edu) reject obvious bot user agents, so
# browser_session() mimics a real Chrome install. get_soup keeps the polite
# self-identifying UA for the venues that don't care.
BOT_UA = 'Mozilla/5.0 (compatible; CinemaClubBot/1.0)'
BROWSER_HEADERS = {
    'User-Agent': ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) '
                   'Chrome/126.0.0.0 Safari/537.36'),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7',
    'Accept-Language': 'en-US,en;q=0.9',
    # NOTE: no Accept-Encoding here — requests advertises what it can decode
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1',
}


def get_soup(url, timeout=15, retries=3, headers=None):
    headers = headers or {'User-Agent': BOT_UA}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return BeautifulSoup(r.text, 'html.parser')
        except (requests.ConnectionError, requests.Timeout):
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Retry {attempt + 1}/{retries} for {url} (waiting {wait}s)")
                time.sleep(wait)
            else:
                raise


def browser_session():
    """A requests.Session with realistic browser headers, for picky origins."""
    s = requests.Session()
    s.headers.update(BROWSER_HEADERS)
    return s


def get_json(session, url, timeout=15, retries=3, **kwargs):
    """GET a JSON endpoint through a session with retry/backoff."""
    for attempt in range(retries):
        try:
            r = session.get(url, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, ValueError):
            if attempt < retries - 1:
                wait = 2 ** attempt
                print(f"  Retry {attempt + 1}/{retries} for {url} (waiting {wait}s)")
                time.sleep(wait)
            else:
                raise


def with_retry(fn, attempts=3, base_delay=1.0, label=''):
    """Run fn() with exponential backoff. Retries any exception (covers
    transient DNS resolution failures, connection resets, and rate limits)."""
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            if i < attempts - 1:
                wait = base_delay * (2 ** i)
                where = f" for {label}" if label else ''
                print(f"  Retry {i + 1}/{attempts}{where} ({e.__class__.__name__}); waiting {wait:.0f}s")
                time.sleep(wait)
            else:
                raise


class ScrapeResult(list):
    """A scraper's movie list plus the dates it couldn't fetch. Sync cancels
    showtimes that disappeared only on dates that were actually checked, so a
    rate-limited or failed day never wipes real screenings off the calendar.
    Plain lists still work (every date counts as checked)."""
    def __init__(self, movies=(), missed_dates=()):
        super().__init__(movies)
        self.missed_dates = set(missed_dates)


def polite_pause(seconds, jitter=1.0):
    """Wait between requests to the same site, with a little randomness."""
    time.sleep(seconds + random.uniform(0, jitter))


def retry_after(response, default):
    """Seconds a 429/503 response asks us to wait (Retry-After), capped at 2 min."""
    try:
        return min(120.0, max(1.0, float(response.headers.get('Retry-After', default))))
    except (TypeError, ValueError):
        return default


class PerDateFetcher:
    """Pacing + a circuit breaker for scrapers that make one request per date:
    after `max_consecutive_failures` failures in a row it stops asking (the
    site is throttling us), and every date it didn't get is reported missed."""
    def __init__(self, label, pause=2.0, jitter=1.0, max_consecutive_failures=3):
        self.label, self.pause, self.jitter = label, pause, jitter
        self.max_failures, self.failures_in_row = max_consecutive_failures, 0
        self.missed = set()
        self.tripped = False

    def run(self, dates, fetch, ingest, to_date=lambda d: d):
        for d in dates:
            if self.tripped:
                self.missed.add(to_date(d))
                continue
            polite_pause(self.pause, self.jitter)
            try:
                ingest(fetch(d))
                self.failures_in_row = 0
            except Exception as e:
                self.missed.add(to_date(d))
                self.failures_in_row += 1
                print(f"  {self.label}: failed {d}: {e}")
                if self.failures_in_row >= self.max_failures:
                    self.tripped = True
                    print(f"  {self.label}: {self.max_failures} failures in a row — stopping for this run; "
                          f"showtimes on unchecked dates are kept")


def safe_text(tag, strip=True):
    if not tag:
        return ''
    text = tag.get_text()
    return text.strip() if strip else text


def new_movie_dict():
    """The movie-dict contract every scraper returns a list of."""
    return {
        'title': '', 'director': '', 'release_year': '',
        'runtime_minutes': 120, 'starring': '', 'description': '',
        'trailer_link': '', 'showtimes': [], 'poster_url': ''
    }


AMPM_RE = re.compile(r'(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.|am|pm)', re.I)


def parse_ampm_time(text):
    """Parse '6:00 pm' / '11:15 a.m.' → (hour, minute) in 24h, or None."""
    m = AMPM_RE.search(text or '')
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    ampm = m.group(3).lower()
    if ampm.startswith('p') and hour != 12:
        hour += 12
    elif ampm.startswith('a') and hour == 12:
        hour = 0
    return hour, minute


def make_showtime(start, runtime_minutes=120, purchase_link='', is_sold_out=False):
    end = start + datetime.timedelta(minutes=(runtime_minutes or 120) + 20)
    return {
        'start_time': start,
        'end_time': end,
        'purchase_link': purchase_link,
        'is_sold_out': is_sold_out,
    }


_WS_RE = re.compile(r'\s+')

# Words that mark a program/series label wrapped around the film title, as a
# leading "PROGRAM: Title" prefix or a trailing "Title - Program" descriptor.
# Matched as whole words, so "fest" doesn't fire inside "Manifesto".
_SERIES_WORDS = (
    'series', 'presents', 'presented', 'sunday', 'monday', 'tuesday',
    'wednesday', 'thursday', 'friday', 'saturday', 'nights', 'matinee',
    'midnight', 'double feature', 'triple feature', 'festival', 'fest',
    'retrospective', 'tribute', 'spotlight', 'classics', 'epic',
    'anniversary', 'program', 'fundraiser', 'benefit', 'marathon',
    'showcase', 'special event', 'q&a', 'in concert', 'sing-along',
    'sing along', 'brunch', 'club', 'noir',
)
_SERIES_RE = re.compile(r'\b(?:' + '|'.join(map(re.escape, _SERIES_WORDS)) + r')\b', re.I)

# Format / edition tags venues append, e.g. "The Odyssey (70mm)",
# "Alien (4K Restoration)", "DUNE in IMAX". Removed (with a leading "in")
# wherever they appear.
_FORMAT_PATTERNS = [
    r'\d{2,3}\s*mm', r'imax', r'4k', r'dcp', r'3d', r'dolby(?:\s+(?:atmos|vision|cinema))?',
    r'(?:new\s+)?(?:digital\s+)?restoration', r'restored', r'remaster(?:ed)?',
    r're-?release', r'new\s+print', r"director'?s\s+cut", r'extended\s+cut',
    r'uncut', r'unrated', r'\d+th\s+anniversary', r'anniversary',
    r'sing[-\s]?along', r'subtitled', r'open\s+caption(?:s|ed)?', r'digital$',
]
_FORMAT_RE = re.compile(r'(?:\bin\s+)?\b(?:' + '|'.join(_FORMAT_PATTERNS) + r')\b', re.I)

# Display labels for the formats worth showing on a screening ("70mm",
# "Digital"…). Order is display order; several can apply ("70mm · IMAX").
_FORMAT_LABELS = [
    (re.compile(r'\b70\s*mm\b', re.I), '70mm'),
    (re.compile(r'\b35\s*mm\b', re.I), '35mm'),
    (re.compile(r'\b16\s*mm\b', re.I), '16mm'),
    (re.compile(r'\bimax\b', re.I), 'IMAX'),
    (re.compile(r'\b4k\b', re.I), '4K'),
    (re.compile(r'\b3d\b', re.I), '3D'),
    (re.compile(r'\bdolby\b', re.I), 'Dolby'),
    (re.compile(r"\bdirector'?s\s+cut\b", re.I), "Director's Cut"),
    (re.compile(r'\bextended\s+cut\b', re.I), 'Extended Cut'),
    (re.compile(r'\bopen\s+caption', re.I), 'Open Captions'),
    # "(Digital)", "in Digital", or a trailing "Digital" — not "The Digital Age".
    (re.compile(r'\(\s*digital\s*\)|\bin\s+digital\b|\bdigital\s*$', re.I), 'Digital'),
]

_YEAR_PAREN_RE = re.compile(r'\((\d{4})\)')
_PARENS_RE = re.compile(r'\([^)]*\)')
_DASH_SPLIT_RE = re.compile(r'\s[-–—]\s')
_PRESENTS_RE = re.compile(r'^.+?\bpresents?\b:?\s+(.+)$', re.I)
# A program *code* in front of the film: "SOS26: THE THING", "NOIR 24: LAURA",
# "SOS'26 – HALLOWEEN". Letters then a 2–4 digit number as one short token
# (or letters, a space and two digits) — never a real title: "2001: A Space
# Odyssey" has no letters, "M3GAN" isn't letters-then-digits, "THX 1138" has
# four digits after its space. Removed outright; the billing keeps it.
_CODE_PREFIX_RE = re.compile(r"^\s*[A-Za-z]{2,6}(?:['’]?\d{2,4}|\s['’]?\d{2})\s*[:–—|-]\s*(?=\S)")
_TRIM_CHARS = ' -–—:·|.'


def _looks_like_series(segment):
    """True when a label segment reads like a program/series name rather than a
    film title."""
    return bool(_SERIES_RE.search(segment or ''))


def parse_movie_title(raw):
    """Parse a venue's screening label into (clean_title, year_or_None).

    Removes cruft that is never part of a film's title:
      "The Odyssey (70mm)" / "The Odyssey in 35mm"  -> ("The Odyssey", None)
      "HIS GIRL FRIDAY (1940)"                      -> ("HIS GIRL FRIDAY", "1940")
      "Planes (2013) - NASM 50th Film Series"       -> ("Planes", "2013")

    Program *codes* ("SOS26: THE THING" -> "THE THING") are removed. Program
    *names* ("EPIC SUNDAY: BATMAN BEGINS") are deliberately kept: a
    prefix can't be told apart from a real colon title ("Friday the 13th Part
    VII: The New Blood") without a lookup, so title_search_variants() offers the
    stripped form as an extra search instead. The year is returned separately so
    enrichment searches the film's real year, not a re-release date. Only a
    "(YYYY)" parenthetical counts as a year — "1917" or "2001: A Space Odyssey"
    keep their digits.
    """
    if not raw:
        return '', None
    t = _CODE_PREFIX_RE.sub('', raw.strip(), count=1)

    year = None
    m = _YEAR_PAREN_RE.search(t)
    if m and 1900 <= int(m.group(1)) <= datetime.date.today().year + 1:
        year = m.group(1)

    # Trailing " - Series/Program" descriptor.
    parts = _DASH_SPLIT_RE.split(t)
    if len(parts) > 1 and _looks_like_series(parts[-1]):
        t = ' - '.join(parts[:-1])

    t = _PARENS_RE.sub(' ', t)
    t = _FORMAT_RE.sub(' ', t)
    t = _WS_RE.sub(' ', t).strip(_TRIM_CHARS).strip()
    return (t or _WS_RE.sub(' ', raw).strip()), year


def title_search_variants(raw):
    """Titles to search for, most literal first: the clean title, then with a
    program prefix removed ("EPIC SUNDAY: BATMAN BEGINS" -> "BATMAN BEGINS",
    "Count Gore De Vol presents THE FLY" -> "THE FLY"). Trying the full title
    first means a real colon title wins over the stripped guess."""
    clean, _ = parse_movie_title(raw)
    variants = [clean]
    head, sep, tail = clean.partition(':')
    if sep and tail.strip() and _looks_like_series(head):
        variants.append(tail.strip())
    m = _PRESENTS_RE.match(clean)
    if m:
        variants.append(m.group(1).strip(_TRIM_CHARS))
    return list(dict.fromkeys(v for v in variants if v))


def _drop_format_parens(match):
    inner = match.group(0)[1:-1]
    return ' ' if not _FORMAT_RE.sub('', inner).strip(' ·-,&+') else match.group(0)


def billing_title(raw):
    """The venue's billing minus its year and format tags. Unlike the clean
    title it keeps program names and session notes: 'EPIC SUNDAY: BATMAN
    BEGINS', 'Planes - NASM 50th Film Series', 'MY UNDESIRABLE FRIENDS: PART I
    (Chapters 1-3)'."""
    t = _YEAR_PAREN_RE.sub(' ', raw or '')
    t = _PARENS_RE.sub(_drop_format_parens, t)
    t = _FORMAT_RE.sub(' ', t)
    return _WS_RE.sub(' ', t).strip(_TRIM_CHARS).strip()


def event_label(raw, film_title):
    """A screening's own billing when it says more than the film's title (shown
    under the film in the drawer), else None."""
    billing = billing_title(raw)
    return billing if billing and billing.casefold() != (film_title or '').casefold() else None


def extract_format_label(raw):
    """Display label for a screening's format ("70mm", "IMAX", "Digital"…),
    or None. Several join with " · " ("70mm · IMAX")."""
    labels = [label for rx, label in _FORMAT_LABELS if rx.search(raw or '')]
    return ' · '.join(labels) or None


def normalize_title(title):
    """Casefolded, diacritic-stripped, whitespace-collapsed clean title — the
    key for matching the same film across venues."""
    if not title:
        return ''
    clean, _ = parse_movie_title(title)
    t = unicodedata.normalize('NFKD', clean or title)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    return _WS_RE.sub(' ', t).strip().casefold()[:220]

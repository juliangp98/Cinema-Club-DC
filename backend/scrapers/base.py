"""Shared helpers for all theatre scrapers."""

import datetime
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

# Keywords that mark a program/series label wrapped around the real film title,
# either as a leading "PROGRAM: Title" prefix or a trailing "Title - Program"
# descriptor. Matched case-insensitively as substrings of the label segment.
_SERIES_KEYWORDS = (
    'series', 'presents', 'presented', 'sunday', 'monday', 'tuesday',
    'wednesday', 'thursday', 'friday', 'saturday', 'nights', 'matinee',
    'midnight', 'double feature', 'triple feature', 'festival',
    'retrospective', 'tribute', 'spotlight', 'classics', 'epic',
    'anniversary', 'program', 'fundraiser', 'benefit', 'marathon',
    'showcase', 'special event', 'q&a', 'in concert', 'sing-along',
    'sing along', 'brunch', 'club', 'noir', 'fest',
)

# Format / edition tags venues append, e.g. "The Odyssey (70mm)",
# "Alien (4K Restoration)", "The Odyssey in 35mm". Removed wherever they appear.
_FORMAT_PATTERNS = [
    r'\bin\s+\d{2,3}\s*mm\b', r'\b\d{2,3}\s*mm\b', r'\bimax\b', r'\b4k\b',
    r'\bdcp\b', r'\b3d\b', r'\bdolby(?:\s+(?:atmos|vision|cinema))?\b',
    r'\b(?:new\s+)?(?:digital\s+)?restoration\b', r'\brestored\b',
    r'\bremaster(?:ed)?\b', r'\bre-?release\b', r'\bnew\s+print\b',
    r"\bdirector'?s\s+cut\b", r'\bextended\s+cut\b', r'\buncut\b',
    r'\bunrated\b', r'\b\d+th\s+anniversary\b', r'\banniversary\b',
    r'\bsing[-\s]?along\b', r'\bsubtitled\b',
]

_YEAR_PAREN_RE = re.compile(r'\((\d{4})\)')
_PARENS_RE = re.compile(r'\([^)]*\)')
_FORMAT_RE = re.compile('|'.join(_FORMAT_PATTERNS), re.I)
_DASH_SPLIT_RE = re.compile(r'\s[-–—]\s')
_TRIM_CHARS = ' -–—:·|.'


def _looks_like_series(segment):
    """True when a label segment reads like a program/series name rather than a
    film title (so it's safe to strip)."""
    s = (segment or '').strip().casefold()
    return bool(s) and any(kw in s for kw in _SERIES_KEYWORDS)


def parse_movie_title(raw):
    """Parse a venue's screening label into (clean_title, year_or_None).

    Strips repertory/event cruft so enrichment can find the film:
      "The Odyssey (70mm)"                  -> ("The Odyssey", None)
      "The Odyssey in 35mm"                 -> ("The Odyssey", None)
      "HIS GIRL FRIDAY (1940)"              -> ("HIS GIRL FRIDAY", "1940")
      "EPIC SUNDAY: BATMAN BEGINS"          -> ("BATMAN BEGINS", None)
      "Planes (2013) - NASM 50th Film Series" -> ("Planes", "2013")

    The year is returned separately so enrichment searches on the film's real
    release year, not the venue's re-release date. Only a "(YYYY)" parenthetical
    is treated as a year — standalone digits (e.g. "1917", "2001: A Space
    Odyssey") stay part of the title.
    """
    if not raw:
        return '', None
    t = raw.strip()

    # 1) Release year from a (YYYY) parenthetical only.
    year = None
    m = _YEAR_PAREN_RE.search(t)
    if m:
        y = int(m.group(1))
        if 1900 <= y <= datetime.date.today().year + 1:
            year = str(y)

    # 2) Leading "PROGRAM: Title" prefix, only when the prefix is a series label
    #    (protects real colon titles like "Mission: Impossible").
    if ':' in t:
        head, _, tail = t.partition(':')
        if tail.strip() and _looks_like_series(head):
            t = tail.strip()

    # 3) Trailing " - Series/Program" descriptor.
    parts = _DASH_SPLIT_RE.split(t)
    if len(parts) > 1 and _looks_like_series(parts[-1]):
        t = ' - '.join(parts[:-1])

    # 4) Remove parentheticals (year + format tags) and inline format tokens.
    t = _PARENS_RE.sub(' ', t)
    t = _FORMAT_RE.sub(' ', t)

    t = _WS_RE.sub(' ', t).strip(_TRIM_CHARS).strip()
    if not t:
        t = _WS_RE.sub(' ', raw).strip()
    return t, year


def normalize_title(title):
    """Casefolded, diacritic-stripped, whitespace-collapsed title with venue
    format/edition/series cruft removed — used to match the same film across
    venues (and as an enrichment-search fallback)."""
    if not title:
        return ''
    clean, _ = parse_movie_title(title)
    t = unicodedata.normalize('NFKD', clean or title)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = _WS_RE.sub(' ', t).strip().casefold()
    # If cleaning removed everything, fall back to the raw title.
    if not t:
        t = _WS_RE.sub(' ', title).strip().casefold()
    return t[:220]

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


# Trailing format/edition tags venues append to titles, e.g. "Alien (4K Restoration)".
_PAREN_TAIL_RE = re.compile(r'\s*\((?:[^)]*)\)\s*$')
_WS_RE = re.compile(r'\s+')


def normalize_title(title):
    """Casefolded, diacritic-stripped, whitespace-collapsed title with trailing
    parentheticals removed — used to match the same film across venues."""
    if not title:
        return ''
    t = unicodedata.normalize('NFKD', title)
    t = ''.join(c for c in t if not unicodedata.combining(c))
    t = _PAREN_TAIL_RE.sub('', t)
    t = _WS_RE.sub(' ', t).strip().casefold()
    # If stripping parentheticals removed everything (title was all-parenthetical), keep original
    if not t:
        t = _WS_RE.sub(' ', title).strip().casefold()
    return t[:220]

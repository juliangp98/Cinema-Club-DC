"""National Gallery of Art — free film programs (East Building Auditorium).

nga.gov rejects non-browser TLS fingerprints (curl_cffi Chrome impersonation
passes). The film-programs calendar page links each screening as
/calendar/<series>/<film>?evd=YYYYMMDDHHMM — the evd param IS the local
screening datetime, so only the event pages need fetching for metadata.
Screenings are free; purchase_link points at the event page.
"""

import datetime
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import new_movie_dict, make_showtime

BASE = 'https://www.nga.gov'
LISTING_URL = f'{BASE}/calendar/film-programs.html'
EVD_RE = re.compile(r'href="(/calendar/[^"?]+)\?evd=(\d{12})"')


def _fetch(url):
    from curl_cffi import requests as cffi_requests
    r = cffi_requests.get(url, impersonate='chrome', timeout=25)
    r.raise_for_status()
    return r.text


def scrape_nga():
    """Scrape NGA film programs. Returns list of movie dicts."""
    print("Scraping National Gallery of Art films...")
    movies = []

    try:
        listing = _fetch(LISTING_URL)

        screenings = {}   # event path -> [datetime, ...]
        for path, evd in EVD_RE.findall(listing):
            try:
                start = datetime.datetime.strptime(evd, '%Y%m%d%H%M')
            except ValueError:
                continue
            screenings.setdefault(path, []).append(start)

        for path, starts in screenings.items():
            url = urljoin(BASE, path)
            try:
                soup = BeautifulSoup(_fetch(url), 'html.parser')
                time.sleep(0.5)
            except Exception as e:
                print(f"  Error on NGA event page {url}: {e}")
                continue

            movie = new_movie_dict()
            h1 = soup.find('h1')
            if h1:
                movie['title'] = h1.get_text(strip=True)
            if not movie['title']:
                og = soup.find('meta', property='og:title')
                if og and og.get('content'):
                    movie['title'] = og['content'].strip()
            if not movie['title']:
                continue

            og_desc = soup.find('meta', property='og:description')
            if og_desc and og_desc.get('content'):
                movie['description'] = og_desc['content'].strip()
            og_img = soup.find('meta', property='og:image')
            if og_img and og_img.get('content'):
                movie['poster_url'] = urljoin(BASE, og_img['content'])

            # Runtime if stated, e.g. "(Robert Wise, 1965, 174 minutes)"
            body = soup.get_text(' ', strip=True)
            m_rt = re.search(r'(\d{2,3})\s*minutes', body)
            if m_rt:
                movie['runtime_minutes'] = int(m_rt.group(1))
            m_year = re.search(r'\b(19\d{2}|20\d{2})\b\s*,\s*\d{2,3}\s*minutes', body)
            if m_year:
                movie['release_year'] = m_year.group(1)

            for start in sorted(set(starts)):
                movie['showtimes'].append(make_showtime(
                    start, movie['runtime_minutes'], purchase_link=url))

            movies.append(movie)

    except Exception as e:
        print(f"  ERROR scraping NGA: {e}")

    print(f"  Found {len(movies)} film programs at NGA")
    return movies

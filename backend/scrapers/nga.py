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

from .base import Blocked, finish_scrape, looks_blocked, new_movie_dict, make_showtime, with_retry

BASE = 'https://www.nga.gov'
LISTING_URL = f'{BASE}/calendar/film-programs.html'
EVD_RE = re.compile(r'href="(/calendar/[^"?]+)\?evd=(\d{12})"')


def _fetch(url):
    from curl_cffi import requests as cffi_requests

    def go():
        r = cffi_requests.get(url, impersonate='chrome', timeout=25)
        r.raise_for_status()
        if looks_blocked(r.text):
            raise Blocked('served a bot check instead of the page')
        return r.text

    return with_retry(go, label=url)


def scrape_nga():
    """Scrape NGA film programs. Returns list of movie dicts."""
    print("Scraping National Gallery of Art films...")
    movies = []
    error, skipped = None, 0

    try:
        listing = _fetch(LISTING_URL)

        screenings = {}   # event path -> [datetime, ...]
        for path, evd in EVD_RE.findall(listing):
            try:
                start = datetime.datetime.strptime(evd, '%Y%m%d%H%M')
            except ValueError:
                continue
            screenings.setdefault(path, []).append(start)
        if not screenings and 'c-event-list-item' not in listing:
            raise ValueError("no screenings on the film calendar — has its layout changed?")
        # Each listing item's title, for when its event page can't be had
        listed = {}
        for a in BeautifulSoup(listing, 'html.parser').select('a[href*="?evd="]'):
            heading = a.find(['h5', 'h4', 'h3'])
            if heading:
                listed.setdefault(a['href'].split('?')[0], heading.get_text(' ', strip=True))

        blocked = False
        for path, starts in screenings.items():
            url = urljoin(BASE, path)
            soup = None
            if not blocked:
                try:
                    soup = BeautifulSoup(_fetch(url), 'html.parser')
                    time.sleep(0.5)
                except Blocked as e:
                    blocked = True               # don't keep asking past a bot check this run
                    print(f"  NGA event page {url}: {e}; using the listing for the rest")
                except Exception as e:
                    print(f"  Error on NGA event page {url}: {e}")
            if soup is None:
                if not listed.get(path):
                    skipped += 1
                    continue
                movie = new_movie_dict()         # the listing's title and times; details another run
                movie['title'] = listed[path]
                for start in sorted(set(starts)):
                    movie['showtimes'].append(make_showtime(start, None, purchase_link=url))
                movies.append(movie)
                continue

            movie = new_movie_dict()
            # NGA pages have a "Global Search" <h1> in the site chrome before the
            # real film-title <h1>, so prefer og:title (e.g. "Giant | National
            # Gallery of Art") and fall back to the first non-chrome heading.
            title = ''
            og = soup.find('meta', property='og:title')
            if og and og.get('content'):
                title = og['content'].split('|')[0].strip()
            if not title or title.lower() == 'global search':
                for h in soup.find_all('h1'):
                    t = h.get_text(strip=True)
                    if t and t.lower() != 'global search':
                        title = t
                        break
            if not title:
                skipped += 1
                continue
            movie['title'] = title

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
        error = e
    return finish_scrape('NGA', movies, error, skipped=skipped)

"""Smithsonian IMAX theaters (si.edu) — Lockheed Martin IMAX (Air & Space,
DC) and Airbus IMAX (Udvar-Hazy Center, Chantilly).

si.edu rejects non-browser TLS fingerprints, so pages are fetched with
curl_cffi Chrome impersonation. Each theater page lists film teasers; each
movie page (/theaters/movie/<slug> or /imax/movie/<slug>) renders the full
showtime calendar for BOTH venues as .c-showtime date sections containing
per-venue .c-showtime__inner-wrap blocks. Movie pages are fetched once per
process and shared between the two registry entries.
"""

import datetime
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import new_movie_dict, parse_ampm_time, make_showtime, with_retry

BASE = 'https://www.si.edu'
MOVIE_HREF_RE = re.compile(r'/(?:theaters|imax)/movie/[a-z0-9-]+$', re.I)

_page_cache = {}


def _fetch(url):
    if url not in _page_cache:
        from curl_cffi import requests as cffi_requests

        def go():
            r = cffi_requests.get(url, impersonate='chrome', timeout=25)
            r.raise_for_status()
            return r.text

        _page_cache[url] = with_retry(go, label=url)
        time.sleep(0.5)
    return _page_cache[url]


def scrape_smithsonian(theater_slug):
    """Scrape one Smithsonian theater ('lockheedmartin' or 'airbus')."""
    print(f"Scraping Smithsonian IMAX ({theater_slug})...")
    movies = []

    try:
        theater_html = _fetch(f'{BASE}/theaters/{theater_slug}')
        soup = BeautifulSoup(theater_html, 'html.parser')

        movie_urls = []
        for a in soup.find_all('a', href=True):
            href = a['href'].split('?')[0]
            if MOVIE_HREF_RE.search(href):
                url = urljoin(BASE, href)
                if url not in movie_urls:
                    movie_urls.append(url)

        for url in movie_urls:
            try:
                movie = _scrape_movie_page(url, theater_slug)
                if movie and movie['showtimes']:
                    movies.append(movie)
            except Exception as e:
                print(f"  Error on SI movie page {url}: {e}")

    except Exception as e:
        print(f"  ERROR scraping Smithsonian {theater_slug}: {e}")

    print(f"  Found {len(movies)} movies at Smithsonian {theater_slug}")
    return movies


def _scrape_movie_page(url, theater_slug):
    html = _fetch(url)
    soup = BeautifulSoup(html, 'html.parser')

    movie = new_movie_dict()

    h1 = soup.find('h1')
    if h1:
        movie['title'] = h1.get_text(strip=True)
    if not movie['title']:
        og = soup.find('meta', property='og:title')
        if og and og.get('content'):
            movie['title'] = og['content'].strip()
    if not movie['title']:
        return None

    og_img = soup.find('meta', property='og:image')
    if og_img and og_img.get('content'):
        movie['poster_url'] = urljoin(BASE, og_img['content'])
    og_desc = soup.find('meta', property='og:description')
    if og_desc and og_desc.get('content'):
        movie['description'] = og_desc['content'].strip()

    # Runtime, e.g. "Running Time: 43 minutes" somewhere in body text
    m_rt = re.search(r'Running Time:?\s*(\d+)\s*min', soup.get_text(' ', strip=True), re.I)
    if m_rt:
        movie['runtime_minutes'] = int(m_rt.group(1))

    venue_href = f'/theaters/{theater_slug}'
    for section in soup.select('.c-showtime'):
        time_tag = section.select_one('.c-showtime__date time[datetime]')
        if not time_tag:
            continue
        try:
            date_obj = datetime.date.fromisoformat(time_tag['datetime'][:10])
        except ValueError:
            continue

        for wrap in section.select('.c-showtime__inner-wrap'):
            name_link = wrap.select_one('.c-showtime__name-link')
            if not name_link or venue_href not in (name_link.get('href') or ''):
                continue
            for li in wrap.select('.c-showtime__times li'):
                hm = parse_ampm_time(li.get_text(strip=True))
                if not hm:
                    continue
                start = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, hm[0], hm[1])
                classes = ' '.join(li.get('class', []))
                sold_out = 'sold' in classes.lower() or 'sold out' in li.get_text().lower()
                link = li.find('a', href=True)
                movie['showtimes'].append(make_showtime(
                    start, movie['runtime_minutes'],
                    purchase_link=urljoin(BASE, link['href']) if link else url,
                    is_sold_out=sold_out))

    return movie

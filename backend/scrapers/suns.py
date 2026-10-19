"""Suns Cinema — static HTML on sunscinema.com."""

import datetime
import html
import re
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from .base import BOT_UA, finish_scrape, get_json, get_soup, new_movie_dict, parse_ampm_time, make_showtime

SHOWS_API = 'https://sunscinema.com/wp-json/nj/v1/show'
ET = ZoneInfo('America/New_York')


def scrape_suns():
    """Scrape Suns Cinema upcoming films. Returns list of movie dicts."""
    print("Scraping Suns Cinema...")
    movies = []
    error = None

    try:
        soup = get_soup('https://sunscinema.com/upcoming-films-3/')
        containers = soup.find_all('div', class_='showtimes-description')
        if not containers:
            raise ValueError("no films on the upcoming page — has its layout changed?")

        for container in containers:
            movie = new_movie_dict()

            title_tag = container.find('h2', class_='show-title')
            if title_tag:
                movie['title'] = title_tag.get_text(strip=True)

            def find_field(label):
                tag = container.find('span', string=lambda t: t and label in t)
                if tag and tag.next_sibling:
                    return str(tag.next_sibling).strip()
                return ''

            movie['director'] = find_field('Director:')
            movie['release_year'] = find_field('Release Year:')

            runtime_raw = find_field('Run Time:')
            if runtime_raw:
                m = re.search(r'\d+', runtime_raw)
                if m:
                    movie['runtime_minutes'] = int(m.group())

            starring_tag = container.find('p', class_='starring')
            if starring_tag:
                movie['starring'] = starring_tag.get_text(strip=True).replace('Starring:', '').strip()

            trailer_tag = container.find('a', class_='show-trailer-modal')
            if trailer_tag and 'data-trailer' in trailer_tag.attrs:
                url_match = re.search(r'src=[\'"]?([^\'" >]+)', trailer_tag['data-trailer'])
                if url_match:
                    movie['trailer_link'] = url_match.group(1)

            # Poster — in sibling div.show-poster under shared parent
            show_details = container.find_parent('div', class_='show-details')
            if show_details:
                poster_div = show_details.find('div', class_='show-poster')
                if poster_div:
                    img_tag = poster_div.find('img')
                    if img_tag and img_tag.get('src'):
                        movie['poster_url'] = img_tag['src']

            # Description — in div.show-description within this container
            desc_tag = container.find('div', class_='show-description')
            if desc_tag:
                movie['description'] = desc_tag.get_text(separator=' ', strip=True)

            # Showtimes — from li[data-date] elements with a.showtime or span.showtime
            for li in container.find_all('li', attrs={'data-date': True}):
                try:
                    epoch = int(li['data-date'])
                    st_tag = li.find(['a', 'span'], class_='showtime')
                    if not st_tag:
                        continue

                    # The time ("6:00 pm") is the tag's own text; a sold-out
                    # one adds <span class="extra">Sold Out</span> after it.
                    time_text = st_tag.find(string=True, recursive=False) or st_tag.get_text(' ', strip=True)
                    time_text = re.sub(r'(?i)sold\s*out', '', time_text).strip()

                    # Date from the epoch (in DC, whatever the server's clock), time from the text
                    date_obj = datetime.datetime.fromtimestamp(epoch, ET).date()
                    hm = parse_ampm_time(time_text)
                    if not hm:
                        continue
                    start = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, hm[0], hm[1])

                    is_sold_out = 'sold-out' in st_tag.get('class', [])
                    purchase_link = st_tag.get('href', '')     # a sold-out <span> keeps its href too

                    movie['showtimes'].append(make_showtime(
                        start, movie['runtime_minutes'],
                        purchase_link=purchase_link, is_sold_out=is_sold_out))
                except (ValueError, TypeError):
                    continue

            if movie['title']:
                movies.append(movie)

    except Exception as e:
        error = e
    return finish_scrape('Suns Cinema', movies, error)


def scrape_suns_announced(pages=2):
    """Films Suns has posted with a date (R8b). Suns posts a film about a week
    before its showtimes and ticket links appear; sync_announced keeps the
    ones that aren't on sale yet. Undated posts are skipped (placeholders)."""
    session = requests.Session()
    session.headers['User-Agent'] = BOT_UA
    out = []
    for page in range(1, pages + 1):             # newest posts first; 100 a page covers months
        posts = get_json(session, SHOWS_API, params={'per_page': 100, 'page': page}) or []
        for p in posts:
            stamp = str(p.get('_start_date') or '')
            if p.get('status') != 'publish' or not stamp.isdigit():
                continue
            m = new_movie_dict()
            m['title'] = html.unescape(re.sub(r'<[^>]+>', '', (p.get('title') or {}).get('rendered', ''))).strip()
            m['announced_for'] = datetime.datetime.fromtimestamp(int(stamp), ET).date()
            m['url'] = p.get('link') or ''
            m['tmdb_id'] = int(p['_tmdb_id']) if str(p.get('_tmdb_id') or '').isdigit() else None
            m['release_year'] = (p.get('_release_date') or '')[:4]
            if str(p.get('_length') or '').isdigit():
                m['runtime_minutes'] = int(p['_length'])
            m['director'] = ', '.join(d['name'] for d in p.get('director') or [] if isinstance(d, dict) and d.get('name'))
            m['starring'] = ', '.join(c['name'] for c in (p.get('cast') or [])[:5] if isinstance(c, dict) and c.get('name'))
            m['poster_url'] = p.get('featured_media_url') or ''
            text = BeautifulSoup((p.get('content') or {}).get('rendered', ''), 'html.parser').get_text()
            m['description'] = re.sub(r'\s+', ' ', text).strip()[:2000]
            if m['title']:
                out.append(m)
        if len(posts) < 100:
            break
    print(f"  Found {len(out)} dated film posts at Suns Cinema")
    return out

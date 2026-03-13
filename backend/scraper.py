"""
Cinema Club Scraper
Scrapes Suns Cinema, AFI Silver Theatre, and E Street Cinema / Landmark.
Run on a cron job: 0 */6 * * * python scraper.py
"""

import requests
import re
import json
import datetime
import time
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import sys
import os

# Add parent dir for DB access when running standalone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ─── Helpers ──────────────────────────────────────────────────────────────────

def get_soup(url, timeout=15, retries=3):
    headers = {'User-Agent': 'Mozilla/5.0 (compatible; CinemaClubBot/1.0)'}
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            r.raise_for_status()
            return BeautifulSoup(r.text, 'html.parser')
        except (requests.ConnectionError, requests.Timeout) as e:
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


# ─── Suns Cinema ──────────────────────────────────────────────────────────────

def scrape_suns():
    """Scrape Suns Cinema upcoming films. Returns list of movie dicts."""
    print("Scraping Suns Cinema...")
    movies = []

    try:
        soup = get_soup('https://sunscinema.com/upcoming-films-3/')
        containers = soup.find_all('div', class_='showtimes-description')

        for container in containers:
            movie = {
                'title': '', 'director': '', 'release_year': '',
                'runtime_minutes': 120, 'starring': '', 'description': '',
                'trailer_link': '', 'showtimes': [], 'poster_url': ''
            }

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

                    # Parse time text (e.g. "6:00 pm")
                    time_text = st_tag.find(string=True, recursive=False)
                    if not time_text:
                        time_text = st_tag.get_text(strip=True)
                    time_text = time_text.strip().rstrip('Sold Out').strip()

                    # Build datetime: date from epoch + time from text
                    date_obj = datetime.date.fromtimestamp(epoch)
                    time_match = re.match(r'(\d{1,2}):(\d{2})\s*(am|pm)', time_text, re.I)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = int(time_match.group(2))
                        ampm = time_match.group(3).lower()
                        if ampm == 'pm' and hour != 12:
                            hour += 12
                        elif ampm == 'am' and hour == 12:
                            hour = 0
                        start = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, hour, minute)
                    else:
                        continue

                    end = start + datetime.timedelta(minutes=movie['runtime_minutes'] + 20)
                    is_sold_out = 'sold-out' in st_tag.get('class', [])
                    purchase_link = st_tag.get('href', '') if st_tag.name == 'a' else ''

                    movie['showtimes'].append({
                        'start_time': start,
                        'end_time': end,
                        'purchase_link': purchase_link,
                        'is_sold_out': is_sold_out
                    })
                except (ValueError, TypeError):
                    continue

            if movie['title']:
                movies.append(movie)

    except Exception as e:
        print(f"  ERROR scraping Suns: {e}")

    print(f"  Found {len(movies)} movies at Suns Cinema")
    return movies


# ─── AFI Silver Theatre ───────────────────────────────────────────────────────

def scrape_afi():
    """Scrape AFI Silver Theatre. Returns list of movie dicts."""
    print("Scraping AFI Silver Theatre...")
    movies = []

    base_url = 'https://silver.afi.com'

    try:
        # Discover films from the \"Films by Title\" page, which links to
        # canonical detail pages under /movies/detail/ID.
        soup = get_soup(f'{base_url}/now-playing/')

        film_links = set()
        for a in soup.find_all('a', href=True):
            href = a['href']
            if 'movies/detail/' in href:
                film_links.add(urljoin(base_url, href))

        # Process all discovered film pages (with a generous safety cap).
        for link in sorted(film_links)[:100]:
            try:
                film_soup = get_soup(link)
                movie = {
                    'title': '', 'director': '', 'release_year': '',
                    'runtime_minutes': 120, 'starring': '', 'description': '',
                    'trailer_link': '', 'showtimes': [], 'poster_url': ''
                }

                full_text = film_soup.get_text(' ', strip=True)

                # Title
                h1 = film_soup.find('h1')
                if h1:
                    movie['title'] = h1.get_text(strip=True)

                # Description – first substantial paragraph after the title.
                if h1:
                    for sib in h1.find_all_next():
                        if sib.name == 'p':
                            desc_text = sib.get_text(' ', strip=True)
                            if len(desc_text) > 40:
                                movie['description'] = desc_text
                                break

                # Runtime
                m_rt = re.search(r'Run Time:\s*(\d+)\s+Minutes', full_text, re.I)
                if m_rt:
                    try:
                        movie['runtime_minutes'] = int(m_rt.group(1))
                    except ValueError:
                        pass

                # Release year – best-effort from country/year line.
                m_year = re.search(r',\s*(\d{4})\s*,\s*color', full_text)
                if m_year:
                    movie['release_year'] = m_year.group(1)

                # Trailer link – look for a link mentioning \"Trailer\".
                trailer_tag = film_soup.find('a', string=re.compile(r'Trailer', re.I))
                if trailer_tag and trailer_tag.get('href') and not trailer_tag['href'].startswith('javascript'):
                    movie['trailer_link'] = urljoin(base_url, trailer_tag['href'])

                # Poster image – first reasonably prominent image on the page.
                poster = film_soup.find('img', class_=re.compile(r'poster|film.?image', re.I)) or film_soup.find('img')
                if poster and poster.get('src'):
                    movie['poster_url'] = urljoin(base_url, poster['src'])

                # Showtimes – each day is a div.show_wrap with a <p> date
                # and <a class="select_show"> time links.
                showtimes = []
                for wrap in film_soup.find_all('div', class_='show_wrap'):
                    date_p = wrap.find('p')
                    if not date_p:
                        continue
                    date_text = date_p.get_text(strip=True)
                    try:
                        current_date = datetime.datetime.strptime(date_text, '%A, %B %d, %Y').date()
                    except ValueError:
                        continue

                    for a_tag in wrap.find_all('a', class_='select_show'):
                        t_text = a_tag.get_text(' ', strip=True)
                        m_time = re.match(r'(\d{1,2}):(\d{2})\s*(a\.m\.|p\.m\.|am|pm)', t_text, re.I)
                        if not m_time:
                            continue
                        hour = int(m_time.group(1))
                        minute = int(m_time.group(2))
                        ampm = m_time.group(3).lower()
                        if ampm in ('pm', 'p.m.') and hour != 12:
                            hour += 12
                        elif ampm in ('am', 'a.m.') and hour == 12:
                            hour = 0

                        start = datetime.datetime(
                            current_date.year, current_date.month, current_date.day, hour, minute
                        )
                        runtime = movie['runtime_minutes'] or 120
                        end = start + datetime.timedelta(minutes=runtime + 20)

                        showtimes.append({
                            'start_time': start,
                            'end_time': end,
                            'purchase_link': link,
                            'is_sold_out': False,
                        })

                movie['showtimes'] = showtimes

                if movie['title'] and movie['showtimes']:
                    movies.append(movie)
                time.sleep(0.5)

            except Exception as e:
                print(f"  Error on AFI film page {link}: {e}")

    except Exception as e:
        print(f"  ERROR scraping AFI: {e}")

    print(f"  Found {len(movies)} movies at AFI Silver")
    return movies


# ─── DB Sync ──────────────────────────────────────────────────────────────────

def sync_to_db(theatre_slug, scraped_movies):
    """Upsert scraped movies + showtimes into the database."""
    from app import app, db, Theatre, Movie, Showtime

    with app.app_context():
        theatre = Theatre.query.filter_by(slug=theatre_slug).first()
        if not theatre:
            print(f"  Theatre '{theatre_slug}' not found in DB. Run app.py first to seed theatres.")
            return

        for m in scraped_movies:
            if not m.get('title'):
                continue

            # Upsert movie
            movie = Movie.query.filter_by(title=m['title']).first()
            if not movie:
                movie = Movie(title=m['title'])
                db.session.add(movie)

            movie.director = m.get('director') or movie.director
            movie.release_year = m.get('release_year') or movie.release_year
            movie.runtime_minutes = m.get('runtime_minutes') or movie.runtime_minutes or 120
            movie.starring = m.get('starring') or movie.starring
            movie.description = m.get('description') or movie.description
            movie.trailer_link = m.get('trailer_link') or movie.trailer_link
            movie.poster_url = m.get('poster_url') or movie.poster_url
            movie.last_updated = datetime.datetime.utcnow()
            db.session.flush()

            # Upsert showtimes
            for st in m.get('showtimes', []):
                start = st['start_time']
                existing = Showtime.query.filter_by(
                    movie_id=movie.id,
                    theatre_id=theatre.id,
                    start_time=start
                ).first()
                if not existing:
                    showtime = Showtime(
                        movie_id=movie.id,
                        theatre_id=theatre.id,
                        start_time=start,
                        end_time=st.get('end_time'),
                        purchase_link=st.get('purchase_link'),
                        is_sold_out=st.get('is_sold_out', False)
                    )
                    db.session.add(showtime)
                else:
                    existing.is_sold_out = st.get('is_sold_out', False)
                    existing.purchase_link = st.get('purchase_link') or existing.purchase_link

        db.session.commit()
        print(f"  Synced {len(scraped_movies)} movies for {theatre_slug}")


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("=" * 50)
    print("Cinema Club Scraper")
    print("=" * 50)

    suns_movies = scrape_suns()
    afi_movies = scrape_afi()

    print("\nSyncing to database...")
    sync_to_db('suns', suns_movies)
    sync_to_db('afi', afi_movies)

    print("\nDone!")

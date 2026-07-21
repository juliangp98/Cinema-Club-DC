"""AFI Silver Theatre — two-stage HTML crawl of silver.afi.com."""

import datetime
import re
import time
from urllib.parse import urljoin

from .base import get_soup, new_movie_dict, parse_ampm_time, make_showtime


def scrape_afi():
    """Scrape AFI Silver Theatre. Returns list of movie dicts."""
    print("Scraping AFI Silver Theatre...")
    movies = []

    base_url = 'https://silver.afi.com'

    try:
        # Discover films from the "Now Playing" page, which links to
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
                movie = new_movie_dict()

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

                # Trailer link – look for a link mentioning "Trailer".
                trailer_tag = film_soup.find('a', string=re.compile(r'Trailer', re.I))
                if trailer_tag and trailer_tag.get('href') and not trailer_tag['href'].startswith('javascript'):
                    movie['trailer_link'] = urljoin(base_url, trailer_tag['href'])

                # Poster image – look for the FilmPosterGraphic from vista CDN.
                poster = film_soup.find('img', src=re.compile(r'FilmPosterGraphic', re.I))
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
                        hm = parse_ampm_time(t_text)
                        if not hm:
                            continue
                        start = datetime.datetime(
                            current_date.year, current_date.month, current_date.day, hm[0], hm[1]
                        )
                        showtimes.append(make_showtime(
                            start, movie['runtime_minutes'], purchase_link=link))

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

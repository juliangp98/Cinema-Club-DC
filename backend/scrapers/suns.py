"""Suns Cinema — static HTML on sunscinema.com."""

import datetime
import re

from .base import get_soup, new_movie_dict, parse_ampm_time, make_showtime


def scrape_suns():
    """Scrape Suns Cinema upcoming films. Returns list of movie dicts."""
    print("Scraping Suns Cinema...")
    movies = []

    try:
        soup = get_soup('https://sunscinema.com/upcoming-films-3/')
        containers = soup.find_all('div', class_='showtimes-description')

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

                    # Parse time text (e.g. "6:00 pm")
                    time_text = st_tag.find(string=True, recursive=False)
                    if not time_text:
                        time_text = st_tag.get_text(strip=True)
                    time_text = time_text.strip().rstrip('Sold Out').strip()

                    # Build datetime: date from epoch + time from text
                    date_obj = datetime.date.fromtimestamp(epoch)
                    hm = parse_ampm_time(time_text)
                    if not hm:
                        continue
                    start = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, hm[0], hm[1])

                    is_sold_out = 'sold-out' in st_tag.get('class', [])
                    purchase_link = st_tag.get('href', '') if st_tag.name == 'a' else ''

                    movie['showtimes'].append(make_showtime(
                        start, movie['runtime_minutes'],
                        purchase_link=purchase_link, is_sold_out=is_sold_out))
                except (ValueError, TypeError):
                    continue

            if movie['title']:
                movies.append(movie)

    except Exception as e:
        print(f"  ERROR scraping Suns: {e}")

    print(f"  Found {len(movies)} movies at Suns Cinema")
    return movies

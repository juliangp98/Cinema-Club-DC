"""Avalon Theatre (Chevy Chase DC) — Agile Ticketing public JSON feed.

The feed (updated every 10 min) returns ArrayOfShows[] with metadata,
CustomProperties (Release Year, Rating, Director), EventImage, and
CurrentShowings[] carrying ISO start/end, a direct per-showing purchase
link, SalesState, and Venue (Avalon 1/2 — same building).
"""

import datetime

from .base import browser_session, get_json, new_movie_dict

FEED_URL = ('https://prod5.agileticketing.net/websales/feed.ashx'
            '?guid=ebe3acab-05c7-4109-9a69-78d1846b26af&showslist=true&format=json')


def _prop_values(show, name):
    return [p.get('Value', '') for p in show.get('CustomProperties', [])
            if p.get('Name') == name and p.get('Value')]


def scrape_avalon():
    """Scrape the Avalon Theatre. Returns list of movie dicts."""
    print("Scraping Avalon Theatre...")
    movies = []

    try:
        session = browser_session()
        data = get_json(session, FEED_URL, timeout=20)

        for show in data.get('ArrayOfShows', []):
            title = (show.get('Name') or '').strip()
            if not title:
                continue

            movie = new_movie_dict()
            movie['title'] = title
            movie['description'] = show.get('ShortDescription') or ''
            movie['poster_url'] = show.get('EventImage') or ''
            try:
                movie['runtime_minutes'] = int(show.get('Duration') or 0) or 120
            except (TypeError, ValueError):
                pass
            years = _prop_values(show, 'Release Year')
            if years:
                movie['release_year'] = years[0]
            directors = _prop_values(show, 'Director')
            if directors:
                movie['director'] = ', '.join(directors)

            for showing in show.get('CurrentShowings', []):
                if showing.get('DateTBD'):
                    continue
                if showing.get('ContentDelivery') and showing['ContentDelivery'] != 'InPerson':
                    continue
                try:
                    start = datetime.datetime.fromisoformat(showing['StartDate'])
                except (KeyError, ValueError):
                    continue
                try:
                    end = datetime.datetime.fromisoformat(showing['EndDate'])
                except (KeyError, ValueError):
                    end = start + datetime.timedelta(minutes=movie['runtime_minutes'] + 20)

                sales_state = (showing.get('SalesState') or '').lower()
                movie['showtimes'].append({
                    'start_time': start,
                    'end_time': end,
                    'purchase_link': showing.get('LegacyPurchaseLink')
                                     or show.get('InfoLink') or '',
                    'is_sold_out': 'sold' in sales_state,
                })

            if movie['showtimes']:
                movies.append(movie)

    except Exception as e:
        print(f"  ERROR scraping Avalon: {e}")

    print(f"  Found {len(movies)} movies at Avalon Theatre")
    return movies

"""Alamo Drafthouse — public JSON schedule feed.

One market feed covers multiple cinemas; the registry has one entry per
cinema (DC Bryant Street + Crystal City, both in the 'dc-metro-area'
market). The feed is fetched once per market per process.

Feed shape (data.*): presentations[] {slug, show{title, posterImages,
headline, certification}}, sessions[] {cinemaId, presentationSlug,
showTimeClt (local ET ISO), status}, market[0].cinemas[] {id, slug, name}.
"""

import datetime

from .base import browser_session, get_json, new_movie_dict, make_showtime

MARKET_FEED = 'https://drafthouse.com/s/mother/v2/schedule/market/{market}'

_feed_cache = {}


def _market_feed(market_slug):
    if market_slug not in _feed_cache:
        session = browser_session()
        _feed_cache[market_slug] = get_json(session, MARKET_FEED.format(market=market_slug))
    return _feed_cache[market_slug]


def scrape_alamo(market_slug, cinema_slug):
    """Scrape one Alamo cinema out of a market feed. Returns list of movie dicts."""
    print(f"Scraping Alamo Drafthouse ({cinema_slug})...")
    movies = []

    try:
        data = _market_feed(market_slug).get('data', {})

        cinema_id = None
        for market in data.get('market', []):
            for cinema in market.get('cinemas', []):
                if cinema.get('slug') == cinema_slug:
                    cinema_id = cinema.get('id')
        if not cinema_id:
            raise ValueError(f"cinema '{cinema_slug}' not found in market '{market_slug}'")

        shows = {}
        for p in data.get('presentations', []):
            show = p.get('show') or {}
            if p.get('slug') and show.get('title'):
                shows[p['slug']] = show

        by_presentation = {}
        for s in data.get('sessions', []):
            if s.get('cinemaId') != cinema_id:
                continue
            slug = s.get('presentationSlug')
            if slug not in shows:
                continue
            try:
                start = datetime.datetime.fromisoformat(s['showTimeClt'])
            except (KeyError, ValueError):
                continue
            by_presentation.setdefault(slug, []).append((start, s))

        for slug, sessions in by_presentation.items():
            show = shows[slug]
            movie = new_movie_dict()
            movie['title'] = show['title']
            movie['description'] = show.get('headline') or ''
            posters = show.get('posterImages') or []
            if posters and posters[0].get('uri'):
                movie['poster_url'] = posters[0]['uri']

            page = f"https://drafthouse.com/{market_slug}/show/{slug}"
            for start, s in sessions:
                movie['showtimes'].append(make_showtime(
                    start, movie['runtime_minutes'],
                    purchase_link=page,
                    is_sold_out=(s.get('status') == 'SOLDOUT')))

            movies.append(movie)

    except Exception as e:
        print(f"  ERROR scraping Alamo {cinema_slug}: {e}")

    print(f"  Found {len(movies)} movies at Alamo {cinema_slug}")
    return movies

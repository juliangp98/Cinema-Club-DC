"""
Cinema Club Scraper — thin runner over the scrapers/ package.
Run on a cron job: 0 */6 * * * python scraper.py

Usage:
    python scraper.py                     # scrape every enabled venue
    python scraper.py --only suns,afi     # scrape specific venues (even if disabled)
    python scraper.py --list              # list registered venues
    python scraper.py --emit-test-event [slug]   # synthetic new_drop event (bot testing)
"""

import argparse
import sys
import os

# Add parent dir for DB access when running standalone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers import THEATRE_REGISTRY, get_config, enabled_configs
from scrapers.sync import sync_to_db, record_scrape_error


def run(configs):
    for cfg in configs:
        try:
            movies = cfg.scrape()
        except Exception as e:
            print(f"  ERROR scraping {cfg.slug}: {e}")
            try:
                record_scrape_error(cfg, e)
            except Exception as db_err:
                print(f"  (also failed to record error for {cfg.slug}: {db_err})")
            continue

        try:
            sync_to_db(cfg, movies)
        except Exception as e:
            print(f"  ERROR syncing {cfg.slug}: {e}")
            try:
                record_scrape_error(cfg, e)
            except Exception as db_err:
                print(f"  (also failed to record error for {cfg.slug}: {db_err})")


def emit_test_event(slug):
    """Insert a synthetic new_drop ScrapeEvent so the Discord bot can be tested."""
    import json
    import datetime
    from app import app, db, Theatre, ScrapeEvent

    with app.app_context():
        theatre = Theatre.query.filter_by(slug=slug).first()
        if not theatre:
            print(f"Theatre '{slug}' not found — run app.py once to seed theatres.")
            return
        now = datetime.datetime.now()
        payload = {
            'theatre_slug': slug,
            'theatre_name': theatre.name,
            'new_showtime_count': 23,
            'new_movie_count': 6,
            'cancelled_count': 0,
            'date_min': now.isoformat(),
            'date_max': (now + datetime.timedelta(days=30)).isoformat(),
            'movie_ids': [],
            'movie_summaries': [
                {'movie_id': 0, 'title': 'Test Drop: The Movie', 'poster_url': '',
                 'first_showtime': now.isoformat(), 'showtime_count': 23},
            ],
            'first_scrape': False,
            'test': True,
        }
        db.session.add(ScrapeEvent(theatre_id=theatre.id, event_type='new_drop',
                                   payload_json=json.dumps(payload)))
        db.session.commit()
        print(f"Emitted synthetic new_drop event for '{slug}'.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Cinema Club scraper')
    parser.add_argument('--only', help='comma-separated venue slugs to scrape')
    parser.add_argument('--list', action='store_true', help='list registered venues')
    parser.add_argument('--emit-test-event', nargs='?', const='suns', metavar='SLUG',
                        help='insert a synthetic new_drop event (default slug: suns)')
    args = parser.parse_args()

    if args.list:
        for cfg in THEATRE_REGISTRY:
            state = 'enabled' if cfg.enabled else 'DISABLED'
            print(f"  {cfg.slug:16s} {cfg.name:34s} [{state}]")
        sys.exit(0)

    if args.emit_test_event:
        emit_test_event(args.emit_test_event)
        sys.exit(0)

    print("=" * 50)
    print("Cinema Club Scraper")
    print("=" * 50)

    if args.only:
        slugs = [s.strip() for s in args.only.split(',') if s.strip()]
        configs = []
        for slug in slugs:
            cfg = get_config(slug)
            if not cfg:
                print(f"Unknown venue slug: {slug}")
                sys.exit(1)
            configs.append(cfg)
    else:
        configs = enabled_configs()

    run(configs)
    print("\nDone!")

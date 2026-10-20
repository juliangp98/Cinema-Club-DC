"""
Cinema Club Scraper — thin runner over the scrapers/ package.
Run on a cron job: 0 */6 * * * python scraper.py

Usage:
    python scraper.py                     # scrape every enabled venue
    python scraper.py --only suns,afi     # scrape specific venues (even if disabled)
    python scraper.py --city dc           # one city's venues (its own schedule)
    python scraper.py --list              # list registered venues
    python scraper.py --emit-test-event [slug]   # synthetic new_drop event (bot testing)
"""

import argparse
import sys
import os

# Add parent dir for DB access when running standalone
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scrapers import THEATRE_REGISTRY, get_config, enabled_configs
from scrapers.sync import sync_to_db, sync_announced, record_scrape_error


# What a theatre's `needs` checks before a run (scrapers/__init__.py).
def _checks():
    from scrapers import amc
    return {'amc': amc.key_check}


def ready(configs):
    """The configs whose service works, checking each service once; the rest
    are hidden until it does (one error recorded per service — one owner DM a
    day, not one per theatre)."""
    from scrapers.sync import set_service_ready
    out, checks = [c for c in configs if not c.needs], _checks()
    for need in dict.fromkeys(c.needs for c in configs if c.needs):
        group = [c for c in configs if c.needs == need]
        ok, why = checks[need](group[0].scrape.args[0])
        set_service_ready(need, ok)
        if ok:
            out += group
            continue
        print(f"  {need}: {why}")
        try:
            record_scrape_error(group[0], RuntimeError(why))
        except Exception as db_err:
            print(f"  (also failed to record error for {need}: {db_err})")
    return [c for c in configs if c in out]


def run(configs):
    configs = ready(configs)
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
            continue

        if cfg.announced:                  # films announced before tickets (R8b)
            try:
                sync_announced(cfg, cfg.announced())
            except Exception as e:
                print(f"  ERROR reading {cfg.slug}'s announced films: {e}")


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
        import places
        now = places.now_at(theatre)
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
    parser.add_argument('--city', help="one city's venues (cities.py), e.g. --city dc")
    parser.add_argument('--list', action='store_true', help='list registered venues')
    parser.add_argument('--emit-test-event', nargs='?', const='suns', metavar='SLUG',
                        help='insert a synthetic new_drop event (default slug: suns)')
    args = parser.parse_args()

    if args.list:
        for cfg in THEATRE_REGISTRY:
            state = ('enabled' if cfg.enabled else 'DISABLED') + (f', needs {cfg.needs}' if cfg.needs else '')
            print(f"  {cfg.slug:20s} {cfg.name:34s} {cfg.city:10s} [{state}]")
        sys.exit(0)

    if args.emit_test_event:
        emit_test_event(args.emit_test_event)
        sys.exit(0)

    print("=" * 50)
    print("Cinema Club Scraper")
    print("=" * 50)
    from app import prepare_db
    prepare_db()                          # a database the new code hasn't started on yet: migrate it first

    if args.only:
        slugs = [s.strip() for s in args.only.split(',') if s.strip()]
        configs = []
        for slug in slugs:
            cfg = get_config(slug)
            if not cfg:
                print(f"Unknown venue slug: {slug}")
                sys.exit(1)
            configs.append(cfg)
    elif args.city:
        import cities
        if not cities.get(args.city):
            print(f"Unknown city: {args.city} (cities.py has {', '.join(c.slug for c in cities.CITIES)})")
            sys.exit(1)
        configs = [cfg for cfg in enabled_configs() if cfg.city == args.city]
    else:
        configs = enabled_configs()

    run(configs)
    try:                                   # films newly fitting someone's saved search (R10a)
        import notify
        print(f"Saved-search alerts: {notify.alert_saved_searches()}")
    except Exception as e:
        print(f"  ERROR checking saved searches: {e}")
    try:                                   # connected Letterboxd diaries that are due (R10f)
        import letterboxd
        print(f"Letterboxd diaries read: {letterboxd.sync_due()}")
    except Exception as e:
        print(f"  ERROR reading Letterboxd diaries: {e}")
    try:                                   # trivia's TMDB film pool, weekly (R15)
        import film_pool
        n = film_pool.refresh_if_due()
        if n is not None:
            print(f"Trivia film pool refreshed: {n} films")
    except Exception as e:
        print(f"  ERROR refreshing the trivia film pool: {e}")
    try:                                   # the club games' posts and notices (R14)
        import game_posts
        print(f"Game posts checked for {game_posts.tick()} club(s)")
    except Exception as e:
        print(f"  ERROR checking game posts: {e}")
    try:                                   # Monday's digest on the site, if it's due
        import digest
        published = digest.publish_due()
        if published:
            print(f"Digest published for {published} club(s)")
    except Exception as e:
        print(f"  ERROR publishing the digest: {e}")
    try:                                   # this run's alerts go out together (R8)
        import notify
        print(f"Alert emails sent: {notify.release()}")
    except Exception as e:
        print(f"  ERROR releasing alerts: {e}")
    print("\nDone!")

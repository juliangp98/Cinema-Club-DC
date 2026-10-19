"""Phase 8 sync rules: a show gone from a venue's site is off sale (likely
sold out), never cancelled; a partial run takes nothing off sale; a show
listed twice is one show; end times follow the film; announced films stop
saying "Coming soon" once their tickets came up. No network."""
import datetime

import pytest

from helpers import setup_db

NOW = datetime.datetime.now().replace(second=0, microsecond=0)


@pytest.fixture
def suns(monkeypatch):
    """Suns, seeded, with nothing enriched (no TMDB)."""
    import enrich
    from app import app, seed_theatres, Theatre
    setup_db()
    monkeypatch.setattr(enrich, 'enrich_movie', lambda *a, **k: None)
    with app.app_context():
        seed_theatres()
        return Theatre.query.filter_by(slug='suns').first().id


def cfg():
    from scrapers import get_config
    return get_config('suns')


def film(title, *starts, sold=(), **extra):
    return {'title': title, 'runtime_minutes': extra.pop('runtime', 100), **extra,
            'showtimes': [{'start_time': t, 'end_time': None if extra.get('no_end') else t + datetime.timedelta(minutes=120),
                           'purchase_link': 'https://example.test/t', 'is_sold_out': t in sold} for t in starts]}


def sync(movies):
    from scrapers.sync import sync_to_db
    return sync_to_db(cfg(), movies)


def rows(title):
    from app import app, Showtime, Movie
    with app.app_context():
        m = Movie.query.filter_by(title=title).first()
        return [dict(start=s.start_time, sold=s.is_sold_out, off=bool(s.off_sale_at), cancelled=bool(s.is_cancelled),
                     end=s.end_time, id=s.id)
                for s in Showtime.query.filter_by(movie_id=m.id).order_by(Showtime.start_time)] if m else []


def day(n, hour=19):
    return datetime.datetime.combine(NOW.date() + datetime.timedelta(days=n), datetime.time(hour))


def test_a_vanished_show_goes_off_sale_and_keeps_its_rsvps(suns):
    from app import app, db, RSVP, User, Showtime
    sync([film('KEEPER', day(1), day(2)), film('OTHER', day(3))])
    with app.app_context():
        u = User(name='Olly', email='olly@scratch.test')
        db.session.add(u)
        db.session.flush()
        sid = rows('KEEPER')[0]['id']
        db.session.add(RSVP(user_id=u.id, showtime_id=sid, status='going'))
        db.session.commit()
    sync([film('KEEPER', day(2)), film('OTHER', day(3))])            # the first KEEPER show is gone
    gone, kept = rows('KEEPER')
    assert gone['off'] and gone['sold'] and not gone['cancelled']
    assert not kept['off'] and not kept['sold']
    with app.app_context():
        assert RSVP.query.filter_by(showtime_id=sid).count() == 1
        assert db.session.get(Showtime, sid).to_dict()['off_sale'] is True
    sync([film('KEEPER', day(1), day(2)), film('OTHER', day(3))])    # back on the site
    back = rows('KEEPER')[0]
    assert not back['off'] and not back['sold']


def test_a_partial_run_takes_nothing_off_sale(suns):
    from app import app, ScrapeRun
    from scrapers.base import ScrapeResult
    sync([film('KEEPER', day(1), day(2)), film('OTHER', day(3))])
    run_id = sync(ScrapeResult([film('OTHER', day(3))], partial=True))
    assert not any(r['off'] for r in rows('KEEPER'))
    with app.app_context():
        run = ScrapeRun.query.get(run_id)
        assert run.status == 'partial' and run.off_sale_showtimes == 0


def test_the_same_show_listed_twice_is_one_show(suns):
    sync([film('TWICE', day(1), day(1), sold=(day(1),)) | {'showtimes': [
        {'start_time': day(1), 'end_time': None, 'purchase_link': '', 'is_sold_out': True},
        {'start_time': day(1), 'end_time': None, 'purchase_link': '', 'is_sold_out': False}]}])
    (r,) = rows('TWICE')
    assert not r['sold']                                            # another screen still has seats


def test_end_time_follows_the_film_when_the_venue_doesnt_say(suns):
    from app import app, db, Movie
    sync([{'title': 'SHORT ONE', 'runtime_minutes': None,
           'showtimes': [{'start_time': day(1), 'end_time': None, 'purchase_link': '', 'is_sold_out': False}]}])
    with app.app_context():
        Movie.query.filter_by(title='SHORT ONE').first().runtime_minutes = 80
        db.session.commit()
    sync([{'title': 'SHORT ONE', 'runtime_minutes': None,
           'showtimes': [{'start_time': day(1), 'end_time': None, 'purchase_link': '', 'is_sold_out': False}]}])
    assert rows('SHORT ONE')[0]['end'] == day(1) + datetime.timedelta(minutes=100)    # 80 + 20


def test_a_venue_cancellation_is_kept_as_one(suns):
    show = film('CALLED OFF', day(1))
    show['showtimes'][0]['is_cancelled'] = True
    sync([show, film('OTHER', day(3))])
    (r,) = rows('CALLED OFF')
    assert r['cancelled'] and not r['off']


def test_old_cancellations_come_back_as_off_sale(suns):
    from app import app, db, migrate, BotSetting, Showtime
    sync([film('WAS CANCELLED', day(1))])
    with app.app_context():
        Showtime.query.update({'is_cancelled': True})
        db.session.query(BotSetting).filter_by(key='off_sale_backfill_done').delete()
        db.session.commit()
        migrate()
    (r,) = rows('WAS CANCELLED')
    assert r['off'] and r['sold'] and not r['cancelled']


# ─── Announced films (THE INVASION, Oct 18) ───────────────────────────────────

def announce(title, on):
    from scrapers.sync import sync_announced
    return sync_announced(cfg(), [{'title': title, 'announced_for': on, 'url': 'https://sunscinema.com/movies/x/'}])


def announcement(title):
    from app import app, Announcement, Movie
    with app.app_context():
        m = Movie.query.filter_by(title=title).first()
        a = Announcement.query.filter_by(movie_id=m.id).first() if m else None
        return a and {'on_sale': bool(a.on_sale_at), 'expected_on': a.expected_on}


def test_a_film_whose_show_already_started_isnt_coming_soon(suns):
    from app import app, db, Showtime, Movie
    sync([film('THE INVASION', day(1))])
    with app.app_context():                                         # tonight's show has started
        m = Movie.query.filter_by(title='THE INVASION').first()
        Showtime.query.filter_by(movie_id=m.id).update({'start_time': NOW - datetime.timedelta(hours=1)})
        db.session.commit()
    assert announce('THE INVASION', NOW.date()) == 0
    assert announcement('THE INVASION') is None


def test_a_sold_out_or_off_sale_film_isnt_coming_soon(suns):
    sync([film('SOLD OUT FILM', day(2), sold=(day(2),)), film('OTHER', day(3))])
    sync([film('OTHER', day(3))])                                   # …and now gone from the site
    assert announce('SOLD OUT FILM', day(2).date()) == 0


def test_a_stuck_coming_soon_clears_itself(suns):
    assert announce('LATE TICKETS', day(2).date()) == 1             # posted before its showtimes
    from app import app, db, Announcement
    sync([film('LATE TICKETS', day(2)), film('OTHER', day(3))])
    with app.app_context():                                         # as if alert_on_sale had missed it
        Announcement.query.update({'on_sale_at': None})
        db.session.commit()
    announce('LATE TICKETS', day(2).date())
    assert announcement('LATE TICKETS')['on_sale']


def test_a_return_engagement_is_announced_again(suns):
    from app import app, db, Showtime, Movie
    sync([film('BACK AGAIN', day(1))])
    with app.app_context():                                         # its run ended last week
        m = Movie.query.filter_by(title='BACK AGAIN').first()
        Showtime.query.filter_by(movie_id=m.id).update({'start_time': day(-6)})
        db.session.commit()
    assert announce('BACK AGAIN', day(25).date()) == 1               # posted again for three weeks on
    assert announcement('BACK AGAIN') == {'on_sale': False, 'expected_on': day(25).date()}


# ─── A scraper that fails outright tells the owner ─────────────────────────────

def test_a_failed_scrape_is_recorded_as_an_error(suns, monkeypatch):
    import scraper
    from app import app, ScrapeEvent, ScrapeRun
    from scrapers.base import finish_scrape

    def broken():
        return finish_scrape('Suns Cinema', [], ValueError('no films on the upcoming page — has its layout changed?'))
    c = cfg()
    monkeypatch.setattr(c, 'scrape', broken)
    monkeypatch.setattr(c, 'announced', None)
    scraper.run([c])
    with app.app_context():
        run = ScrapeRun.query.order_by(ScrapeRun.id.desc()).first()
        assert run.status == 'error' and 'layout' in run.error_text
        assert ScrapeEvent.query.filter_by(event_type='scrape_error').count() == 1     # the owner's DM

"""Every scraper against a saved copy of its venue's page or feed (trimmed real
pages in tests/fixtures/scrapers — what the sites served in October 2026;
the Smithsonian's are Internet Archive copies from July 2026). No network."""
import datetime
import json
import os
import sys
import types

import pytest
from bs4 import BeautifulSoup

FIX = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'scrapers')


def text(name):
    with open(os.path.join(FIX, name)) as f:
        return f.read()


def data(name):
    return json.loads(text(name))


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    from scrapers import base
    monkeypatch.setattr(base.time, 'sleep', lambda s: None)


def shows(movies):
    return [s for m in movies for s in m['showtimes']]


# ─── Suns ─────────────────────────────────────────────────────────────────────

def test_suns_reads_times_dates_and_sold_out(monkeypatch):
    from scrapers import suns
    monkeypatch.setattr(suns, 'get_soup', lambda url, **k: BeautifulSoup(text('suns_upcoming.html'), 'html.parser'))
    out = suns.scrape_suns()
    by = {m['title']: m for m in out}
    jekyll = by['DR. JEKYLL & SISTER HYDE']
    (show,) = jekyll['showtimes']
    assert show['start_time'] == datetime.datetime(2026, 10, 20, 19, 0)       # DC date, whatever the server clock
    assert show['is_sold_out'] and show['purchase_link'] == 'https://sunscinema.com/purchase/427344/'  # sold out keeps its link
    assert jekyll['runtime_minutes'] == 97
    assert not by['PRIVATE PARTS']['showtimes'][0]['is_sold_out']
    assert out.partial is False


def test_suns_page_without_films_is_an_error(monkeypatch):
    from scrapers import suns
    monkeypatch.setattr(suns, 'get_soup', lambda url, **k: BeautifulSoup('<html><body>Maintenance</body></html>', 'html.parser'))
    with pytest.raises(ValueError, match='layout'):
        suns.scrape_suns()


def test_suns_announced_posts(monkeypatch):
    from scrapers import suns
    monkeypatch.setattr(suns, 'get_json', lambda session, url, **k: data('suns_shows.json'))
    out = suns.scrape_suns_announced(pages=1)
    inv = next(m for m in out if m['title'] == 'THE INVASION')
    assert inv['announced_for'] == datetime.date(2026, 10, 18) and inv['runtime_minutes'] == 99
    assert inv['url'] == 'https://sunscinema.com/movies/the-invasion/'
    assert len(out) == 3                                    # the undated placeholder is skipped


# ─── AFI ──────────────────────────────────────────────────────────────────────

def afi_site(monkeypatch, film_ok=lambda url: '0100005700' in url):
    from scrapers import afi

    def get_soup(url, **k):
        if url.endswith('/now-playing/'):
            return BeautifulSoup(text('afi_now_playing.html'), 'html.parser')
        if film_ok(url):
            return BeautifulSoup(text('afi_film.html'), 'html.parser')
        raise RuntimeError('HTTP 500')
    monkeypatch.setattr(afi, 'get_soup', get_soup)
    return afi


def test_afi_reads_each_film_page(monkeypatch):
    afi = afi_site(monkeypatch, film_ok=lambda url: True)
    out = afi.scrape_afi()
    film = out[0]
    assert film['title'] == 'CAMERON WINTER AT CARNEGIE HALL in 35mm'
    assert [s['start_time'] for s in film['showtimes']][:2] == [datetime.datetime(2026, 11, 27, 18, 15),
                                                               datetime.datetime(2026, 11, 28, 18, 0)]
    assert len(film['showtimes']) == 5 and not any(s['is_sold_out'] for s in film['showtimes'])
    assert out.partial is False


def test_afi_film_page_failing_makes_a_partial_run(monkeypatch):
    afi = afi_site(monkeypatch)
    out = afi.scrape_afi()
    assert len(out) == 1 and out.partial is True             # two pages failed: nothing taken off sale


def test_afi_reads_past_a_hundred_films(monkeypatch):
    from scrapers import afi
    listing = ''.join(f'<a href="https://silver.afi.com/movies/detail/{n:010d}">x</a>' for n in range(104))
    asked = []
    monkeypatch.setattr(afi, 'get_soup', lambda url, **k: asked.append(url) or BeautifulSoup(
        listing if url.endswith('/now-playing/') else text('afi_film.html'), 'html.parser'))
    afi.scrape_afi()
    assert len(asked) == 1 + 104                                 # no cap at 100 — AFI listed 104 in October 2026


# ─── Alamo ────────────────────────────────────────────────────────────────────

def test_alamo_sold_out_hidden_and_no_runtime(monkeypatch):
    from scrapers import alamo
    monkeypatch.setattr(alamo, '_feed_cache', {'dc-metro-area': data('alamo_market.json')})
    dc = alamo.scrape_alamo('dc-metro-area', 'dc-bryant-street')
    crystal = alamo.scrape_alamo('dc-metro-area', 'crystal-city')
    feed = data('alamo_market.json')['data']['sessions']
    hidden = [s for s in feed if s.get('isHidden')]
    assert hidden and len(shows(dc)) + len(shows(crystal)) == len(feed) - len(hidden)
    sold = {s['showTimeClt'] for s in feed if s['status'] == 'SOLDOUT'}
    assert {s['start_time'].isoformat() for s in shows(dc + crystal) if s['is_sold_out']} == sold
    assert all(s['end_time'] is None for s in shows(dc))         # the feed has no runtimes: sync uses the film's


# ─── Regal ────────────────────────────────────────────────────────────────────

@pytest.fixture
def regal_api(monkeypatch):
    """The saved Regal day (all three theatres in one answer), served for every date."""
    from scrapers import regal
    for name, fresh in (('_days', None), ('_missed', set()), ('_error', None)):
        monkeypatch.setattr(regal, name, fresh)
    remember = regal._mark_deep
    monkeypatch.setattr(regal, '_mark_deep', lambda now=None: None)   # no database, unless a test asks
    calls = []
    today = datetime.date.today()
    site = types.SimpleNamespace(calls=calls, remember=remember, dates=[today + datetime.timedelta(days=n) for n in (0, 1, 2, 20, 30)])

    def get(url, params=None, **k):
        calls.append(params)
        body = data('regal_day.json')
        body['datesWithShows'] = [d.isoformat() for d in site.dates]
        day = datetime.datetime.strptime(params['date'], '%m-%d-%Y').date()
        for th in body['shows']:
            for film in th['Film']:
                for p in film['Performances']:
                    p['CalendarShowTime'] = f"{day.isoformat()}{p['CalendarShowTime'][10:]}"
        body['shows'][0]['Film'][0]['Performances'][0]['StopSales'] = True
        return types.SimpleNamespace(status_code=200, headers={}, json=lambda: body, raise_for_status=lambda: None)
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(requests=types.SimpleNamespace(get=get)))
    return site


def test_regal_one_request_per_date_covers_all_three(regal_api):
    from scrapers import regal
    outs = {code: regal.scrape_regal(code, f'regal-{code}', deep=True) for code in regal.CODES}
    assert len(regal_api.calls) == len(regal_api.dates)          # not three times over
    assert all(p['theatres'] == '1551,0296,1862' for p in regal_api.calls)
    assert all(outs[c] for c in regal.CODES)
    for th in data('regal_day.json')['shows']:                     # each theatre keeps only its own showings
        own = {(f['Title'].strip(), p['CalendarShowTime'][11:16]) for f in th['Film'] for p in f['Performances']}
        got = {(m['title'], s['start_time'].strftime('%H:%M')) for m in outs[str(th['TheatreCode'])] for s in m['showtimes']}
        assert got == own
    first = data('regal_day.json')['shows'][0]
    sold = [s for m in outs[str(first['TheatreCode'])] for s in m['showtimes'] if s['is_sold_out']]
    assert sold                                                    # StopSales → sold out
    assert outs['1551'].missed_dates == set()


def test_regal_far_dates_wait_for_the_daily_check(regal_api):
    from scrapers import regal
    out = regal.scrape_regal('1551', 'regal-1551', deep=False)
    asked = {datetime.datetime.strptime(p['date'], '%m-%d-%Y').date() for p in regal_api.calls}
    near, far = regal_api.dates[:3], regal_api.dates[3:]
    assert asked == set(near)
    assert out.missed_dates == set(far)                           # unchecked: their showtimes stay as they are


def test_regal_daily_check_is_remembered(regal_api, monkeypatch):
    from helpers import setup_db
    from scrapers import regal
    setup_db()
    monkeypatch.setattr(regal, '_mark_deep', regal_api.remember)
    from app import app, db, BotSetting
    with app.app_context():
        db.session.query(BotSetting).filter_by(key=regal.DEEP_KEY).delete()
        db.session.commit()
    assert regal.deep_due()
    regal.scrape_regal('1551', 'regal-1551')
    assert len(regal_api.calls) == len(regal_api.dates)          # due: every date asked
    assert not regal.deep_due()                                   # …and not again for 20 hours
    later = datetime.datetime.utcnow() + datetime.timedelta(hours=21)
    assert regal.deep_due(now=later)


def test_regal_first_request_failing_is_an_error_once(monkeypatch):
    from scrapers import regal
    for name, fresh in (('_days', None), ('_missed', set()), ('_error', None)):
        monkeypatch.setattr(regal, name, fresh)
    calls = []

    def get(url, **k):
        calls.append(1)
        raise ConnectionError('down')
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(requests=types.SimpleNamespace(get=get)))
    for code in regal.CODES:
        with pytest.raises(ConnectionError):
            regal.scrape_regal(code, f'regal-{code}', deep=False)
    assert len(calls) == 1                                        # not asked again for the other two


# ─── Smithsonian ──────────────────────────────────────────────────────────────

@pytest.fixture
def si_site(monkeypatch):
    """The theater page and Blue Angels are saved; any other page gets si.edu's bot check."""
    from scrapers import smithsonian
    monkeypatch.setattr(smithsonian, '_page_cache', {
        f'{smithsonian.BASE}/theaters/lockheedmartin': text('smithsonian_theater.html'),
        f'{smithsonian.BASE}/theaters/movie/blue-angels': text('smithsonian_movie.html'),
    })
    asked = []

    def get(url, **k):
        asked.append(url)
        return types.SimpleNamespace(text='<html><head><title>Smithsonian request verification</title></head></html>',
                                     raise_for_status=lambda: None)
    monkeypatch.setitem(sys.modules, 'curl_cffi', types.SimpleNamespace(requests=types.SimpleNamespace(get=get)))
    return asked


def test_smithsonian_reads_its_venue_and_counts_a_bot_check_as_failed(si_site):
    from scrapers import smithsonian
    out = smithsonian.scrape_smithsonian('lockheedmartin')
    (film,) = out
    assert film['title'] == 'The Blue Angels'
    assert film['showtimes'] and all(s['start_time'].year == 2026 for s in film['showtimes'])
    assert film['runtime_minutes'] is None and all(s['end_time'] is None for s in film['showtimes'])
    assert out.partial is True                                    # the bot check: nothing taken off sale
    assert len(si_site) == 1                                      # and it isn't asked again straight away


def test_smithsonian_theater_page_blocked_is_an_error(monkeypatch, si_site):
    from scrapers import smithsonian
    monkeypatch.setattr(smithsonian, '_page_cache', {})
    with pytest.raises(Exception, match='bot check'):
        smithsonian.scrape_smithsonian('lockheedmartin')


# ─── Avalon ───────────────────────────────────────────────────────────────────

def test_avalon_feed(monkeypatch):
    from scrapers import avalon
    monkeypatch.setattr(avalon, 'get_json', lambda session, url, **k: data('avalon_feed.json'))
    out = avalon.scrape_avalon()
    feed = data('avalon_feed.json')['ArrayOfShows']
    assert [m['title'] for m in out] == [s['Name'].strip() for s in feed if s.get('CurrentShowings')]
    assert all(s['purchase_link'] and s['end_time'] > s['start_time'] for s in shows(out))


# ─── Angelika ─────────────────────────────────────────────────────────────────

def test_angelika_reads_every_date(monkeypatch):
    from scrapers import angelika
    asked = []

    class Session:
        def get(self, url, params=None, **k):
            asked.append(params['selectedDate'])
            return types.SimpleNamespace(json=lambda: data('angelika_films.json'), raise_for_status=lambda: None)
    monkeypatch.setattr(angelika, '_session', Session())
    out = angelika.scrape_angelika('0000000006', 'mosaic')
    dates = [d['value'] for d in data('angelika_films.json')['nowShowing']['data']['filter']['session']]
    assert asked[0] == '' and set(asked[1:]) <= set(dates)
    assert out and all(s['start_time'].tzinfo is None for s in shows(out))
    assert out.missed_dates == set()


# ─── AMC (switched off until there's an API key; a sample in its documented shape) ─

def test_amc_cancelled_and_sold_out(monkeypatch):
    from scrapers import amc
    day = datetime.date.today().strftime('%Y-%m-%d')
    page = {'_embedded': {'showtimes': [
        {'movieName': 'SINNERS', 'showDateTimeLocal': f'{day}T19:00:00', 'runTime': 137, 'isSoldOut': True,
         'purchaseUrl': 'https://www.amctheatres.com/showtimes/1'},
        {'movieName': 'SINNERS', 'showDateTimeLocal': f'{day}T22:00:00', 'runTime': 137, 'isCanceled': True}]},
        '_links': {}}

    class Session:
        def get(self, url, **k):
            return types.SimpleNamespace(status_code=200, json=lambda: page if day.replace('-', '') in url.replace('-', '')
                                         or url.endswith(datetime.date.today().strftime('%m-%d-%Y')) else {'_embedded': {}},
                                         raise_for_status=lambda: None)
    monkeypatch.setattr(amc, '_session', lambda: Session())
    monkeypatch.setattr(amc.time, 'sleep', lambda s: None)
    (film,) = amc.scrape_amc('amc-georgetown-14', 'amc-georgetown-14')
    a, b = sorted(film['showtimes'], key=lambda s: s['start_time'])
    assert a['is_sold_out'] and not a['is_cancelled'] and b['is_cancelled']
    assert a['end_time'] - a['start_time'] == datetime.timedelta(minutes=157)


# ─── Shared helpers ───────────────────────────────────────────────────────────

def test_bot_check_pages_are_recognized():
    from scrapers.base import looks_blocked
    assert looks_blocked('<title>Just a moment...</title>') and looks_blocked('<TITLE>Smithsonian request verification</TITLE>')
    assert not looks_blocked(text('smithsonian_movie.html')) and not looks_blocked(text('afi_film.html'))


def test_get_soup_waits_out_a_busy_site(monkeypatch):
    from scrapers import base
    waits, answers = [], [(429, {'Retry-After': '9'}), (503, {}), (200, {})]
    monkeypatch.setattr(base.time, 'sleep', waits.append)

    class Session:
        def get(self, url, **k):
            status, headers = answers.pop(0)
            r = types.SimpleNamespace(status_code=status, headers=headers, text='<p>ok</p>')
            r.raise_for_status = lambda: None
            return r
    monkeypatch.setattr(base, '_http', Session())
    assert base.get_soup('https://example.test/').p.text == 'ok'
    assert waits == [9, 2]                                        # what it asked, then the back-off


def test_finish_scrape():
    from scrapers.base import finish_scrape
    with pytest.raises(RuntimeError):
        finish_scrape('X', [], RuntimeError('down'))              # nothing read: a failed run
    assert finish_scrape('X', [{'title': 'A'}], RuntimeError('down')).partial
    assert finish_scrape('X', [{'title': 'A'}], skipped=1).partial
    assert not finish_scrape('X', [{'title': 'A'}]).partial


# ─── NGA (a saved listing; the event page is hand-written in its format) ──────

@pytest.fixture
def nga_site(monkeypatch):
    """The listing, Salesman's event page, and si.edu-style bot checks for the rest."""
    from scrapers import nga
    from scrapers.base import Blocked
    asked = []

    def fetch(url):
        asked.append(url)
        if url == nga.LISTING_URL:
            return text('nga_listing.html')
        if url.endswith('maysles-films-incs-salesman'):
            return text('nga_event.html')
        raise Blocked('served a bot check instead of the page')
    monkeypatch.setattr(nga, '_fetch', fetch)
    return asked


def test_nga_reads_event_pages_and_falls_back_to_the_listing(nga_site):
    from scrapers import nga
    out = nga.scrape_nga()
    by = {m['title']: m for m in out}
    salesman = by['Maysles Films Inc.’s Salesman']
    assert salesman['runtime_minutes'] == 91 and salesman['release_year'] == '1969'
    assert [s['start_time'] for s in salesman['showtimes']] == [datetime.datetime(2026, 10, 17, 18, 0)]
    # Bot check on the next page: the rest come from the listing (same titles), and nothing more is asked
    assert set(by) == {'Maysles Films Inc.’s Salesman', 'The National Gallery and its Artists: Portraits on Film',
                       'Eyes on the Prize: The Promised Land (1967–1968) and On the Case'}
    assert len(nga_site) == 3 and out.partial is False


def test_nga_listing_blocked_is_an_error(monkeypatch):
    from scrapers import nga
    from scrapers.base import Blocked

    def fetch(url):
        raise Blocked('served a bot check instead of the page')
    monkeypatch.setattr(nga, '_fetch', fetch)
    with pytest.raises(Blocked):
        nga.scrape_nga()

"""The Letterboxd watchlist import: members upload Letterboxd's export (the zip,
or its watchlist.csv); its films join their watchlist once they're in our
listings — at import, or when a scrape or a TMDB search adds them later.
Re-imports mirror Letterboxd (site films are never touched; a film removed
here stays off); the first import asks whether its films alert you (not
asked = no); imports never show in the club feed."""
import datetime
import io
import os
import zipfile

import pytest

from helpers import H, client, setup_db

FIX = os.path.join(os.path.dirname(__file__), '..', 'fixtures', 'letterboxd', 'watchlist.csv')
CSV = open(FIX, 'rb').read()          # Letterboxd's format: BOM, CRLF, a quoted comma, a repeat, a row with no year


def zipped(**files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for name, data in files.items():
            z.writestr(name.replace('__', '/'), data)
    return buf.getvalue()


def upload(uid, data, name='watchlist.csv'):
    return client(uid).post('/api/me/letterboxd/watchlist', data={'file': (io.BytesIO(data), name)},
                            content_type='multipart/form-data')


@pytest.fixture
def lib(monkeypatch):
    """Ana and Bo in club 1. Our catalog (the test database's films) has
    "VERTIGO (Digital)" (1958), "NORTH BY NORTHWEST in 70mm" (1959) and "Count
    Gore De Vol presents THE FLY (1986)"; we add PARIS, TEXAS with no year. Ana
    already watchlisted VERTIGO on the site."""
    import enrich
    from app import app, db, GroupMembership, Movie, User, Watchlist
    setup_db()
    monkeypatch.setattr(enrich, 'enrich_movie', lambda *a, **k: None)
    with app.app_context():
        us = {n: User(name=n, email=f'{n.lower()}@lbw.test', is_active=True) for n in ('Ana', 'Bo')}
        db.session.add_all(us.values())
        db.session.flush()
        for u in us.values():
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role='member'))
        films = {key: Movie.query.filter_by(title=title).one().id
                 for key, title in (('VERTIGO', 'VERTIGO (Digital)'), ('NXNW', 'NORTH BY NORTHWEST in 70mm'),
                                    ('FLY', 'Count Gore De Vol presents THE FLY (1986)'))}
        paris = Movie(title='PARIS, TEXAS')
        db.session.add(paris)
        db.session.flush()
        films['PARIS'] = paris.id
        db.session.add(Watchlist(user_id=us['Ana'].id, movie_id=films['VERTIGO']))
        db.session.commit()
        return {**{n: u.id for n, u in us.items()}, **films}


def rows(uid):
    from app import app, Watchlist
    with app.app_context():
        return {w.movie.title: w.source for w in Watchlist.query.filter_by(user_id=uid)}


# ─── Reading the export ───────────────────────────────────────────────────────

def test_reading_the_csv_and_the_zip():
    import letterboxd
    got, err = letterboxd.read_export(CSV)
    assert err is None
    assert [(r['title'], r['year']) for r in got] == [('Vertigo', 1958), ('North by Northwest', 1959), ('The Fly', 1958),
                                                      ('Stalker', 1979), ('Paris, Texas', 1984), ('Untitled Short', None)]
    assert got[0]['added_on'] == datetime.date(2025, 2, 1) and got[0]['uri'] == 'https://boxd.it/2bfS'
    # The whole export: the top watchlist.csv, not the one in deleted/
    whole = zipped(**{'diary.csv': b'Date,Name\n', 'deleted__watchlist.csv': b'Date,Name,Year,Letterboxd URI\n2020-01-01,Old,1950,u\n',
                      'watchlist.csv': CSV})
    assert [r['title'] for r in letterboxd.read_export(whole)[0]][:2] == ['Vertigo', 'North by Northwest']


@pytest.mark.parametrize('data, error', [
    (b'Date,Name,Year\n2025-01-01,Vertigo,1958\n', 'not_export'),          # not Letterboxd's watchlist
    (b'Date,Name,Year,Letterboxd URI\r\n', 'empty'),
    (zipped(**{'diary.csv': b'Date,Name\n'}), 'not_export'),                # an export without a watchlist
    (b'PK\x03\x04 not really a zip', 'not_export'),
    (b'\x89PNG\r\n\x1a\n', 'not_export'),
])
def test_wrong_files_are_refused(data, error):
    import letterboxd
    assert letterboxd.read_export(data) == (None, error)


# ─── Importing ────────────────────────────────────────────────────────────────

def test_import_matches_our_films_and_asks_about_alerts(lib):
    r = upload(lib['Ana'], CSV)
    assert r.status_code == 200
    d = r.json
    assert d['ask_alerts'] is True and d['watchlist']['on'] is True
    assert d['imported'] == {'films': 6, 'matched': 2, 'added': 1, 'removed': 0}
    assert d['watchlist']['films'] == 6 and d['watchlist']['matched'] == 2
    # VERTIGO was already a site film (stays one); NXNW matched through "in 70mm"; THE FLY (1958) isn't
    # our 1986 film; our PARIS, TEXAS has no year, so it isn't guessed; STALKER isn't listed yet.
    assert rows(lib['Ana']) == {'VERTIGO (Digital)': None, 'NORTH BY NORTHWEST in 70mm': 'letterboxd'}
    assert upload(lib['Ana'], CSV).json['ask_alerts'] is True                   # still unanswered
    put = client(lib['Ana']).put('/api/me/letterboxd', json={'watch_alerts': False}).json
    assert put['watchlist']['alerts'] is False
    assert upload(lib['Ana'], CSV).json['ask_alerts'] is False


def test_matched_counts_entries_not_rows(lib):
    from app import app, LetterboxdWatch
    upload(lib['Ana'], CSV)
    with app.app_context():
        matched = {lw.title for lw in LetterboxdWatch.query.filter(LetterboxdWatch.movie_id.isnot(None))}
    assert matched == {'Vertigo', 'North by Northwest'}


def test_reimport_mirrors_letterboxd_and_never_touches_site_films(lib):
    upload(lib['Ana'], CSV)
    without = b'Date,Name,Year,Letterboxd URI\n2025-04-20,Stalker,1979,u\n'           # Vertigo and NxNW gone
    d = upload(lib['Ana'], without).json
    assert d['imported']['removed'] == 1
    assert rows(lib['Ana']) == {'VERTIGO (Digital)': None}                                     # the site film stays


def test_a_film_removed_here_stays_off(lib):
    upload(lib['Ana'], CSV)
    client(lib['Ana']).post('/api/watchlist', json={'movie_id': lib['NXNW']})        # toggle: off
    assert 'NORTH BY NORTHWEST in 70mm' not in rows(lib['Ana'])
    d = upload(lib['Ana'], CSV).json
    assert 'NORTH BY NORTHWEST in 70mm' not in rows(lib['Ana']) and d['watchlist']['films'] == 5   # not counted either


def test_adding_an_imported_film_in_discord_makes_it_a_site_film(lib, monkeypatch):
    from app import app, db, User
    with app.app_context():
        db.session.get(User, lib['Ana']).discord_user_id = '8801'
        db.session.commit()
    upload(lib['Ana'], CSV)
    client().post('/api/internal/watch', headers=H, json={'discord_user_id': '8801', 'title': f"movie:{lib['NXNW']}",
                                                         'action': 'add'})
    assert rows(lib['Ana'])['NORTH BY NORTHWEST in 70mm'] is None
    upload(lib['Ana'], b'Date,Name,Year,Letterboxd URI\n2025-04-20,Stalker,1979,u\n')
    assert 'NORTH BY NORTHWEST in 70mm' in rows(lib['Ana'])                           # re-imports leave it


def test_turning_it_off_removes_only_imported_films(lib):
    upload(lib['Ana'], CSV)
    d = client(lib['Ana']).delete('/api/me/letterboxd/watchlist').json
    assert d['watchlist'] == {'on': False, 'imported_at': None, 'films': 0, 'matched': 0, 'alerts': None}
    assert rows(lib['Ana']) == {'VERTIGO (Digital)': None}


def test_guests_wrong_files_and_size(lib):
    from app import app, db, User
    with app.app_context():
        g = User(name='Guest', is_guest=True, is_active=True)
        db.session.add(g)
        db.session.commit()
        gid = g.id
    assert upload(gid, CSV).status_code == 403
    bad = upload(lib['Ana'], b'hello')
    assert bad.status_code == 400 and 'Export your data' in bad.json['error']
    assert client(lib['Ana']).post('/api/me/letterboxd/watchlist').status_code == 400
    big = upload(lib['Ana'], b'x' * (7 * 1024 * 1024), 'letterboxd.zip')
    assert big.status_code == 413 and 'watchlist.csv' in big.json['error']


# ─── Films that turn up later ─────────────────────────────────────────────────

def scrape(title, year, days=3):
    from scrapers import get_config
    from scrapers.sync import sync_to_db
    start = datetime.datetime.combine(datetime.date.today() + datetime.timedelta(days=days), datetime.time(19))
    return sync_to_db(get_config('afi'), [
        {'title': 'ALREADY ON', 'showtimes': [{'start_time': start, 'end_time': None, 'purchase_link': '', 'is_sold_out': False}]},
        {'title': title, 'release_year': year,
         'showtimes': [{'start_time': start, 'end_time': None, 'purchase_link': '', 'is_sold_out': False}]}])


def showing_alerts(uid):
    from app import app, Notification
    with app.app_context():
        return [n.payload_json for n in Notification.query.filter_by(user_id=uid, kind='showings')]


def test_a_film_booked_later_joins_the_watchlist_and_alerts_in_the_same_run(lib):
    upload(lib['Ana'], CSV)
    client(lib['Ana']).put('/api/me/letterboxd', json={'watch_alerts': True})
    scrape('ALREADY ON', '2001', days=4)                                   # the theatre has a schedule already
    scrape('STALKER', '1979')
    assert rows(lib['Ana'])['STALKER'] == 'letterboxd'
    assert any('STALKER' in p for p in showing_alerts(lib['Ana']))
    assert 'STALKER' not in rows(lib['Bo'])


def test_not_asked_or_no_means_no_alert(lib):
    upload(lib['Ana'], CSV)                                                 # alerts not answered yet
    scrape('ALREADY ON', '2001', days=4)
    scrape('STALKER', '1979')
    assert rows(lib['Ana'])['STALKER'] == 'letterboxd' and showing_alerts(lib['Ana']) == []


def test_a_film_opened_from_tmdb_search_joins_too(lib, monkeypatch):
    import enrich
    from app import app, movie_for_tmdb
    monkeypatch.setattr(enrich, 'enrich_by_tmdb_id', lambda tid: {'tmdb_id': tid, 'tmdb_title': 'Stalker',
                                                                   'release_year': '1979'})
    upload(lib['Ana'], CSV)
    with app.app_context():
        m = movie_for_tmdb(1398)
        assert m.title == 'Stalker' and m.release_year == '1979'
    assert rows(lib['Ana'])['Stalker'] == 'letterboxd'


def test_merging_a_discord_account_keeps_the_import(lib):
    from app import app, db, User, LetterboxdWatch, merge_users
    upload(lib['Ana'], CSV)
    with app.app_context():
        keep = User(name='Ana again', email='ana2@lbw.test', is_active=True)
        db.session.add(keep)
        db.session.flush()
        merge_users(keep, db.session.get(User, lib['Ana']))
        db.session.commit()
        assert LetterboxdWatch.query.filter_by(user_id=keep.id).count() == 6 and keep.letterboxd_watch_on


# ─── Where imported films do and don't show ───────────────────────────────────

def test_imports_stay_out_of_the_feed(lib):
    upload(lib['Ana'], CSV)
    client(lib['Ana']).post('/api/watchlist', json={'movie_id': lib['FLY']})          # a site add does show
    feed = client(lib['Bo']).get('/api/feed', query_string={'group_id': 1}).json
    keys = {card['key'] for card in feed['cards']}
    assert f"w{lib['FLY']}" in keys and f"w{lib['NXNW']}" not in keys


def test_the_lists_mark_imported_films(lib):
    upload(lib['Ana'], CSV)
    items = client(lib['Bo']).get(f"/api/users/{lib['Ana']}/watchlist").json['items']
    assert {i['movie']['title']: i['source'] for i in items} == {'VERTIGO (Digital)': None, 'NORTH BY NORTHWEST in 70mm': 'letterboxd'}
    assert {i['movie']['title']: i['source'] for i in client(lib['Ana']).get('/api/watchlist').json}['NORTH BY NORTHWEST in 70mm'] == 'letterboxd'


def test_digest_counts_but_never_tags_or_emails_muted_imports(lib):
    from app import app, db, DiscordServerMember, Showtime, Theatre, User
    upload(lib['Ana'], CSV)
    with app.app_context():
        ana = db.session.get(User, lib['Ana'])
        ana.discord_user_id = '8802'
        db.session.add(DiscordServerMember(discord_user_id='8802'))
        afi = Theatre.query.filter_by(slug='afi').first()
        st = Showtime(movie_id=lib['NXNW'], theatre_id=afi.id, start_time=datetime.datetime.now() + datetime.timedelta(days=2))
        db.session.add(st)
        db.session.commit()
        sid = st.id
    client(lib['Ana']).put('/api/discord/prefs', json={'watchlist': 'always'})

    def item():
        d = client().get('/api/internal/digest', query_string={'group_id': 1, 'days': 7}, headers=H).json
        return next(i for i in d['watchlist'] if i['showtime_id'] == sid)
    client(lib['Ana']).put('/api/me/letterboxd', json={'watch_alerts': False})
    muted = item()
    assert muted['watchers'] == [] and muted['more'] == 1 and muted['quiet_ids'] == []
    client(lib['Ana']).put('/api/me/letterboxd', json={'watch_alerts': True})
    assert [w['name'] for w in item()['watchers']] == ['Ana']


def test_the_bot_marks_imported_films():
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'bot'))
    import embeds
    e = embeds.watchlist_embed([{'title': 'STALKER', 'year': '1979', 'source': 'letterboxd', 'next_showtime': None},
                                {'title': 'VERTIGO', 'year': '1958', 'source': None, 'next_showtime': None}], 'Ana')
    assert '**STALKER** (1979) 📓' in e.description and '**VERTIGO** (1958) —' in e.description
    assert e.footer.text.startswith('📓 = from Letterboxd')

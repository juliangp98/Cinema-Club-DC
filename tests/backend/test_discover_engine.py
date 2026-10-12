"""The Discover engine (R3): time windows, every shelf, Browse's filters,
paging and facets, Surprise me, and the routes. A fixed "now": Wednesday
2026-10-07, noon."""
import json
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from helpers import client, setup_db

NOW = datetime(2026, 10, 7, 12, 0)


def test_time_windows():
    import discover as D
    s, e = D.window('tonight', NOW)
    assert s == NOW and e.date() == NOW.date() and e.hour == 23
    s, e = D.window('weekend', NOW)                                        # from a Wednesday: Fri 5pm → Sunday night
    assert s == datetime(2026, 10, 9, 17) and e.date() == datetime(2026, 10, 11).date()
    s, e = D.window('weekend', datetime(2026, 10, 10, 14))                 # on Saturday: now → Sunday night
    assert s == datetime(2026, 10, 10, 14) and e.date() == datetime(2026, 10, 11).date()
    s, e = D.window(None, NOW, '2026-10-09', '2026-10-10')
    assert s == datetime(2026, 10, 9) and e.date() == datetime(2026, 10, 10).date()
    assert D.normalize('SIRÂT') == 'sirat'                                 # accent-insensitive search text


@pytest.fixture
def disco():
    """A club over two weeks: THE CONVERSATION (one night, 35mm, 1974, at
    AFI), BIG HIT (everywhere, 160 min), QUIET ROOM (arthouse, 2 want it),
    SPACE DOC (IMAX, 45 min), LOCAL STORY (Q&A), MIDNIGHT MADNESS (11:15pm),
    PSYCHO + THE BIRDS (a Hitchcock double at Suns, 35-min gap). Ana likes
    horror and wants QUIET ROOM and THE CONVERSATION; Bo is going to BIG HIT.
    Yields with a database context open."""
    import discover as D
    from app import app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist
    setup_db()
    with app.app_context():
        th = {t.slug: t for t in Theatre.query.filter(Theatre.slug.in_(['afi', 'suns', 'alamo-dc', 'alamo-crystal', 'regal-gallery', 'smi-dc']))}
        g = Group(name='Disco', slug='disco-r3', is_public=False)
        db.session.add(g)
        db.session.flush()
        films = {}

        def film(title, year, genres='', runtime=100, **kw):
            m = Movie(title=title, release_year=str(year), genres=genres, runtime_minutes=runtime, **kw)
            db.session.add(m)
            db.session.flush()
            films[title] = m
            return m

        def show(m, slug, day, hour, minute=0, fmt=None, event=None, end=None):
            st = NOW.replace(hour=0) + timedelta(days=day, hours=hour, minutes=minute)
            s = Showtime(movie_id=m.id, theatre_id=th[slug].id, start_time=st, format_label=fmt, event_label=event,
                         end_time=end or st + timedelta(minutes=(m.runtime_minutes or 100) + 15))
            db.session.add(s)
            db.session.flush()
            return s
        conv = film('THE CONVERSATION', 1974, 'drama,thriller,mystery', 113, director='Francis Ford Coppola',
                    cast_json=json.dumps([{'name': 'Gene Hackman'}, {'name': 'John Cazale'}]))
        show(conv, 'afi', 1, 19, fmt='35mm')
        blk = film('BIG HIT', 2026, 'action,adventure', 160)
        for d in range(5):
            for slug in ('alamo-dc', 'alamo-crystal', 'regal-gallery'):
                show(blk, slug, d, 13)
                show(blk, slug, d, 19, 30)
        art = film('QUIET ROOM', 2025, 'drama', 88)
        show(art, 'suns', 2, 19)
        show(art, 'suns', 3, 19)
        imax = film('SPACE DOC', 2024, 'documentary', 45)
        show(imax, 'smi-dc', 0, 14)
        show(imax, 'smi-dc', 1, 14)
        show(film('LOCAL STORY', 2026, 'documentary', 90), 'afi', 3, 19, event='LOCAL STORY + Q&A with the director')
        show(film('MIDNIGHT MADNESS', 1985, 'horror,comedy', 92), 'alamo-dc', 0, 23, 15)
        psycho = film('PSYCHO', 1960, 'horror,thriller', 100, director='Alfred Hitchcock')
        birds = film('THE BIRDS', 1963, 'horror,thriller', 119, director='Alfred Hitchcock')
        show(psycho, 'suns', 5, 19, end=NOW.replace(hour=0) + timedelta(days=5, hours=20, minutes=55))
        show(birds, 'suns', 5, 21, 30)
        users = [User(email=f'u{i}@r3.test', name=n, is_active=True, favorite_genres=fg)
                 for i, (n, fg) in enumerate([('Ana', 'horror'), ('Bo', ''), ('Cy', '')])]
        db.session.add_all(users)
        db.session.flush()
        for u in users:
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        db.session.add_all([Watchlist(user_id=users[0].id, movie_id=art.id), Watchlist(user_id=users[1].id, movie_id=art.id),
                            Watchlist(user_id=users[0].id, movie_id=conv.id)])
        db.session.add(RSVP(user_id=users[1].id, showtime_id=Showtime.query.filter_by(movie_id=blk.id).first().id,
                            group_id=g.id, status='going'))
        db.session.commit()
        group, ana = db.session.get(Group, g.id), db.session.get(User, users[0].id)
        start, end = D.window('2weeks', NOW)
        cat = D.catalog(group, start, end, ana)
        ctx = D.context(group, ana, cat, NOW)
        yield SimpleNamespace(D=D, group=group, ana=ana, cat=cat, ctx=ctx, films={t: m.id for t, m in films.items()})


def shelf(w, key):
    return [f.movie.title for f, _ in w.D.shelf(key, w.cat, w.ctx)]


def reasons(w, key, title):
    return next(r for f, r in w.D.shelf(key, w.cat, w.ctx) if f.movie.title == title)


def test_rare_one_night_and_on_film(disco):
    assert shelf(disco, 'rare')[0] == 'THE CONVERSATION' and reasons(disco, 'rare', 'THE CONVERSATION') == ['one night only', '35mm', '1974']
    assert 'BIG HIT' not in shelf(disco, 'rare')
    assert set(shelf(disco, 'one-night')) >= {'THE CONVERSATION', 'LOCAL STORY', 'MIDNIGHT MADNESS', 'PSYCHO', 'THE BIRDS'}
    assert 'QUIET ROOM' not in shelf(disco, 'one-night')
    assert shelf(disco, 'on-film') == ['THE CONVERSATION']


def test_big_screen_events_blockbusters_arthouse_classics(disco):
    assert shelf(disco, 'big-screen') == ['SPACE DOC'] and reasons(disco, 'big-screen', 'SPACE DOC') == ['IMAX']
    assert shelf(disco, 'events') == ['LOCAL STORY'] and reasons(disco, 'events', 'LOCAL STORY') == ['Q&A']
    assert shelf(disco, 'blockbusters') == ['BIG HIT']                                    # recent, 3+ theatres, 10+ showings
    assert 'QUIET ROOM' in shelf(disco, 'arthouse') and 'BIG HIT' not in shelf(disco, 'arthouse')
    assert shelf(disco, 'classics')[0] == 'THE CONVERSATION' and 'MIDNIGHT MADNESS' in shelf(disco, 'classics')


def test_the_clubs_shelves(disco):
    assert shelf(disco, 'friends') == ['BIG HIT'] and reasons(disco, 'friends', 'BIG HIT') == ['1 going']
    assert shelf(disco, 'most-wanted')[0] == 'QUIET ROOM' and reasons(disco, 'most-wanted', 'QUIET ROOM') == ['2 want to see it']
    assert set(shelf(disco, 'for-you')[:2]) == {'QUIET ROOM', 'THE CONVERSATION'} and 'PSYCHO' in shelf(disco, 'for-you')   # list first, then genres


def test_runtime_late_night_and_genre_shelves(disco):
    assert 'SPACE DOC' in shelf(disco, 'short') and shelf(disco, 'epics') == ['BIG HIT']
    late = shelf(disco, 'late-night')
    assert late[:2] == ['MIDNIGHT MADNESS', 'BIG HIT'] or set(late) >= {'MIDNIGHT MADNESS', 'THE BIRDS'}
    assert set(shelf(disco, 'documentaries')) == {'SPACE DOC', 'LOCAL STORY'} and 'PSYCHO' in shelf(disco, 'horror')


def test_double_features_and_spotlights(disco):
    assert any(x['first']['movie']['title'] == 'PSYCHO' and x['second']['movie']['title'] == 'THE BIRDS' and x['gap_minutes'] == 35
               for x in disco.D.double_features(disco.cat))
    assert any(x['role'] == 'director' and x['name'] == 'Alfred Hitchcock' and x['count'] == 2
               for x in disco.D.spotlights(disco.group, disco.ana, NOW))


def browse(w, **p):
    return [c['movie']['title'] for c in w.D.browse(w.group, w.ana, p, now=NOW)['films']]


def test_browse_by_when_genre_mood_decade(disco):
    assert set(browse(disco, when='tonight')) == {'BIG HIT', 'SPACE DOC', 'MIDNIGHT MADNESS'}
    assert set(browse(disco, when='2weeks', genres='horror')) == {'PSYCHO', 'THE BIRDS', 'MIDNIGHT MADNESS'}
    assert 'THE CONVERSATION' in browse(disco, when='2weeks', mood='mind-bender')
    assert browse(disco, when='2weeks', decade='1960') == ['PSYCHO', 'THE BIRDS']


def test_browse_by_format_time_place(disco):
    assert browse(disco, when='2weeks', format='film') == ['THE CONVERSATION']
    assert browse(disco, when='2weeks', format='big') == ['SPACE DOC']
    assert set(browse(disco, when='2weeks', time='late')) == {'MIDNIGHT MADNESS', 'THE BIRDS'}
    assert browse(disco, when='2weeks', theatres='suns') == ['QUIET ROOM', 'PSYCHO', 'THE BIRDS']
    assert browse(disco, when='2weeks', regions='virginia') == ['BIG HIT']


def test_browse_by_rarity_club_runtime(disco):
    assert 'BIG HIT' in browse(disco, when='2weeks', rarity='wide') and 'THE CONVERSATION' in browse(disco, when='2weeks', rarity='rare')
    assert 'QUIET ROOM' not in browse(disco, when='2weeks', rarity='repertory')
    assert browse(disco, when='2weeks', club='going') == ['BIG HIT']
    assert set(browse(disco, when='2weeks', club='mine')) == {'QUIET ROOM', 'THE CONVERSATION'}
    assert 'BIG HIT' in browse(disco, when='2weeks', runtime='long') and 'SPACE DOC' in browse(disco, when='2weeks', runtime='short')


def test_browse_search_shelf_and_sort(disco):
    assert browse(disco, when='2weeks', q='conversation') == ['THE CONVERSATION']
    assert browse(disco, when='2weeks', q='hitchcock') == ['PSYCHO', 'THE BIRDS']               # director
    assert browse(disco, when='2weeks', q='HACKMAN') == ['THE CONVERSATION']                     # cast
    r = disco.D.browse(disco.group, disco.ana, {'when': '2weeks', 'shelf': 'rare'}, now=NOW)
    assert r['title'] == 'Rare gems' and r['films'][0]['movie']['title'] == 'THE CONVERSATION'    # keeps the shelf's order
    assert browse(disco, when='2weeks', sort='title')[0] == 'BIG HIT'


def test_paging_facets_and_card_shape(disco):
    D = disco.D
    r = D.browse(disco.group, disco.ana, {'when': '2weeks'}, now=NOW, limit=3)
    r2 = D.browse(disco.group, disco.ana, {'when': '2weeks'}, now=NOW, limit=3, offset=3)
    titles = lambda x: [c['movie']['title'] for c in x['films']]
    assert r['total'] == 8 and r['next_offset'] == 3 and not set(titles(r)) & set(titles(r2))
    assert r['facets']['genres'].get('horror') == 3 and r['facets']['decades'].get('1960') == 2 and r['facets']['theatres'].get('suns') == 3
    c = D.browse(disco.group, disco.ana, {'when': '2weeks', 'q': 'conversation'}, now=NOW)['films'][0]
    assert c['next']['theatre'] == 'AFI' and c['showings'] == 1 and c['club']['you_want']
    assert c['reasons'][:2] == ['one night only', '35mm']


def test_surprise_me(disco):
    D = disco.D
    p = D.surprise(disco.group, disco.ana, 'tonight', now=NOW, rng=random.Random(1))
    assert p['when'] == 'tonight' and p['movie']['title'] in {'BIG HIT', 'SPACE DOC', 'MIDNIGHT MADNESS'}
    tonight = [disco.films[t] for t in ('BIG HIT', 'SPACE DOC', 'MIDNIGHT MADNESS')]
    p = D.surprise(disco.group, disco.ana, 'tonight', exclude=tonight, now=NOW, rng=random.Random(1))
    assert p['when'] == 'week' and p['movie']['id'] not in tonight                     # nothing left tonight: the week
    picks = [D.surprise(disco.group, disco.ana, 'week', now=NOW, rng=random.Random(i))['movie']['title'] for i in range(300)]
    assert picks.count('THE CONVERSATION') > picks.count('BIG HIT')                     # weighted toward rare + your genres


def test_the_routes(disco):
    c, G = client(disco.ana.id), disco.group.id
    assert c.get('/api/discover', query_string={'group_id': G}).status_code == 200
    assert c.get('/api/discover/browse', query_string={'group_id': G, 'when': 'month'}).status_code == 200
    assert c.get('/api/discover/browse', query_string={'group_id': G, 'from': 'nope'}).status_code == 400
    assert c.get('/api/discover', query_string={'group_id': 1}).status_code == 403
    assert client().get('/api/discover', query_string={'group_id': G}).status_code == 401

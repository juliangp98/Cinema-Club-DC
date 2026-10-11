"""discover_engine"""
from helpers import H, client, Checks, WORK


def test_discover_engine():
    checks = Checks()
    check = checks.check
    import sys, json, random
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist)
    import discover as D


    # Fixed "now": Wednesday 2026-10-07 12:00
    NOW = datetime(2026, 10, 7, 12, 0)
    print('--- windows ---')
    s, e = D.window('tonight', NOW); check('tonight = now → end of today', s == NOW and e.date() == NOW.date() and e.hour == 23)
    s, e = D.window('weekend', NOW); check('weekend from a Wednesday = Fri 5pm → Sun night', s == datetime(2026, 10, 9, 17) and e.date() == datetime(2026, 10, 11).date())
    s, e = D.window('weekend', datetime(2026, 10, 10, 14)); check('on Saturday: now → Sunday night', s == datetime(2026, 10, 10, 14) and e.date() == datetime(2026, 10, 11).date())
    s, e = D.window(None, NOW, '2026-10-09', '2026-10-10'); check('explicit dates', s == datetime(2026, 10, 9) and e.date() == datetime(2026, 10, 10).date())
    check('accent-insensitive search text', D.normalize('SIRÂT') == 'sirat')

    with app.app_context():
        db.create_all(); migrate()
        th = {t.slug: t for t in Theatre.query.filter(Theatre.slug.in_(['afi', 'suns', 'alamo-dc', 'alamo-crystal', 'regal-gallery', 'smi-dc']))}
        g = Group(name='Disco', slug='disco-r3', is_public=False); db.session.add(g); db.session.flush()
        films = {}
        def film(title, year, genres='', runtime=100, **kw):
            m = Movie(title=title, release_year=str(year), genres=genres, runtime_minutes=runtime, **kw); db.session.add(m); db.session.flush()
            films[title] = m; return m
        def show(m, slug, day, hour, minute=0, fmt=None, event=None, end=None):
            st = NOW.replace(hour=0) + timedelta(days=day, hours=hour, minutes=minute)
            s = Showtime(movie_id=m.id, theatre_id=th[slug].id, start_time=st, end_time=end or st + timedelta(minutes=(m.runtime_minutes or 100) + 15),
                         format_label=fmt, event_label=event)
            db.session.add(s); db.session.flush(); return s
        conv = film('THE CONVERSATION', 1974, 'drama,thriller,mystery', 113, director='Francis Ford Coppola',
                    cast_json=json.dumps([{'name': 'Gene Hackman'}, {'name': 'John Cazale'}]))
        show(conv, 'afi', 1, 19, fmt='35mm')
        blk = film('BIG HIT', 2026, 'action,adventure', 160)
        for d in range(5):
            for slug in ('alamo-dc', 'alamo-crystal', 'regal-gallery'):
                show(blk, slug, d, 13); show(blk, slug, d, 19, 30)
        art = film('QUIET ROOM', 2025, 'drama', 88)
        show(art, 'suns', 2, 19); show(art, 'suns', 3, 19)
        imax = film('SPACE DOC', 2024, 'documentary', 45)
        show(imax, 'smi-dc', 0, 14); show(imax, 'smi-dc', 1, 14)
        qa = film('LOCAL STORY', 2026, 'documentary', 90)
        show(qa, 'afi', 3, 19, event='LOCAL STORY + Q&A with the director')
        late = film('MIDNIGHT MADNESS', 1985, 'horror,comedy', 92)
        show(late, 'alamo-dc', 0, 23, 15)
        # double feature at Suns on day 5: 7:00 (ends 8:55) then 9:30 (gap 35)
        a = film('PSYCHO', 1960, 'horror,thriller', 100, director='Alfred Hitchcock')
        b = film('THE BIRDS', 1963, 'horror,thriller', 119, director='Alfred Hitchcock')
        show(a, 'suns', 5, 19, end=NOW.replace(hour=0) + timedelta(days=5, hours=20, minutes=55))
        show(b, 'suns', 5, 21, 30)
        users = [User(email=f'u{i}@r3.test', name=n, is_active=True, favorite_genres=fg)
                 for i, (n, fg) in enumerate([('Ana', 'horror'), ('Bo', ''), ('Cy', '')])]
        db.session.add_all(users); db.session.flush()
        for u in users:
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        db.session.add_all([Watchlist(user_id=users[0].id, movie_id=art.id), Watchlist(user_id=users[1].id, movie_id=art.id),
                            Watchlist(user_id=users[0].id, movie_id=conv.id)])
        bs = Showtime.query.filter_by(movie_id=blk.id).first()
        db.session.add(RSVP(user_id=users[1].id, showtime_id=bs.id, group_id=g.id, status='going'))
        db.session.commit()
        G, A = g.id, users[0].id

        group, ana = db.session.get(Group, G), db.session.get(User, A)
        start, end = D.window('2weeks', NOW)
        cat = D.catalog(group, start, end, ana)
        ctx = D.context(group, ana, cat, NOW)
        sh = lambda key: [f.movie.title for f, _ in D.shelf(key, cat, ctx)]
        reasons = lambda key, title: next(r for f, r in D.shelf(key, cat, ctx) if f.movie.title == title)
        print('--- shelves ---')
        check('rare: the one-night 35mm 1974 print first, with reasons', sh('rare')[0] == 'THE CONVERSATION'
              and reasons('rare', 'THE CONVERSATION') == ['one night only', '35mm', '1974'], sh('rare'))
        check('rare excludes the wide release', 'BIG HIT' not in sh('rare'))
        check('one night only', set(sh('one-night')) >= {'THE CONVERSATION', 'LOCAL STORY', 'MIDNIGHT MADNESS', 'PSYCHO', 'THE BIRDS'}
              and 'QUIET ROOM' not in sh('one-night'))
        check('on film = 35mm print', sh('on-film') == ['THE CONVERSATION'])
        check('big screen = IMAX theatre', sh('big-screen') == ['SPACE DOC'] and reasons('big-screen', 'SPACE DOC') == ['IMAX'])
        check('special events from billing', sh('events') == ['LOCAL STORY'] and reasons('events', 'LOCAL STORY') == ['Q&A'])
        check('blockbusters: recent, 3+ theatres, 10+ showings', sh('blockbusters') == ['BIG HIT'])
        check('arthouse: recent, one arthouse venue', 'QUIET ROOM' in sh('arthouse') and 'BIG HIT' not in sh('arthouse'))
        check('classics: 20+ years, rarest first', sh('classics')[0] == 'THE CONVERSATION' and 'MIDNIGHT MADNESS' in sh('classics'))
        check('friends going', sh('friends') == ['BIG HIT'] and reasons('friends', 'BIG HIT') == ['1 going'])
        check('most wanted: by watchlist count', sh('most-wanted')[0] == 'QUIET ROOM' and reasons('most-wanted', 'QUIET ROOM') == ['2 want to see it'])
        check('for you: your watchlist first, then your genres', set(sh('for-you')[:2]) == {'QUIET ROOM', 'THE CONVERSATION'}
              and 'PSYCHO' in sh('for-you'), sh('for-you'))
        check('short & epics', 'SPACE DOC' in sh('short') and sh('epics') == ['BIG HIT'])
        check('late night (9:30pm+)', sh('late-night')[:2] == ['MIDNIGHT MADNESS', 'BIG HIT'] or set(sh('late-night')) >= {'MIDNIGHT MADNESS', 'THE BIRDS'}, sh('late-night'))
        check('documentaries / horror genre shelves', set(sh('documentaries')) == {'SPACE DOC', 'LOCAL STORY'} and 'PSYCHO' in sh('horror'))
        df = D.double_features(cat)
        check('double feature: same theatre, 35-min gap', any(x['first']['movie']['title'] == 'PSYCHO' and x['second']['movie']['title'] == 'THE BIRDS'
              and x['gap_minutes'] == 35 for x in df), df[:2])
        sp = D.spotlights(group, ana, NOW)
        check('spotlight: a director with 2 films', any(x['role'] == 'director' and x['name'] == 'Alfred Hitchcock' and x['count'] == 2 for x in sp), sp)

        print('--- browse ---')
        B = lambda **p: D.browse(group, ana, p, now=NOW)
        titles = lambda r: [c['movie']['title'] for c in r['films']]
        check('when=tonight', set(titles(B(when='tonight'))) == {'BIG HIT', 'SPACE DOC', 'MIDNIGHT MADNESS'}, titles(B(when='tonight')))
        check('genres', set(titles(B(when='2weeks', genres='horror'))) == {'PSYCHO', 'THE BIRDS', 'MIDNIGHT MADNESS'})
        check('mood maps to genres', 'THE CONVERSATION' in titles(B(when='2weeks', mood='mind-bender')))
        check('decade', titles(B(when='2weeks', decade='1960')) == ['PSYCHO', 'THE BIRDS'])
        check('format=film', titles(B(when='2weeks', format='film')) == ['THE CONVERSATION'])
        check('format=big', titles(B(when='2weeks', format='big')) == ['SPACE DOC'])
        check('time=late keeps only late showings', set(titles(B(when='2weeks', time='late'))) == {'MIDNIGHT MADNESS', 'THE BIRDS'}, titles(B(when='2weeks', time='late')))
        check('theatres filter', titles(B(when='2weeks', theatres='suns')) == ['QUIET ROOM', 'PSYCHO', 'THE BIRDS'])
        check('regions filter (Virginia)', titles(B(when='2weeks', regions='virginia')) == ['BIG HIT'])
        check('rarity tiers', 'BIG HIT' in titles(B(when='2weeks', rarity='wide')) and 'THE CONVERSATION' in titles(B(when='2weeks', rarity='rare'))
              and 'QUIET ROOM' not in titles(B(when='2weeks', rarity='repertory')))
        check('club filters', titles(B(when='2weeks', club='going')) == ['BIG HIT'] and set(titles(B(when='2weeks', club='mine'))) == {'QUIET ROOM', 'THE CONVERSATION'})
        check('runtime', 'BIG HIT' in titles(B(when='2weeks', runtime='long')) and 'SPACE DOC' in titles(B(when='2weeks', runtime='short')))
        check('search: title, director, cast', titles(B(when='2weeks', q='conversation')) == ['THE CONVERSATION']
              and titles(B(when='2weeks', q='hitchcock')) == ['PSYCHO', 'THE BIRDS'] and titles(B(when='2weeks', q='HACKMAN')) == ['THE CONVERSATION'])
        check('shelf as a filter keeps the shelf order + title', B(when='2weeks', shelf='rare')['title'] == 'Rare gems'
              and titles(B(when='2weeks', shelf='rare'))[0] == 'THE CONVERSATION')
        check('sort=title', titles(B(when='2weeks', sort='title'))[0] == 'BIG HIT')
        r = D.browse(group, ana, {'when': '2weeks'}, now=NOW, limit=3)
        r2 = D.browse(group, ana, {'when': '2weeks'}, now=NOW, limit=3, offset=3)
        check('pagination', r['total'] == 8 and r['next_offset'] == 3 and not set(titles(r)) & set(titles(r2)), (r['total'], titles(r), titles(r2)))
        check('facets', r['facets']['genres'].get('horror') == 3 and r['facets']['decades'].get('1960') == 2 and r['facets']['theatres'].get('suns') == 3, r['facets'])
        c = B(when='2weeks', q='conversation')['films'][0]
        check('card shape', c['next']['theatre'] == 'AFI' and c['showings'] == 1 and c['club']['you_want'] and c['reasons'][:2] == ['one night only', '35mm'], c)

        print('--- surprise ---')
        p = D.surprise(group, ana, 'tonight', now=NOW, rng=random.Random(1))
        check('surprise picks something playing tonight', p and p['when'] == 'tonight' and p['movie']['title'] in {'BIG HIT', 'SPACE DOC', 'MIDNIGHT MADNESS'})
        ex = [films[t].id for t in ('BIG HIT', 'SPACE DOC', 'MIDNIGHT MADNESS')]
        p = D.surprise(group, ana, 'tonight', exclude=ex, now=NOW, rng=random.Random(1))
        check('nothing left tonight → widens to the week', p and p['when'] == 'week' and p['movie']['id'] not in ex, p and p['when'])
        picks = [D.surprise(group, ana, 'week', now=NOW, rng=random.Random(i))['movie']['title'] for i in range(300)]
        check('weighted toward rare and your genres', picks.count('THE CONVERSATION') > picks.count('BIG HIT'), (picks.count('THE CONVERSATION'), picks.count('BIG HIT')))

    c = app.test_client()
    with c.session_transaction() as s: s['user_id'] = A
    print('--- routes ---')
    check('/api/discover', c.get('/api/discover', query_string={'group_id': G}).status_code == 200)
    check('/api/discover/browse', c.get('/api/discover/browse', query_string={'group_id': G, 'when': 'month'}).status_code == 200)
    check('bad dates -> 400', c.get('/api/discover/browse', query_string={'group_id': G, 'from': 'nope'}).status_code == 400)
    check('non-member -> 403', c.get('/api/discover', query_string={'group_id': 1}).status_code == 403)
    check('signed out -> 401', app.test_client().get('/api/discover', query_string={'group_id': G}).status_code == 401)
    checks.done()

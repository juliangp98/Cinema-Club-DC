"""film_pages"""
from helpers import H, client, Checks, WORK


def test_film_pages():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist, Attendance)


    with app.app_context():
        db.create_all(); migrate()
        now = datetime.now()
        afi, suns, alamo = (Theatre.query.filter_by(slug=s).first() for s in ('afi', 'suns', 'alamo-dc'))
        g = Group(name='Film Club', slug='film-club-r2', is_public=False, theatres='afi,suns'); db.session.add(g); db.session.flush()
        m = Movie(title='THE CONVERSATION', release_year='1974', director='Francis Ford Coppola', description='A surveillance expert ' * 20,
                  backdrop_url='https://image.tmdb.org/t/p/w1280/x.jpg', poster_url='https://image.tmdb.org/t/p/w500/p.jpg')
        db.session.add(m); db.session.flush()
        def show(th, hours, fmt=None):
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(hours=hours), end_time=now + timedelta(hours=hours + 2), format_label=fmt)
            db.session.add(s); db.session.flush(); return s
        s1 = show(afi, 30, '35mm'); s_other = show(alamo, 40); past = show(suns, -48); s_later = show(suns, 24 * 20)
        ana, bo, cy, out = (User(email=f'{n}@r2.test', name=n.title(), is_active=True) for n in ('ana', 'bo', 'cy', 'out'))
        db.session.add_all([ana, bo, cy, out]); db.session.flush()
        for u in (ana, bo, cy):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        db.session.add_all([Watchlist(user_id=ana.id, movie_id=m.id), Watchlist(user_id=out.id, movie_id=m.id),
                            RSVP(user_id=bo.id, showtime_id=s1.id, group_id=g.id, status='going'),
                            RSVP(user_id=ana.id, showtime_id=s1.id, group_id=g.id, status='maybe'),
                            Attendance(user_id=cy.id, showtime_id=past.id, status='went', answered_at=datetime.utcnow())])
        db.session.commit()
        G, MID, S1, SL, A, O = g.id, m.id, s1.id, s_later.id, ana.id, out.id

    def as_user(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, o, anon = as_user(A), as_user(O), app.test_client()

    print('--- film page data ---')
    d = a.get(f'/api/films/{MID}', query_string={'group_id': G}).get_json()
    check("upcoming showings at the group's theatres only, soonest first", [s['id'] for s in d['showtimes']] == [S1, SL], [s['id'] for s in d['showtimes']])
    check('each showing carries RSVP state and who is going (movie sent once, at the top)',
          d['showtimes'][0]['user_rsvp'] == 'maybe' and [x['name'] for x in d['showtimes'][0]['attendees']] == ['Bo']
          and 'movie' not in d['showtimes'][0] and d['movie']['title'] == 'THE CONVERSATION')
    check('club: who wants it (members only), is going, has seen it', [u['name'] for u in d['club']['wanters']] == ['Ana']
          and [u['name'] for u in d['club']['going']] == ['Bo'] and [u['name'] for u in d['club']['seen']] == ['Cy'], d['club'])
    check('viewer_wants', d['viewer_wants'] is True)
    check("rare this week: one night, 35mm, 1974", d['rare'] and d['rare']['reasons'] == ['one night only', '35mm', '1974'], d['rare'])
    check('not a member -> 403', o.get(f'/api/films/{MID}', query_string={'group_id': G}).status_code == 403)
    check('unknown film -> 404', a.get('/api/films/999999', query_string={'group_id': G}).status_code == 404)
    check('signed out -> 401', anon.get(f'/api/films/{MID}', query_string={'group_id': G}).status_code == 401)

    print('--- link previews ---')
    h = anon.get(f'/api/og/films/{MID}').get_data(as_text=True)
    check('film preview: public, title with year, large image card', 'og:title" content="THE CONVERSATION (1974)"' in h
          and 'summary_large_image' in h and 'w1280/x.jpg' in h, h[:400])
    check('…next showing with format, count across theatres, director', '35mm' in h and '3 showings at 3 theatres' in h
          and 'Dir. Francis Ford Coppola' in h, h)
    check('…description trimmed with an ellipsis', '…' in h and h.count('surveillance expert') < 20)
    check('…points people at the real page', f'/films/{MID}"' in h and 'http-equiv="refresh"' in h)
    h = anon.get(f'/api/og/showtimes/{S1}').get_data(as_text=True)
    check('screening preview: film, time, theatre, format', 'THE CONVERSATION —' in h and 'AFI Silver Theatre · 35mm' in h
          and f'/calendar?showtime={S1}' in h, h[:500])
    check("previews never show who's going", all(n not in h for n in ('Ana', 'Bo', 'Cy')))
    check('unknown ids get a generic card', '<title>Cinema Club DC</title>' in anon.get('/api/og/films/999999').get_data(as_text=True)
          and '<title>Cinema Club DC</title>' in anon.get('/api/og/showtimes/999999').get_data(as_text=True))
    check('titles are HTML-escaped', True)
    with app.app_context():
        mm = db.session.get(Movie, MID); mm.title = 'A "quoted" <b>title</b>'; db.session.commit()
    h = anon.get(f'/api/og/films/{MID}').get_data(as_text=True)
    check('…really escaped', '&quot;quoted&quot; &lt;b&gt;' in h and '<b>title' not in h)
    checks.done()

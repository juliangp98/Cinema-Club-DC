"""A film's page (R2): its showings at the club's theatres, where the club
stands on it, rarity; and its link previews."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def film():
    """THE CONVERSATION (1974) in a club at AFI + Suns: a 35mm showing at AFI
    tomorrow-ish, one at Alamo (not the club's), a past one at Suns, a later
    one at Suns. Ana wants it (and maybe goes), Bo's going, Cy saw it; an
    outsider wants it too."""
    from app import app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist, Attendance
    setup_db()
    with app.app_context():
        now = datetime.now()
        afi, suns, alamo = (Theatre.query.filter_by(slug=s).first() for s in ('afi', 'suns', 'alamo-dc'))
        g = Group(name='Film Club', slug='film-club-r2', is_public=False, theatres='afi,suns')
        db.session.add(g)
        db.session.flush()
        m = Movie(title='THE CONVERSATION', release_year='1974', director='Francis Ford Coppola',
                  description='A surveillance expert ' * 20,
                  backdrop_url='https://image.tmdb.org/t/p/w1280/x.jpg', poster_url='https://image.tmdb.org/t/p/w500/p.jpg')
        db.session.add(m)
        db.session.flush()

        def show(th, hours, fmt=None):
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(hours=hours),
                         end_time=now + timedelta(hours=hours + 2), format_label=fmt)
            db.session.add(s)
            db.session.flush()
            return s
        s1, _, past, later = show(afi, 30, '35mm'), show(alamo, 40), show(suns, -48), show(suns, 24 * 20)
        ana, bo, cy, out = (User(email=f'{n}@r2.test', name=n.title(), is_active=True) for n in ('ana', 'bo', 'cy', 'out'))
        db.session.add_all([ana, bo, cy, out])
        db.session.flush()
        for u in (ana, bo, cy):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        db.session.add_all([Watchlist(user_id=ana.id, movie_id=m.id), Watchlist(user_id=out.id, movie_id=m.id),
                            RSVP(user_id=bo.id, showtime_id=s1.id, group_id=g.id, status='going'),
                            RSVP(user_id=ana.id, showtime_id=s1.id, group_id=g.id, status='maybe'),
                            Attendance(user_id=cy.id, showtime_id=past.id, status='went', answered_at=datetime.utcnow())])
        db.session.commit()
        return {'group': g.id, 'movie': m.id, 's1': s1.id, 'later': later.id, 'ana': ana.id, 'out': out.id}


def page(f, uid):
    return client(uid).get(f"/api/films/{f['movie']}", query_string={'group_id': f['group']})


def test_showings_at_the_clubs_theatres_with_rsvps(film):
    d = page(film, film['ana']).json
    assert [s['id'] for s in d['showtimes']] == [film['s1'], film['later']]       # soonest first, club's theatres
    first = d['showtimes'][0]
    assert first['user_rsvp'] == 'maybe' and [x['name'] for x in first['attendees']] == ['Bo']
    assert 'movie' not in first and d['movie']['title'] == 'THE CONVERSATION'      # the film is sent once


def test_where_the_club_stands_and_rarity(film):
    d = page(film, film['ana']).json
    club = d['club']
    assert [u['name'] for u in club['wanters']] == ['Ana']                        # members only
    assert [u['name'] for u in club['going']] == ['Bo'] and [u['name'] for u in club['seen']] == ['Cy']
    assert d['viewer_wants'] is True
    assert d['rare']['reasons'] == ['one night only', '35mm', '1974']


def test_club_mode_needs_membership(film):
    assert page(film, film['out']).status_code == 403
    assert client(film['ana']).get('/api/films/999999', query_string={'group_id': film['group']}).status_code == 404
    assert page(film, None).status_code == 401


def test_film_link_preview(film):
    h = client().get(f"/api/og/films/{film['movie']}").get_data(as_text=True)
    assert 'og:title" content="THE CONVERSATION (1974)"' in h and 'summary_large_image' in h and 'w1280/x.jpg' in h
    assert '35mm' in h and '3 showings at 3 theatres' in h and 'Dir. Francis Ford Coppola' in h
    assert '…' in h and h.count('surveillance expert') < 20                      # description trimmed
    assert f"/films/{film['movie']}\"" in h and 'http-equiv="refresh"' in h     # sends people on to the page


def test_screening_link_preview_never_names_people(film):
    h = client().get(f"/api/og/showtimes/{film['s1']}").get_data(as_text=True)
    assert 'THE CONVERSATION —' in h and 'AFI Silver Theatre · 35mm' in h and f"/calendar?showtime={film['s1']}" in h
    assert all(n not in h for n in ('Ana', 'Bo', 'Cy'))


def test_previews_for_unknown_ids_and_escaping(film):
    from app import app, db, Movie
    for path in ('/api/og/films/999999', '/api/og/showtimes/999999'):
        assert '<title>Cinema Club DC</title>' in client().get(path).get_data(as_text=True)
    with app.app_context():
        db.session.get(Movie, film['movie']).title = 'A "quoted" <b>title</b>'
        db.session.commit()
    h = client().get(f"/api/og/films/{film['movie']}").get_data(as_text=True)
    assert '&quot;quoted&quot; &lt;b&gt;' in h and '<b>title' not in h

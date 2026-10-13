"""Your taste, shared (R13): an alert when a theatre books a favorite's film,
and taste match on profiles and Compare — only for people who show their taste."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    """Ana loves Agnès Varda and CLÉO; Bo watchlists CLÉO. Both in club 1."""
    import taste
    from app import app, db, GroupMembership, Movie, User, Watchlist
    setup_db()
    with app.app_context():
        ana, bo = User(name='Ana', email='ana@ts.test', is_active=True), User(name='Bo', email='bo@ts.test', is_active=True)
        cleo = Movie(title='CLÉO FROM 5 TO 7', director='Agnès Varda', release_year='1962')
        gleaners = Movie(title='THE GLEANERS AND I', director='Agnès Varda', release_year='2000',
                         cast_json='[{"name": "Agnès Varda"}]')
        other = Movie(title='SOMETHING ELSE', director='Someone Else')
        db.session.add_all([ana, bo, cleo, gleaners, other])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        db.session.add(Watchlist(user_id=bo.id, movie_id=cleo.id))
        db.session.commit()
        taste.add(ana, {'kind': 'director', 'name': 'Agnès Varda'})
        taste.add(ana, {'kind': 'movie', 'movie_id': cleo.id})
        return {'ana': ana.id, 'bo': bo.id, 'cleo': cleo.id, 'gleaners': gleaners.id, 'other': other.id}


def book(c, *movies):
    """A scrape just booked these films at AFI: watchlist alerts, then favorites'."""
    import notify
    from app import app, db, Notification, Showtime, Theatre
    with app.app_context():
        afi = Theatre.query.filter_by(slug='afi').first()
        shows = [Showtime(movie_id=c[m], theatre_id=afi.id, start_time=datetime.now() + timedelta(days=3), format_label='35mm')
                 for m in movies]
        db.session.add_all(shows)
        db.session.flush()
        notify.alert_new_showings(afi, shows, set())
        made = notify.alert_favorites(afi, shows, set())
        db.session.commit()
        return made, [(n.user_id, n.kind, notify.describe(n)['detail'].split(' · ')[0])
                      for n in Notification.query.order_by(Notification.id)]


def test_a_favorites_film_booked(club):
    made, alerts = book(club, 'cleo', 'gleaners', 'other')
    assert made == 2
    assert sorted(alerts) == sorted([
        (club['bo'], 'showings', 'AFI Silver Theatre'),                        # Bo's watchlist
        (club['ana'], 'favorite', 'A favorite of yours'),                     # CLÉO
        (club['ana'], 'favorite', 'Because you love Agnès Varda (director)'),    # THE GLEANERS AND I
    ])
    assert book(club, 'gleaners')[0] == 0                                    # not again for days


def test_favorites_alerts_can_be_switched_off(club):
    client(club['ana']).put('/api/me/notifications', json={'types': {'favorites': False}})
    assert book(club, 'cleo', 'gleaners')[0] == 0
    info = client(club['ana']).get('/api/me/notifications').json['types_info']
    assert any(t['key'] == 'favorites' for t in info)


def test_taste_match_only_with_people_who_show_their_taste(club):
    ana, bo = client(club['ana']), client(club['bo'])
    bo.put('/api/me/taste', json={'genres': ['drama']})
    bo.post('/api/me/taste/items', json={'kind': 'director', 'name': 'Agnès Varda'})
    assert 'taste_match' not in ana.get(f"/api/users/{club['bo']}/profile").json
    assert ana.get(f"/api/users/{club['bo']}/compare").json['taste'] is None
    bo.put('/api/me/taste', json={'public': True})
    m = ana.get(f"/api/users/{club['bo']}/profile").json['taste_match']
    assert m == {'score': 40, 'shared': ['Agnès Varda']}                     # 2 shared of 2+2+1 weighted
    assert ana.get(f"/api/users/{club['bo']}/compare").json['taste'] == m

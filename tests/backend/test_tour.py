"""The welcome tour (R11): shown once to each account (and once to everyone
who had one when it shipped), replayable any time; whether you've seen it
is yours alone."""
import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    from app import app, db, Group, GroupMembership, User
    setup_db()
    with app.app_context():
        g = Group(name='Tour Club', slug='tour-club', is_public=False)
        ana, bo = User(name='Ana', email='ana@t.test', is_active=True), User(name='Bo', email='bo@t.test', is_active=True)
        db.session.add_all([g, ana, bo])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        db.session.commit()
        return {'Ana': ana.id, 'Bo': bo.id}


def me(c, who='Ana'):
    return client(c[who]).get('/api/auth/me').json['user']


def test_the_tour_shows_until_its_finished_or_skipped(club):
    assert me(club)['tour_seen'] is False
    r = client(club['Ana']).post('/api/me/tour')
    assert r.status_code == 200 and r.json == {'tour_seen': True}
    assert me(club)['tour_seen'] is True and me(club, 'Bo')['tour_seen'] is False
    assert client(club['Ana']).post('/api/me/tour').json == {'tour_seen': True}       # replaying changes nothing


def test_only_you_see_whether_you_took_the_tour(club):
    theirs = client(club['Bo']).get(f"/api/users/{club['Ana']}/profile").json
    assert 'tour_seen' not in theirs and 'name' in theirs


def test_signed_out_visitors_have_no_tour_to_finish():
    setup_db()
    assert client().post('/api/me/tour').status_code == 401

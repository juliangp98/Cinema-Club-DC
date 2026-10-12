"""Members don't see each other's emails (or private settings); club admins
see emails."""
import json
import re

import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    """A private club: an admin, me, and another member; a scored poll."""
    from app import app, db, User, Group, GroupMembership, Poll
    setup_db()
    with app.app_context():
        ad = User(email='admin@p.test', name='Ad', is_active=True)
        me = User(email='member@p.test', name='Me', is_active=True)
        other = User(email='other@p.test', name='Other', is_active=True)
        db.session.add_all([ad, me, other])
        db.session.flush()
        g = Group(name='Private Club', slug='private-club', is_public=False)
        db.session.add(g)
        db.session.flush()
        for u, r in ((ad, 'admin'), (me, 'member'), (other, 'member')):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, role=r, status='active'))
        p = Poll(group_id=g.id, created_by=ad.id, title='P', status='scored')
        db.session.add(p)
        db.session.commit()
        return {'admin': ad.id, 'me': me.id, 'other': other.id, 'group': g.id, 'slug': g.slug, 'poll': p.id}


def emails(obj):
    return set(re.findall(r'[\w.]+@p\.test', json.dumps(obj)))


def test_members_list_shows_emails_to_admins_only(club):
    url = f"/api/groups/{club['slug']}/members"
    assert emails(client(club['me']).get(url).json) == set()
    assert emails(client(club['admin']).get(url).json) == {'admin@p.test', 'member@p.test', 'other@p.test'}
    assert emails(client(club['me']).get(f"/api/groups/{club['slug']}").json) == set()


def test_profiles_hide_email_and_private_settings(club):
    theirs = client(club['me']).get(f"/api/users/{club['other']}/profile").json
    assert 'email' not in theirs and 'share_prefs' not in theirs
    assert client(club['admin']).get(f"/api/users/{club['other']}/profile").json.get('email') == 'other@p.test'
    assert client(club['me']).get(f"/api/users/{club['me']}/profile").json['email'] == 'member@p.test'
    assert client(club['me']).get('/api/auth/me').json['user']['email'] == 'member@p.test'


def test_leaderboards_never_show_emails(club):
    for who in ('me', 'admin'):
        assert emails(client(club[who]).get(f"/api/groups/{club['group']}/leaderboard").json) == set()
    assert emails(client(club['me']).get(f"/api/polls/{club['poll']}/leaderboard").json) == set()

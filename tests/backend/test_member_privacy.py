"""Members don't see each other's emails (or private settings); club admins see emails."""
from helpers import H, client, Checks, WORK


def test_member_privacy():
    checks = Checks()
    check = checks.check
    import sys, json
    from app import app, db, migrate, User, Group, GroupMembership, Poll
    with app.app_context():
        db.create_all(); migrate()
        ad = User(email='admin@p.test', name='Ad', is_active=True)
        me = User(email='member@p.test', name='Me', is_active=True)
        other = User(email='other@p.test', name='Other', is_active=True)
        db.session.add_all([ad, me, other]); db.session.flush()
        g = Group(name='Private Club', slug='private-club', is_public=False); db.session.add(g); db.session.flush()
        for u, r in ((ad, 'admin'), (me, 'member'), (other, 'member')):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, role=r, status='active'))
        p = Poll(group_id=g.id, created_by=ad.id, title='P', status='scored'); db.session.add(p)
        db.session.commit()
        AD, ME, OT, G, SLUG, PID = ad.id, me.id, other.id, g.id, g.slug, p.id
    def client(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    m, a = client(ME), client(AD)
    def emails(obj): return set(__import__('re').findall(r'[\w.]+@p\.test', json.dumps(obj)))
    check('members list: no emails for a member', emails(m.get(f'/api/groups/{SLUG}/members').json) == set())
    check('…club admins see them', emails(a.get(f'/api/groups/{SLUG}/members').json) == {'admin@p.test', 'member@p.test', 'other@p.test'})
    check('club details: none for a member', emails(m.get(f'/api/groups/{SLUG}').json) == set())
    check("someone's profile: no email, no private settings", 'email' not in m.get(f'/api/users/{OT}/profile').json
          and 'share_prefs' not in m.get(f'/api/users/{OT}/profile').json)
    check("…an admin of a shared club sees the email", a.get(f'/api/users/{OT}/profile').json.get('email') == 'other@p.test')
    check('your own profile still has yours', m.get(f'/api/users/{ME}/profile').json['email'] == 'member@p.test'
          and m.get('/api/auth/me').json['user']['email'] == 'member@p.test')
    check('leaderboard: no emails', emails(m.get(f'/api/groups/{G}/leaderboard').json) == set() and emails(a.get(f'/api/groups/{G}/leaderboard').json) == set())
    check('poll leaderboard: no emails', emails(m.get(f'/api/polls/{PID}/leaderboard').json) == set())
    checks.done()

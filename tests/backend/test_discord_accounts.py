"""discord_accounts"""
from helpers import H, client, Checks, WORK


def test_discord_accounts():
    checks = Checks()
    check = checks.check
    import os, sqlite3, sys
    from datetime import datetime, timedelta
    from urllib.parse import urlparse, parse_qs
    DBPATH = os.environ['DATABASE_URL'].replace('sqlite:///', '')
    pre = sqlite3.connect(DBPATH)
    before = {t: pre.execute(f'select count(*) from "{t}"').fetchone()[0] for t in ('user', 'rsvp', 'watchlist', 'group_membership')}
    pre.close()
    import app as A
    from app import app, db, migrate, User, GroupMembership, RSVP, Watchlist, Showtime, Movie, Reaction, INTERNAL_API_TOKEN

    H = {'X-Internal-Token': INTERNAL_API_TOKEN}
    c = app.test_client()

    print('--- migration ---')
    with app.app_context():
        db.create_all(); migrate()
        ddl = db.session.execute(db.text("select sql from sqlite_master where name='user'")).scalar()
        check('user.email now nullable', 'email VARCHAR(120) NOT NULL' not in ddl and 'email VARCHAR(120)' in ddl)
        after = {t: db.session.execute(db.text(f'select count(*) from "{t}"')).scalar() for t in before}
        check('all rows preserved', after == before, (before, after))
        admin = User.query.filter_by(email='sunscinemafanclub@gmail.com').first()
        check('existing accounts intact (admin keeps email + group)', admin and GroupMembership.query.filter_by(user_id=admin.id, group_id=1).first())
        check('backup written next to the DB', os.path.exists(DBPATH + '.pre-discord-accounts.bak'))
        idx = db.session.execute(db.text("select name from sqlite_master where type='index' and name='ux_user_discord_user_id'")).scalar()
        check('unique Discord-id index added', idx == 'ux_user_discord_user_id')
        migrate()   # second boot
        check('migration is idempotent', 'NOT NULL' not in db.session.execute(db.text("select sql from sqlite_master where name='user'")).scalar().split('email')[1].split(',')[0])
        sid = Showtime.query.filter(Showtime.movie_id == Movie.query.filter_by(title='SIRÂT').first().id).first().id
        movie_title = db.session.get(Movie, db.session.get(Showtime, sid).movie_id).title

    print('--- Discord-only accounts ---')
    ident = {'discord_user_id': '5001', 'discord_name': 'Ana (server nick)', 'discord_username': 'ana_d',
             'discord_avatar': 'https://cdn.discordapp.com/a.png', 'group_id': 1}
    r = c.post('/api/internal/rsvp', json={**ident, 'create': False, 'showtime_id': sid, 'status': 'going'}, headers=H)
    check('outside the home server: no account is created', r.status_code == 404 and r.get_json()['error'] == 'no_account')
    r = c.post('/api/internal/rsvp', json={**ident, 'create': True, 'showtime_id': sid, 'status': 'going'}, headers=H)
    check('in the home server: RSVP works with no site account', r.status_code == 200 and any(a['name'] == 'Ana (server nick)' for a in r.get_json()['attendees']), r.get_json())
    with app.app_context():
        ana = User.query.filter_by(discord_user_id='5001').first()
        check('Discord-only account: no email, handle + avatar stored', ana and ana.email is None and ana.discord_username == 'ana_d' and ana.avatar_url)
        check('…and is an active member of the server group', GroupMembership.query.filter_by(user_id=ana.id, group_id=1, status='active').first() is not None)
        ANA = ana.id
    c.post('/api/internal/watch', json={**ident, 'create': True, 'discord_name': 'Ana B', 'title': movie_title, 'action': 'add'}, headers=H)
    with app.app_context():
        check('repeat use: same account, no duplicate', User.query.filter_by(discord_user_id='5001').count() == 1)
        check('Discord-only name follows Discord', db.session.get(User, ANA).name == 'Ana B')
    d = c.get('/api/internal/watchlist', query_string={**ident, 'create': True, 'discord_name': 'Ana B'}, headers=H).get_json()
    check('/watch show works for a Discord-only member', d['owner'] == 'Ana B' and len(d['items']) == 1, d)
    d = c.get('/api/internal/watchlist', query_string={'member_id': ANA}, headers=H).get_json()
    check("viewing someone else's watchlist needs no account", d['owner'] == 'Ana B')
    members = c.get('/api/internal/members?group_id=1', headers=H).get_json()
    check('shows up in the member picker', any(m['id'] == ANA for m in members))

    print('--- /profile endpoints ---')
    p = c.get('/api/internal/profile', query_string={**ident, 'create': True, 'discord_name': 'Ana B'}, headers=H).get_json()
    check('own profile + genre options', p['user']['id'] == ANA and 'horror' in p['genre_options'] and p['site_account'] is False and p['upcoming_rsvps'] == 0, p)
    p = c.post('/api/internal/profile', json={**ident, 'create': True, 'discord_name': 'Ana B', 'favorite_genres': ['Horror', 'noir', 'not-a-genre'],
               'bio': '  i like it scary  ', 'letterboxd_username': 'ana d!'}, headers=H).get_json()
    check('update: genres validated, bio trimmed, Letterboxd sanitized',
          p['genres'] == ['horror', 'noir'] and p['user']['bio'] == 'i like it scary' and p['user']['letterboxd_username'] == 'anad', p)
    check("someone else's profile (no account) -> 404", c.get('/api/internal/profile', query_string={'member_discord_id': '7777'}, headers=H).status_code == 404)
    check("someone else's profile (has account)", c.get('/api/internal/profile', query_string={'member_discord_id': '5001'}, headers=H).get_json()['user']['name'] == 'Ana B')

    print('--- /link merges a Discord-only account ---')
    with app.app_context():
        site = User(email='ana@test.dev', name='Ana Site', is_active=True); db.session.add(site); db.session.flush()
        db.session.add(GroupMembership(user_id=site.id, group_id=1, status='pending'))
        db.session.add(RSVP(user_id=site.id, showtime_id=sid, group_id=1, status='maybe'))   # clashes with Ana's 'going'
        db.session.add(Reaction(user_id=ANA, showtime_id=sid, group_id=1, emoji='\U0001F37F'))
        site.discord_link_code = 'ABC234'; site.discord_link_code_expires = datetime.utcnow() + timedelta(minutes=5)
        db.session.commit(); SITE = site.id
    r = c.post('/api/internal/link/verify', json={'code': 'abc234', 'discord_user_id': '5001', 'discord_username': 'ana_d'}, headers=H)
    with app.app_context():
        site = db.session.get(User, SITE)
        check('link succeeds and the site account takes the Discord id', r.status_code == 200 and site.discord_user_id == '5001', r.get_json())
        check('Discord-only account is gone', db.session.get(User, ANA) is None)
        check('watchlist + reaction moved over', Watchlist.query.filter_by(user_id=SITE).count() == 1 and Reaction.query.filter_by(user_id=SITE).count() == 1)
        rs = RSVP.query.filter_by(user_id=SITE, showtime_id=sid).all()
        check("clashing RSVP: the site account's own one wins", len(rs) == 1 and rs[0].status == 'maybe')
        check('pending membership upgraded to active', GroupMembership.query.filter_by(user_id=SITE, group_id=1).first().status == 'active')
        check('profile fields carried over', site.favorite_genres == 'horror,noir' and site.letterboxd_username == 'anad')
        check('site account keeps its own name', site.name == 'Ana Site')

    print('--- Sign in with Discord (OAuth) ---')
    check('providers: off when not configured', c.get('/api/auth/providers').get_json() == {'discord': False})
    A.DISCORD_CLIENT_ID, A.DISCORD_CLIENT_SECRET = 'cid', 'secret'
    check('providers: on when configured', c.get('/api/auth/providers').get_json() == {'discord': True})
    import requests
    fake_me = {}
    class Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data
    requests.post = lambda *a, **k: Resp({'access_token': 'tok'})
    requests.get = lambda *a, **k: Resp(fake_me)
    def oauth(client, mode=None):
        r = client.get('/api/auth/discord/start' + ('?mode=connect' if mode else ''))
        q = parse_qs(urlparse(r.headers['Location']).query)
        return client.get('/api/auth/discord/callback', query_string={'code': 'x', 'state': q['state'][0]})
    br = app.test_client()
    r = br.get('/api/auth/discord/start'); q = parse_qs(urlparse(r.headers['Location']).query)
    check('start: redirects to Discord with identify scope + state', r.status_code == 302 and q['scope'] == ['identify'] and q['state'])
    r = br.get('/api/auth/discord/callback', query_string={'code': 'x', 'state': 'forged'})
    check('callback with a forged state is rejected', 'discord_error=expired' in r.headers['Location'])
    fake_me.update(id='6001', username='ben_h', global_name='Ben', avatar='abc')
    r = oauth(br)
    me = br.get('/api/auth/me').get_json()['user']
    check('login: new Discord-only account, signed in', 'discord=signed_in' in r.headers['Location'] and me and me['name'] == 'Ben' and me['discord_only'], me)
    with app.app_context():
        BEN = User.query.filter_by(discord_user_id='6001').first().id
        check('…with no group yet (joins the normal way)', GroupMembership.query.filter_by(user_id=BEN).count() == 0)
    br2 = app.test_client(); oauth(br2)
    check('login again: same account', br2.get('/api/auth/me').get_json()['user']['id'] == BEN)
    fake_me.update(id='5001', username='ana_d', global_name='Ana')
    br3 = app.test_client(); oauth(br3)
    check('login as a linked member signs into their site account', br3.get('/api/auth/me').get_json()['user']['id'] == SITE)
    with app.app_context():
        carl = User(email='carl@test.dev', name='Carl', is_active=True); db.session.add(carl); db.session.commit(); CARL = carl.id
        db.session.add(Watchlist(user_id=BEN, movie_id=Movie.query.first().id)); db.session.commit()
    cc = app.test_client()
    with cc.session_transaction() as s: s['user_id'] = CARL
    fake_me.update(id='6001', username='ben_h', global_name='Ben')
    r = oauth(cc, mode='connect')
    with app.app_context():
        check('connect: merges the Discord-only account into the site account', 'discord=connected' in r.headers['Location']
              and db.session.get(User, BEN) is None and db.session.get(User, CARL).discord_user_id == '6001'
              and Watchlist.query.filter_by(user_id=CARL).count() == 1, r.headers['Location'])
    dd = app.test_client()
    with app.app_context():
        dan = User(email='dan@test.dev', name='Dan', is_active=True); db.session.add(dan); db.session.commit(); DAN = dan.id
    with dd.session_transaction() as s: s['user_id'] = DAN
    r = oauth(dd, mode='connect')
    with app.app_context():
        check("connect: refuses a Discord account linked to another site account", 'discord_error=taken' in r.headers['Location']
              and db.session.get(User, CARL).discord_user_id == '6001' and db.session.get(User, DAN).discord_user_id is None)
    checks.done()

"""R5b guest profiles: creation, private personal plans, counts, upgrades, expiry."""
from helpers import H, client, Checks, WORK


def test_guests():
    checks = Checks()
    check = checks.check
    import sys, time
    from datetime import datetime, timedelta
    from urllib.parse import urlparse, parse_qs
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist, Reaction,
                     LoginToken, INTERNAL_API_TOKEN)
    import app as A
    import requests

    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Club G', slug='club-g-r5b', is_public=True); db.session.add(g); db.session.flush()
        owner = User(email='owner@r5b.test', name='Olive Owner', is_active=True, discord_user_id='313131')
        accts = [User(email=f'a{i}@r5b.test', name=f'Acct {i}', is_active=True) for i in range(3)]
        db.session.add_all([owner, *accts]); db.session.flush()
        db.session.add(GroupMembership(user_id=owner.id, group_id=g.id, status='active', role='admin'))
        now = datetime.now()
        def film(t):
            m = Movie(title=t, release_year='2024'); db.session.add(m); db.session.flush(); return m
        m1, m2 = film('GUEST FILM ONE'), film('GUEST FILM TWO')
        s1 = Showtime(movie_id=m1.id, theatre_id=th.id, start_time=now + timedelta(days=2))
        s2 = Showtime(movie_id=m2.id, theatre_id=th.id, start_time=now + timedelta(days=3))
        db.session.add_all([s1, s2]); db.session.flush()
        db.session.add(RSVP(user_id=owner.id, showtime_id=s1.id, group_id=g.id, status='going'))
        db.session.add(Watchlist(user_id=owner.id, movie_id=m2.id))
        db.session.commit()
        G, OWNER, S1, S2, M1, M2 = g.id, owner.id, s1.id, s2.id, m1.id, m2.id
        ACCTS = [a.id for a in accts]

    def client(uid=None, ip='198.51.100.1'):
        c = app.test_client()
        c.environ_base['HTTP_CF_CONNECTING_IP'] = ip
        if uid:
            with c.session_transaction() as s: s['user_id'] = uid; s['seen'] = int(time.time())
        return c

    print('--- creating a guest ---')
    v = client()
    r = v.post('/api/auth/guest')
    gu = r.json['user']
    check('first personal action makes a private guest profile', r.status_code == 201 and gu['is_guest'] and gu['name'] == 'Guest' and gu['email'] is None)
    check('…and signs into it', v.get('/api/auth/me').json['user']['id'] == gu['id'])
    check('asking again returns the same guest', v.post('/api/auth/guest').json['user']['id'] == gu['id'])
    codes = [client(ip='203.0.113.50').post('/api/auth/guest').status_code for _ in range(6)]
    check('creation is capped per visitor (5 an hour)', codes == [201] * 5 + [429], codes)
    check('…per visitor only', client(ip='203.0.113.51').post('/api/auth/guest').status_code == 201)
    with app.app_context():
        stored = User.query.get(gu['id'])
        check('the address is stored only as a keyed hash', stored.guest_ip_hash and '198.51.100.1' not in stored.guest_ip_hash and len(stored.guest_ip_hash) == 64)

    print('--- personal plans ---')
    r = v.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going'})
    check('RSVP without a club = personal', r.status_code == 200 and r.json['user_rsvp'] == 'going' and r.json['public'] and r.json['attendees'] == [])
    check('it shows on public pages for the guest', v.get(f'/api/showtimes/{S1}').json['user_rsvp'] == 'going')
    check('…and nobody else', client().get(f'/api/showtimes/{S1}').json['user_rsvp'] is None)
    m = client(OWNER).get(f'/api/showtimes/{S1}', query_string={'group_id': G}).json
    check("never in a club's lists", [a['name'] for a in m['attendees']] == ['Olive Owner'], m['attendees'])
    lst = v.get(f"/api/users/{gu['id']}/rsvps").json
    check('your own list includes it', [i['showtime_id'] for i in lst['items']] == [S1], lst)
    check("others can't see a guest's list", client(OWNER).get(f"/api/users/{gu['id']}/rsvps").status_code == 403)
    check('"Mine" works in public Browse', [c['movie']['title'] for c in v.get('/api/discover/browse', query_string={'when': '2weeks', 'club': 'mine'}).json['films']] == ['GUEST FILM ONE'])
    v.post('/api/watchlist', json={'movie_id': M2})
    check('watchlist works for guests', any(i['movie']['id'] == M2 for i in v.get('/api/watchlist').json))
    wl = client(OWNER).get('/api/watchlist').json
    check('watchlist next showings carry no names (old leak fixed)', all(i['next_showtime']['attendees'] == [] for i in wl if i['next_showtime']))

    print('--- anonymous counts: accounts only ---')
    for ip in ('192.0.2.1', '192.0.2.2', '192.0.2.3'):
        c = client(ip=ip); c.post('/api/auth/guest'); c.post('/api/rsvp', json={'showtime_id': S2, 'status': 'going'})
        c.post('/api/reactions', json={'showtime_id': S2, 'emoji': '🔥'})
    st = client().get(f'/api/showtimes/{S2}').json
    check('3 guests going / reacting → no public count', st['interest']['going'] is None and st['reactions'] == {}, (st['interest'], st['reactions']))
    for uid in ACCTS:
        c = client(uid); c.post('/api/rsvp', json={'showtime_id': S2, 'status': 'going'}); c.post('/api/reactions', json={'showtime_id': S2, 'emoji': '🔥'})
    st = client().get(f'/api/showtimes/{S2}').json
    check('3 accounts → counted, anonymously', st['interest']['going'] == 3 and st['reactions'] == {'🔥': {'count': 3, 'users': [], 'user_reacted': False}}, st)
    r = v.post('/api/reactions', json={'showtime_id': S2, 'emoji': '🍿'})
    check('your own reaction shows (count withheld)', r.json.get('🍿') == {'count': None, 'users': [], 'user_reacted': True} and r.json['🔥']['count'] == 3, r.json)

    print('--- guests stay out of clubs ---')
    check("can't start a club", v.post('/api/groups', json={'name': 'Guest club'}).json.get('code') == 'guest')
    check("can't join one", v.post('/api/groups/club-g-r5b/join').status_code == 403)
    check("can't link Discord by code", v.post('/api/me/discord-link-code').status_code == 403)
    check("can't read club data", v.get(f'/api/showtimes/{S1}', query_string={'group_id': G}).status_code == 403)

    print('--- keeping the profile: new email ---')
    sent = {}
    A.email_signin_link = lambda email, link, purpose: sent.update(email=email, link=link)
    check('sign-up link requested as the guest', v.post('/api/auth/signup', json={'email': 'kept@r5b.test', 'name': 'Kept'}).status_code == 200)
    phone = client(ip='198.51.100.9')            # opened on another device
    r = phone.post('/api/auth/verify', json={'token': parse_qs(urlparse(sent['link']).query)['token'][0]})
    u = r.json['user']
    check('the guest profile becomes the account (same id, not a guest)', u['id'] == gu['id'] and not u['is_guest'] and u['email'] == 'kept@r5b.test' and u['name'] == 'Kept', u)
    check('its plans came along', phone.get(f'/api/showtimes/{S1}').json['user_rsvp'] == 'going')

    print('--- keeping the profile: an existing account ---')
    v2 = client(ip='198.51.100.20'); g2 = v2.post('/api/auth/guest').json['user']
    v2.post('/api/rsvp', json={'showtime_id': S2, 'status': 'maybe'}); v2.post('/api/watchlist', json={'movie_id': M2})
    v2.post('/api/auth/login', json={'email': 'owner@r5b.test'})
    r = client().post('/api/auth/verify', json={'token': parse_qs(urlparse(sent['link']).query)['token'][0]})
    with app.app_context():
        o = User.query.get(OWNER)
        check("signs into the existing account, guest folded in", r.json['user']['id'] == OWNER and User.query.get(g2['id']) is None
              and RSVP.query.filter_by(user_id=OWNER, showtime_id=S2, group_id=None).first().status == 'maybe')
        check('duplicates resolved (the account keeps its own watchlist row)', Watchlist.query.filter_by(user_id=OWNER, movie_id=M2).count() == 1)
        check("…and the account's Discord link is untouched", o.discord_user_id == '313131')

    print('--- keeping the profile: Discord ---')
    class Resp:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data
    fake_me = {}
    requests.post = lambda *a, **k: Resp({'access_token': 'tok'})
    requests.get = lambda *a, **k: Resp(fake_me)
    A.DISCORD_CLIENT_ID, A.DISCORD_CLIENT_SECRET = 'cid', 'secret'
    def oauth(c, mode=None):
        r = c.get('/api/auth/discord/start' + ('?mode=connect' if mode else ''))
        q = parse_qs(urlparse(r.headers['Location']).query)
        return c.get('/api/auth/discord/callback', query_string={'code': 'x', 'state': q['state'][0]})
    v3 = client(ip='198.51.100.30'); g3 = v3.post('/api/auth/guest').json['user']; v3.post('/api/rsvp', json={'showtime_id': S1, 'status': 'going'})
    fake_me.update(id='777000', username='newbie', global_name='Newbie')
    oauth(v3, mode='connect')        # a guest "connecting" signs in instead
    me = v3.get('/api/auth/me').json['user']
    check('new Discord: the guest profile becomes the Discord account', me['id'] == g3['id'] and not me['is_guest'] and me['discord_linked'], me)
    v4 = client(ip='198.51.100.31'); g4 = v4.post('/api/auth/guest').json['user']; v4.post('/api/watchlist', json={'movie_id': M1})
    fake_me.update(id='313131', username='olive', global_name='Olive')
    oauth(v4)
    with app.app_context():
        check('existing Discord: signed into it, guest folded in', v4.get('/api/auth/me').json['user']['id'] == OWNER
              and User.query.get(g4['id']) is None and Watchlist.query.filter_by(user_id=OWNER, movie_id=M1).count() == 1)

    print('--- expiry and sessions ---')
    with app.app_context():
        old = User(name='Guest', is_guest=True, is_active=True, last_seen_at=datetime.now() - timedelta(days=95)); db.session.add(old); db.session.flush()
        db.session.add(RSVP(user_id=old.id, showtime_id=S1, group_id=None, status='going')); db.session.commit()
        OLD = old.id
    client(ip='198.51.100.40').post('/api/auth/guest')
    with app.app_context():
        check('guests idle 90+ days are deleted (with their plans)', User.query.get(OLD) is None and RSVP.query.filter_by(user_id=OLD).count() == 0)
    m = client(OWNER)
    with m.session_transaction() as s: s['seen'] = int(time.time()) - 31 * 86400
    check('members are signed out after 30 days away', m.get('/api/auth/me').json['user'] is None)
    v5 = client(ip='198.51.100.41'); v5.post('/api/auth/guest')
    with v5.session_transaction() as s: s['seen'] = int(time.time()) - 60 * 86400
    check('guests stay signed in for 90', v5.get('/api/auth/me').json['user'] is not None)
    checks.done()

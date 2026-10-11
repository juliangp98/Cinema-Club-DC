"""R7a: calendar subscriptions, theatre pages, sitemap, link previews."""
from helpers import H, client, Checks, WORK


def test_calendar_feeds_theatres():
    checks = Checks()
    check = checks.check
    import sys, re
    import xml.etree.ElementTree as ET
    from datetime import datetime, timedelta
    from app import app, db, migrate, seed_theatres, User, Group, GroupMembership, Showtime, Movie, Theatre, RSVP

    with app.app_context():
        db.create_all(); migrate(); seed_theatres()
        afi = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Feed Club', slug='feed-r7a', is_public=False); db.session.add(g); db.session.flush()
        ana = User(email='ana@r7a.test', name='Ana', is_active=True)
        bo = User(email='bo@r7a.test', name='Bo', is_active=True)
        guest = User(name='Guest', is_active=True, is_guest=True)
        db.session.add_all([ana, bo, guest]); db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        now = datetime.now().replace(second=0, microsecond=0)
        def show(title, days, **kw):
            m = Movie(title=title, director='Some Director, Another', runtime_minutes=100); db.session.add(m); db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=afi.id, start_time=now + timedelta(days=days), **kw)
            db.session.add(s); db.session.flush(); return s.id
        S_GO, S_MAYBE, S_BOTH, S_OLD, S_CANCEL, S_RECENT = (show('GOING FILM', 3), show('MAYBE FILM', 4), show('BOTH FILM', 5),
                                                             show('OLD FILM', -60), show('CANCELLED FILM', 6, is_cancelled=True),
                                                             show('RECENT FILM', -3))
        add = lambda u, s, st, gid=g.id: db.session.add(RSVP(user_id=u.id, showtime_id=s, group_id=gid, status=st))
        add(ana, S_GO, 'going'); add(ana, S_MAYBE, 'maybe'); add(ana, S_BOTH, 'maybe'); add(ana, S_BOTH, 'going', None)
        add(ana, S_OLD, 'going'); add(ana, S_CANCEL, 'going'); add(ana, S_RECENT, 'going')
        add(bo, S_GO, 'going'); add(bo, S_MAYBE, 'going')
        db.session.commit()
        A, B, GU, G = ana.id, bo.id, guest.id, g.id

    def client(uid=None):
        c = app.test_client()
        if uid:
            with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, b, anon = client(A), client(B), client()
    path = lambda url: url.split('cinemaclub', 1)[-1] if False else re.sub(r'^https?://[^/]+', '', url)

    print('--- calendar subscriptions ---')
    links = a.get('/api/me/calendar').json
    check('links made on first ask: yours and one per club', links['personal'].endswith('.ics') and len(links['clubs']) == 1
          and '/api/calendar/club/' in links['clubs'][0]['url'], links)
    check('same links next time', a.get('/api/me/calendar').json == links)
    r = anon.get(path(links['personal']))
    body = r.get_data(as_text=True)
    check('the feed: a calendar file, no sign-in needed', r.status_code == 200 and r.mimetype == 'text/calendar' and body.startswith('BEGIN:VCALENDAR'))
    check('…CRLF line endings, lines folded to 75 octets', '\r\n' in body and all(len(l.encode()) <= 75 for l in body.split('\r\n')))
    unfolded = body.replace('\r\n ', '')
    check('…in DC time, with its time-zone rules', 'DTSTART;TZID=America/New_York:' in unfolded and 'BEGIN:VTIMEZONE' in unfolded)
    check('…your Going and Maybe screenings', 'SUMMARY:GOING FILM' in unfolded and 'SUMMARY:MAYBE FILM (maybe)' in unfolded)
    check('…Going wins over Maybe across clubs (one event)', unfolded.count('BOTH FILM') >= 1 and 'SUMMARY:BOTH FILM\r\n' in unfolded
          and 'BOTH FILM (maybe)' not in unfolded)
    check('…recent ones stay, old ones drop off', 'RECENT FILM' in unfolded and 'OLD FILM' not in unfolded)
    check('…a cancelled screening says so', re.search(r'SUMMARY:CANCELLED FILM.*?STATUS:CANCELLED', unfolded, re.S))
    check('…text is escaped (commas in the address)', 'LOCATION:AFI Silver Theatre\\, 8633 Colesville Rd\\, Silver Spring' in unfolded)
    check("…not someone else's plans", 'GOING FILM' in unfolded and b.get('/api/me/calendar').json['personal'] != links['personal'])
    club = anon.get(path(links['clubs'][0]['url'])).get_data(as_text=True).replace('\r\n ', '')
    check("club feed: what members are going to, with who's going", 'SUMMARY:GOING FILM · 2 going' in club
          and 'Going: Ana\\, Bo' in club and 'SUMMARY:MAYBE FILM · 1 going' in club, re.findall(r'SUMMARY:.*', club))
    old = links['personal']
    new = a.post('/api/me/calendar/reset', json={}).json
    check('a new link turns the old one off', new['personal'] != old and anon.get(path(old)).status_code == 404
          and anon.get(path(new['personal'])).status_code == 200)
    check('made-up links: not found', anon.get('/api/calendar/nope.ics').status_code == 404
          and anon.get('/api/calendar/' + 'x' * 43 + '.ics').status_code == 404)
    blink = b.get('/api/me/calendar').json['clubs'][0]['url']
    with app.app_context():
        GroupMembership.query.filter_by(user_id=B, group_id=G).delete(); db.session.commit()
    check("leaving the club ends that club's link", anon.get(path(blink)).status_code == 404)
    check('guests keep their profile first', client(GU).get('/api/me/calendar').status_code == 403)
    one = anon.get(f'/api/showtimes/{S_GO}/ical')
    check('a single screening downloads the same way', one.status_code == 200 and 'TZID=America/New_York' in one.get_data(as_text=True)
          and 'GOING FILM.ics' in one.headers['Content-Disposition'])

    print('--- theatres ---')
    t = anon.get('/api/theatres/afi').json
    check('a theatre: address, area, map coordinates, next month', t['name'] == 'AFI Silver Theatre' and t['region'] == 'Maryland'
          and abs(t['lat'] - 38.9966) < 0.01 and abs(t['lon'] + 77.0272) < 0.01 and t['films'] >= 3 and t['next'], t)
    check('unknown or closed theatres: not found', anon.get('/api/theatres/nope').status_code == 404
          and anon.get('/api/theatres/amc-hoffman').status_code == 404)
    ov = anon.get('/api/theatres-overview').json
    check('the list: every active theatre, with numbers', len(ov) >= 10 and all('films' in x and 'region' in x for x in ov)
          and not any(x['slug'] == 'amc-hoffman' for x in ov))
    og = anon.get('/api/og/theatres/afi').get_data(as_text=True)
    check('link previews for theatre pages', 'og:title" content="AFI Silver Theatre"' in og and '/theatres/afi' in og)

    print('--- sitemap ---')
    r = anon.get('/api/sitemap.xml')
    locs = [e.text for e in ET.fromstring(r.data).iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    check('valid sitemap of public pages', r.mimetype == 'application/xml' and any(l.endswith('/theatres/afi') for l in locs)
          and any(l.endswith(f'/films/{0}') or '/films/' in l for l in locs) and any(l.endswith('/calendar') for l in locs))
    check('…only films that are playing, never private pages', not any(re.search(r'/(me|club|polls|groups|signin)\b', l) for l in locs)
          and not any('amc-hoffman' in l for l in locs))
    checks.done()

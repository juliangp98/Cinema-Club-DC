"""R7a: calendar subscriptions (yours and your club's), theatre pages, the
sitemap and theatre link previews."""
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def feeds():
    """Ana and Bo in a club. Ana: GOING FILM (going), MAYBE FILM (maybe),
    BOTH FILM (maybe in the club, going on her own), OLD FILM (60 days ago),
    CANCELLED FILM, RECENT FILM (3 days ago). Bo is going to GOING FILM and
    MAYBE FILM. And a guest."""
    from app import app, db, seed_theatres, User, Group, GroupMembership, Showtime, Movie, Theatre, RSVP
    setup_db()
    with app.app_context():
        seed_theatres()
        afi = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Feed Club', slug='feed-r7a', is_public=False)
        db.session.add(g)
        db.session.flush()
        ana = User(email='ana@r7a.test', name='Ana', is_active=True)
        bo = User(email='bo@r7a.test', name='Bo', is_active=True)
        guest = User(name='Guest', is_active=True, is_guest=True)
        db.session.add_all([ana, bo, guest])
        db.session.flush()
        for u in (ana, bo):
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        now = datetime.now().replace(second=0, microsecond=0)

        def show(title, days, **kw):
            m = Movie(title=title, director='Some Director, Another', runtime_minutes=100)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=afi.id, start_time=now + timedelta(days=days), **kw)
            db.session.add(s)
            db.session.flush()
            return s.id
        ids = {'go': show('GOING FILM', 3), 'maybe': show('MAYBE FILM', 4), 'both': show('BOTH FILM', 5),
               'old': show('OLD FILM', -60), 'cancel': show('CANCELLED FILM', 6, is_cancelled=True), 'recent': show('RECENT FILM', -3)}
        for u, key, st, gid in [(ana, 'go', 'going', g.id), (ana, 'maybe', 'maybe', g.id), (ana, 'both', 'maybe', g.id),
                                (ana, 'both', 'going', None), (ana, 'old', 'going', g.id), (ana, 'cancel', 'going', g.id),
                                (ana, 'recent', 'going', g.id), (bo, 'go', 'going', g.id), (bo, 'maybe', 'going', g.id)]:
            db.session.add(RSVP(user_id=u.id, showtime_id=ids[key], group_id=gid, status=st))
        db.session.commit()
        return {**ids, 'ana': ana.id, 'bo': bo.id, 'guest': guest.id, 'group': g.id}


def path(url):
    return re.sub(r'^https?://[^/]+', '', url)


def feed(url):
    return client().get(path(url)).get_data(as_text=True).replace('\r\n ', '')      # unfolded


def test_links_are_made_once_yours_and_each_clubs(feeds):
    links = client(feeds['ana']).get('/api/me/calendar').json
    assert links['personal'].endswith('.ics') and len(links['clubs']) == 1 and '/api/calendar/club/' in links['clubs'][0]['url']
    assert client(feeds['ana']).get('/api/me/calendar').json == links
    assert client(feeds['bo']).get('/api/me/calendar').json['personal'] != links['personal']     # not shared


def test_your_feed_is_a_proper_calendar_file(feeds):
    r = client().get(path(client(feeds['ana']).get('/api/me/calendar').json['personal']))
    body = r.get_data(as_text=True)
    assert r.status_code == 200 and r.mimetype == 'text/calendar' and body.startswith('BEGIN:VCALENDAR')   # no sign-in
    assert '\r\n' in body and all(len(line.encode()) <= 75 for line in body.split('\r\n'))   # CRLF, folded at 75 octets
    unfolded = body.replace('\r\n ', '')
    assert re.search(r'DTSTART:\d{8}T\d{6}Z', unfolded)                                  # UTC, from the theatre's city
    assert 'LOCATION:AFI Silver Theatre\\, 8633 Colesville Rd\\, Silver Spring' in unfolded              # escaped


def test_your_feed_has_your_going_and_maybes(feeds):
    body = feed(client(feeds['ana']).get('/api/me/calendar').json['personal'])
    assert 'SUMMARY:GOING FILM' in body and 'SUMMARY:MAYBE FILM (maybe)' in body
    assert 'SUMMARY:BOTH FILM\r\n' in body and 'BOTH FILM (maybe)' not in body       # Going wins, one event
    assert 'RECENT FILM' in body and 'OLD FILM' not in body                           # recent history stays
    assert re.search(r'SUMMARY:CANCELLED FILM.*?STATUS:CANCELLED', body, re.S)


def test_the_club_feed_shows_whos_going(feeds):
    body = feed(client(feeds['ana']).get('/api/me/calendar').json['clubs'][0]['url'])
    assert 'SUMMARY:GOING FILM · 2 going' in body and 'Going: Ana\\, Bo' in body and 'SUMMARY:MAYBE FILM · 1 going' in body


def test_links_can_be_turned_off(feeds):
    old = client(feeds['ana']).get('/api/me/calendar').json['personal']
    new = client(feeds['ana']).post('/api/me/calendar/reset', json={}).json['personal']
    assert new != old and client().get(path(old)).status_code == 404 and client().get(path(new)).status_code == 200
    assert client().get('/api/calendar/nope.ics').status_code == 404
    assert client().get('/api/calendar/' + 'x' * 43 + '.ics').status_code == 404
    club_link = client(feeds['bo']).get('/api/me/calendar').json['clubs'][0]['url']
    from app import app, db, GroupMembership
    with app.app_context():
        GroupMembership.query.filter_by(user_id=feeds['bo'], group_id=feeds['group']).delete()
        db.session.commit()
    assert client().get(path(club_link)).status_code == 404                         # left the club
    assert client(feeds['guest']).get('/api/me/calendar').status_code == 403         # guests keep a profile first


def test_one_screening_downloads_the_same_way(feeds):
    one = client().get(f"/api/showtimes/{feeds['go']}/ical")
    assert one.status_code == 200 and re.search(r'DTSTART:\d{8}T\d{6}Z', one.get_data(as_text=True))
    assert 'GOING FILM.ics' in one.headers['Content-Disposition']


def test_theatre_pages(feeds):
    t = client().get('/api/theatres/afi').json
    assert t['name'] == 'AFI Silver Theatre' and t['area_label'] == 'Maryland' and t['city'] == 'dc' and t['films'] >= 3 and t['next']
    assert abs(t['lat'] - 38.9966) < 0.01 and abs(t['lon'] + 77.0272) < 0.01
    assert client().get('/api/theatres/nope').status_code == 404
    assert client().get('/api/theatres/amc-hoffman').status_code == 404              # closed
    overview = client().get('/api/theatres-overview').json
    assert len(overview) >= 10 and all('films' in x and x['area_label'] and x['city'] == 'dc' for x in overview)
    assert not any(x['slug'] == 'amc-hoffman' for x in overview)
    og = client().get('/api/og/theatres/afi').get_data(as_text=True)
    assert 'og:title" content="AFI Silver Theatre"' in og and '/theatres/afi' in og


def test_the_sitemap_lists_public_pages_only(feeds):
    r = client().get('/api/sitemap.xml')
    locs = [e.text for e in ET.fromstring(r.data).iter('{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
    assert r.mimetype == 'application/xml'
    assert any(loc.endswith('/theatres/afi') for loc in locs) and any('/films/' in loc for loc in locs)
    assert any(loc.endswith('/calendar') for loc in locs)
    assert not any(re.search(r'/(me|club|polls|groups|signin)\b', loc) for loc in locs)
    assert not any('amc-hoffman' in loc for loc in locs)

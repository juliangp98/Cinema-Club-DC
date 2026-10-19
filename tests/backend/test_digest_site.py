"""The Monday digest as a club setting: on for the home club, off for new
ones; when on it's published on the site Monday at 10 (a Feed card and a bell
item, the bell only unless you asked for more), once a week, and the bot's
copy says whether it may post."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db


def next_monday(hour=10, minute=30):
    today = datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0)
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


@pytest.fixture
def club():
    """A club at AFI with the digest on: a rare 35mm one-off and a film Mo
    (the organizer) and Ivy want, all in next week. Ivy asked for alerts by email."""
    import notify
    from app import app, db, Group, GroupMembership, Movie, Showtime, Theatre, User, Watchlist
    setup_db()
    monday = next_monday()
    with app.app_context():
        afi = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Digest Club', slug='digest-club', is_public=False, theatres='afi', digest_enabled=True)
        db.session.add(g)
        db.session.flush()

        def film(title, year, hours, fmt=None):
            m = Movie(title=title, release_year=str(year))
            db.session.add(m)
            db.session.flush()
            for h in hours:
                db.session.add(Showtime(movie_id=m.id, theatre_id=afi.id, format_label=fmt,
                                        start_time=monday.replace(hour=0, minute=0) + timedelta(hours=h)))
            return m
        film('RARE PRINT', 1961, [43], '35mm')
        wanted = film('WANTED', 2001, [44, 68])
        people = {}
        for name, role in (('Mo', 'organizer'), ('Ivy', 'member'), ('Pat', 'member')):
            u = User(name=name, email=f'{name.lower()}@t.dev', is_active=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active', role=role))
            people[name] = u
        for name in ('Mo', 'Ivy'):
            db.session.add(Watchlist(user_id=people[name].id, movie_id=wanted.id))
        notify.set_prefs(people['Ivy'], {'channels': {'email': True}})
        notify.set_prefs(people['Pat'], {'types': {'digest': False}})
        db.session.commit()
        return {'G': g.id, 'monday': monday, **{n: u.id for n, u in people.items()}}


def publish(when):
    import digest
    from app import app
    with app.app_context():
        return digest.publish_due(when)


def notes(kind='digest'):
    from app import app, Notification
    with app.app_context():
        return {n.user_id: n.channels for n in Notification.query.filter_by(kind=kind)}


def test_the_home_club_has_it_and_new_clubs_dont():
    from app import app, db, Group
    setup_db()
    with app.app_context():
        assert db.session.get(Group, 1).digest_enabled is True        # it always had the digest
        g = Group(name='New', slug='new-club')
        db.session.add(g)
        db.session.commit()
        assert g.to_dict()['digest'] == {'enabled': False}


def test_organizers_switch_it(club):
    r = client(club['Mo']).put('/api/groups/digest-club', json={'digest_enabled': False})
    assert r.status_code == 200 and r.json['digest'] == {'enabled': False}
    assert client(club['Ivy']).put('/api/groups/digest-club', json={'digest_enabled': True}).status_code == 403


def test_published_monday_at_ten_once_a_week(club):
    monday = club['monday']
    assert publish(monday - timedelta(days=1)) == 0                    # Sunday
    assert publish(monday.replace(hour=9)) == 0                       # before 10
    assert publish(monday) >= 1
    assert publish(monday + timedelta(hours=3)) == 0                  # already out this week
    # the bell for everyone who wants it; email only for those who asked for more
    got = notes()
    assert got[club['Mo']] == '' and got[club['Ivy']] == '' and club['Pat'] not in got
    from app import app, Notification
    import notify
    with app.app_context():
        n = Notification.query.filter_by(kind='digest', user_id=club['Mo']).first()
        d = notify.describe(n)
    assert d['headline'] == 'This week’s digest is up' and d['link'] == '/feed?type=digests'
    assert 'Digest Club' in d['detail']


def test_more_than_the_bell_when_asked(club):
    import notify
    from app import app, db, User
    with app.app_context():
        notify.set_prefs(db.session.get(User, club['Ivy']), {'types': {'digest_out': True}})
        db.session.commit()
    publish(club['monday'])
    assert notes()[club['Ivy']] == 'email'


def test_off_publishes_nothing(club):
    client(club['Mo']).put('/api/groups/digest-club', json={'digest_enabled': False})
    publish(club['monday'])
    from app import app, ClubDigest
    with app.app_context():
        assert ClubDigest.query.filter_by(group_id=club['G']).count() == 0
    assert club['Mo'] not in notes()


def test_the_feed_card(club):
    publish(club['monday'])
    r = client(club['Mo']).get('/api/feed', query_string={'group_id': club['G'], 'type': 'digests'})
    cards = r.json['cards']
    assert [c['type'] for c in cards] == ['digest']
    d = cards[0]['digest']
    assert d['week_of'] == club['monday'].date().isoformat()
    assert 'RARE PRINT' in [x['title'] for x in d['rare']]
    assert [(y['title'], y['count']) for y in d['yours']] == [('WANTED', 2)]       # Mo's own watchlist
    pat = client(club['Pat']).get('/api/feed', query_string={'group_id': club['G'], 'type': 'digests'}).json
    assert pat['cards'][0]['digest']['yours'] == []                                  # Pat wants nothing


def test_the_bot_is_told_whether_it_may_post(club):
    d = client().get('/api/internal/digest', query_string={'group_id': club['G']}, headers=H).json
    assert d['enabled'] is True
    client(club['Mo']).put('/api/groups/digest-club', json={'digest_enabled': False})
    d = client().get('/api/internal/digest', query_string={'group_id': club['G']}, headers=H).json
    assert d['enabled'] is False and 'rare' in d                                     # still there to preview


def test_the_settings_list_it_under_your_club(club):
    s = client(club['Ivy']).get('/api/me/notifications').json
    info = {t['key']: t for t in s['types_info']}
    assert info['digest']['group'] == 'club' and info['digest_out']['needs'] == 'digest'
    assert s['types']['digest'] is True and s['types']['digest_out'] is False

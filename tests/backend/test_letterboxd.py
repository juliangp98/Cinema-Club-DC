"""Letterboxd diary sync (R10f): connect your diary in your profile (the
feed must exist; one site account per username, which a club admin can
clear); diary entries that match screenings you said you were going to
follow your choice — ask (the "Did you make it?" prompt says so), always
(checked in), never; ratings show with check-ins only if you say so."""
from datetime import date, datetime, timedelta

import pytest

from helpers import client, setup_db


def feed(*entries):
    items = []
    for e in entries:
        if e.get('list'):
            items.append(f"<item><title>{e['title']}</title><link>https://letterboxd.com/x/list/y/</link>"
                         f"<guid>letterboxd-list-{e['guid']}</guid></item>")
            continue
        rating = f"<letterboxd:memberRating>{e['rating']}</letterboxd:memberRating>" if e.get('rating') else ''
        tmdb = f"<tmdb:movieId>{e['tmdb']}</tmdb:movieId>" if e.get('tmdb') else ''
        items.append(f"""<item><title>{e['title']}</title><link>https://letterboxd.com/ana/film/{e['guid']}/</link>
          <guid isPermaLink="false">letterboxd-review-{e['guid']}</guid>
          <letterboxd:watchedDate>{e['day'].isoformat()}</letterboxd:watchedDate><letterboxd:rewatch>No</letterboxd:rewatch>
          <letterboxd:filmTitle>{e['title']}</letterboxd:filmTitle><letterboxd:filmYear>{e['year']}</letterboxd:filmYear>
          {rating}{tmdb}</item>""")
    return ("""<?xml version='1.0' encoding='utf-8'?><rss version="2.0" xmlns:letterboxd="https://letterboxd.com"
      xmlns:tmdb="https://themoviedb.org"><channel><title>Letterboxd - ana</title>""" + ''.join(items)
            + '</channel></rss>').encode()


TODAY = date.today()
DIARY = [
    {'guid': 1, 'title': 'Vertigo', 'year': 1958, 'tmdb': 426, 'rating': '4.5', 'day': TODAY - timedelta(days=1)},
    {'guid': 2, 'title': 'North by Northwest', 'year': 1959, 'tmdb': 213, 'day': TODAY - timedelta(days=2)},
    {'guid': 3, 'title': 'Home Alone', 'year': 1990, 'tmdb': 771, 'day': TODAY - timedelta(days=1)},   # no RSVP
    {'guid': 4, 'title': 'A list', 'list': True},
]


@pytest.fixture
def club(monkeypatch):
    """Ana and Bo in club 1 (Adm its admin). Ana said she was going to VERTIGO
    (TMDB 426) last night and "NORTH BY NORTHWEST in 70mm" (no TMDB id) two
    nights ago. Letterboxd answers with DIARY for any username but "nobody"."""
    import letterboxd
    from app import app, db, GroupMembership, Movie, RSVP, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        us = {n: User(name=n, email=f'{n.lower()}@lb.test', is_active=True) for n in ('Ana', 'Bo', 'Adm')}
        db.session.add_all(us.values())
        db.session.flush()
        for n, u in us.items():
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role='admin' if n == 'Adm' else 'member'))
        afi = Theatre.query.filter_by(slug='afi').first()
        ids = {n: u.id for n, u in us.items()}
        for key, title, tmdb, year, days in (('VERTIGO', 'VERTIGO', 426, '1958', 1),
                                             ('NXNW', 'NORTH BY NORTHWEST in 70mm', None, '1959', 2)):
            m = Movie(title=title, tmdb_id=tmdb, release_year=year)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=afi.id,
                         start_time=datetime.combine(TODAY - timedelta(days=days), datetime.min.time()).replace(hour=19))
            db.session.add(s)
            db.session.flush()
            db.session.add(RSVP(user_id=us['Ana'].id, showtime_id=s.id, group_id=1, status='going'))
            ids[key] = s.id
        db.session.commit()
        slug = db.session.get(__import__('app').Group, 1).slug
    calls = []

    def fake_fetch(username):
        calls.append(username)
        return (None, 'not_found') if username == 'nobody' else (letterboxd.parse(feed(*DIARY)), None)
    monkeypatch.setattr(letterboxd, 'fetch', fake_fetch)
    return {**ids, 'slug': slug, 'calls': calls}


def connect(c, who='Ana', username='ana'):
    return client(c[who]).post('/api/me/letterboxd', json={'username': username})


def pending(c, who='Ana'):
    return {p['title']: p['letterboxd'] for p in client(c[who]).get('/api/attendance/pending').json}


def attendance(uid, sid):
    from app import app, Attendance
    with app.app_context():
        a = Attendance.query.filter_by(user_id=uid, showtime_id=sid).first()
        return (a.status, a.source) if a else None


def test_reading_a_diary_feed():
    import letterboxd
    entries = letterboxd.parse(feed(*DIARY))
    assert [e['title'] for e in entries] == ['Vertigo', 'North by Northwest', 'Home Alone']   # lists skipped
    assert entries[0]['rating'] == 4.5 and entries[0]['tmdb_id'] == 426 and entries[1]['rating'] is None
    assert letterboxd.parse(b'not xml') == []
    assert letterboxd.clean_title('NORTH BY NORTHWEST in 70mm') == letterboxd.clean_title('North by Northwest')
    assert letterboxd.clean_title("BRAZIL - DIRECTOR'S CUT") == 'brazil'
    assert letterboxd.clean_title('Count Gore De Vol presents THE FLY (1986)') == 'the fly'
    assert letterboxd.clean_username('https://letterboxd.com/Ana_B/films/') == 'Ana_B'
    assert letterboxd.clean_username('ana b') is None


def test_connecting_checks_the_feed(club):
    assert 'no Letterboxd member' in connect(club, username='nobody').json['error']
    assert connect(club, username='bad name!').status_code == 400
    r = connect(club)
    assert r.status_code == 200 and r.json['connected'] and r.json['username'] == 'ana'
    assert r.json['checkin'] == 'ask' and r.json['ratings'] is False and r.json['synced_at']


def test_ask_marks_the_did_you_make_it_prompts(club):
    connect(club)
    p = pending(club)
    assert p['VERTIGO'] == {'rating': 4.5, 'link': 'https://letterboxd.com/ana/film/1/'}
    assert p['NORTH BY NORTHWEST in 70mm'] is not None                        # matched by title + year
    assert attendance(club['Ana'], club['VERTIGO']) is None                    # nothing logged without a yes


def test_always_checks_you_in(club):
    client(club['Ana']).put('/api/me/letterboxd', json={'checkin': 'always'})
    connect(club)
    assert attendance(club['Ana'], club['VERTIGO']) == ('went', 'letterboxd')
    assert attendance(club['Ana'], club['NXNW']) == ('went', 'letterboxd')
    assert pending(club) == {}
    import kernels
    from app import app
    with app.app_context():
        assert kernels.breakdown(club['Ana'], 1)['detail']['went'] == 10


def test_never_leaves_the_diary_out(club):
    client(club['Ana']).put('/api/me/letterboxd', json={'checkin': 'never'})
    connect(club)
    assert attendance(club['Ana'], club['VERTIGO']) is None
    assert set(pending(club).values()) == {None}


def test_already_answered_screenings_are_left_alone(club):
    client(club['Ana']).post('/api/attendance', json={'showtime_id': club['VERTIGO'], 'status': 'missed'})
    client(club['Ana']).put('/api/me/letterboxd', json={'checkin': 'always'})
    connect(club)
    assert attendance(club['Ana'], club['VERTIGO']) == ('missed', 'site')


def test_one_member_per_letterboxd_account(club):
    connect(club)
    r = connect(club, who='Bo')
    assert r.status_code == 409 and 'ask a club admin' in r.json['error']
    assert client(club['Bo']).delete(f"/api/groups/{club['slug']}/members/{club['Ana']}/letterboxd").status_code == 403
    assert client(club['Adm']).delete(f"/api/groups/{club['slug']}/members/{club['Ana']}/letterboxd").status_code == 200
    assert client(club['Ana']).get('/api/me/letterboxd').json['connected'] is False
    assert connect(club, who='Bo').status_code == 200


def test_ratings_show_in_the_feed_only_if_you_say_so(club):
    client(club['Ana']).put('/api/me/letterboxd', json={'checkin': 'always'})
    connect(club)
    card = lambda: next(c for c in client(club['Bo']).get('/api/feed', query_string={'group_id': 1}).json['cards']
                        if c.get('showtime', {}).get('id') == club['VERTIGO'])
    assert card()['letterboxd'] == []
    client(club['Ana']).put('/api/me/letterboxd', json={'ratings': True})
    [r] = card()['letterboxd']
    assert r['user']['name'] == 'Ana' and r['rating'] == 4.5 and r['link'].endswith('/film/1/')


def test_disconnecting_and_changing_the_username(club):
    connect(club)
    client(club['Ana']).put('/api/auth/profile', json={'letterboxd_username': 'someone_else'})
    assert client(club['Ana']).get('/api/me/letterboxd').json == {
        'username': 'someone_else', 'connected': False, 'synced_at': client(club['Ana']).get('/api/me/letterboxd').json['synced_at'],
        'checkin': 'ask', 'ratings': False}                                   # a different diary: connect it again
    connect(club)
    gone = client(club['Ana']).delete('/api/me/letterboxd').json
    assert gone['connected'] is False and gone['username'] == ''
    assert pending(club)['VERTIGO'] is None


def test_diaries_are_read_every_few_hours(club):
    import letterboxd
    from app import app, db, User
    connect(club)
    club['calls'].clear()
    assert letterboxd.sync_due() == 0                                          # just read
    with app.app_context():
        db.session.get(User, club['Ana']).letterboxd_synced_at = datetime.utcnow() - timedelta(hours=4)
        db.session.commit()
    assert letterboxd.sync_due() == 1 and club['calls'] == ['ana']


def test_the_discord_dm_mentions_the_diary_too(club):
    """The bot's "Did you make it?" DM carries the same hint as the site."""
    from app import app, db, User
    from helpers import H, patch_bot_api
    with app.app_context():
        ana = db.session.get(User, club['Ana'])
        ana.discord_user_id, ana.notify_prefs = '7701', '{"types": {"attendance": true}}'
        db.session.commit()
    connect(club)
    [ask] = client().get('/api/internal/attendance/prompts', headers=H).json
    hints = {s['title']: s['letterboxd'] for s in ask['screenings']}
    assert hints['VERTIGO'] == {'rating': 4.5, 'link': 'https://letterboxd.com/ana/film/1/'}
    text = patch_bot_api().attendance_text(ask['screenings'])
    assert text.count('📓 in your Letterboxd diary') == 2 and 'VERTIGO' in text

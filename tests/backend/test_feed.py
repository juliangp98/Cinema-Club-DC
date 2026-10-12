"""The club activity feed: one card per screening / watchlisted film / poll
/ day of joins, newest first, only this club's current members; changes bump
cards; paging."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db

NOW = datetime.utcnow()


def ago(**k):
    return NOW - timedelta(**k)


@pytest.fixture
def club():
    """Feed Club: Ana (admin), Bo, Cy (Discord-only, joined yesterday);
    Gone (left the club); Out (another club). S1 SIRÂT (Ana going, Bo maybe,
    Cy commented, Bo reacted), S2 HAMNET (Bo not going, Gone going), S3 CLOUD
    (only an old RSVP here), PAST KHARTOUM (Ana went); SINNERS on Ana's and
    Cy's watchlists; a new poll."""
    from app import (app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist, Attendance,
                     Message, Reaction, Poll, PollCategory, PollOption)
    setup_db()
    with app.app_context():
        now = datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        films = {t: Movie.query.filter_by(title=t).first().id for t in ('SIRÂT', 'HAMNET', 'CLOUD', 'SINNERS', 'KHARTOUM')}

        def show(title, days):
            s = Showtime(movie_id=films[title], theatre_id=tid, start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=2))
            db.session.add(s)
            db.session.flush()
            return s.id
        S1, S2, S3, PAST, NEXT_SINNERS = show('SIRÂT', 2), show('HAMNET', 3), show('CLOUD', 4), show('KHARTOUM', -2), show('SINNERS', 6)
        g, g2 = Group(name='Feed Club', slug='feed-club', is_public=False), Group(name='Other', slug='feed-other', is_public=False)
        db.session.add_all([g, g2])
        db.session.flush()
        users = {n: User(email=None if n == 'cy' else f'{n}8@test.dev', name=n.title(), is_active=True,
                         discord_user_id='8803' if n == 'cy' else None) for n in ('ana', 'bo', 'cy', 'gone', 'out')}
        db.session.add_all(users.values())
        db.session.flush()
        A, B, C, X, O = (users[n].id for n in ('ana', 'bo', 'cy', 'gone', 'out'))
        G, G2 = g.id, g2.id
        db.session.add_all([
            GroupMembership(user_id=A, group_id=G, status='active', role='admin', joined_at=ago(days=60)),
            GroupMembership(user_id=B, group_id=G, status='active', joined_at=ago(days=60)),
            GroupMembership(user_id=C, group_id=G, status='active', joined_at=ago(hours=30)),
            GroupMembership(user_id=X, group_id=G, status='active', joined_at=ago(hours=29)),
            GroupMembership(user_id=O, group_id=G2, status='active', joined_at=ago(hours=1)),
            GroupMembership(user_id=A, group_id=G2, status='active', joined_at=ago(days=200)),
            RSVP(user_id=A, showtime_id=S1, group_id=G, status='going', created_at=ago(hours=10), updated_at=ago(hours=10)),
            RSVP(user_id=B, showtime_id=S1, group_id=G, status='maybe', created_at=ago(hours=9), updated_at=ago(hours=9)),
            RSVP(user_id=B, showtime_id=S2, group_id=G, status='not_going', created_at=ago(hours=8), updated_at=ago(hours=8)),
            RSVP(user_id=O, showtime_id=S3, group_id=G2, status='going', created_at=ago(hours=1), updated_at=ago(hours=1)),
            RSVP(user_id=A, showtime_id=S3, group_id=G, status='going', created_at=ago(days=120), updated_at=ago(days=120)),
            RSVP(user_id=X, showtime_id=S2, group_id=G, status='going', created_at=ago(hours=7), updated_at=ago(hours=7)),
            RSVP(user_id=A, showtime_id=PAST, group_id=G, status='going', created_at=ago(days=5), updated_at=ago(days=5)),
            Attendance(user_id=A, showtime_id=PAST, status='went', source='discord', answered_at=ago(hours=6)),
            Message(user_id=C, showtime_id=S1, group_id=G, body='See you all there', created_at=ago(hours=5)),
            Message(user_id=O, showtime_id=S1, group_id=G2, body='other group chat', created_at=ago(minutes=30)),
            Reaction(user_id=B, showtime_id=S1, group_id=G, emoji='🔥', created_at=ago(hours=4)),
            Watchlist(user_id=A, movie_id=films['SINNERS'], created_at=ago(hours=3)),
            Watchlist(user_id=C, movie_id=films['SINNERS'], created_at=ago(hours=2)),
        ])
        p = Poll(group_id=G, created_by=A, title='Oscar picks', created_at=ago(hours=1))
        db.session.add(p)
        db.session.flush()
        cat = PollCategory(poll_id=p.id, title='Best Picture')
        db.session.add(cat)
        db.session.flush()
        opt = PollOption(category_id=cat.id, text='SIRÂT')
        db.session.add(opt)
        db.session.commit()
        GroupMembership.query.filter_by(user_id=X, group_id=G).delete()           # Gone leaves
        db.session.commit()
        return {'G': G, 'A': A, 'B': B, 'C': C, 'O': O, 'S1': S1, 'S2': S2, 'S3': S3, 'PAST': PAST, 'NEXT_SINNERS': NEXT_SINNERS,
                'SINNERS': films['SINNERS'], 'CLOUD': films['CLOUD'], 'tid': tid, 'POLL': p.id, 'CAT': cat.id, 'OPT': opt.id}


def feed(c, who='A', **q):
    return client(c[who]).get('/api/feed', query_string={'group_id': c['G'], **q}).json


def keys(f):
    return [card['key'] for card in f['cards']]


def test_every_rsvp_has_an_updated_time():
    from app import app, RSVP
    setup_db()
    with app.app_context():
        assert RSVP.query.filter(RSVP.updated_at.is_(None)).count() == 0          # the migration backfilled it


def test_members_only(club):
    assert client(club['O']).get('/api/feed', query_string={'group_id': club['G']}).status_code == 403
    assert client(club['A']).get('/api/feed').status_code == 400


def test_card_order(club):
    f = feed(club)
    assert keys(f)[:4] == [f"p{club['POLL']}", f"w{club['SINNERS']}", f"s{club['S1']}", f"s{club['PAST']}"]
    assert f['next_offset'] is None and f['days'] == 90


def test_a_screening_card_gathers_its_activity(club):
    s1 = {c['key']: c for c in feed(club)['cards']}[f"s{club['S1']}"]
    assert s1['type'] == 'screening'
    assert [x['name'] for x in s1['showtime']['attendees']] == ['Ana'] and [x['name'] for x in s1['showtime']['maybes']] == ['Bo']
    assert s1['at'].startswith(ago(hours=4).isoformat()[:16]) and s1['at'].endswith('+00:00')      # latest activity, in UTC
    assert [(x['kind'], x['user']['name']) for x in s1['activity']] == [('reaction', 'Bo'), ('comment', 'Cy'), ('rsvp', 'Bo'), ('rsvp', 'Ana')]
    assert s1['activity'][0]['detail'] == '🔥' and s1['showtime']['reactions']['🔥']['count'] == 1
    assert s1['latest_comment']['body'] == 'See you all there' and s1['latest_comment']['user']['discord_only']   # this club's only
    assert s1['showtime']['user_rsvp'] == 'going' and 'user_attendance' in s1['showtime']                    # drawer-ready


def test_what_stays_out(club):
    f = feed(club)
    assert f"s{club['S2']}" not in keys(f)                                       # only not-going + someone who left
    assert all(x['user']['name'] != 'Gone' for c in f['cards'] for x in c.get('activity', []))
    assert f"s{club['S3']}" not in keys(f)                                       # another club's RSVP; ours is 120 days old


def test_went_watchlist_poll_and_join_cards(club):
    cards = {c['key']: c for c in feed(club)['cards']}
    past = cards[f"s{club['PAST']}"]
    assert [x['name'] for x in past['went']] == ['Ana'] and past['activity'][0]['kind'] == 'went'
    w = cards[f"w{club['SINNERS']}"]
    assert w['type'] == 'watchlist' and [u['name'] for u in w['users']] == ['Cy', 'Ana']        # newest adder first
    assert w['wanters'] == 2 and w['viewer_wants'] and w['next']['showtime_id'] == club['NEXT_SINNERS']
    poll = cards[f"p{club['POLL']}"]
    assert poll['poll']['status'] == 'open' and not poll['you_voted'] and poll['poll']['categories'] == 1
    joins = [c for c in feed(club)['cards'] if c['type'] == 'joined']
    assert [u['name'] for u in joins[0]['users']] == ['Cy']                       # by day, current members only
    assert any('Ana' in [u['name'] for u in j['users']] for j in joins)          # within 90 days


def rsvp(club, who, sid, status):
    client(club[who]).post('/api/rsvp', json={'showtime_id': club[sid], 'status': status, 'group_id': club['G']})


def test_rsvp_changes_move_cards(club):
    rsvp(club, 'A', 'S1', 'going')
    assert keys(feed(club))[0] == f"p{club['POLL']}"                             # the same status: no bump
    rsvp(club, 'B', 'S1', 'going')
    top = feed(club)['cards'][0]
    assert top['key'] == f"s{club['S1']}" and [x['name'] for x in top['showtime']['attendees']] == ['Ana', 'Bo']
    rsvp(club, 'B', 'S2', 'going')
    assert keys(feed(club))[0] == f"s{club['S2']}"
    rsvp(club, 'B', 'S2', None)
    assert f"s{club['S2']}" not in keys(feed(club))


def test_watchlist_and_poll_changes(club):
    from app import app, db, Watchlist, PollVote
    with app.app_context():
        Watchlist.query.filter_by(movie_id=club['SINNERS']).delete()
        db.session.add(PollVote(category_id=club['CAT'], user_id=club['A'], option_id=club['OPT']))
        db.session.commit()
    assert f"w{club['SINNERS']}" not in keys(feed(club))                        # on nobody's list: gone
    assert next(c for c in feed(club)['cards'] if c['key'] == f"p{club['POLL']}")['you_voted']
    r = client(club['A']).post(f"/api/polls/{club['POLL']}/score", json={'winners': {str(club['CAT']): club['OPT']}})
    top = feed(club)['cards'][0]
    assert r.status_code == 200 and top['key'] == f"p{club['POLL']}" and top['poll']['status'] == 'scored'


def test_comments_use_utc_times_and_bump_the_card(club):
    b, q = client(club['B']), {'showtime_id': club['S1'], 'group_id': club['G']}
    r = b.post('/api/messages', json={**q, 'body': 'Fresh one'}).json
    assert r['created_at'].endswith('+00:00')
    msgs = b.get('/api/messages', query_string=q).json
    assert [m['body'] for m in b.get('/api/messages', query_string={**q, 'since': msgs[0]['created_at']}).json] == ['Fresh one']
    top = feed(club)['cards'][0]
    assert top['key'] == f"s{club['S1']}" and top['latest_comment']['body'] == 'Fresh one'


def test_paging(club):
    from app import app, db, RSVP, Showtime, FEED_PAGE
    with app.app_context():
        for i in range(FEED_PAGE + 5):
            s = Showtime(movie_id=club['CLOUD'], theatre_id=club['tid'], start_time=datetime.now() + timedelta(days=10, hours=i),
                         end_time=datetime.now() + timedelta(days=10, hours=i + 2))
            db.session.add(s)
            db.session.flush()
            db.session.add(RSVP(user_id=club['B'], showtime_id=s.id, group_id=club['G'], status='going',
                                created_at=ago(days=20, minutes=i), updated_at=ago(days=20, minutes=i)))
        db.session.commit()
    p1 = feed(club)
    p2 = feed(club, offset=p1['next_offset'])
    every = keys(p1) + keys(p2)
    assert len(p1['cards']) == FEED_PAGE and p1['next_offset'] == FEED_PAGE
    assert len(set(every)) == len(every) and p2['next_offset'] is None
    assert p1['cards'][-1]['at'] >= p2['cards'][0]['at']

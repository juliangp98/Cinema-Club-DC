"""Kernels beyond polls (R10b): checking in, planning it, being the
trailblazer, crew nights — worked out from RSVPs and check-ins, so they
follow any change — and kernels members give (or take) for each other's
activity, within weekly limits. One total, with where it came from."""
from datetime import datetime, timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    """Kernel Club: Ana, Bo, Cy, Dee, Eve, Fay, Gil (members), Out (another
    club), Gus (a guest member). PAST was yesterday; SOON is in 3 days."""
    from app import app, db, Group, GroupMembership, Movie, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        g, other = Group(name='Kernel Club', slug='kernel-club', is_public=False), Group(name='Other', slug='k-other')
        db.session.add_all([g, other])
        db.session.flush()
        names = ['Ana', 'Bo', 'Cy', 'Dee', 'Eve', 'Fay', 'Gil', 'Out', 'Gus']
        us = {n: User(name=n, email=None if n == 'Gus' else f'{n.lower()}@k.test', is_active=True, is_guest=n == 'Gus')
              for n in names}
        db.session.add_all(us.values())
        db.session.flush()
        for n, u in us.items():
            db.session.add(GroupMembership(user_id=u.id, group_id=other.id if n == 'Out' else g.id, status='active'))
        db.session.add(GroupMembership(user_id=us['Ana'].id, group_id=other.id, status='active'))
        th = Theatre.query.filter_by(slug='afi').first()
        ids = {n: u.id for n, u in us.items()}
        for key, days in (('PAST', -1), ('SOON', 3), ('LATER', 5)):
            m = Movie(title=f'K {key}')
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=datetime.now() + timedelta(days=days))
            db.session.add(s)
            db.session.flush()
            ids[key] = s.id
        db.session.commit()
        return {**ids, 'G': g.id, 'OTHER': other.id}


def rsvp(c, who, sid, status='going', group='G'):
    from app import app, db, RSVP
    with app.app_context():
        db.session.add(RSVP(user_id=c[who], showtime_id=c[sid], group_id=c[group], status=status,
                            created_at=datetime.utcnow() + timedelta(seconds=len(RSVP.query.all()))))
        db.session.commit()


def went(c, who, sid='PAST', status='went'):
    from app import app, db, Attendance
    with app.app_context():
        db.session.add(Attendance(user_id=c[who], showtime_id=c[sid], status=status, source='site',
                                  answered_at=datetime.utcnow()))
        db.session.commit()


def k(c, who, group='G'):
    import kernels
    from app import app
    with app.app_context():
        return kernels.breakdown(c[who], c[group] if group else None)


def toss(c, giver, to, delta=1, sid='PAST'):
    return client(c[giver]).post('/api/kernels/toss', json={'group_id': c['G'], 'showtime_id': c[sid],
                                                           'user_id': c[to], 'delta': delta})


# ── going out ──

def test_checking_in_and_having_planned_it(club):
    went(club, 'Bo')
    assert k(club, 'Bo')['detail'] == {'went': 5, 'planned': 0, 'trailblazer': 0, 'crew': 0}
    rsvp(club, 'Ana', 'PAST')
    went(club, 'Ana')
    assert k(club, 'Ana')['going_out'] == 7                                   # +5, and +2 for planning it
    assert k(club, 'Ana', 'OTHER')['going_out'] == 5                         # the RSVP was made in Kernel Club
    assert k(club, 'Ana', None)['going_out'] == 7                            # overall: once


def test_the_trailblazer(club):
    for who in ('Ana', 'Bo', 'Cy', 'Dee'):
        rsvp(club, who, 'SOON')
    rsvp(club, 'Eve', 'SOON', 'maybe')                                       # only "going" counts
    assert k(club, 'Ana')['detail']['trailblazer'] == 3 and k(club, 'Bo')['detail']['trailblazer'] == 0
    for who in ('Eve', 'Fay', 'Gil'):
        rsvp(club, who, 'LATER')
    for who in ('Bo', 'Cy', 'Dee', 'Out'):                                    # Out isn't in the club
        rsvp(club, who, 'LATER')
    assert k(club, 'Eve')['detail']['trailblazer'] == 5                       # capped


def test_a_trailblazer_who_missed_it_gets_nothing(club):
    rsvp(club, 'Ana', 'PAST')
    rsvp(club, 'Bo', 'PAST')
    went(club, 'Ana', status='missed')
    assert k(club, 'Ana')['detail']['trailblazer'] == 0


def test_crew_night(club):
    for who in ('Ana', 'Bo'):
        went(club, who)
    assert k(club, 'Ana')['detail']['crew'] == 0
    went(club, 'Cy')
    assert all(k(club, who)['detail']['crew'] == 3 for who in ('Ana', 'Bo', 'Cy'))


def test_undoing_takes_the_kernels_back(club):
    from app import app, db, RSVP
    rsvp(club, 'Ana', 'SOON')
    rsvp(club, 'Bo', 'SOON')
    assert k(club, 'Ana')['detail']['trailblazer'] == 1
    with app.app_context():
        RSVP.query.filter_by(user_id=club['Bo']).delete()
        db.session.commit()
    assert k(club, 'Ana')['kernels'] == 0


# ── giving and taking ──

@pytest.fixture
def active(club):
    """Ana, Bo and Cy went to PAST; everyone else commented on it."""
    from app import app, db, Message
    for who in ('Ana', 'Bo', 'Cy'):
        went(club, who)
    with app.app_context():
        for who in ('Dee', 'Eve', 'Fay', 'Gil', 'Gus'):
            db.session.add(Message(user_id=club[who], showtime_id=club['PAST'], group_id=club['G'], body='hi'))
        db.session.commit()
    return club


def test_giving_kernels(active):
    r = toss(active, 'Bo', 'Ana')
    assert r.status_code == 200 and r.json['mine'] == 1 and r.json['net'] == 1
    assert r.json['allowance']['give_left'] == 9
    toss(active, 'Bo', 'Ana')
    toss(active, 'Bo', 'Ana')
    r = toss(active, 'Bo', 'Ana')
    assert r.status_code == 400 and 'Up to 3' in r.json['error']             # per person, per screening
    assert k(active, 'Ana')['members'] == 3 and k(active, 'Ana')['kernels'] == 5 + 3 + 3
    assert toss(active, 'Bo', 'Ana', -1).json['mine'] == 2                     # undo one
    assert client(active['Bo']).get('/api/kernels', query_string={'group_id': active['G']}).json['allowance']['give_left'] == 8


def test_the_weekly_allowance_to_give(active):
    for who in ('Ana', 'Cy', 'Dee'):
        for _ in range(3):
            assert toss(active, 'Bo', who).status_code == 200
    assert toss(active, 'Bo', 'Eve').status_code == 200                      # the 10th
    r = toss(active, 'Bo', 'Fay')
    assert r.status_code == 400 and 'all 10 this week' in r.json['error']


def test_taking_kernels(active):
    r = toss(active, 'Bo', 'Ana', -1)
    assert r.status_code == 200 and r.json['mine'] == -1 and k(active, 'Ana')['members'] == -1
    assert 'only take 1' in toss(active, 'Bo', 'Ana', -1).json['error']        # one per person per screening
    assert toss(active, 'Bo', 'Cy', -1).status_code == 200
    toss(active, 'Bo', 'Dee', 1)                                              # Dee needs a kernel to lose
    assert toss(active, 'Cy', 'Dee', -1).status_code == 200
    with_three = toss(active, 'Bo', 'Fay', -1)
    assert with_three.status_code == 400 and "don't have any" in with_three.json['error']   # never below 0


def test_three_takes_a_week_and_five_lost_at_most(active):
    rsvp(active, 'Ana', 'SOON')                                               # Ana's active on three screenings
    rsvp(active, 'Ana', 'LATER')
    for sid in ('PAST', 'SOON', 'LATER'):
        assert toss(active, 'Bo', 'Ana', -1, sid=sid).status_code == 200
    assert 'all 3 this week' in toss(active, 'Bo', 'Cy', -1).json['error']
    assert toss(active, 'Cy', 'Ana', -1).status_code == 200
    assert toss(active, 'Dee', 'Ana', -1).status_code == 200                  # Ana has lost 5 this week
    assert 'lost enough' in toss(active, 'Eve', 'Ana', -1).json['error']


def test_who_can_give_to_whom(active):
    assert "yourself" in toss(active, 'Ana', 'Ana').json['error']
    assert toss(active, 'Out', 'Ana').status_code == 403                      # not in the club
    assert 'account' in toss(active, 'Gus', 'Ana').json['error']               # guests
    assert "haven't done anything" in toss(active, 'Ana', 'Bo', sid='SOON').json['error']   # no activity there
    assert toss(active, 'Ana', 'Bo', delta=5).status_code == 400


# ── where it shows ──

def test_the_leaderboard_adds_it_all_up(active):
    toss(active, 'Bo', 'Ana')
    rows = client(active['Ana']).get(f"/api/groups/{active['G']}/leaderboard").json
    top = rows[0]
    assert top['user']['name'] == 'Ana' and top['kernels'] == 9
    assert top['breakdown'] == {'polls': 0, 'going_out': 8, 'members': 1}
    assert client(active['Bo']).get(f"/api/users/{active['Ana']}/kernels").json['breakdown']['members'] == 1


def test_the_feed_shows_gifts_and_who_can_get_them(active):
    toss(active, 'Bo', 'Ana')
    toss(active, 'Bo', 'Ana')
    toss(active, 'Cy', 'Bo', -1)
    feed = client(active['Bo']).get('/api/feed', query_string={'group_id': active['G']}).json
    assert feed['allowance']['give_left'] == 8
    card = next(c for c in feed['cards'] if c['key'] == f"s{active['PAST']}")
    gifts = [(a['user']['name'], a['detail']['to']['name'], a['detail']['amount']) for a in card['activity'] if a['kind'] == 'kernels']
    assert gifts == [('Cy', 'Bo', -1), ('Bo', 'Ana', 2)]                      # newest first
    people = {p['user']['name']: p for p in card['kernels']['people']}
    assert 'Bo' not in people                                                 # not yourself
    assert people['Ana']['did'] == 'went' and people['Ana']['net'] == 2 and people['Ana']['mine'] == 2
    assert people['Dee']['did'] == 'commented' and people['Dee']['mine'] == 0

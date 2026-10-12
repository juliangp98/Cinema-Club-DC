"""Discover's "This week in the club" strip: plans in the next 7 days, open
polls with your vote state, new comments from others."""
from datetime import datetime, timedelta, timezone

import pytest

from helpers import client, setup_db


@pytest.fixture
def week():
    """Me, Ana and Bo in a club (and an outsider): BIG (all three going, in 2
    days), SMALL (Ana going, Bo maybe), LATER (in 9 days), PAST; comments;
    two open polls (I voted in one) and a scored one."""
    from app import (app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Message, Poll,
                     PollCategory, PollOption, PollVote)
    setup_db()
    with app.app_context():
        g = Group(name='Week', slug='week-r3c', is_public=False)
        db.session.add(g)
        db.session.flush()
        th = Theatre.query.filter_by(slug='afi').first()
        us = [User(email=f'w{i}@r3c.test', name=n, is_active=True) for i, n in enumerate(['Me', 'Ana', 'Bo', 'Outsider'])]
        db.session.add_all(us)
        db.session.flush()
        for u in us[:3]:
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        now = datetime.now()

        def show(title, days):
            m = Movie(title=title)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=days))
            db.session.add(s)
            db.session.flush()
            return s
        big, small, later, past = show('BIG', 2), show('SMALL', 1), show('LATER', 9), show('PAST', -1)
        rsvps = [(u, big, 'going') for u in us[:3]] + [(us[1], small, 'going'), (us[2], small, 'maybe'),
                                                        (us[1], later, 'going'), (us[1], past, 'going')]
        for u, s, status in rsvps:
            db.session.add(RSVP(user_id=u.id, showtime_id=s.id, group_id=g.id, status=status))
        utc = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.add_all([Message(user_id=us[1].id, showtime_id=big.id, group_id=g.id, body='old', created_at=utc - timedelta(days=9)),
                            Message(user_id=us[0].id, showtime_id=big.id, group_id=g.id, body='mine', created_at=utc),
                            Message(user_id=us[2].id, showtime_id=small.id, group_id=g.id, body='Bo says hi', created_at=utc - timedelta(hours=1))])
        polls = [Poll(group_id=g.id, created_by=us[1].id, title=t, status=st)
                 for t, st in (('Voted one', 'open'), ('Fresh one', 'open'), ('Done', 'scored'))]
        db.session.add_all(polls)
        db.session.flush()
        c = PollCategory(poll_id=polls[0].id, title='C')
        db.session.add(c)
        db.session.flush()
        o = PollOption(category_id=c.id, text='x')
        db.session.add(o)
        db.session.flush()
        db.session.add(PollVote(category_id=c.id, user_id=us[0].id, option_id=o.id))
        db.session.commit()
        return {'group': g.id, 'me': us[0].id, 'outsider': us[3].id}


def get_week(uid, group):
    return client(uid).get('/api/club/week', query_string={'group_id': group})


def test_plans_are_this_weeks_going_most_attended_first(week):
    plans = get_week(week['me'], week['group']).json['plans']
    assert [p['movie']['title'] for p in plans] == ['BIG', 'SMALL']
    assert plans[0]['you_going'] and len(plans[0]['going']) == 3
    assert not plans[1]['you_going'] and plans[1]['going'][0]['name'] == 'Ana'


def test_open_polls_say_whether_you_voted(week):
    polls = get_week(week['me'], week['group']).json['polls']
    assert {(p['title'], p['you_voted']) for p in polls} == {('Voted one', True), ('Fresh one', False)}


def test_comments_are_this_weeks_from_others_latest_first(week):
    comments = get_week(week['me'], week['group']).json['comments']
    assert comments['count'] == 1 and comments['latest']['user'] == 'Bo' and comments['latest']['movie'] == 'SMALL'


def test_members_only(week):
    assert get_week(week['outsider'], week['group']).status_code == 403
    assert client().get('/api/club/week', query_string={'group_id': week['group']}).status_code == 401

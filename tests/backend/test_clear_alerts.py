"""Clear in the bell: every alert goes except those still asking you something
(a game post waiting for your OK, today's trivia you haven't answered); cleared
alerts are kept out of sight, so nothing is sent twice."""
import json
from datetime import timedelta

import pytest

from helpers import client, setup_db


@pytest.fixture
def bell():
    """Olly (an organizer) with five alerts: a film booking, a game post waiting
    for an OK and one already decided, today's trivia (unanswered) and yesterday's."""
    import trivia
    from app import app, db, GamePost, Group, GroupMembership, Notification, TriviaQuestion, User
    setup_db()
    with app.app_context():
        g = Group(name='Bell Club', slug='bell-club', trivia_enabled=True)
        u = User(name='Olly', email='olly@t.dev', is_active=True)
        db.session.add_all([g, u])
        db.session.flush()
        db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active', role='organizer'))
        today = trivia.today()
        q = TriviaQuestion(group_id=g.id, day=today, kind='director', prompt='Who directed it?',
                           options_json=json.dumps(['A', 'B', 'C', 'D']), answer=0)
        waiting = GamePost(group_id=g.id, kind='trivia', ref='w', status='waiting')
        done = GamePost(group_id=g.id, kind='bingo_card', ref='d', status='posted')
        db.session.add_all([q, waiting, done])
        db.session.flush()

        def note(kind, **payload):
            db.session.add(Notification(user_id=u.id, kind=kind, payload_json=json.dumps(payload)))
        note('showings', title='VERTIGO')
        note('game_review', post_id=waiting.id, post_kind='trivia', group='bell-club')
        note('game_review', post_id=done.id, post_kind='bingo_card', group='bell-club')
        note('trivia_daily', day=today.isoformat(), group='bell-club', prompt='Who directed it?')
        note('trivia_daily', day=(today - timedelta(days=1)).isoformat(), group='bell-club', prompt='Old one')
        db.session.commit()
        return {'user': u.id, 'question': q.id}


def test_clear_keeps_only_what_needs_an_answer(bell):
    c = client(bell['user'])
    items = c.get('/api/notifications').json['items']
    assert sorted(n['kind'] for n in items if n['needs_answer']) == ['game_review', 'trivia_daily']
    r = c.post('/api/notifications/clear').json
    assert r['cleared'] == 3 and r['unread'] == 2
    assert sorted(n['kind'] for n in r['items']) == ['game_review', 'trivia_daily']
    after = c.get('/api/notifications').json
    assert len(after['items']) == 2 and after['unread'] == 2
    assert c.get('/api/notifications?count=1').json == {'unread': 2}


def test_cleared_alerts_are_kept_so_nothing_is_sent_twice(bell):
    from app import app, Notification
    client(bell['user']).post('/api/notifications/clear')
    with app.app_context():
        assert Notification.query.filter_by(user_id=bell['user']).count() == 5          # out of sight, not gone
        assert Notification.query.filter(Notification.cleared_at.isnot(None)).count() == 3


def test_answering_lets_it_go(bell):
    from app import app, db, TriviaAnswer
    with app.app_context():
        db.session.add(TriviaAnswer(question_id=bell['question'], user_id=bell['user'], choice=0, correct=True))
        db.session.commit()
    r = client(bell['user']).post('/api/notifications/clear').json
    assert [n['kind'] for n in r['items']] == ['game_review']                         # trivia answered: cleared too


def test_clearing_is_yours_alone(bell):
    from app import app, db, Notification, User
    with app.app_context():
        other = User(name='Pat', email='pat@t.dev', is_active=True)
        db.session.add(other)
        db.session.flush()
        db.session.add(Notification(user_id=other.id, kind='showings', payload_json='{}'))
        db.session.commit()
        pat = other.id
    client(bell['user']).post('/api/notifications/clear')
    assert len(client(pat).get('/api/notifications').json['items']) == 1
    assert client().post('/api/notifications/clear').status_code == 401

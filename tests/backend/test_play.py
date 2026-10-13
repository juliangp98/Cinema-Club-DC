"""What there is to play today (R10 Play): one summary — trivia, bingo, polls
waiting for your vote, your kernels — for the feed's rail and strip, the
Club page and Play; games the club has off are left out."""
import json

import pytest

from helpers import client, setup_db


@pytest.fixture
def club():
    """Play Club: Ana (admin), Bo; one open poll; two films to ask about."""
    from app import app, db, Group, GroupMembership, Poll, PollCategory, PollOption, Quote, User
    setup_db()
    with app.app_context():
        g = Group(name='Play Club', slug='play-club', is_public=False, theatres='afi')
        ana, bo, out = (User(name=n, email=f'{n.lower()}@p.test', is_active=True) for n in ('Ana', 'Bo', 'Out'))
        db.session.add_all([g, ana, bo, out])
        db.session.flush()
        db.session.add(GroupMembership(user_id=ana.id, group_id=g.id, status='active', role='admin'))
        db.session.add(GroupMembership(user_id=bo.id, group_id=g.id, status='active'))
        p = Poll(group_id=g.id, created_by=ana.id, title='Best of fall', status='open')
        db.session.add(p)
        db.session.flush()
        c = PollCategory(poll_id=p.id, title='Pick')
        db.session.add(c)
        db.session.flush()
        db.session.add_all([PollOption(category_id=c.id, text='x'), PollOption(category_id=c.id, text='y')])
        for t, q in (('Here’s looking at you, kid.', 'Casablanca'), ('I’ll be back.', 'The Terminator'),
                     ('You talking to me?', 'Taxi Driver'), ('Fasten your seatbelts.', 'All About Eve')):
            db.session.add(Quote(text=t, movie=q))
        db.session.commit()
        return {'Ana': ana.id, 'Bo': bo.id, 'Out': out.id, 'G': g.id, 'slug': g.slug, 'poll': p.id}


def summary(c, who='Bo'):
    return client(c[who]).get('/api/play', query_string={'group_id': c['G']})


def test_with_the_games_off_theres_polls_and_kernels(club):
    s = summary(club).json
    assert s['trivia'] is None and s['bingo'] is None
    assert s['polls'] == [{'id': club['poll'], 'title': 'Best of fall', 'you_voted': False}]
    assert s['todo'] == 1 and s['kernels']['kernels'] == 0 and s['kernels']['allowance']['give_left'] == 10
    assert summary(club, 'Out').status_code == 403


def test_trivia_and_bingo_once_theyre_on(club):
    from app import app, db, TriviaQuestion
    client(club['Ana']).put(f"/api/groups/{club['slug']}", json={'trivia_enabled': True, 'bingo_enabled': True})
    s = summary(club).json
    assert s['trivia']['to_answer'] and s['todo'] == 2
    assert s['bingo']['filled'] == 0 and s['bingo']['cells'] == [False] * 4 + [True] + [False] * 4
    q = client(club['Bo']).get('/api/trivia/today', query_string={'group_id': club['G']}).json['question']
    with app.app_context():
        right = db.session.get(TriviaQuestion, q['id']).answer
    client(club['Bo']).post('/api/trivia/answer', json={'group_id': club['G'], 'question_id': q['id'], 'choice': right})
    s = summary(club).json
    assert s['trivia'] == {'daily': True, 'anytime': False, 'to_answer': False, 'waiting': False,
                           'answered': True, 'correct': True}
    assert s['todo'] == 1 and s['kernels']['trivia'] == 2 and s['kernels']['kernels'] == 2
    assert json.dumps(s)                                                        # plain JSON all the way down


def test_open_polls_read_the_same_on_play_and_the_club_week(club):
    """One open-polls helper behind Play, the rail and Discover's club week."""
    from app import app, db, PollCategory
    with app.app_context():
        cat = PollCategory.query.filter_by(poll_id=club['poll']).first()
        cat_id, opt_id = cat.id, cat.options[0].id

    def week(who='Bo'):
        return client(club[who]).get('/api/club/week', query_string={'group_id': club['G']}).json['polls']
    assert week() == summary(club).json['polls'] == [{'id': club['poll'], 'title': 'Best of fall', 'you_voted': False}]
    client(club['Bo']).post(f"/api/polls/{club['poll']}/vote", json={'votes': [{'category_id': cat_id, 'option_id': opt_id}]})
    assert week()[0]['you_voted'] and summary(club).json['polls'][0]['you_voted'] and summary(club).json['todo'] == 0
    assert not week('Ana')[0]['you_voted']                                      # per person

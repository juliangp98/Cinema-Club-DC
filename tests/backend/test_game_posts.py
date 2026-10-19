"""What the club games post in Discord, and who hears about it (R14): each
post Never / Ask first / Always (wins Never / Always), an admin's OK (and
changes) for Ask first, posts that lapse, wins that name only people who said
so, and each person's own game notices."""
import json
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, client, setup_db

NOON = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


@pytest.fixture(autouse=True)
def noon(monkeypatch):
    """The club's clock at noon, whatever time the tests run."""
    import game_posts
    monkeypatch.setattr(game_posts, '_local_now', lambda *_: NOON)


@pytest.fixture
def club():
    """Club 1 (the Discord one): Ana (admin, Discord, takes DMs), Bo (member,
    Discord), Vi (read-only). Quotes to ask about; a 35mm 1950 film at AFI."""
    import notify
    from app import app, db, GroupMembership, Group, Movie, Quote, Showtime, Theatre, User
    setup_db()
    with app.app_context():
        us = {n: User(name=n, email=f'{n.lower()}@gp.test', is_active=True, discord_user_id=d)
              for n, d in (('Ana', '9701'), ('Bo', '9702'), ('Vi', None))}
        db.session.add_all(us.values())
        db.session.flush()
        for n, role in (('Ana', 'admin'), ('Bo', 'member'), ('Vi', 'viewer')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=1, status='active', role=role))
        for text, movie in (('Here’s looking at you, kid.', 'Casablanca'), ('I’ll be back.', 'The Terminator'),
                            ('You talking to me?', 'Taxi Driver'), ('Fasten your seatbelts.', 'All About Eve'),
                            ('Rosebud.', 'Citizen Kane'), ('Stella!', 'A Streetcar Named Desire')):
            db.session.add(Quote(text=text, movie=movie))
        m = Movie(title='OLD PRINT', release_year='1950', genres='drama')
        db.session.add(m)
        db.session.flush()
        afi = Theatre.query.filter_by(slug='afi').first()
        s = Showtime(movie_id=m.id, theatre_id=afi.id, start_time=datetime.now().replace(day=1, hour=19) + timedelta(days=1),
                     format_label='35mm')
        db.session.add(s)
        notify.set_prefs(us['Ana'], {'channels': {'discord': True}})
        db.session.commit()
        slug = db.session.get(Group, 1).slug
        ids = {n: u.id for n, u in us.items()}
        show = s.id
    all_linked_present()
    return {**ids, 'slug': slug, 'show': show}


def settings(c, **data):
    r = client(c['Ana']).put(f"/api/groups/{c['slug']}", json=data)
    assert r.status_code == 200, r.json
    return r.json


def tick(now=NOON):
    import game_posts
    from app import app
    with app.app_context():
        game_posts.tick(now)


def ready():
    return client().get('/api/internal/games/posts', query_string={'group_id': 1}, headers=H).json['posts']


def posts(c, who='Ana'):
    return client(c[who]).get(f"/api/groups/{c['slug']}/game-posts")


def decide(c, post_id, action, who='Ana'):
    return client(c[who]).post(f"/api/groups/{c['slug']}/game-posts/{post_id}", json={'action': action})


def bell(c, who):
    return [i['kind'] for i in client(c[who]).get('/api/notifications').json['items']]


def test_nothing_posts_until_a_club_says_so(club):
    s = settings(club, trivia_enabled=True, bingo_enabled=True)
    assert s['trivia']['post'] == 'never' and s['bingo']['card_post'] == 'never' and s['bingo']['wins_post'] == 'never'
    tick()
    assert ready() == [] and posts(club).json == {'waiting': [], 'skipped': []}
    assert 'trivia_daily' not in bell(club, 'Bo')                             # a personal notice is off until you say so
    assert settings(club, bingo_wins_post='ask')['bingo']['wins_post'] == 'never'   # wins: never / always only


def test_ask_first_waits_for_an_admin(club):
    settings(club, trivia_enabled=True, trivia_post='ask')
    tick()
    assert ready() == []
    [p] = posts(club).json['waiting']
    assert p['kind'] == 'trivia' and p['question']['options'][p['answer']] and p['can_swap']
    assert 'game_review' in bell(club, 'Ana') and posts(club, 'Bo').status_code == 403
    dm = client().get('/api/internal/notifications/dm', headers=H).json
    assert [d['reviews'] for d in dm if d['discord_user_id'] == '9701'] == [[p['id']]]   # the DM gets the buttons
    swapped = decide(club, p['id'], 'another').json
    assert swapped['status'] == 'waiting'
    q0, q1 = p['question'], swapped['question']                 # "Which came out first?" keeps its wording: the films change
    assert (q1['prompt'], q1['options']) != (q0['prompt'], q0['options'])
    assert decide(club, p['id'], 'post', who='Bo').status_code == 403
    assert decide(club, p['id'], 'post').json['status'] == 'approved'
    [r] = ready()
    assert r['id'] == p['id'] and r['question']['prompt'] == swapped['question']['prompt']
    client().post('/api/internal/games/posted', json={'post_id': r['id'], 'message_id': '777'}, headers=H)
    tick()
    assert ready() == [] and posts(club).json['waiting'] == []                # once a day


def test_a_question_someone_answered_cant_be_swapped(club):
    settings(club, trivia_enabled=True, trivia_post='ask')
    tick()
    [p] = posts(club).json['waiting']
    client(club['Bo']).post('/api/trivia/answer', json={'group_id': 1, 'question_id': p['question']['id'], 'choice': 0})
    r = decide(club, p['id'], 'another')
    assert r.status_code == 400 and 'answered' in r.json['error'] and r.json['can_swap'] is False


def test_unapproved_and_skipped_posts_dont_go_out(club):
    settings(club, trivia_enabled=True, trivia_post='ask')
    tick(NOON.replace(hour=9))
    assert posts(club).json['waiting'] == []                                  # not before 11 AM
    tick()
    [p] = posts(club).json['waiting']
    tick(NOON.replace(hour=22, minute=5))
    assert posts(club).json['waiting'] == [] and ready() == []                # nobody said yes by 10 PM
    from app import app, db, GamePost
    with app.app_context():
        assert db.session.get(GamePost, p['id']).status == 'expired'


def test_always_posts_on_its_own(club):
    settings(club, trivia_enabled=True, trivia_post='always')
    tick()
    [r] = ready()
    assert r['kind'] == 'trivia' and 'game_review' not in bell(club, 'Ana')


def test_the_months_card_reshuffle_then_post(club):
    settings(club, bingo_enabled=True, bingo_card_post='ask')
    client(club['Bo']).put('/api/me/notifications', json={'types': {'bingo_card': True}})
    tick()
    [p] = posts(club).json['waiting']
    before = [s['key'] for s in p['squares']]
    after = [s['key'] for s in decide(club, p['id'], 'reshuffle').json['squares']]
    assert len(after) == 8 and after != before
    assert client(club['Ana']).get('/api/bingo', query_string={'group_id': 1}).json['squares'][0]['key'] == after[0]
    assert decide(club, p['id'], 'post').json['status'] == 'approved'
    assert [r['kind'] for r in ready()] == ['bingo_card']
    assert 'bingo_card' in bell(club, 'Bo') and 'bingo_card' not in bell(club, 'Ana')   # Bo asked for it


def test_wins_name_only_people_who_say_so(club):
    import bingo
    from app import app, db, Attendance, BingoCard
    settings(club, bingo_enabled=True, bingo_wins_post='always')
    with app.app_context():                     # a card where one 35mm 1950 screening completes a line (film · free · pre1960)
        db.session.add(BingoCard(group_id=1, month=bingo.month_of(), squares_json=json.dumps(
            ['horror', 'film', 'long', 'late', 'comedy', 'matinee', 'pre1960', 'documentary'])))
        db.session.add(Attendance(user_id=club['Bo'], showtime_id=club['show'], status='went', source='site',
                                  answered_at=datetime.utcnow()))
        db.session.commit()
    tick()
    [win] = ready()
    assert win['kind'] == 'bingo_win' and win['which'] == 'line' and win['name'] is None   # Bo hasn't said Always
    assert 'bingo_win' in bell(club, 'Bo')                                   # your own bingo: on to start with
    tick()
    assert len(ready()) == 1                                                  # not again
    client(club['Bo']).put('/api/discord/prefs', json={'games': 'always'})
    from app import app, db, GamePost
    with app.app_context():
        GamePost.query.delete()
        db.session.commit()
    tick()
    assert ready()[0]['name'] == 'Bo'


def test_yesterdays_answer_for_those_who_want_it(club):
    import trivia
    from app import app, db, Group, TriviaAnswer
    settings(club, trivia_enabled=True)
    client(club['Bo']).put('/api/me/notifications', json={'types': {'trivia_result': True, 'trivia_daily': True}})
    with app.app_context():
        q = trivia.question_for(db.session.get(Group, 1), trivia.today() - timedelta(days=1))
        db.session.add(TriviaAnswer(question_id=q.id, user_id=club['Bo'], choice=q.answer, correct=True))
        db.session.commit()
    tick()
    items = {i['kind']: i for i in client(club['Bo']).get('/api/notifications').json['items']}
    assert items['trivia_result']['detail'].endswith('You got it ✅ · 1 of 1 got it')
    assert items['trivia_daily']['headline'] == 'Today’s trivia question is up'
    assert 'trivia_daily' not in bell(club, 'Vi')                             # read-only members can't play
    tick()
    assert [i['kind'] for i in client(club['Bo']).get('/api/notifications').json['items']].count('trivia_result') == 1


def test_the_old_discord_switch_carries_over():
    from app import app, db, Group, migrate
    setup_db()
    with app.app_context():
        g = db.session.get(Group, 1)
        g.trivia_discord, g.trivia_post = True, 'never'
        db.session.commit()
        migrate()
        migrate()
        g = db.session.get(Group, 1)
        assert g.trivia_post == 'always' and not g.trivia_discord


def test_the_scraper_runs_it_on_its_own(club):
    """scraper.py calls tick() outside any request — it makes its own context."""
    import game_posts
    settings(club, trivia_enabled=True, trivia_post='always')
    assert game_posts.tick(NOON) == 1
    assert [r['kind'] for r in ready()] == ['trivia']


def test_a_skipped_post_can_still_go_up_until_it_lapses(club):
    """R15: "Post it after all" — straight up, until 10 PM for the question."""
    settings(club, trivia_enabled=True, trivia_post='ask')
    tick()
    [p] = posts(club).json['waiting']
    assert decide(club, p['id'], 'skip').json['status'] == 'skipped'
    [s] = posts(club).json['skipped']
    assert s['id'] == p['id'] and s['until'] == '10 PM'
    assert decide(club, p['id'], 'post', who='Bo').status_code == 403
    assert decide(club, p['id'], 'post').json['status'] == 'approved'
    assert [r['id'] for r in ready()] == [p['id']]


def test_a_skipped_question_lapses_at_10_pm(club, monkeypatch):
    import game_posts
    settings(club, trivia_enabled=True, trivia_post='ask')
    tick()
    [p] = posts(club).json['waiting']
    decide(club, p['id'], 'skip')
    late = NOON.replace(hour=22, minute=5)
    monkeypatch.setattr(game_posts, '_local_now', lambda *_: late)
    assert posts(club).json['skipped'] == []                                  # not offered any more
    r = decide(club, p['id'], 'post')
    assert r.status_code == 400 and 'too late' in r.json['error']
    tick(late)
    from app import app, db, GamePost
    with app.app_context():
        assert db.session.get(GamePost, p['id']).status == 'expired'

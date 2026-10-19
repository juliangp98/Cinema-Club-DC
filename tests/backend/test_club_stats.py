"""The Club page's numbers and who runs what (R15): each member's stats for a
period, the leaderboard's superlatives (each with a minimum), the Overview's
club stats — and organizers managing theatres, games, join requests and game
posts while the club's details stay with admins."""
import time
from datetime import datetime, timedelta

import pytest

from helpers import all_linked_present, setup_db

NOW = datetime.now().replace(day=15, hour=23, minute=59, second=0, microsecond=0)   # mid-month, late


def day(n, h=19, m=0):
    return NOW.replace(day=n, hour=h, minute=m)


@pytest.fixture
def season():
    """Stats Club: Ana (admin), Olly (organizer), Bo, Cy, Dee (members); Newt
    asked to join. This month: Ana, Bo and Cy at a 35mm show on the 1st (a crew
    night); Ana at 10 PM on the 8th and a 70mm show at 9:45 PM on the 15th
    (three weeks running); Bo at two more theatres. Bo said "going" first to
    two screenings others joined; Dee commented three times; Olly answered ten
    questions of the day (one wrong). Cy also saw a 35mm show last year."""
    from app import (app, db, Attendance, Group, GroupMembership, Message, Movie, RSVP, Showtime, Theatre,
                     TriviaAnswer, TriviaQuestion, User, Watchlist)
    setup_db()
    with app.app_context():
        ts = Theatre.query.order_by(Theatre.id).limit(3).all()
        g = Group(name='Stats Club', slug='stats-club', is_public=False)
        db.session.add(g)
        db.session.flush()
        us = {n: User(email=f'{n}@stats.test', name=n.title(), is_active=True) for n in
              ('ana', 'olly', 'bo', 'cy', 'dee', 'newt')}
        db.session.add_all(us.values())
        db.session.flush()
        for n, role in (('ana', 'admin'), ('olly', 'organizer'), ('bo', 'member'), ('cy', 'member'), ('dee', 'member')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g.id, status='active', role=role))
        db.session.add(GroupMembership(user_id=us['newt'].id, group_id=g.id, status='pending', role='member'))
        m = Movie(title='STATS FILM')
        wanted = Movie(title='WANTED FILM', tmdb_id=1)
        db.session.add_all([m, wanted])
        db.session.flush()

        def show(when, theatre, fmt=None, event=None, movie=m):
            s = Showtime(movie_id=movie.id, theatre_id=theatre.id, start_time=when, format_label=fmt, event_label=event)
            db.session.add(s)
            db.session.flush()
            return s
        s1, s2 = show(day(1), ts[0], '35mm'), show(day(8, 22), ts[1])
        s3 = show(day(15, 21, 45), ts[0], event='Presented in 70mm')
        s4, s6 = show(day(12), ts[2]), show(day(13), ts[1])
        s5 = show(NOW - timedelta(days=400), ts[1], '35mm')
        upcoming = show(datetime.now() + timedelta(days=30), ts[0], movie=wanted)
        went = {'ana': [s1, s2, s3], 'bo': [s1, s4, s6], 'cy': [s1, s5]}
        for n, ss in went.items():
            for s in ss:
                db.session.add(Attendance(user_id=us[n].id, showtime_id=s.id, status='went', answered_at=s.start_time))
        for s, order in ((s2, ('bo', 'ana')), (s3, ('bo', 'cy'))):
            for i, n in enumerate(order):
                db.session.add(RSVP(user_id=us[n].id, showtime_id=s.id, group_id=g.id, status='going',
                                    created_at=s.start_time - timedelta(days=5 - i)))
        for n, s in (('bo', s2), ('bo', s3), ('cy', s3)):                 # said going, didn't make it
            db.session.add(Attendance(user_id=us[n].id, showtime_id=s.id, status='missed'))
        for i in range(3):
            db.session.add(Message(user_id=us['dee'].id, showtime_id=s1.id, group_id=g.id, body=f'take {i}'))
        for d in range(1, 11):
            q = TriviaQuestion(group_id=g.id, day=day(d).date(), slot='daily', kind='quote', prompt='?',
                               options_json='["a","b","c","d"]', answer=0, ref=f'q{d}')
            db.session.add(q)
            db.session.flush()
            db.session.add(TriviaAnswer(question_id=q.id, user_id=us['olly'].id, choice=0 if d != 5 else 1,
                                        correct=d != 5))
            if d <= 3:
                db.session.add(TriviaAnswer(question_id=q.id, user_id=us['ana'].id, choice=0, correct=True))
        for n in ('bo', 'cy'):
            db.session.add(Watchlist(user_id=us[n].id, movie_id=wanted.id))
        db.session.commit()
        ids = {n: u.id for n, u in us.items()}
        out = {**ids, 'group': g.id, 'slug': g.slug, 'theatres': [t.slug for t in ts], 'wanted': wanted.id,
               'upcoming': upcoming.id, 's3': s3.id}
    all_linked_present()
    return out


def as_(season, name):
    from app import app
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = season[name]
        s['seen'] = int(time.time())
    return c


def board(season, period):
    import club_stats
    from app import app, db, Group
    with app.app_context():
        return club_stats.leaderboard(db.session.get(Group, season['group']), period, now=NOW)


def test_each_members_stats_for_the_month(season):
    rows = {r['user']['name']: r for r in board(season, 'month')['rows']}
    ana, bo = rows['Ana']['stats'], rows['Bo']['stats']
    assert (ana['screenings'], ana['film_prints'], ana['theatres'], ana['late'], ana['crew_nights'], ana['week_streak']) \
        == (3, 2, 2, 2, 1, 3)
    assert (bo['screenings'], bo['theatres'], bo['first_going']) == (3, 3, 2)
    assert rows['Dee']['stats']['comments'] == 3
    olly = rows['Olly']['stats']['trivia']
    assert (olly['answered'], olly['correct'], olly['accuracy'], olly['streak']) == (10, 9, 90, 5)
    assert rows['Ana']['attendance'] == 3 and rows['Ana']['breakdown']['going_out'] > 0


def test_periods_count_what_happened_in_them(season):
    month = {r['user']['name']: r for r in board(season, 'month')['rows']}
    ever = {r['user']['name']: r for r in board(season, 'all')['rows']}
    assert month['Cy']['stats']['screenings'] == 1 and ever['Cy']['stats']['screenings'] == 2
    assert month['Cy']['stats']['film_prints'] == 1 and ever['Cy']['stats']['film_prints'] == 2
    assert ever['Cy']['breakdown']['going_out'] - month['Cy']['breakdown']['going_out'] == 5   # last year's check-in
    assert board(season, 'month')['since'].startswith(NOW.strftime('%Y-%m-01'))
    assert board(season, 'all')['since'] is None


def test_superlatives_go_to_the_leader_once_they_reach_the_minimum(season):
    won = {s['key']: (s['user']['name'], s['value']) for s in board(season, 'month')['superlatives']}
    assert won == {'night_owl': ('Ana', 2), 'purist': ('Ana', 2), 'explorer': ('Bo', 3), 'early_bird': ('Bo', 2),
                   'critic': ('Dee', 3), 'sharpshooter': ('Olly', 90), 'regular': ('Ana', 3)}
    # Ana's three right answers out of three don't beat Olly's 90%: ten answers first.


def test_the_overview(season):
    import club_stats
    from app import app, db, Group
    with app.app_context():
        o = club_stats.overview(db.session.get(Group, season['group']), now=NOW)
    assert o['screenings_together'] == 1 and o['member_screenings'] == 7         # Cy's last-year show doesn't count
    assert o['busiest_theatre']['theatre']['slug'] == season['theatres'][0] and o['busiest_theatre']['screenings'] == 4
    assert o['most_wanted']['movie']['id'] == season['wanted'] and o['most_wanted']['wanters'] == 2
    assert o['members'][season['ana']]['screenings'] == 3 and o['members'][season['dee']] == {'screenings': 0, 'last_out': None}
    assert [t['user']['name'] for t in o['top']][:1] in (['Ana'], ['Bo'])


def test_the_endpoints(season):
    ana = as_(season, 'ana')
    r = ana.get(f"/api/groups/{season['group']}/leaderboard", query_string={'period': 'year'})
    assert r.status_code == 200 and r.json['period'] == 'year' and r.json['rows'] and 'superlatives' in r.json
    assert ana.get(f"/api/groups/{season['group']}/leaderboard", query_string={'period': 'decade'}).status_code == 400
    assert ana.get(f"/api/groups/{season['group']}/stats").json['month_label'] == datetime.now().strftime('%B')
    assert as_(season, 'newt').get(f"/api/groups/{season['group']}/stats").status_code == 403


def test_organizers_run_theatres_and_games_but_not_the_clubs_details(season):
    olly, bo, url = as_(season, 'olly'), as_(season, 'bo'), f"/api/groups/{season['slug']}"
    r = olly.put(url, json={'theatres': season['theatres'][:1], 'trivia_enabled': True, 'trivia_post': 'ask'})
    assert r.status_code == 200 and r.json['theatres'] == season['theatres'][:1]
    assert olly.put(url, json={'name': 'Olly Club'}).status_code == 403
    assert olly.put(url, json={'trivia_enabled': False, 'description': 'x'}).status_code == 403   # all or nothing
    assert bo.put(url, json={'bingo_enabled': True}).status_code == 403
    assert as_(season, 'ana').put(url, json={'name': 'Renamed'}).json['name'] == 'Renamed'


def test_organizers_answer_join_requests_and_review_game_posts(season):
    import game_posts
    from app import app, db, GamePost, Group, User
    olly, bo = as_(season, 'olly'), as_(season, 'bo')
    assert bo.post(f"/api/groups/{season['slug']}/members/{season['newt']}/approve").status_code == 403
    assert olly.post(f"/api/groups/{season['slug']}/members/{season['newt']}/approve").status_code == 200
    with app.app_context():
        g = db.session.get(Group, season['group'])
        assert {u.name for u in game_posts._reviewers(g)} == {'Ana', 'Olly'}        # they hear a post is waiting
        g.bingo_enabled = True
        post = GamePost(group_id=g.id, kind='bingo_card', ref=NOW.strftime('%Y-%m'), status='waiting')
        db.session.add(post)
        db.session.commit()
        pid = post.id
        view, err = game_posts.decide(db.session.get(GamePost, pid), db.session.get(User, season['bo']), 'skip')
        assert view is None and 'organizers and admins' in err
    assert olly.get(f"/api/groups/{season['slug']}/game-posts").status_code == 200
    assert olly.post(f"/api/groups/{season['slug']}/game-posts/{pid}", json={'action': 'skip'}).json['status'] == 'skipped'


def test_organizers_choose_whether_join_requests_email_them(season, monkeypatch):
    import routes.clubs as clubs
    sent = []
    monkeypatch.setattr(clubs, 'email_join_request', lambda to, who, club: sent.append(to))
    assert as_(season, 'ana').put(f"/api/groups/{season['slug']}", json={'is_public': True}).status_code == 200   # open to requests
    from app import app, db, User
    with app.app_context():
        for n in ('kit', 'lee'):
            db.session.add(User(email=f'{n}@stats.test', name=n.title(), is_active=True))
        db.session.commit()
        kit, lee = (User.query.filter_by(email=f'{n}@stats.test').first().id for n in ('kit', 'lee'))
    season.update(kit=kit, lee=lee)
    as_(season, 'kit').post(f"/api/groups/{season['slug']}/join")
    assert sent == ['ana@stats.test']                                         # admins always; organizers only if asked
    olly = as_(season, 'olly')
    assert olly.put('/api/me/notifications', json={'types': {'join_requests': True}}).status_code == 200
    as_(season, 'lee').post(f"/api/groups/{season['slug']}/join")
    assert sorted(sent[1:]) == ['ana@stats.test', 'olly@stats.test']


def test_club_running_switches_only_for_people_who_run_a_club(season):
    keys = lambda who: {t['key'] for t in as_(season, who).get('/api/me/notifications').json['types_info']}
    assert {'reviews', 'join_requests'} <= keys('olly')
    assert 'reviews' in keys('ana') and 'join_requests' not in keys('ana')          # admins always get them
    assert not {'reviews', 'join_requests'} & keys('bo')


def test_this_weeks_movers_count_from_monday(season):
    import club_stats
    since = club_stats.since_of('week', NOW)
    assert since.weekday() == 0 and since <= NOW < since + timedelta(days=7)
    assert board(season, 'week')['period'] == 'week'


def test_ties_share_a_place(season):
    """Places go by kernels: equal kernels share one, and the next place skips (1, 1, 3)."""
    rows = board(season, 'all')['rows']
    for r in rows:
        assert r['place'] == 1 + sum(1 for x in rows if x['kernels'] > r['kernels'])
    zero = [r for r in rows if r['kernels'] == 0]
    assert len({r['place'] for r in zero}) <= 1                                   # everyone on 0 shares the last place

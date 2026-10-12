"""The weekly digest's content (backend) and its Discord post (embeds):
rarity, plans, last chance, opening, the recap and the post's shape."""
import json
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, client, setup_db


@pytest.fixture
def digest():
    """A club at AFI + Suns over the next week: a one-night 35mm 1974 print, a
    wide re-release, a new film once on 35mm, an indie doc with a Q&A, six
    classics, SINNERS (2 watchers, nobody going), HOT TICKET (2 watchers,
    someone going), SOLO WANT (1 watcher), LEAVING (final showing), EDGE (last
    showing at the edge of the published schedule), OPENER, RETURNING; last
    week's check-ins, comments, a scored poll and a schedule drop. Everyone
    lets the digest mention their watchlist."""
    from app import (app, db, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist,
                     Attendance, Message, Poll, PollCategory, PollOption, PollVote, ScrapeEvent)
    setup_db()
    with app.app_context():
        now = datetime.now().replace(minute=0, second=0, microsecond=0)
        afi, suns = Theatre.query.filter_by(slug='afi').first(), Theatre.query.filter_by(slug='suns').first()
        g = Group(name='Digest Club', slug='digest-club', is_public=False, theatres='afi,suns'); db.session.add(g); db.session.flush()
        users = [User(email=f'd{i}@t.dev', name=n, is_active=True, discord_user_id=f'77{i}' if i < 3 else None)
                 for i, n in enumerate(['Ana', 'Bo', 'Cy', 'Dee'])]
        db.session.add_all(users); db.session.flush()
        A, B, C, D = users
        for u in users:
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        def film(title, year):
            m = Movie(title=title, release_year=str(year)); db.session.add(m); db.session.flush(); return m
        def show(m, th, hours, fmt=None, event=None):
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(hours=hours),
                         end_time=now + timedelta(hours=hours + 2), format_label=fmt, event_label=event)
            db.session.add(s); db.session.flush(); return s
        y = now.year
        conv = film('THE CONVERSATION', 1974); conv_s = show(conv, afi, 30, '35mm')                       # one night, 35mm, old
        lotr = film('FELLOWSHIP', 2001)
        for h in range(10, 10 + 8 * 12, 12): show(lotr, afi, h); show(lotr, suns, h + 1)                # wide re-release
        new35 = film('NEW ON FILM', y); show(new35, suns, 50, '35mm')                                     # new, once, 35mm
        qa = film('INDIE DOC', y - 1); show(qa, suns, 60, event='INDIE DOC + Q&A with the director'); show(qa, suns, 84)
        olds = [film(f'CLASSIC {i}', 1950 + i) for i in range(6)]                                         # 6 more rare films
        for i, m in enumerate(olds): show(m, afi, 100 + i)
        want = film('SINNERS', y); want_s = show(want, afi, 40); show(want, afi, 64)                       # 2 watchers, nobody going
        hot = film('HOT TICKET', y); hot_s = show(hot, afi, 20); show(hot, afi, 44)                        # 2 watchers, someone going
        solo = film('SOLO WANT', y); show(solo, suns, 22); show(solo, suns, 46)                            # 1 watcher
        leaving = film('LEAVING', y - 1)
        for d in (-6, -4, -2): show(leaving, suns, d * 24)
        leave_s = show(leaving, suns, 70)                                                                  # final showing in window
        later = film('SUNS LATER', y)                                                                     # suns' full schedule runs on
        for d in range(8, 13):                                                                            # (a full day's worth, so the
            for h in (12, 15, 18, 21): show(later, suns, 24 * d + h)                                     # horizon holds at any hour)
        edge = film('EDGE', y - 1)
        for d in (-5, -3): show(edge, afi, d * 24)
        edge_s = show(edge, afi, 24 * 6 + 20)                                                              # last afi show... see below
        opener = film('OPENER', y); show(opener, afi, 26); show(opener, suns, 27)                          # first ever showings
        returning = film('RETURNING', y); show(returning, afi, -24 * 20); show(returning, afi, 28)          # had earlier showings
        for u in (A, B):
            db.session.add(Watchlist(user_id=u.id, movie_id=want.id))
            db.session.add(Watchlist(user_id=u.id, movie_id=hot.id))
        db.session.add(Watchlist(user_id=C.id, movie_id=solo.id))
        db.session.add(RSVP(user_id=C.id, showtime_id=hot_s.id, group_id=g.id, status='going'))
        # last week: check-ins and talk
        past = show(conv, afi, -48); past2 = show(film('LAST WEEK', y), suns, -30)
        for u in (A, B):
            db.session.add(RSVP(user_id=u.id, showtime_id=past.id, group_id=g.id, status='going'))
        db.session.add(Attendance(user_id=C.id, showtime_id=past.id, status='went', answered_at=datetime.utcnow()))
        db.session.add(Attendance(user_id=D.id, showtime_id=past2.id, status='went', answered_at=datetime.utcnow()))
        for i in range(4):
            db.session.add(Message(user_id=A.id, showtime_id=past.id, group_id=g.id, body=f'c{i}', created_at=datetime.utcnow()))
        p = Poll(group_id=g.id, created_by=A.id, title='Fest picks', status='scored', scoring_mode='single',
                 scored_at=datetime.utcnow() - timedelta(days=1)); db.session.add(p); db.session.flush()
        c = PollCategory(poll_id=p.id, title='Best'); db.session.add(c); db.session.flush()
        o = PollOption(category_id=c.id, text='X'); db.session.add(o); db.session.flush(); c.correct_option_id = o.id
        db.session.add(PollVote(category_id=c.id, user_id=B.id, option_id=o.id))
        db.session.add(ScrapeEvent(theatre_id=afi.id, event_type='new_drop', payload_json=json.dumps({'new_showtime_count': 23})))
        db.session.commit()
        G, IDS = g.id, {'conv': conv_s.id, 'want': want_s.id, 'leave': leave_s.id, 'edge': edge_s.id}

    all_linked_present()   # R6a.1: they're all in the club's server
    with app.app_context():                # …and let the digest mention their watchlists
        Watchlist.query.update({'share_discord': True}); db.session.commit()
    d = client().get('/api/internal/digest', query_string={'group_id': G, 'days': 7}, headers=H).json
    return {'d': d, 'ids': IDS, 'now': now}


def titles(d, section):
    return [x['title'] for x in d[section]]


def test_rare_screenings_lead_with_their_reasons(digest):
    d = digest['d']
    top = d['rare'][0]
    assert top['title'] == 'THE CONVERSATION' and top['reasons'] == ['one night only', '35mm', '1974'] and top['score'] == 10
    assert 'FELLOWSHIP' not in titles(d, 'rare')                               # a wide re-release isn't rare
    assert len(d['rare']) == 5                                                  # capped
    assert any(r['title'] == 'NEW ON FILM' and r['score'] == 7 for r in d['rare']) or 'NEW ON FILM' in titles(d, 'rare')


def test_a_q_and_a_adds_points_and_a_reason(digest):
    from app import app, rarity, Showtime
    with app.app_context():
        s = Showtime.query.filter(Showtime.event_label.like('%Q&A%')).first()
        score, why = rarity(s, 2, 1, digest['now'].year)
    assert 'Q&A' in why and '2 showings' in why and score == 5


def test_make_plans(digest):
    d = digest['d']
    assert titles(d, 'plans') == ['SINNERS'] and d['plans'][0]['wanters'] == ['Ana', 'Bo']
    assert d['plans'][0]['showtime_id'] == digest['ids']['want']
    assert 'HOT TICKET' not in titles(d, 'plans') and 'HOT TICKET' in titles(d, 'whos_going')   # someone's going
    assert 'SOLO WANT' not in titles(d, 'plans')                                               # one watcher isn't enough
    assert [w['planned'] for w in d['watchlist'] if w['title'] == 'SINNERS'] == [True]


def test_last_chance_and_opening(digest):
    d = digest['d']
    assert titles(d, 'last_chance') == ['LEAVING']                    # final showing, its theatre's schedule runs on
    assert 'EDGE' not in titles(d, 'last_chance')                     # its last showing is just the schedule's edge
    assert any(o['title'] == 'OPENER' and o['theatres'] == 2 for o in d['opening'])
    assert 'RETURNING' not in titles(d, 'opening') and 'THE CONVERSATION' not in titles(d, 'opening')
    every = [t for s in ('plans', 'rare', 'last_chance', 'opening') for t in titles(d, s)]
    assert len(every) == len(set(every))                              # each film in one section


def test_last_weeks_recap(digest):
    d = digest['d']
    r = d['recap']
    assert r['checkins'] == 4 and r['films'] == 2 and r['top_film'] == {'title': 'THE CONVERSATION', 'count': 3}
    assert r['discussed']['comments'] == 4 and r['poll'] == {'title': 'Fest picks', 'winner': 'Bo', 'kernels': 1}
    assert d['new_on_calendar'][0]['showtimes'] == 23


@pytest.fixture
def post(digest):
    import embeds
    return embeds.digest_message(digest['d'], tag_watchers=True)


def test_the_discord_post(post):
    content, embed, tagged, plans = post
    assert [f.name for f in embed.fields] == ["🎟️ Who's going", '🤝 Make plans — nobody’s going yet', '💎 Rare this week',
                                              '🆕 Opening this week', '⏳ Last chance', '👀 On your watchlists', '📊 Last week']
    assert embed.footer.text.startswith('New on the calendar: AFI +23\n')
    assert 'one night only · 35mm · 1974' in embed.fields[2].value
    assert 'SINNERS' not in embed.fields[5].value and 'SINNERS' in content     # under plans only — but still pinged
    assert sum(f.value.count('\n') + 1 for f in embed.fields) <= 22          # short
    assert [p['title'] for p in plans] == ['SINNERS']                          # for the Going buttons

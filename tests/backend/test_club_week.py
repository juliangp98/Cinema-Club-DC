"""club_week"""
from helpers import H, client, Checks, WORK


def test_club_week():
    checks = Checks()
    check = checks.check
    import sys
    from datetime import datetime, timedelta, timezone
    from app import app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Message, Poll, PollCategory, PollOption, PollVote
    with app.app_context():
        db.create_all(); migrate()
        g = Group(name='Week', slug='week-r3c', is_public=False); db.session.add(g); db.session.flush()
        th = Theatre.query.filter_by(slug='afi').first()
        us = [User(email=f'w{i}@r3c.test', name=n, is_active=True) for i, n in enumerate(['Me', 'Ana', 'Bo', 'Outsider'])]
        db.session.add_all(us); db.session.flush()
        for u in us[:3]:
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        now = datetime.now()
        def film(t):
            m = Movie(title=t); db.session.add(m); db.session.flush(); return m
        def show(m, days):
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=days)); db.session.add(s); db.session.flush(); return s
        big, small, later, past = show(film('BIG'), 2), show(film('SMALL'), 1), show(film('LATER'), 9), show(film('PAST'), -1)
        for u in us[:3]: db.session.add(RSVP(user_id=u.id, showtime_id=big.id, group_id=g.id, status='going'))
        db.session.add(RSVP(user_id=us[1].id, showtime_id=small.id, group_id=g.id, status='going'))
        db.session.add(RSVP(user_id=us[2].id, showtime_id=small.id, group_id=g.id, status='maybe'))
        db.session.add(RSVP(user_id=us[1].id, showtime_id=later.id, group_id=g.id, status='going'))
        db.session.add(RSVP(user_id=us[1].id, showtime_id=past.id, group_id=g.id, status='going'))
        utc = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.add_all([Message(user_id=us[1].id, showtime_id=big.id, group_id=g.id, body='old', created_at=utc - timedelta(days=9)),
                            Message(user_id=us[0].id, showtime_id=big.id, group_id=g.id, body='mine', created_at=utc),
                            Message(user_id=us[2].id, showtime_id=small.id, group_id=g.id, body='Bo says hi', created_at=utc - timedelta(hours=1))])
        p1 = Poll(group_id=g.id, created_by=us[1].id, title='Voted one', status='open'); p2 = Poll(group_id=g.id, created_by=us[1].id, title='Fresh one', status='open')
        p3 = Poll(group_id=g.id, created_by=us[1].id, title='Done', status='scored')
        db.session.add_all([p1, p2, p3]); db.session.flush()
        c = PollCategory(poll_id=p1.id, title='C'); db.session.add(c); db.session.flush()
        o = PollOption(category_id=c.id, text='x'); db.session.add(o); db.session.flush()
        db.session.add(PollVote(category_id=c.id, user_id=us[0].id, option_id=o.id))
        db.session.commit()
        G, ME, OUT = g.id, us[0].id, us[3].id

    c = app.test_client()
    with c.session_transaction() as s: s['user_id'] = ME
    r = c.get('/api/club/week', query_string={'group_id': G}).json
    check('plans: next 7 days only, going only, most-attended first', [p['movie']['title'] for p in r['plans']] == ['BIG', 'SMALL'], r['plans'])
    check('plan shape', r['plans'][0]['you_going'] and len(r['plans'][0]['going']) == 3 and not r['plans'][1]['you_going']
          and r['plans'][1]['going'][0]['name'] == 'Ana')
    check('open polls with your vote state', {(p['title'], p['you_voted']) for p in r['polls']} == {('Voted one', True), ('Fresh one', False)})
    check("comments: this week, others' only, latest first", r['comments']['count'] == 1 and r['comments']['latest']['user'] == 'Bo'
          and r['comments']['latest']['movie'] == 'SMALL', r['comments'])
    o = app.test_client()
    with o.session_transaction() as s: s['user_id'] = OUT
    check('non-members get 403', o.get('/api/club/week', query_string={'group_id': G}).status_code == 403)
    check('signed out gets 401', app.test_client().get('/api/club/week', query_string={'group_id': G}).status_code == 401)
    checks.done()

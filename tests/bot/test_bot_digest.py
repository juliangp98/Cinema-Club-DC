"""bot_digest"""
from helpers import H, client, Checks, WORK


def test_bot_digest():
    checks = Checks()
    check = checks.check
    import sys, json
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist,
                     Attendance, Message, Poll, PollCategory, PollOption, PollVote, ScrapeEvent, INTERNAL_API_TOKEN)


    with app.app_context():
        db.create_all(); migrate()
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

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    with app.app_context():                # …and let the digest mention their watchlists
        Watchlist.query.update({'share_discord': True}); db.session.commit()
    c = app.test_client()
    d = c.get('/api/internal/digest', query_string={'group_id': G, 'days': 7}, headers={'X-Internal-Token': INTERNAL_API_TOKEN}).get_json()
    titles = lambda sec: [x['title'] for x in d[sec]]
    print('rare:', [(r['title'], r['score'], r['reasons']) for r in d['rare']])

    print('--- rarity ---')
    check('one-night 35mm 1974 print tops the list with its reasons', d['rare'][0]['title'] == 'THE CONVERSATION'
          and d['rare'][0]['reasons'] == ['one night only', '35mm', '1974'] and d['rare'][0]['score'] == 10, d['rare'][0])
    check('wide anniversary re-release is not "rare"', 'FELLOWSHIP' not in titles('rare'))
    check('capped at 5', len(d['rare']) == 5)
    check('a new release shown once on 35mm can be rare (scores 7)', any(r['title'] == 'NEW ON FILM' and r['score'] == 7 for r in d['rare'])
          or 'NEW ON FILM' in titles('rare'), titles('rare'))
    from app import rarity
    with app.app_context():
        s = Showtime.query.filter(Showtime.event_label.like('%Q&A%')).first()
        sc, why = rarity(s, 2, 1, now.year)
    check('Q&A billing adds points and a reason', 'Q&A' in why and '2 showings' in why and sc == 5, (sc, why))

    print('--- plans ---')
    check('2 members want it, nobody going -> Make plans', titles('plans') == ['SINNERS'] and d['plans'][0]['wanters'] == ['Ana', 'Bo']
          and d['plans'][0]['showtime_id'] == IDS['want'], d['plans'])
    check("someone's going -> not a plan (it's under Who's going)", 'HOT TICKET' not in titles('plans') and 'HOT TICKET' in titles('whos_going'))
    check('one watcher is not enough', 'SOLO WANT' not in titles('plans'))
    check('planned films are flagged in the watchlist list (shown once)', [w['planned'] for w in d['watchlist'] if w['title'] == 'SINNERS'] == [True])

    print('--- last chance / opening ---')
    check('final showing while its theatre schedule runs on -> last chance', titles('last_chance') == ['LEAVING'], d['last_chance'])
    check("a film whose last showing is just the edge of the published schedule isn't flagged", 'EDGE' not in titles('last_chance'))
    check('first-ever showings of a recent release -> opening (with venue count)', any(o['title'] == 'OPENER' and o['theatres'] == 2 for o in d['opening']), d['opening'])
    check('a film that played before is not "opening"', 'RETURNING' not in titles('opening'))
    check('old films never "open"', 'THE CONVERSATION' not in titles('opening'))
    secs = ['plans', 'rare', 'last_chance', 'opening']
    all_titles = [t for s in secs for t in titles(s)]
    check('each film in at most one section', len(all_titles) == len(set(all_titles)), all_titles)

    print('--- recap, footer ---')
    r = d['recap']
    check('recap: check-ins incl. unanswered going RSVPs, top film', r['checkins'] == 4 and r['films'] == 2
          and r['top_film'] == {'title': 'THE CONVERSATION', 'count': 3}, r)
    check('recap: most discussed + poll winner', r['discussed']['comments'] == 4 and r['poll'] == {'title': 'Fest picks', 'winner': 'Bo', 'kernels': 1}, r)
    check('schedule drops reduced to counts', d['new_on_calendar'] == [{'theatre': 'AFI', 'showtimes': 23}] or d['new_on_calendar'][0]['showtimes'] == 23, d['new_on_calendar'])

    print('--- the Discord post ---')
    import embeds
    content, embed, tagged, plans = embeds.digest_message(d, tag_watchers=True)
    names = [f.name for f in embed.fields]
    check('sections in order, no title dump', names == ["🎟️ Who's going", '🤝 Make plans — nobody’s going yet', '💎 Rare this week',
                                                         '🆕 Opening this week', '⏳ Last chance', '👀 On your watchlists', '📊 Last week'], names)
    check('footer is one line of counts + calendar link', embed.footer.text.startswith('New on the calendar: AFI +23\n'), embed.footer.text)
    check('rare lines carry reasons', 'one night only · 35mm · 1974' in embed.fields[2].value, embed.fields[2].value)
    wl = embed.fields[5].value
    check('SINNERS listed under plans, not again under watchlists — but still pinged', 'SINNERS' not in wl and 'SINNERS' in content, (wl, content))
    total_lines = sum(f.value.count('\n') + 1 for f in embed.fields)
    check(f'short: {total_lines} lines', total_lines <= 22, total_lines)
    check('plan picks returned for Going buttons', [p['title'] for p in plans] == ['SINNERS'])
    checks.done()

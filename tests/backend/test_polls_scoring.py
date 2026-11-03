"""Scoring a poll: answers all at once (finalize) or live (each as it's set,
locking that category), the deadline, fixing a poll after it's made, and
each voter's result in their bell."""
import json
from datetime import timedelta

import test_polls_voting as voting
from helpers import H, client
from test_polls_voting import FEST, ballot, discord_vote, posts

club, fest = voting.club, voting.fest          # the same fixtures: Vote Club and Ana's Fest picks


def live_fest(club, **extra):
    r = client(club['ana']).post(f"/api/groups/{club['group']}/polls", json={**FEST, 'reveal': 'live', **extra}).json
    bp, bd = r['categories']
    return {**club, 'poll': r['id'], 'bp': bp['id'], 'bd': bd['id'],
            **dict(zip(('sirat', 'hamnet', 'sinners'), [o['id'] for o in bp['options']])),
            **dict(zip(('laxe', 'zhao'), [o['id'] for o in bd['options']]))}


def site_vote(c, uid, cat, opt, conf=1):
    return client(uid).post(f"/api/polls/{c['poll']}/vote",
                            json={'votes': [{'category_id': c[cat], 'option_id': c[opt], 'confidence': conf}]})


def set_answer(c, cat, opt):
    return client(c['ana']).put(f"/api/polls/{c['poll']}/categories/{c[cat]}/winner", json={'option_id': c[opt]})


def cat_of(poll, cat_id):
    return next(x for x in poll['categories'] if x['id'] == cat_id)


def poll_kernels(uid):
    return client(uid).get('/api/kernels').json['polls']


def test_all_at_once_answers_wait_for_finalize(fest):
    """The default: answers and standings stay hidden from members until the
    poll's finalized; the organizer sees what they've saved (and a preview)."""
    site_vote(fest, fest['cy'], 'bp', 'sirat', 6)
    discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['hamnet'], 'confidence': 4}])
    assert set_answer(fest, 'bp', 'sirat').status_code == 200

    member = client(fest['cy']).get(f"/api/polls/{fest['poll']}").json
    assert cat_of(member, fest['bp'])['correct_option_id'] is None and 'saved_answer' not in cat_of(member, fest['bp'])
    assert member['your_score'] is None and member['decided'] == 0
    assert client(fest['cy']).get(f"/api/polls/{fest['poll']}/leaderboard").json == []
    assert client(fest['cy']).get(f"/api/polls/{fest['poll']}/leaderboard?preview=1").json == []      # members can't preview
    organizer = client(fest['ana']).get(f"/api/polls/{fest['poll']}").json
    assert cat_of(organizer, fest['bp'])['saved_answer'] == fest['sirat']                              # back after a reload
    assert [r['kernels'] for r in client(fest['ana']).get(f"/api/polls/{fest['poll']}/leaderboard?preview=1").json] == [6, -4]
    assert ballot(fest, fest['poll']).json['categories'][0]['correct_option_id'] is None                # Discord too
    discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['sirat'], 'confidence': 4}])
    assert ballot(fest, fest['poll']).json['categories'][0]['picks'][0]['option_id'] == fest['sirat']    # not locked

    assert client(fest['ana']).post(f"/api/polls/{fest['poll']}/score", json={}).status_code == 200    # saved answers count
    member = client(fest['cy']).get(f"/api/polls/{fest['poll']}").json
    assert cat_of(member, fest['bp'])['correct_option_id'] == fest['sirat'] and cat_of(member, fest['bp'])['your_kernels'] == 6
    assert member['your_score'] == {'kernels': 6, 'correct': 1, 'total': 1, 'place': 1, 'of': 2}


def test_finalizing_needs_an_answer(fest):
    r = client(fest['ana']).post(f"/api/polls/{fest['poll']}/score", json={})
    assert r.status_code == 400 and 'at least one answer' in r.json['error']


def test_live_answers_show_and_lock_their_category(club):
    """Live: each answer shows as soon as it's set — on the site, in the
    Discord ballot and in the announcement's standings — and that category
    stops taking votes. Kernels reach totals only when it's finalized."""
    c = live_fest(club)
    site_vote(c, c['cy'], 'bp', 'sirat', 6)
    discord_vote(c, c['poll'], votes=[{'category_id': c['bp'], 'option_id': c['hamnet'], 'confidence': 4}])
    set_answer(c, 'bp', 'sirat')

    me = client(c['cy']).get(f"/api/polls/{c['poll']}").json
    bp = cat_of(me, c['bp'])
    assert bp['correct_option_id'] == c['sirat'] and bp['locked'] and bp['your_kernels'] == 6 and me['decided'] == 1
    assert me['your_score'] == {'kernels': 6, 'correct': 1, 'total': 1, 'place': 1, 'of': 2}
    assert [r['kernels'] for r in client(c['cy']).get(f"/api/polls/{c['poll']}/leaderboard").json] == [6, -4]

    b = ballot(c, c['poll']).json
    assert b['categories'][0]['locked'] and b['categories'][0]['kernels'] == -4 and b['score']['place'] == 2
    discord_vote(c, c['poll'], votes=[{'category_id': c['bp'], 'option_id': c['sirat'], 'confidence': 10}])
    assert ballot(c, c['poll']).json['categories'][0]['picks'][0]['option_id'] == c['hamnet']      # too late to switch
    site_vote(c, c['cy'], 'bp', 'hamnet', 1)
    assert cat_of(client(c['cy']).get(f"/api/polls/{c['poll']}").json, c['bp'])['user_vote']['option_id'] == c['sirat']
    discord_vote(c, c['poll'], votes=[{'category_id': c['bd'], 'option_id': c['zhao'], 'confidence': 2}])
    assert ballot(c, c['poll']).json['categories'][1]['picks']                                      # the rest stay open

    [post] = posts('poll', c['poll'])
    assert post['decided'] == 1 and [t['kernels'] for t in post['live_top']] == [6, -4] and post['live_top'][0]['name'] == 'Cy'
    assert poll_kernels(c['cy']) == 0                                                               # not in totals yet
    client(c['ana']).post(f"/api/polls/{c['poll']}/score", json={})
    assert poll_kernels(c['cy']) == 6


def test_how_its_scored_is_set_once_anyone_votes(fest):
    a = client(fest['ana'])
    assert a.put(f"/api/polls/{fest['poll']}", json={'reveal': 'live'}).status_code == 200            # nobody's voted yet
    site_vote(fest, fest['cy'], 'bp', 'sirat', 3)
    for change in ({'scoring_mode': 'ranked'}, {'reveal': 'final'}, {'poll_type': 'standard'}):
        r = a.put(f"/api/polls/{fest['poll']}", json=change)
        assert r.status_code == 409 and r.json['code'] == 'has_votes'
    assert a.put(f"/api/polls/{fest['poll']}", json={'title': '   '}).status_code == 400
    assert a.put(f"/api/polls/{fest['poll']}", json={'title': 'Fest picks!', 'reveal': 'live'}).status_code == 200   # unchanged is fine


def test_a_deadline_closes_voting_by_itself(club):
    from app import app, db, Poll, _utcnow_naive
    import places
    a = client(club['ana'])
    local = (places.now_in('dc') + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0)
    r = a.post(f"/api/groups/{club['group']}/polls", json={**FEST, 'closes_at': local.isoformat(timespec='minutes')})
    assert r.status_code == 201 and r.json['closes_at_local'] == local.isoformat(timespec='minutes')     # the club's clock
    c = {**club, 'poll': r.json['id'], 'bp': r.json['categories'][0]['id'], 'sirat': r.json['categories'][0]['options'][0]['id']}
    assert site_vote(c, c['cy'], 'bp', 'sirat').status_code == 200
    past = a.post(f"/api/groups/{club['group']}/polls", json={**FEST, 'closes_at': '2020-01-01T20:00'})
    assert past.status_code == 400 and 'future' in past.json['error']

    with app.app_context():                                    # time passes
        db.session.get(Poll, c['poll']).closes_at = _utcnow_naive() - timedelta(minutes=1)
        db.session.commit()
    r = site_vote(c, c['cy'], 'bp', 'sirat')
    assert r.status_code == 400 and r.json['code'] == 'closed'
    assert discord_vote(c, c['poll'], votes=[{'category_id': c['bp'], 'option_id': c['sirat']}]).status_code == 409
    assert client(c['cy']).get(f"/api/polls/{c['poll']}").json['status'] == 'closed'
    assert posts('poll', c['poll'])[0]['status'] == 'closed'                                       # Discord's post follows
    reopened = a.put(f"/api/polls/{c['poll']}", json={'status': 'open'}).json
    assert reopened['status'] == 'open' and reopened['closes_at'] is None                          # open until closed again


def test_the_sweep_closes_polls_past_their_deadline(club):
    from app import app, db, Poll, close_due_polls, _utcnow_naive
    r = client(club['ana']).post(f"/api/groups/{club['group']}/polls", json=FEST).json
    with app.app_context():
        db.session.get(Poll, r['id']).closes_at = _utcnow_naive() - timedelta(seconds=5)
        db.session.commit()
        close_due_polls(force=True)
        p = db.session.get(Poll, r['id'])
        assert p.status == 'closed' and p.closed_at == p.closes_at


def test_fixing_a_poll_after_its_made(fest):
    """Rename, add, reorder and remove — but never what someone has picked."""
    a = client(fest['ana'])
    site_vote(fest, fest['cy'], 'bp', 'hamnet', 2)
    p = a.get(f"/api/polls/{fest['poll']}").json
    cats = [{'id': c['id'], 'title': c['title'], 'options': [{'id': o['id'], 'text': o['text']} for o in c['options']]}
            for c in p['categories']]
    bad = json.loads(json.dumps(cats))
    bad[0]['title'] = 'Best Film'
    bad[0]['options'] = [o for o in bad[0]['options'] if o['text'] != 'HAMNET']
    r = a.put(f"/api/polls/{fest['poll']}", json={'categories': bad})
    assert r.status_code == 409 and '“HAMNET” has picks' in r.json['error']
    assert a.get(f"/api/polls/{fest['poll']}").json['categories'][0]['title'] == 'Best Picture'      # nothing half-saved

    good = json.loads(json.dumps(cats))
    good[0]['options'][0]['text'] = 'Sirât'
    good[0]['options'] = [o for o in good[0]['options'] if o['text'] != 'SINNERS'] + [{'text': 'BUGONIA'}]
    good = [good[1], good[0], {'title': 'Best Score', 'options': [{'text': 'A'}, {'text': 'B'}]}]
    assert a.put(f"/api/polls/{fest['poll']}", json={'categories': good}).status_code == 200
    after = a.get(f"/api/polls/{fest['poll']}").json
    assert [c['title'] for c in after['categories']] == ['Best Director', 'Best Picture', 'Best Score']
    assert [o['text'] for o in after['categories'][1]['options']] == ['Sirât', 'HAMNET', 'BUGONIA']
    assert after['categories'][1]['vote_count'] == 1                                                   # Cy's pick kept
    without = [after['categories'][1]]
    r = a.put(f"/api/polls/{fest['poll']}", json={'categories': [{'id': c['id'], 'title': c['title'], 'options': c['options']} for c in without]})
    assert r.status_code == 200 and len(a.get(f"/api/polls/{fest['poll']}").json['categories']) == 1   # unpicked ones can go
    assert client(fest['cy']).put(f"/api/polls/{fest['poll']}", json={'categories': good}).status_code == 403


def test_results_reach_each_voters_bell_only(fest):
    """Finalized: each voter's result in their bell (never a DM, email or
    push); a correction updates it, undoing scoring takes it away."""
    import notify
    from app import app, db, Notification, User
    site_vote(fest, fest['cy'], 'bp', 'sirat', 6)
    discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['hamnet'], 'confidence': 4}])
    with app.app_context():
        cy = db.session.get(User, fest['cy'])
        notify.set_prefs(cy, {'channels': {'email': True}})
        db.session.commit()
    a = client(fest['ana'])
    a.post(f"/api/polls/{fest['poll']}/score", json={'winners': {str(fest['bp']): fest['sirat']}})

    def notes():
        with app.app_context():
            return {n.user_id: (json.loads(n.payload_json), n.channels, n.read_at)
                    for n in Notification.query.filter_by(kind='poll_result')}
    got = notes()
    assert len(got) == 2 and fest['cy'] in got                                                     # Cy and Bo voted
    cy_note, channels, _ = got[fest['cy']]
    assert (cy_note['kernels'], cy_note['place'], cy_note['of']) == (6, 1, 2) and channels == ''      # the bell only
    item = client(fest['cy']).get('/api/notifications').json['items'][0]
    assert item['headline'] == 'Results are in: Fest picks' and item['detail'] == '+6 🍿 · 1 of 1 right · 1st of 2'
    assert item['link'] == f"/polls/{fest['poll']}" and item['icon'] == '🏆'
    assert fest['ana'] not in got                                                                     # didn't vote

    set_answer(fest, 'bp', 'hamnet')                                                                  # a correction
    got = notes()
    assert len(got) == 2 and got[fest['cy']][0]['kernels'] == -6
    assert client(fest['cy']).get('/api/notifications').json['items'][0]['detail'].startswith('−6 🍿')
    a.put(f"/api/polls/{fest['poll']}", json={'status': 'closed'})                                    # Edit answers
    assert notes() == {}


def test_turning_off_poll_results(fest):
    import notify
    from app import app, db, Notification, User
    with app.app_context():
        notify.set_prefs(db.session.get(User, fest['cy']), {'types': {'poll_result': False}})
        db.session.commit()
    site_vote(fest, fest['cy'], 'bp', 'sirat', 6)
    client(fest['ana']).post(f"/api/polls/{fest['poll']}/score", json={'winners': {str(fest['bp']): fest['sirat']}})
    with app.app_context():
        assert Notification.query.filter_by(kind='poll_result').count() == 0


def test_standings_count_answered_categories(club):
    """"x of y right" is over the categories with an answer you picked in —
    ranked polls count each category once."""
    a = client(club['ana'])
    r = a.post(f"/api/groups/{club['group']}/polls", json={**FEST, 'scoring_mode': 'ranked'}).json
    bp, bd = r['categories']
    o = [x['id'] for x in bp['options']]
    client(club['cy']).post(f"/api/polls/{r['id']}/vote", json={'votes': [
        {'category_id': bp['id'], 'option_id': o[1], 'rank': 1}, {'category_id': bp['id'], 'option_id': o[0], 'rank': 2},
        {'category_id': bd['id'], 'option_id': bd['options'][0]['id'], 'rank': 1}]})
    a.put(f"/api/polls/{r['id']}/categories/{bp['id']}/winner", json={'option_id': o[0]})
    [row] = a.get(f"/api/polls/{r['id']}/leaderboard?preview=1").json
    assert (row['kernels'], row['correct'], row['total']) == (2, 1, 1)                     # Best Director's not answered yet


def test_create_now_in_discord_follows_the_creators_setting(club):
    """Discord's "Create now" announces like the site's form does by default —
    but not when their "Polls I create" setting says Never."""
    from app import app, db, DiscordPost, PollDraft, User, set_share_pref
    with app.app_context():
        set_share_pref(db.session.get(User, club['ana']), 'poll', 'never')
        d = PollDraft(group_id=club['group'], user_id=club['ana'], prompt='x', data_json=json.dumps(FEST))
        db.session.add(d)
        db.session.commit()
        draft_id = d.id
    r = client().post(f'/api/internal/poll-drafts/{draft_id}/create',
                      json={'discord_user_id': '9901', 'group_id': club['group']}, headers=H)
    assert r.status_code == 201 and r.json['announced'] is False
    with app.app_context():
        assert DiscordPost.query.filter_by(kind='poll', ref_id=r.json['id']).count() == 0


def test_the_old_oscars_template_is_gone(club):
    assert client(club['ana']).post(f"/api/groups/{club['group']}/polls/oscars", json={}).status_code in (404, 405)

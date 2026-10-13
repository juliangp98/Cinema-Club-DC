"""Sharing to Discord (R3d): per-kind preferences (ask / always / never), RSVP
posts batched and kept current, "who's in?" invites, poll announcements and
results, and comments that go out only once a screening has a thread."""
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, client, setup_db


@pytest.fixture
def club():
    """Ana (admin), Bo and Cy in the Discord club (group 1) and in a club with
    no Discord. ALPHA, BRAVO, CHARLIE, DELTA in 2–5 days."""
    from app import app, db, User, Group, GroupMembership, Showtime, Movie, Theatre
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        other = Group(name='No Discord', slug='nodisc-r3d', is_public=False)
        db.session.add(other)
        db.session.flush()
        us = [User(email=f'd{i}@r3d.test', name=n, is_active=True, discord_user_id=str(7700 + i)) for i, n in enumerate(['Ana', 'Bo', 'Cy'])]
        db.session.add_all(us)
        db.session.flush()
        for u, role in zip(us, ('admin', 'member', 'member')):
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active', role=role))
            db.session.add(GroupMembership(user_id=u.id, group_id=other.id, status='active'))
        now, ids = datetime.now(), {}
        for key, title, days in (('S1', 'ALPHA', 2), ('S2', 'BRAVO', 3), ('S3', 'CHARLIE', 4), ('S4', 'DELTA', 5)):
            m = Movie(title=title)
            db.session.add(m)
            db.session.flush()
            s = Showtime(movie_id=m.id, theatre_id=th.id, start_time=(now + timedelta(days=days)).replace(hour=19, minute=30, second=0, microsecond=0))
            db.session.add(s)
            db.session.flush()
            ids[key] = s.id
        db.session.commit()
        ids.update(ana=us[0].id, bo=us[1].id, cy=us[2].id, other=other.id)
    all_linked_present()                                                              # all in the club's server
    return ids


def due():
    return client().get('/api/internal/discord/posts/due', query_string={'group_id': 1}, headers=H).json


def done(pid, **body):
    return client().post(f'/api/internal/discord/posts/{pid}/done', json=body, headers=H)


def rsvp(c, who, sid, status, g=1):
    return client(c[who]).post('/api/rsvp', json={'showtime_id': c[sid], 'status': status, 'group_id': g}).json


def share(c, who, **body):
    return client(c[who]).post('/api/discord/shares', json={'group_id': 1, **body})


def my_share(c, sid):
    return client(c['ana']).get(f'/api/showtimes/{c[sid]}', query_string={'group_id': 1}).json['discord']['my_share']


def fast_forward():
    """Skip the batch window for pending RSVP posts."""
    from app import app, db, DiscordPost
    with app.app_context():
        DiscordPost.query.filter_by(status='pending', kind='rsvp').update({'post_at': datetime.now() - timedelta(seconds=1)})
        db.session.commit()


def at(**k):
    return (datetime.now() + timedelta(**k)).strftime('%Y-%m-%dT%H:%M')


# ── preferences and the RSVP prompt ──

def test_preferences(club):
    r = client(club['ana']).get('/api/discord/prefs').json
    assert r == {'prefs': {'rsvp': 'ask', 'poll': 'ask', 'comment': 'ask', 'watchlist': 'ask', 'games': 'never'},
                 'available': True, 'reason': None}
    r = client(club['cy']).put('/api/discord/prefs', json={'rsvp': 'never', 'comment': 'bogus', 'games': 'ask'}).json
    assert r['prefs'] == {'rsvp': 'never', 'poll': 'ask', 'comment': 'ask', 'watchlist': 'ask', 'games': 'never'}  # bad values ignored
    assert client(club['cy']).put('/api/discord/prefs', json={'games': 'always'}).json['prefs']['games'] == 'always'


def test_the_rsvp_prompt(club):
    d = rsvp(club, 'ana', 'S1', 'going')
    assert d['discord']['prompt'] is True and d['discord']['my_share'] is None and due() == []   # ask: nothing queued
    assert 'prompt' not in rsvp(club, 'ana', 'S1', 'going')['discord']                       # same status again
    client(club['cy']).put('/api/discord/prefs', json={'rsvp': 'never'})
    d = rsvp(club, 'cy', 'S1', 'going')
    assert 'prompt' not in d['discord'] and d['discord']['my_share'] is None
    assert rsvp(club, 'ana', 'S2', 'going', g=club['other'])['discord'] is None               # other clubs: no Discord at all


# ── RSVP posts ──

def test_rsvps_batch_into_one_post(club):
    rsvp(club, 'ana', 'S1', 'going')
    r = share(club, 'ana', kind='rsvp', showtime_id=club['S1'])
    assert r.status_code == 201 and r.json['kind'] == 'rsvp' and r.json['status'] == 'pending'
    assert due() == []                                                                        # the batch window
    rsvp(club, 'ana', 'S2', 'maybe')
    r2 = share(club, 'ana', kind='rsvp', showtime_id=club['S2'], remember=True)
    assert r2.json['id'] == r.json['id']                                                      # joins the same post
    assert client(club['ana']).get('/api/discord/prefs').json['prefs']['rsvp'] == 'always'
    d = rsvp(club, 'ana', 'S3', 'going')
    assert d['discord']['my_share']['id'] == r.json['id'] and 'prompt' not in d['discord']   # always: shares itself
    assert my_share(club, 'S2')['id'] == r.json['id']


def test_only_your_own_rsvps_can_be_shared(club):
    rsvp(club, 'ana', 'S1', 'going')
    assert share(club, 'bo', kind='rsvp', showtime_id=club['S1']).status_code == 400


@pytest.fixture
def batched(club):
    """Ana shared ALPHA (going) and BRAVO (maybe), then CHARLIE and dropped
    it; the batch window has passed."""
    rsvp(club, 'ana', 'S1', 'going')
    pid = share(club, 'ana', kind='rsvp', showtime_id=club['S1']).json['id']
    rsvp(club, 'ana', 'S2', 'maybe')
    share(club, 'ana', kind='rsvp', showtime_id=club['S2'], remember=True)
    rsvp(club, 'ana', 'S3', 'going')
    rsvp(club, 'ana', 'S3', 'not_going')
    fast_forward()
    return {**club, 'P1': pid}


def test_the_batch_goes_out_as_one_post(batched):
    [item] = due()
    assert item['action'] == 'post' and item['data']['user'] == 'Ana'
    assert [i['title'] for i in item['data']['items']] == ['ALPHA', 'BRAVO'] and item['data']['items'][1]['status'] == 'maybe'


@pytest.fixture
def posted(batched):
    done(batched['P1'], action='posted', message_id='555', jump_url='https://discord.com/channels/1/2/555')
    return batched


def test_the_screening_links_to_the_post(posted):
    assert due() == []
    s = my_share(posted, 'S1')
    assert s['jump_url'].endswith('/555') and s['status'] == 'posted'


def test_a_changed_rsvp_edits_the_post(posted):
    rsvp(posted, 'ana', 'S2', 'going')
    [item] = due()
    assert item['action'] == 'edit' and item['message_id'] == '555' and item['data']['items'][1]['status'] == 'going'


def test_removing_rsvps_edits_then_deletes_the_post(posted):
    c = posted
    rsvp(c, 'ana', 'S1', None)
    item = due()[0]
    assert item['action'] == 'edit' and [i['title'] for i in item['data']['items']] == ['BRAVO']
    done(c['P1'], action='edited')
    client(c['ana']).delete(f"/api/discord/shares/{c['P1']}", query_string={'showtime_id': c['S2']})
    items = due()
    assert items and items[0]['action'] == 'delete' and items[0]['message_id'] == '555'      # unshared the last one
    done(c['P1'], action='deleted')
    assert due() == [] and my_share(c, 'S2') is None


def test_changing_your_mind_before_it_posts_cancels_it(club):
    from app import app, DiscordPost
    client(club['ana']).put('/api/discord/prefs', json={'rsvp': 'always'})
    rsvp(club, 'ana', 'S4', 'going')
    rsvp(club, 'ana', 'S4', 'not_going')
    with app.app_context():
        assert DiscordPost.query.order_by(DiscordPost.id.desc()).first().status == 'cancelled'


# ── "who's in?" invites ──

@pytest.fixture
def invited(club):
    """Bo asked who's in for CHARLIE; it's posted (777)."""
    inv = share(club, 'bo', kind='invite', showtime_id=club['S3'], note='Anyone?').json['id']
    done(inv, action='posted', message_id='777', jump_url='u')
    return {**club, 'INV': inv}


def invite(c):
    return next(i for i in due() if i['id'] == c['INV'])


def test_an_invite_is_created_once(club):
    r = share(club, 'bo', kind='invite', showtime_id=club['S3'], note='Anyone?')
    assert r.status_code == 201 and r.json['note'] == 'Anyone?'
    assert share(club, 'cy', kind='invite', showtime_id=club['S3']).json['id'] == r.json['id']
    inv = next(i for i in due() if i['id'] == r.json['id'])
    assert inv['action'] == 'post' and inv['data']['by'] == 'Bo' and inv['data']['card']['going'] == []


def test_the_invite_card_follows_rsvps(invited):
    rsvp(invited, 'cy', 'S3', 'going')
    inv = invite(invited)
    assert inv['action'] == 'edit' and inv['data']['card']['going'] == [{'name': 'Cy'}]      # names only


def test_only_its_author_or_an_admin_takes_an_invite_down(invited):
    c = invited
    assert client(c['cy']).delete(f"/api/discord/shares/{c['INV']}").status_code == 403
    assert client(c['ana']).delete(f"/api/discord/shares/{c['INV']}").status_code == 200
    assert invite(c)['action'] == 'delete'


def test_scheduled_invites(club):
    r = share(club, 'bo', kind='invite', showtime_id=club['S4'], post_at=at(days=1))
    assert r.status_code == 201 and all(i['id'] != r.json['id'] for i in due())
    assert client(club['bo']).post(f"/api/discord/shares/{r.json['id']}/now").json['status'] == 'pending'
    assert any(i['id'] == r.json['id'] for i in due())
    assert share(club, 'bo', kind='invite', showtime_id=club['S1'], post_at=at(days=90)).status_code == 400   # past 60 days
    r = client(club['bo']).post('/api/discord/shares', json={'kind': 'invite', 'group_id': club['other'], 'showtime_id': club['S1']})
    assert r.status_code == 400                                                               # other clubs


# ── polls ──

def make_poll(c, **kw):
    return client(c['ana']).post('/api/groups/1/polls', json={
        'title': kw.pop('title'), 'categories': [{'title': 'C', 'options': [{'text': 'x'}, {'text': 'y'}]}], **kw}).json


def pending_for(pid, kind):
    return [i for i in due() if i['kind'] == kind and i['data'] and i['data'].get('poll_id') == pid]


def by_message(mid):
    return [i for i in due() if i['message_id'] == mid]


def test_announcing_a_poll_now_later_or_never(club):
    from app import app, DiscordPost
    now_poll = make_poll(club, title='Now poll', announce='now')
    it = pending_for(now_poll['id'], 'poll')
    assert len(it) == 1 and it[0]['data']['status'] == 'open'
    later = make_poll(club, title='Later poll', announce='later', announce_at=at(hours=3))
    quiet = make_poll(club, title='Quiet poll', announce='none')
    with app.app_context():
        post = DiscordPost.query.filter_by(kind='poll', ref_id=later['id']).first()
        assert post.status == 'pending' and post.post_at > datetime.now() + timedelta(hours=2)
        assert DiscordPost.query.filter_by(kind='poll', ref_id=quiet['id']).count() == 0
    g = client(club['ana']).get(f"/api/polls/{later['id']}").json
    assert g['discord']['announce']['status'] == 'pending' and g['discord']['results'] is None


@pytest.fixture
def announced(club):
    """Ana's "Now poll" is announced (message 900)."""
    p = make_poll(club, title='Now poll', announce='now')
    done(pending_for(p['id'], 'poll')[0]['id'], action='posted', message_id='900', jump_url='j')
    return {**club, 'poll': p}


def test_closing_the_poll_edits_its_announcement(announced):
    client(announced['ana']).put(f"/api/polls/{announced['poll']['id']}", json={'status': 'closed'})
    it = by_message('900')
    assert it and it[0]['action'] == 'edit' and it[0]['data']['status'] == 'closed'


def test_members_cannot_share_polls(club):
    quiet = make_poll(club, title='Quiet poll', announce='none')
    assert share(club, 'bo', kind='poll', poll_id=quiet['id']).status_code == 403


def test_results_post_follows_scoring(announced):
    c, p = announced, announced['poll']
    ana = client(c['ana'])
    ana.put(f"/api/polls/{p['id']}", json={'status': 'closed'})
    done(by_message('900')[0]['id'], action='edited')
    assert share(c, 'ana', kind='poll_results', poll_id=p['id']).status_code == 400          # needs scoring first
    cat = p['categories'][0]
    ana.post(f"/api/polls/{p['id']}/score", json={'winners': {str(cat['id']): cat['options'][0]['id']}})
    assert pending_for(p['id'], 'poll_results') == []                                         # ask: scoring alone posts nothing
    r = share(c, 'ana', kind='poll_results', poll_id=p['id'])
    it = pending_for(p['id'], 'poll_results')
    assert r.status_code == 201 and it and it[0]['action'] == 'post' and 'top' in it[0]['data']
    done(it[0]['id'], action='posted', message_id='901', jump_url='j')
    ana.put(f"/api/polls/{p['id']}", json={'status': 'closed'})                               # undo scoring
    it = by_message('901')
    assert it and it[0]['action'] == 'delete'
    done(it[0]['id'], action='deleted')
    it = by_message('900')
    assert it and it[0]['action'] == 'edit'                                                   # the announcement refreshed


def test_deleting_the_poll_deletes_its_announcement(announced):
    client(announced['ana']).delete(f"/api/polls/{announced['poll']['id']}")
    it = by_message('900')
    assert it and it[0]['action'] == 'delete'


def test_always_announces_when_the_form_doesnt_say(club):
    client(club['ana']).put('/api/discord/prefs', json={'poll': 'always'})
    p = make_poll(club, title='Always poll')
    assert len(pending_for(p['id'], 'poll')) == 1


def test_deleting_a_poll_cancels_its_scheduled_announcement(club):
    from app import app, DiscordPost
    later = make_poll(club, title='Later poll', announce='later', announce_at=at(hours=3))
    client(club['ana']).delete(f"/api/polls/{later['id']}")
    with app.app_context():
        assert DiscordPost.query.filter_by(kind='poll', ref_id=later['id']).first().status == 'cancelled'


# ── comments and threads ──

def outbox():
    return [p['body'] for p in client().get('/api/internal/discussion/outbox', query_string={'group_id': 1}, headers=H).json['posts']]


@pytest.fixture
def commented(club):
    """Ana commented on BRAVO: one for Discord, one site-only."""
    for body, to_discord in (('public', True), ('site only', False)):
        client(club['ana']).post('/api/messages', json={'showtime_id': club['S2'], 'group_id': 1, 'body': body, 'to_discord': to_discord})
    return club


def test_comments_wait_for_a_thread(commented):
    assert outbox() == []                                                                     # never start one
    info = client().get('/api/internal/discussion/thread', query_string={'showtime_id': commented['S2'], 'group_id': 1}, headers=H).json
    assert 'site only' not in [b['body'] for b in info['backfill']]


def test_starting_a_thread(commented):
    c = commented
    r = share(c, 'bo', kind='thread', showtime_id=c['S2'])
    st = client(c['bo']).get(f"/api/showtimes/{c['S2']}", query_string={'group_id': 1}).json
    assert r.status_code == 201 and st['discord']['thread_pending']
    it = [i for i in due() if i['kind'] == 'thread']
    assert it and it[0]['data'] == {'showtime_id': c['S2']}


@pytest.fixture
def threaded(commented):
    """Bo asked for a thread on BRAVO and the bot made it (3333)."""
    from app import app, db, ShowtimeThread
    c = commented
    share(c, 'bo', kind='thread', showtime_id=c['S2'])
    with app.app_context():
        db.session.add(ShowtimeThread(showtime_id=c['S2'], group_id=1, guild_id='1', channel_id='2', thread_id='3333'))
        db.session.commit()
    pid = next(i for i in due() if i['kind'] == 'thread')['id']
    done(pid, action='posted', message_id='3333', jump_url='https://discord.com/channels/1/3333')
    return c


def test_once_threaded_only_the_public_comment_goes_out(threaded):
    assert outbox() == ['public']


def test_asking_again_returns_the_thread(threaded):
    r = share(threaded, 'bo', kind='thread', showtime_id=threaded['S2'])
    assert r.status_code == 200 and 'thread_url' in r.json


def test_without_a_choice_the_preference_decides(threaded):
    c = threaded
    client(c['cy']).put('/api/discord/prefs', json={'comment': 'never'})
    client(c['cy']).post('/api/messages', json={'showtime_id': c['S2'], 'group_id': 1, 'body': 'old client, never'})
    assert 'old client, never' not in outbox()

"""R6a poll drafts: an AI draft grounded in what's playing, cleaned and
linked to films; limits and roles; creating from it on the site or in
Discord."""
import json
import time
from datetime import datetime, timedelta

import pytest

from helpers import H, all_linked_present, setup_db

SPOOKY = {'title': 'Spookiest of the season', 'description': 'Vote your scariest.', 'poll_type': 'standard',
          'scoring_mode': 'ranked', 'notes': '',
          'categories': [{'title': 'Scariest film playing', 'options': ['The Thing (1982)', 'Hausu', 'Suspiria', 'Suspiria', 'Nosferatu']},
                         {'title': 'Empty category', 'options': ['only one']}]}


@pytest.fixture
def club():
    """Spooky Club at Suns (the Discord server's club): an organizer (6101)
    and a member (6102). Playing: THE THING, HAUSU, PADDINGTON 2, SUSPIRIA.
    The AI answers with whatever `club['next']` is."""
    import app as A
    import ai
    from app import app, db, User, Group, GroupMembership, Showtime, Movie, Theatre
    from fake_groq import Fake
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='suns').first()
        g = Group(name='Spooky Club', slug='spooky-r6', is_public=False, theatres='suns')
        db.session.add(g)
        db.session.flush()
        org = User(email='org@r6.test', name='Org', is_active=True, discord_user_id='6101')
        mem = User(email='mem@r6.test', name='Mem', is_active=True, discord_user_id='6102')
        db.session.add_all([org, mem])
        db.session.flush()
        db.session.add(GroupMembership(user_id=org.id, group_id=g.id, status='active', role='organizer'))
        db.session.add(GroupMembership(user_id=mem.id, group_id=g.id, status='active', role='member'))
        now = datetime.now()
        for i, (t, y, gen) in enumerate([('THE THING', 1982, 'Horror, Science Fiction'), ('HAUSU', 1977, 'Horror, Comedy'),
                                         ('PADDINGTON 2', 2017, 'Family, Comedy'), ('SUSPIRIA', 1977, 'Horror')]):
            m = Movie(title=t, release_year=str(y), genres=gen, poster_url=f'https://img.test/{i}.jpg')
            db.session.add(m)
            db.session.flush()
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=3 + i)))
        db.session.commit()
        state = {'group': g.id, 'org': org.id, 'mem': mem.id, 'next': None}
    A.HOME_GROUP_ID = state['group']
    ai._client = Fake(['qwen/qwen3-32b', 'llama-3.3-70b-versatile'])

    def reply(model, messages, kw):
        state['messages'], state['kw'] = messages, kw
        return 'ok' if messages[-1]['content'].endswith('what should i see this weekend?') else json.dumps(state['next'] or {})
    ai._client.reply = reply
    state['fake'] = ai._client
    all_linked_present()
    return state


def as_(club, who):
    from app import app
    c = app.test_client()
    with c.session_transaction() as s:
        s['user_id'] = club[who]
        s['seen'] = int(time.time())
    return c


def draft(club, prompt='spookiest Halloween movies', who='org'):
    return as_(club, who).post(f"/api/groups/{club['group']}/polls/draft", json={'prompt': prompt})


def test_a_draft_is_grounded_cleaned_and_linked(club):
    from app import app, Poll, PollDraft
    club['next'] = SPOOKY
    r = draft(club)
    d = r.json
    assert r.status_code == 201 and d['title'] == 'Spookiest of the season' and d['id']
    with app.app_context():
        assert Poll.query.filter_by(group_id=club['group']).count() == 0 and PollDraft.query.count() == 1   # a draft only
    asked = club['messages'][-1]['content']
    assert 'PLAYING' in asked and asked.index('HAUSU') < asked.index('PADDINGTON 2')                     # fitting films first
    assert asked.index('THE THING') < asked.index('PADDINGTON 2')
    assert club['kw'].get('response_format') == {'type': 'json_object'}
    [cat] = d['categories']                                                                              # too-short one dropped
    options = cat['options']
    assert [o['text'] for o in options] == ['The Thing (1982)', 'Hausu', 'Suspiria', 'Nosferatu']         # duplicates dropped
    assert options[0]['extra']['year'] == 1982 and options[0]['extra']['poster_url'] and 'extra' not in options[3]
    assert d['poll_type'] == 'standard' and d['scoring_mode'] == 'ranked'


def test_prediction_polls_get_scoring_and_notes(club):
    club['next'] = {'title': '99th Oscars', 'poll_type': 'prediction', 'scoring_mode': 'none', 'notes': 'Nominations are predicted.',
                    'categories': [{'title': 'Best Picture', 'options': ['A', 'B', 'C']}]}
    d = draft(club, 'the 99th Oscar winners poll').json
    assert d['scoring_mode'] == 'single' and d['notes'] == 'Nominations are predicted.'


def test_when_the_ai_cant_help(club):
    fake = club['fake']
    fake.reply = lambda m, msgs, kw: 'ok' if msgs[-1]['content'].endswith('weekend?') else 'Sure! Here is your poll: not json'
    r = draft(club, 'anything')
    assert r.status_code == 502 and 'build the poll by hand' in r.json['error']
    fake.limited = {'qwen/qwen3-32b', 'llama-3.3-70b-versatile'}
    r = draft(club, 'anything')
    assert r.status_code == 429 and 'back in ~11 min' in r.json['error']


def test_who_can_draft_and_how_often(club):
    from app import app, db, PollDraft
    assert draft(club, 'x poll', who='mem').status_code == 403
    assert draft(club, ' ').status_code == 400
    with app.app_context():
        for _ in range(12):
            db.session.add(PollDraft(group_id=club['group'], user_id=club['org'], prompt='x', data_json='{}'))
        db.session.commit()
    assert draft(club, 'one more').status_code == 429


def test_the_editor_reopens_a_draft_and_creates_the_poll(club):
    from app import app, db, PollDraft
    club['next'] = SPOOKY
    d = draft(club).json
    assert as_(club, 'org').get(f"/api/poll-drafts/{d['id']}").json['title'] == 'Spookiest of the season'
    assert as_(club, 'mem').get(f"/api/poll-drafts/{d['id']}").status_code == 403
    r = as_(club, 'org').post(f"/api/groups/{club['group']}/polls", json={**d, 'draft_id': d['id'], 'announce': 'none'})
    assert r.status_code == 201 and len(r.json['categories'][0]['options']) == 4
    with app.app_context():
        assert db.session.get(PollDraft, d['id']).poll_id == r.json['id']              # marked used


def test_drafting_and_creating_from_discord(club):
    from app import app, DiscordPost
    bot = app.test_client()
    who = lambda did: {'discord_user_id': did, 'create': '0', 'group_id': club['group']}
    club['next'] = {'title': 'Comfort watches', 'poll_type': 'standard', 'scoring_mode': 'none',
                    'categories': [{'title': 'Pick one', 'options': ['PADDINGTON 2', 'HAUSU']}]}
    r = bot.post('/api/internal/polls/draft', json={**who('6101'), 'prompt': 'comfort movies'}, headers=H)
    assert r.status_code == 201 and r.json['title'] == 'Comfort watches'
    assert bot.post('/api/internal/polls/draft', json={**who('6102'), 'prompt': 'comfort movies'}, headers=H).status_code == 403
    did = r.json['id']
    r = bot.post(f'/api/internal/poll-drafts/{did}/create', json=who('6101'), headers=H)
    assert r.status_code == 201
    with app.app_context():
        assert DiscordPost.query.filter_by(kind='poll', ref_id=r.json['id']).first().status == 'pending'   # announcement queued
    assert bot.post(f'/api/internal/poll-drafts/{did}/create', json=who('6101'), headers=H).status_code == 409   # once

"""✨ Ask on the Help page (7f): answers come from the Help guide only — the
likeliest topics by keywords, then the AI; links to anything that isn't a
real place or topic become plain words; answers are cached; no AI means
the closest topics. Signed-in accounts only, a few an hour. And page tours
are remembered once taken or turned down."""
import json

import pytest

from helpers import client, setup_db


@pytest.fixture(autouse=True)
def fresh():
    import help_ai
    from routes import help as help_routes
    help_ai._cache.clear()
    help_routes._asks.clear()
    setup_db()


def user(name, guest=False):
    from app import app, db, User
    with app.app_context():
        u = User(name=name, email=None if guest else f'{name.lower()}@help.test', is_active=True, is_guest=guest)
        db.session.add(u)
        db.session.commit()
        return u.id


def test_the_guide_is_the_sites_file():
    import help_ai
    g = help_ai.guide()
    assert len(g['topics']) > 40 and 'club-settings-games' in g['places']
    assert help_ai.retrieve('how do I give kernels to a friend')[0] == 'give-kernels'
    assert help_ai.retrieve('stop the emails')[0] == 'email-messages'


def test_only_real_places_stay_links():
    import help_ai
    assert help_ai.clean_links('[Games](club-settings-games), [x](https://evil.test), [y](nowhere), [z](help:bingo)') \
        == '[Games](club-settings-games), [x](https://evil.test), y, [z](help:bingo)'
    assert help_ai.clean_links('[a](help:not-a-topic)') == 'a'


def test_an_answer_from_the_guide_cached(monkeypatch):
    import ai
    import help_ai
    asked = []

    def chat(messages, **k):
        asked.append(messages)
        return json.dumps({'topics': ['give-kernels', 'made-up'], 'answer': 'Tap 🍿 Kernels in [the feed](feed). [Mars](mars).'})
    monkeypatch.setattr(ai, 'chat', chat)
    r = help_ai.ask('how do I thank someone with kernels')
    assert r == {'ai': True, 'topics': ['give-kernels'], 'answer': 'Tap 🍿 Kernels in [the feed](feed). Mars.', 'cached': False}
    system = asked[0][0]['content']
    assert 'Can I give kernels to people?' in system and 'club-settings-games: Club settings → Games' in system
    assert help_ai.ask('How do I THANK someone with kernels?')['cached'] and len(asked) == 1     # the same question


def test_no_ai_the_closest_topics(monkeypatch):
    import ai
    import help_ai
    monkeypatch.setattr(ai, 'chat', lambda *a, **k: (_ for _ in ()).throw(ai.Unavailable()))
    r = help_ai.ask('save a search for horror films')
    assert r['ai'] is False and r['answer'] is None and r['topics'][0] == 'save-search'
    monkeypatch.setattr(ai, 'chat', lambda *a, **k: 'not json at all')
    assert help_ai.ask('earn more kernels')['ai'] is False


def test_who_can_ask_and_how_often(monkeypatch):
    import ai
    from routes import help as help_routes
    monkeypatch.setattr(ai, 'chat', lambda *a, **k: json.dumps({'topics': ['rsvp'], 'answer': ''}))
    assert client().post('/api/help/ask', json={'q': 'how do I rsvp'}).status_code == 401
    assert client(user('Gus', guest=True)).post('/api/help/ask', json={'q': 'how do I rsvp'}).status_code == 403
    ann = client(user('Ann'))
    assert ann.post('/api/help/ask', json={'q': 'rsvp'}).status_code == 400                  # a word isn't a question
    r = ann.post('/api/help/ask', json={'q': 'how do I rsvp to a show'}).json
    assert r['ai'] and r['topics'] == ['rsvp'] and r['answer'] is None
    monkeypatch.setattr(help_routes, 'ASKS_PER_HOUR', 1)
    assert ann.post('/api/help/ask', json={'q': 'how do I rsvp to a show'}).json['cached']   # cached: free
    r = ann.post('/api/help/ask', json={'q': 'where is my watch history'}).json
    assert r['ai'] is False and 'a lot of questions' in r['note'] and r['topics']


def test_page_tours_are_remembered():
    c = client(user('Pia'))
    assert c.get('/api/auth/me').json['user']['tours_seen'] == []
    assert c.post('/api/me/tour', json={'page': 'play'}).json == {'tours_seen': ['play']}
    assert c.post('/api/me/tour', json={'page': 'play'}).json == {'tours_seen': ['play']}      # once
    assert c.post('/api/me/tour', json={'page': 'Bad Page!'}).status_code == 400
    assert c.post('/api/me/tour').json == {'tour_seen': True}                                # the welcome tour, as before
    assert c.get('/api/auth/me').json['user']['tours_seen'] == ['play']

"""Guess the still and Guess from the reviews (R15): the less you needed to
see, the more it pays (3 / 2 / 1); a still never reaches the browser whole
before the round's over; review clues never name the film or its people,
come from members' diaries unnamed (unless they opt out) and from TMDB."""
import io
import json

import pytest

from helpers import client, setup_db

REVIEWS = [
    "A gorgeous, haunting fever dream. The score alone will follow you home. Stewart has never been better.",
    "Obsession has rarely looked this beautiful on screen. Every frame is a painting you want to step into.",
    "I walked out dizzy and in love with San Francisco all over again, which is surely the point.",
    "Scottie follows Madeleine everywhere and then Judy appears and it all spirals from there in the tower.",
]


@pytest.fixture
def club():
    """Clue Club: Bo plays; Cy (Letterboxd, allows clues) and Di (opted out)
    reviewed VERTIGO in their diaries; look-alikes to choose from."""
    from app import app, db, Group, GroupMembership, LetterboxdEntry, Movie, User
    setup_db()
    with app.app_context():
        g = Group(name='Clue Club', slug='clue-club', is_public=False, trivia_source='local',
                  quizzes_json=json.dumps({'still': True, 'reviews': True}))
        us = {n: User(name=n, email=f'{n.lower()}@clue.test', is_active=True) for n in ('Bo', 'Cy', 'Di')}
        us['Di'].letterboxd_clues = False
        db.session.add_all([g, *us.values()])
        db.session.flush()
        for u in us.values():
            db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active', role='member'))
        cast = [{'name': 'James Stewart', 'character': 'Scottie Ferguson'}, {'name': 'Kim Novak', 'character': 'Madeleine'},
                {'name': 'Barbara Bel Geddes', 'character': 'Midge'}]
        db.session.add(Movie(title='VERTIGO', release_year='1958', tmdb_id=426, director='Alfred Hitchcock', genres='mystery,thriller',
                             cast_json=json.dumps(cast)))
        for i, (t, y) in enumerate((('REAR WINDOW', 1954), ('NORTH BY NORTHWEST', 1959), ('PSYCHO', 1960), ('THE BIRDS', 1963))):
            db.session.add(Movie(title=t, release_year=str(y), tmdb_id=980000 + i, genres='mystery,thriller'))
        db.session.flush()
        for i, (n, text) in enumerate((('Cy', REVIEWS[0]), ('Cy', REVIEWS[1]), ('Di', REVIEWS[2]))):
            db.session.add(LetterboxdEntry(user_id=us[n].id, guid=f'g{i}', watched_on=__import__('datetime').date.today(),
                                           title='Vertigo', year=1958, tmdb_id=426, review=text))
        db.session.commit()
        return {'G': g.id, **{n: u.id for n, u in us.items()}}


def play(c, kind):
    return client(c['Bo']).post('/api/quizzes/start', json={'group_id': c['G'], 'kind': kind})


def answer(c, rid, choice):
    return client(c['Bo']).post('/api/quizzes/answer', json={'group_id': c['G'], 'round_id': rid, 'choice': choice})


def test_a_diary_review_in_plain_words():
    import letterboxd
    html = ('<p><img src="https://a.ltrbxd.com/poster.jpg"/></p> <p>Gorgeous &amp; haunting.</p> <p>Stewart is great.</p>'
            '<p>Watched on Sunday October 5, 2025.</p>')
    assert letterboxd.review_text(html) == 'Gorgeous & haunting.\nStewart is great.'
    assert letterboxd.review_text('<p>This review may contain spoilers.</p><p>The twist!</p>') is None
    assert letterboxd.review_text('<p><img src="x"/></p><p>Watched on Monday.</p>') is None


def test_clues_never_name_the_film_or_its_people(club):
    import film_pool
    import quizzes
    from app import app, Movie
    with app.app_context():
        f = film_pool.from_movie(Movie.query.filter_by(tmdb_id=426).first())
        banned = quizzes._banned_words(f)
        assert {'vertigo', 'stewart', 'scottie', 'madeleine', 'hitchcock', '1958'} <= banned
        assert quizzes.clue(REVIEWS[0], banned) == 'The score alone will follow you home.'   # not the "Stewart" one
        assert quizzes.clue(REVIEWS[3], banned) is None                                   # all plot and names: skipped


def test_reviews_pay_by_how_many_it_took(club, monkeypatch):
    import quizzes
    monkeypatch.setattr(quizzes, '_tmdb_reviews', lambda tid: ['Hitchcock at the peak of his powers, I think, and the best of them.',
                                                               'Dreamy, sad and perfectly made from the first shot to the last one.'])
    r = play(club, 'reviews').json
    assert r['step'] == 1 and len(r['clues']) == 1 and r['worth'] == 3 and 'answer' not in r and 'film' not in r
    r = answer(club, r['id'], 'more').json
    assert r['step'] == 2 and len(r['clues']) == 2 and r['worth'] == 2
    from app import app, db, QuizRound
    with app.app_context():
        state = json.loads(db.session.get(QuizRound, r['id']).state_json)
        right = state['answer']
        clues = state['clues']
    assert all(c['text'] != REVIEWS[2].split('.')[0] for c in clues)                     # Di opted out
    assert {c['from'] for c in clues} <= {'club', 'tmdb'} and not any('Cy' in c['text'] for c in clues)
    r = answer(club, r['id'], right).json
    assert r['done'] and r['last'] == {'right': True, 'paid': 2} and r['options'][r['answer']] == 'Vertigo (1958)'


def make_jpeg():
    from PIL import Image
    img = Image.new('RGB', (1280, 720), (200, 40, 40))
    out = io.BytesIO()
    img.save(out, 'JPEG')
    return out.getvalue()


def test_a_still_close_up_then_wider(club, monkeypatch):
    import enrich
    import quizzes
    monkeypatch.setattr(quizzes, '_backdrops', lambda tid: ['/still.jpg'])

    class R:
        content = make_jpeg()

        def raise_for_status(self):
            pass
    monkeypatch.setattr(enrich._http, 'get', lambda url, **k: R())
    r = play(club, 'still').json
    assert r['step'] == 1 and r['worth'] == 3 and r['image'].endswith('-1.jpg') and 'film' not in r
    img = client().get(r['image'])
    assert img.status_code == 200 and img.mimetype == 'image/jpeg'
    from PIL import Image
    assert Image.open(io.BytesIO(img.data)).size[0] == 768
    assert client().get(r['image'].replace('-1.jpg', '-3.jpg')).status_code == 404       # no peeking ahead
    assert client().get(r['image'].rsplit('/', 1)[0] + '/wrong-1.jpg').status_code == 404                # the token's the key
    r = answer(club, r['id'], 'more').json
    r = answer(club, r['id'], 'more').json
    assert r['step'] == 3 and r['worth'] == 1
    assert "everything" in answer(club, r['id'], 'more').json['error']
    wrong = (r['options'].index('Vertigo (1958)') + 1) % 4 if 'Vertigo (1958)' in r['options'] else 0
    r = answer(club, r['id'], wrong).json
    assert r['done'] and r['last']['right'] is False and r['film']['title'] and r['image'].endswith('-3.jpg')

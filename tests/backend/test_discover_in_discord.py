"""The Discover engine in Discord (R3b): /find's options and results, /surprise,
and the chatbot's picks — the backend side (the bot's commands: tests/bot)."""
from datetime import datetime, timedelta

import pytest

from helpers import H, client, setup_db
import discover as D


@pytest.fixture
def club():
    """A club at AFI + Alamo Crystal City with a rare 35mm one-off, a horror
    double, and a new release in Virginia."""
    from app import app, db, Group, Movie, Showtime, Theatre
    setup_db()
    with app.app_context():
        th = {t.slug: t for t in Theatre.query.filter(Theatre.slug.in_(['afi', 'alamo-crystal']))}
        g = Group(name='Find Club', slug='find-club', is_public=False, theatres='afi,alamo-crystal')
        db.session.add(g)
        base = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        def film(title, year, genres, slug, hours, fmt=None):
            m = Movie(title=title, release_year=str(year), genres=genres, runtime_minutes=100, tmdb_id=hash(title) % 10**6)
            db.session.add(m)
            db.session.flush()
            for h in hours:
                db.session.add(Showtime(movie_id=m.id, theatre_id=th[slug].id, start_time=base + timedelta(hours=h), format_label=fmt))
            return m.id
        ids = {'conv': film('THE CONVERSATION', 1974, 'drama,thriller', 'afi', [19], fmt='35mm'),
               'psycho': film('PSYCHO', 1960, 'horror,thriller', 'afi', [20, 44]),
               'new': film('NEW RELEASE', datetime.now().year, 'comedy', 'alamo-crystal', [13, 37, 61, 85])}
        db.session.commit()
        return {'group': g.id, **ids}


def get(path, **params):
    return client().get(path, query_string=params, headers=H)


def test_find_options_offer_shelves_moods_and_playing_genres(club):
    r = get('/api/internal/discover/options', group_id=club['group']).json
    values = [t['value'] for t in r['types']]
    assert 'shelf:rare' in values and 'mood:scare-me' in values
    genres = {t['value']: t['hint'] for t in r['types'] if t['value'].startswith('genre:')}
    assert genres['genre:horror'].startswith('Genre · 1 film') and 'genre:western' not in genres
    assert {x['value'] for x in r['regions']} == {'region:dc', 'region:maryland', 'region:virginia'}


def test_find_by_kind_links_to_the_same_browse_view(club):
    r = get('/api/internal/discover/find', group_id=club['group'], type='shelf:rare', when='2weeks').json
    assert 'THE CONVERSATION' in [f['movie']['title'] for f in r['films']]
    assert r['label'].startswith('Rare gems') and r['browse_path'].startswith('/browse?') and 'shelf=rare' in r['browse_path']


def test_find_where_and_free_text(club):
    va = get('/api/internal/discover/find', group_id=club['group'], type='genre:comedy', where='region:virginia', when='2weeks').json
    assert [f['movie']['title'] for f in va['films']] == ['NEW RELEASE'] and 'Virginia' in va['label']
    scary = get('/api/internal/discover/find', group_id=club['group'], type='something scary', when='2weeks').json
    assert scary['params'].get('mood') == 'scare-me' and 'PSYCHO' in [f['movie']['title'] for f in scary['films']]
    named = get('/api/internal/discover/find', group_id=club['group'], q='conversation', when='2weeks').json
    assert [f['movie']['title'] for f in named['films']] == ['THE CONVERSATION']


def test_find_limits_and_errors(club):
    r = get('/api/internal/discover/find', group_id=club['group'], when='2weeks', limit=500).json
    assert len(r['films']) <= 25
    assert get('/api/internal/discover/find', group_id=999999).status_code == 404
    assert client().get('/api/internal/discover/find', query_string={'group_id': club['group']}).status_code == 403


def test_surprise_picks_one_and_skips_ones_already_seen(club):
    first = get('/api/internal/discover/surprise', group_id=club['group'], when='week').json
    assert first['movie']['title'] in {'THE CONVERSATION', 'PSYCHO', 'NEW RELEASE'} and first['when'] in ('week',)
    seen = ','.join(str(club[k]) for k in ('conv', 'psycho'))
    again = get('/api/internal/discover/surprise', group_id=club['group'], when='week', exclude=seen).json
    assert again['movie']['title'] == 'NEW RELEASE'
    all_seen = ','.join(str(club[k]) for k in ('conv', 'psycho', 'new'))
    assert get('/api/internal/discover/surprise', group_id=club['group'], when='week', exclude=all_seen).status_code == 404


def test_chatbot_picks_name_what_was_asked_about(club):
    ctx = get('/api/internal/chat-context', group_id=club['group'], discord_user_id='555', prompt='is psycho still playing?').json
    assert ctx['picks']['films'][0]['title'] == 'PSYCHO'
    scary = get('/api/internal/chat-context', group_id=club['group'], discord_user_id='555',
                prompt='anything scary this week?').json['picks']
    assert scary['link'] is True and 'mood=scare-me' in scary['browse_path']
    chatty = get('/api/internal/chat-context', group_id=club['group'], discord_user_id='555', prompt='lol nice').json['picks']
    assert chatty['link'] is False and chatty['films']                     # a vague message still gets a mix


@pytest.mark.parametrize('text, expected', [
    ('anything weird and rare in Virginia this weekend?', {'shelf': 'rare', 'when': 'weekend', 'regions': 'virginia'}),
    ('something on 35mm at AFI', {'shelf': 'on-film', 'theatres': 'afi'}),
    ('a funny 80s movie tomorrow', {'mood': 'laugh', 'decade': '1980', 'when': 'tomorrow'}),
    ('what is on my watchlist', {'club': 'mine'}),
])
def test_reading_a_request(text, expected):
    got = D.parse_request(text, D.COMMON_GENRES)
    assert {k: got.get(k) for k in expected} == expected

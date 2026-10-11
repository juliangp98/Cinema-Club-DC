"""R6c: search suggestions and ✨ AI search."""
from helpers import H, client, Checks, WORK


def test_search():
    checks = Checks()
    check = checks.check
    import sys, json
    from datetime import datetime, timedelta
    from app import app, db, migrate, User, Group, GroupMembership, Showtime, Movie, Theatre
    import app as A, ai, discover
    from fake_groq import Fake

    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='afi').first()
        g = Group(name='Search Club', slug='search-r6c', is_public=False, theatres='afi'); db.session.add(g); db.session.flush()
        u = User(email='u@r6c.test', name='U', is_active=True)
        guest = User(name='Guest', is_active=True, is_guest=True)
        db.session.add_all([u, guest]); db.session.flush()
        db.session.add(GroupMembership(user_id=u.id, group_id=g.id, status='active'))
        now = datetime.now()
        cast = json.dumps([{'name': 'Kurt Russell'}, {'name': 'Wilford Brimley'}])
        for i, (t, y, gen, d) in enumerate([('THE THING', 1982, 'Horror, Science Fiction', 'John Carpenter'),
                                            ('IN THE MOUTH OF MADNESS', 1994, 'Horror', 'John Carpenter'),
                                            ('PADDINGTON 2', 2017, 'Family, Comedy', 'Paul King')]):
            m = Movie(title=t, release_year=str(y), genres=gen, director=d, cast_json=cast if i == 0 else None, tmdb_id=9000 + i)
            db.session.add(m); db.session.flush()
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=2 + i)))
        db.session.add(Movie(title='THE THIN MAN', release_year='1934', tmdb_id=9100))     # in the database, not playing
        db.session.commit()
        G, U, GU = g.id, u.id, guest.id

    def client(uid=None):
        c = app.test_client()
        if uid:
            with c.session_transaction() as s: s['user_id'] = uid
        return c
    c, anon, gc = client(U), client(), client(GU)
    sug = lambda q, who=c, **k: who.get('/api/search/suggest', query_string={'q': q, **k}).json

    print('--- suggestions ---')
    r = sug('thin', group_id=G)
    check('films: playing first, then the rest of the database', [f['title'] for f in r['films']] == ['THE THING', 'THE THIN MAN']
          and r['films'][0]['playing'] and not r['films'][1]['playing'] and r['films'][0]['theatre'], r['films'])
    r = sug('carp', group_id=G)
    check('people: a director, with how many films are playing', r['people'] and r['people'][0] == {'name': 'John Carpenter', 'role': 'director', 'count': 2, 'params': {'q': 'John Carpenter'}}, r['people'])
    r = sug('kurt', group_id=G)
    check('actors too', r['people'] and r['people'][0]['name'] == 'Kurt Russell' and r['people'][0]['role'] == 'actor')
    labels = lambda r: [f['label'] for f in r['filters']]
    check('"spooky" offers the Scare me mood', 'Scare me' in labels(sug('spooky', group_id=G)))
    check('genres playing, with counts', any(f['params'] == {'genres': 'horror'} and '2 films' in f['hint'] for f in sug('horr', group_id=G)['filters']))
    check('"70mm" offers On film and Big screen', {'On film (35/16/70mm)', 'Big screen (IMAX, 70mm, Dolby)'} <= set(labels(sug('70mm', group_id=G))))
    check('shelves by name', 'Rare gems' in labels(sug('rare', group_id=G)))
    check('theatres: the club\'s own', any(f['params'] == {'theatres': 'afi'} for f in sug('afi', group_id=G)['filters'])
          and not any(f['params'].get('theatres') == 'suns' for f in sug('suns', group_id=G)['filters']))
    check('when, areas', 'This weekend' in labels(sug('week', group_id=G)) and 'Virginia' in labels(sug('virg', group_id=G)))
    check('a typed decade', sug("80s", group_id=G)['filters'][0]['params'] == {'decade': '1980'}
          and sug('1990s', group_id=G)['filters'][0]['params'] == {'decade': '1990'})
    check('club filters only in a club', 'Friends going' in labels(sug('friends', group_id=G))
          and 'Friends going' not in labels(sug('friends', anon)) and 'Friends are going' not in labels(sug('friends', anon)))
    check('one letter: nothing yet', sug('t', group_id=G)['films'] == [] and sug('t', group_id=G)['filters'] == [])
    check('names match at word starts only ("urt" is not Kurt)', sug('urt', group_id=G)['people'] == [])
    check('the best-matching group leads', sug('carp', group_id=G)['order'][0] == 'people' and sug('horr', group_id=G)['order'][0] == 'filters'
          and sug('thin', group_id=G)['order'][0] == 'films')
    check('visitors get suggestions (all theatres)', sug('thin', anon)['films'][0]['title'] == 'THE THING')
    check("not a member: refused", c.get('/api/search/suggest', query_string={'q': 'thin', 'group_id': 999999}).status_code in (403, 404))

    print('--- ✨ AI search ---')
    fake = Fake(['qwen/qwen3-32b', 'llama-3.3-70b-versatile']); ai._client = fake
    ai._state.update(primary=None, fallback=None, checked_at=0.0)
    ask = lambda q, who=c, **k: who.post('/api/search/ai', json={'q': q, **k})
    n0 = len(fake.calls)
    r = ask('anything rare in virginia this weekend', group_id=G).json
    check('fully understood without the AI: no AI call', r['ai'] is False and len([x for x in fake.calls[n0:] if 'Request' in x[1]]) == 0
          and r['params'] == {'shelf': 'rare', 'regions': 'virginia', 'when': 'weekend'} and r['path'].startswith('/browse?'), r)
    fake.reply = lambda m, msgs, kw: json.dumps({'params': {'mood': 'scare-me', 'runtime': 'short', 'regions': 'dc',
                                                           'theatres': 'afi,made-up', 'genres': 'horror,nonsense', 'decade': '1985',
                                                           'club': 'going', 'sort': 'chaos'}, 'search': ''})
    r = ask('something to make me jump that is not too long near downtown', group_id=G).json
    check('leftover words go to the AI', r['ai'] is True, r)
    check('…and only real values survive (with the free reading kept)', r['params'] == {'shelf': 'short', 'mood': 'scare-me', 'runtime': 'short',
          'regions': 'dc', 'theatres': 'afi', 'genres': 'horror', 'club': 'going', 'when': 'month'}, r['params'])
    check('…explained in plain words', r['explain'] == 'Short & sweet · Scare me · Next 30 days · DC · AFI', r['explain'])
    fake.reply = lambda m, msgs, kw: json.dumps({'params': {}, 'search': 'John Carpenter'})
    r = ask('that guy who made the thing with kurt russell', group_id=G).json
    check('a person or title becomes a search', r['params'].get('q') == 'John Carpenter')
    fake.reply = lambda m, msgs, kw: 'not json at all'
    r = ask('vibes for a rainy sunday with wine', group_id=G).json
    check("an answer that isn't JSON falls back to the plain reading", r['ai'] is False and r['note'] and r['params']['when'] == 'weekend', r)
    fake.limited = {'qwen/qwen3-32b', 'llama-3.3-70b-versatile'}
    r = ask('zombie musicals with puppets', group_id=G).json
    check('AI rate-limited: the words become a search instead', r['ai'] is False and 'busy' in r['note'] and r['params']['q'] == 'zombie musicals puppets', r)
    fake.limited = set()
    check('guests and visitors can\'t use it', ask('something scary', gc).status_code == 403 and ask('something scary', anon).status_code == 401)
    check('too short', ask('ok').status_code == 400)
    check('not a member of that club', ask('something scary', group_id=999999).status_code == 403)
    fake.reply = lambda m, msgs, kw: json.dumps({'params': {'mood': 'laugh'}, 'search': ''})
    codes = [ask(f'something silly number {i} please', group_id=G).status_code for i in range(16)]
    check('AI searches are limited per hour', 429 in codes, codes)
    checks.done()

"""R6a poll drafts: grounding, validation, linking, limits, roles, Discord create."""
from helpers import H, client, Checks, WORK


def test_poll_drafts():
    checks = Checks()
    check = checks.check
    import sys, json, time
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, Showtime, Movie, Theatre, Poll, PollDraft, DiscordPost,
                     INTERNAL_API_TOKEN)
    import app as A, ai, poll_ai
    from fake_groq import Fake
    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    with app.app_context():
        db.create_all(); migrate()
        th = Theatre.query.filter_by(slug='suns').first()
        g = Group(name='Spooky Club', slug='spooky-r6', is_public=False, theatres='suns'); db.session.add(g); db.session.flush()
        org = User(email='org@r6.test', name='Org', is_active=True, discord_user_id='6101')
        mem = User(email='mem@r6.test', name='Mem', is_active=True, discord_user_id='6102')
        db.session.add_all([org, mem]); db.session.flush()
        db.session.add(GroupMembership(user_id=org.id, group_id=g.id, status='active', role='organizer'))
        db.session.add(GroupMembership(user_id=mem.id, group_id=g.id, status='active', role='member'))
        now = datetime.now()
        for i, (t, y, gen) in enumerate([('THE THING', 1982, 'Horror, Science Fiction'), ('HAUSU', 1977, 'Horror, Comedy'),
                                         ('PADDINGTON 2', 2017, 'Family, Comedy'), ('SUSPIRIA', 1977, 'Horror')]):
            m = Movie(title=t, release_year=str(y), genres=gen, poster_url=f'https://img.test/{i}.jpg'); db.session.add(m); db.session.flush()
            db.session.add(Showtime(movie_id=m.id, theatre_id=th.id, start_time=now + timedelta(days=3 + i)))
        db.session.commit()
        G, ORG, MEM = g.id, org.id, mem.id
    A.DISCORD_GROUP_ID = G
    fake = Fake(['qwen/qwen3-32b', 'llama-3.3-70b-versatile']); ai._client = fake
    seen = {}
    def reply(model, messages, kw):
        seen['messages'], seen['kw'] = messages, kw
        if messages[-1]['content'].endswith('what should i see this weekend?'):
            return 'ok'                       # model probe
        return json.dumps(seen.get('next') or {})
    fake.reply = reply
    def client(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid; s['seen'] = int(time.time())
        return c
    org_c, mem_c = client(ORG), client(MEM)

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- drafting ---')
    seen['next'] = {'title': 'Spookiest of the season', 'description': 'Vote your scariest.', 'poll_type': 'standard', 'scoring_mode': 'ranked',
                    'categories': [{'title': 'Scariest film playing', 'options': ['The Thing (1982)', 'Hausu', 'Suspiria', 'Suspiria', 'Nosferatu']},
                                   {'title': 'Empty category', 'options': ['only one']}], 'notes': ''}
    r = org_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': 'spookiest Halloween movies'})
    d = r.get_json()
    user_msg = seen['messages'][-1]['content']
    check('a draft comes back (not a poll yet)', r.status_code == 201 and d['title'] == 'Spookiest of the season'
          and d['id'], d)
    with app.app_context():
        check('…saved as a draft only', Poll.query.filter_by(group_id=G).count() == 0 and PollDraft.query.count() == 1)
    check('grounded in what is playing, fitting films first', 'PLAYING' in user_msg
          and user_msg.index('HAUSU') < user_msg.index('PADDINGTON 2') and user_msg.index('THE THING') < user_msg.index('PADDINGTON 2'), user_msg[:400])
    check('JSON mode requested', seen['kw'].get('response_format') == {'type': 'json_object'})
    cat = d['categories']
    check('cleaned: duplicates dropped, too-short categories dropped', len(cat) == 1 and [o['text'] for o in cat[0]['options']] == ['The Thing (1982)', 'Hausu', 'Suspiria', 'Nosferatu'])
    check('options linked to films playing (poster, year)', cat[0]['options'][0]['extra']['year'] == 1982 and cat[0]['options'][0]['extra']['poster_url']
          and 'extra' not in cat[0]['options'][3], cat[0]['options'])
    check('scoring kept when valid', d['poll_type'] == 'standard' and d['scoring_mode'] == 'ranked')
    seen['next'] = {'title': '99th Oscars', 'poll_type': 'prediction', 'scoring_mode': 'none',
                    'categories': [{'title': 'Best Picture', 'options': ['A', 'B', 'C']}], 'notes': 'Nominations are predicted.'}
    d2 = org_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': 'the 99th Oscar winners poll'}).get_json()
    check('prediction polls get a scoring mode, notes come through', d2['scoring_mode'] == 'single' and d2['notes'] == 'Nominations are predicted.', d2)
    seen['next'] = None
    fake.reply = lambda m, msgs, kw: 'ok' if msgs[-1]['content'].endswith('weekend?') else 'Sure! Here is your poll: not json'
    r = org_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': 'anything'})
    check('unusable AI output → a clear error', r.status_code == 502 and 'build the poll by hand' in r.get_json()['error'])
    fake.reply = reply
    fake.limited = {'qwen/qwen3-32b', 'llama-3.3-70b-versatile'}
    r = org_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': 'anything'})
    check('AI out of budget → says when, offers the manual way', r.status_code == 429 and 'back in ~11 min' in r.get_json()['error'], r.get_json())
    fake.limited = set()

    print('--- who can draft ---')
    check("members can't draft", mem_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': 'x poll'}).status_code == 403)
    check('empty asks refused', org_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': ' '}).status_code == 400)
    with app.app_context():
        for _ in range(12):
            db.session.add(PollDraft(group_id=G, user_id=ORG, prompt='x', data_json='{}'))
        db.session.commit()
    check('drafts per hour are capped', org_c.post(f'/api/groups/{G}/polls/draft', json={'prompt': 'one more'}).status_code == 429)
    check('the editor can reopen a draft', org_c.get(f"/api/poll-drafts/{d['id']}").get_json()['title'] == 'Spookiest of the season')
    check("…but members can't", mem_c.get(f"/api/poll-drafts/{d['id']}").status_code == 403)

    print('--- creating from a draft ---')
    r = org_c.post(f'/api/groups/{G}/polls', json={**d, 'draft_id': d['id'], 'announce': 'none'})
    p = r.get_json()
    check('the site creates the (edited) draft as a poll', r.status_code == 201 and len(p['categories'][0]['options']) == 4)
    with app.app_context():
        check('…and marks the draft used', db.session.get(PollDraft, d['id']).poll_id == p['id'])
    bot = app.test_client()
    who = lambda did: {'discord_user_id': did, 'create': '0', 'group_id': G}
    with app.app_context():
        for row in PollDraft.query.filter_by(prompt='x').all(): db.session.delete(row)
        db.session.commit()
    seen['next'] = {'title': 'Comfort watches', 'poll_type': 'standard', 'scoring_mode': 'none', 'categories': [{'title': 'Pick one', 'options': ['PADDINGTON 2', 'HAUSU']}]}
    r = bot.post('/api/internal/polls/draft', json={**who('6101'), 'prompt': 'comfort movies'}, headers=H)
    check('/poll from Discord drafts for organizers', r.status_code == 201 and r.get_json()['title'] == 'Comfort watches')
    check("…not for members", bot.post('/api/internal/polls/draft', json={**who('6102'), 'prompt': 'comfort movies'}, headers=H).status_code == 403)
    did = r.get_json()['id']
    r = bot.post(f'/api/internal/poll-drafts/{did}/create', json=who('6101'), headers=H)
    with app.app_context():
        ann = DiscordPost.query.filter_by(kind='poll', ref_id=r.get_json()['id']).first()
        check('"Create now" makes the poll and queues its announcement', r.status_code == 201 and ann and ann.status == 'pending')
    check('…once', bot.post(f'/api/internal/poll-drafts/{did}/create', json=who('6101'), headers=H).status_code == 409)
    checks.done()

"""polls_voting"""
from helpers import H, client, Checks, WORK


def test_polls_voting():
    checks = Checks()
    check = checks.check
    import sys, json
    from app import (app, db, migrate, User, Group, GroupMembership, Poll, PollVote, DiscordPost, render_post, INTERNAL_API_TOKEN)
    import app as APP

    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    with app.app_context():
        db.create_all(); migrate()
        g = Group(name='Vote Club', slug='vote-club', is_public=False); db.session.add(g); db.session.flush()
        ana = User(email='ana9@test.dev', name='Ana', is_active=True, discord_user_id='9901')   # announcing needs the server
        bo = User(email=None, name='Bo', is_active=True, discord_user_id='9902')
        cy = User(email='cy9@test.dev', name='Cy', is_active=True, discord_user_id='9904')
        out = User(email=None, name='Out', is_active=True, discord_user_id='9903')
        db.session.add_all([ana, bo, cy, out]); db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=g.id, status='active', role='admin'),
                            GroupMembership(user_id=bo.id, group_id=g.id, status='active'),
                            GroupMembership(user_id=cy.id, group_id=g.id, status='active')])
        db.session.commit()
        G, A, B, C = g.id, ana.id, bo.id, cy.id
    APP.DISCORD_GROUP_ID = G      # this club plays the Discord server's club (R3d)

    def as_user(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, cy_site = as_user(A), as_user(C)
    bot = app.test_client()
    def who(did, **k): return {'discord_user_id': did, 'create': '0', 'group_id': G, **k}
    def ballot(pid, did='9902'): return bot.get(f'/api/internal/polls/{pid}/ballot', query_string=who(did), headers=H)
    def bvote(pid, did='9902', **body): return bot.post(f'/api/internal/polls/{pid}/vote', json={**who(did), **body}, headers=H)
    def posts(kind, pid):
        with app.app_context():
            return [render_post(p) for p in DiscordPost.query.filter_by(kind=kind, ref_id=pid)]

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- creating ---')
    r = a.post(f'/api/groups/{G}/polls', json={'title': 'Fest picks', 'scoring_mode': 'confidence', 'poll_type': 'prediction', 'announce': 'now',
                                              'categories': [{'title': 'Best Picture', 'options': [{'text': 'SIRÂT'}, {'text': 'HAMNET'}, {'text': 'SINNERS'}]},
                                                             {'title': 'Best Director', 'options': [{'text': 'Laxe'}, {'text': 'Zhao'}]}]})
    P = r.get_json()['id']; cats = r.get_json()['categories']
    BP, BD = cats[0]['id'], cats[1]['id']
    SIRAT, HAMNET, SINNERS = [o['id'] for o in cats[0]['options']]
    LAXE, ZHAO = [o['id'] for o in cats[1]['options']]
    opened = posts('poll', P)
    check('announce now: one #movies announcement queued for its club', len(opened) == 1 and opened[0]['group_id'] == G
          and opened[0]['categories'] == 2, opened)

    print('--- Discord ballot ---')
    b = ballot(P).get_json()
    check('ballot: categories, nominees, nothing answered', b['answered'] == 0 and [c['title'] for c in b['categories']] == ['Best Picture', 'Best Director']
          and [o['text'] for o in b['categories'][0]['options']] == ['SIRÂT', 'HAMNET', 'SINNERS'], b)
    check('no vote split before you pick', all('split' not in c for c in b['categories']))
    b = bvote(P, votes=[{'category_id': BP, 'option_id': SIRAT, 'confidence': 7}]).get_json()
    bp = b['categories'][0]
    check('a pick saves and returns the refreshed ballot', b['answered'] == 1 and bp['picks'] == [{'option_id': SIRAT, 'confidence': 7, 'rank': None}], bp)
    check('…with the split now visible for that category only', bp['split'] == {str(SIRAT): 1} and bp['voters'] == 1 and 'split' not in b['categories'][1])
    b = bvote(P, votes=[{'category_id': BP, 'option_id': HAMNET, 'confidence': 99}]).get_json()
    check('changing a pick replaces it; confidence clamps to 10', b['categories'][0]['picks'] == [{'option_id': HAMNET, 'confidence': 10, 'rank': None}])
    b = bvote(P, votes=[{'category_id': BP, 'option_id': LAXE}, {'category_id': 99999, 'option_id': SIRAT}]).get_json()
    check("nominees from another category / unknown categories are ignored", b['categories'][0]['picks'][0]['option_id'] == HAMNET)
    check('not in the group -> not_member', ballot(P, '9903').status_code == 403 and 'not_member' in ballot(P, '9903').get_data(as_text=True))
    check('no account (and not in the server) -> no_account', ballot(P, '9999').status_code == 404 and 'no_account' in ballot(P, '9999').get_data(as_text=True))
    check('unknown poll -> 404', ballot(99999).status_code == 404)

    print('--- site, same rules ---')
    r = cy_site.post(f'/api/polls/{P}/vote', json={'votes': [{'category_id': BP, 'option_id': SIRAT, 'confidence': 'abc'}]})
    check('junk confidence no longer crashes the site route (defaults to 1)', r.status_code == 200 and r.get_json()['count'] == 1, r.status_code)
    cy_site.post(f'/api/polls/{P}/vote', json={'votes': [{'category_id': BD, 'option_id': ZHAO, 'confidence': 3}]})
    site = cy_site.get(f'/api/polls/{P}').get_json()
    check("site: split shown where you've picked", site['categories'][0].get('vote_distribution') == {SIRAT: 1, HAMNET: 1}
          or site['categories'][0].get('vote_distribution') == {str(SIRAT): 1, str(HAMNET): 1}, site['categories'][0].get('vote_distribution'))
    fresh = a.get(f'/api/polls/{P}').get_json()
    check("site: hidden from someone who hasn't picked yet", all('vote_distribution' not in c for c in fresh['categories']))
    check('Discord sees site votes in the split', ballot(P).get_json()['categories'][0]['voters'] == 2)

    print('--- ranked ---')
    r = a.post(f'/api/groups/{G}/polls', json={'title': 'Top 3', 'scoring_mode': 'ranked',
                                              'categories': [{'title': 'Year best', 'options': [{'text': t} for t in 'ABCDE']}]})
    R = r.get_json()['id']; RC = r.get_json()['categories'][0]; RO = [o['id'] for o in RC['options']]
    b = bvote(R, votes=[{'category_id': RC['id'], 'option_id': RO[0], 'rank': 1}, {'category_id': RC['id'], 'option_id': RO[0], 'rank': 2},
                        {'category_id': RC['id'], 'option_id': RO[1], 'rank': 1}, {'category_id': RC['id'], 'option_id': RO[2], 'rank': 4},
                        {'category_id': RC['id'], 'option_id': RO[3], 'rank': 2}]).get_json()
    check('ranked: duplicates and ranks outside 1–3 are dropped', [(p['option_id'], p['rank']) for p in b['categories'][0]['picks']] == [(RO[0], 1), (RO[3], 2)], b['categories'][0]['picks'])
    b = bvote(R, clear=[RC['id']]).get_json()
    check('ranked: clearing empties the category', b['categories'][0]['picks'] == [] and b['answered'] == 0)
    a.post(f'/api/polls/{R}/vote', json={'votes': [{'category_id': RC['id'], 'option_id': RO[4], 'rank': 1}]})
    a.post(f'/api/polls/{R}/vote', json={'votes': [], 'clear': [RC['id']]})
    check('site: removing your last ranked pick now actually clears it', 'user_votes' not in a.get(f'/api/polls/{R}').get_json()['categories'][0])

    print('--- closing, scoring ---')
    a.put(f'/api/polls/{P}', json={'status': 'closed'})
    r = bvote(P, votes=[{'category_id': BD, 'option_id': LAXE, 'confidence': 2}])
    check('closed poll: Discord vote refused with the read-only ballot', r.status_code == 409 and r.get_json()['error'] == 'poll_closed'
          and r.get_json()['poll']['status'] == 'closed')
    check('closed poll: split visible even where you never picked', 'split' in ballot(P).get_json()['categories'][1])
    check('closed poll: site vote refused', cy_site.post(f'/api/polls/{P}/vote', json={'votes': [{'category_id': BD, 'option_id': LAXE}]}).status_code == 400)
    lst = bot.get('/api/internal/polls', query_string={'group_id': G, 'include_closed': 1}, headers=H).get_json()
    check('/vote picker: open polls first, then recently closed', [p['id'] for p in lst] == [R, P], [p['id'] for p in lst])
    check('/polls still lists only open ones', [p['id'] for p in bot.get('/api/internal/polls', query_string={'group_id': G}, headers=H).get_json()] == [R])
    a.post(f'/api/polls/{P}/score', json={'winners': {str(BP): SIRAT, str(BD): ZHAO}, 'post_results': True})
    b = ballot(P).get_json()
    check('scored: winners shown, kernels per category (wrong confidence pick loses its 10)',
          b['categories'][0]['correct_option_id'] == SIRAT and b['categories'][0]['kernels'] == -10 and 'kernels' not in b['categories'][1], b['categories'])
    check("scored: Bo's total and place", b['score'] == {'kernels': -10, 'correct': 0, 'place': 2, 'of': 2}, b['score'])
    scored = posts('poll_results', P)
    check('posting results: one post with the top 3 (names only, no pings)', len(scored) == 1 and [t['name'] for t in scored[0]['top']] == ['Cy', 'Bo']
          and scored[0]['top'][0]['kernels'] == 4 and 'discord_user_id' not in scored[0]['top'][0], scored)
    a.post(f'/api/polls/{P}/score', json={'winners': {str(BP): SIRAT, str(BD): ZHAO}})
    check('re-scoring (a correction) does not post again', len(posts('poll_results', P)) == 1)
    lb = a.get(f'/api/polls/{P}/leaderboard').get_json()
    check('poll leaderboard: same shape as before', [(x['user']['name'], x['kernels'], x['correct'], x['total']) for x in lb] == [('Cy', 4, 2, 2), ('Bo', -10, 0, 1)], lb)
    k = a.get(f'/api/users/{C}/kernels', query_string={'group_id': G}).get_json()
    check('overall kernels agree with the poll leaderboard', k.get('kernels', k.get('total')) == 4, k)
    checks.done()

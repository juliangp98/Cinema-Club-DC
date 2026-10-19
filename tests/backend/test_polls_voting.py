"""Poll voting on the site and in Discord's /vote (same rules), ranked
ballots, closing, scoring and posting results."""
import pytest

from helpers import H, all_linked_present, client, setup_db

FEST = {'title': 'Fest picks', 'scoring_mode': 'confidence', 'poll_type': 'prediction', 'announce': 'now',
        'categories': [{'title': 'Best Picture', 'options': [{'text': 'SIRÂT'}, {'text': 'HAMNET'}, {'text': 'SINNERS'}]},
                       {'title': 'Best Director', 'options': [{'text': 'Laxe'}, {'text': 'Zhao'}]}]}


@pytest.fixture
def club():
    """Vote Club (the Discord server's club): Ana admin (9901), Bo (9902,
    Discord-only), Cy (9904); Out (9903) isn't in it."""
    import app as A
    from app import app, db, User, Group, GroupMembership
    setup_db()
    with app.app_context():
        g = Group(name='Vote Club', slug='vote-club', is_public=False)
        db.session.add(g)
        db.session.flush()
        ana = User(email='ana9@test.dev', name='Ana', is_active=True, discord_user_id='9901')
        bo = User(email=None, name='Bo', is_active=True, discord_user_id='9902')
        cy = User(email='cy9@test.dev', name='Cy', is_active=True, discord_user_id='9904')
        out = User(email=None, name='Out', is_active=True, discord_user_id='9903')
        db.session.add_all([ana, bo, cy, out])
        db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=g.id, status='active', role='admin'),
                            GroupMembership(user_id=bo.id, group_id=g.id, status='active'),
                            GroupMembership(user_id=cy.id, group_id=g.id, status='active')])
        db.session.commit()
        ids = {'group': g.id, 'ana': ana.id, 'cy': cy.id}
    A.HOME_GROUP_ID = ids['group']
    all_linked_present()
    return ids


@pytest.fixture
def fest(club):
    """Ana's prediction poll (confidence scoring), announced now."""
    r = client(club['ana']).post(f"/api/groups/{club['group']}/polls", json=FEST).json
    bp, bd = r['categories']
    return {**club, 'poll': r['id'], 'bp': bp['id'], 'bd': bd['id'],
            **dict(zip(('sirat', 'hamnet', 'sinners'), [o['id'] for o in bp['options']])),
            **dict(zip(('laxe', 'zhao'), [o['id'] for o in bd['options']]))}


def who(club, did):
    return {'discord_user_id': did, 'create': '0', 'group_id': club['group']}


def ballot(club, pid, did='9902'):
    return client().get(f'/api/internal/polls/{pid}/ballot', query_string=who(club, did), headers=H)


def discord_vote(club, pid, did='9902', **body):
    return client().post(f'/api/internal/polls/{pid}/vote', json={**who(club, did), **body}, headers=H)


def posts(kind, pid):
    from app import app, DiscordPost, render_post
    with app.app_context():
        return [render_post(p) for p in DiscordPost.query.filter_by(kind=kind, ref_id=pid)]


def test_announce_now_queues_one_announcement(fest):
    [post] = posts('poll', fest['poll'])
    assert post['group_id'] == fest['group'] and post['categories'] == 2


def test_a_fresh_ballot(fest):
    b = ballot(fest, fest['poll']).json
    assert b['answered'] == 0 and [c['title'] for c in b['categories']] == ['Best Picture', 'Best Director']
    assert [o['text'] for o in b['categories'][0]['options']] == ['SIRÂT', 'HAMNET', 'SINNERS']
    assert all('split' not in c for c in b['categories'])                        # no split before you pick


def test_a_pick_saves_and_reveals_that_categorys_split(fest):
    b = discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['sirat'], 'confidence': 7}]).json
    bp = b['categories'][0]
    assert b['answered'] == 1 and bp['picks'] == [{'option_id': fest['sirat'], 'confidence': 7, 'rank': None}]
    assert bp['split'] == {str(fest['sirat']): 1} and bp['voters'] == 1 and 'split' not in b['categories'][1]


def test_changing_a_pick_and_ignoring_junk(fest):
    discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['sirat'], 'confidence': 7}])
    b = discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['hamnet'], 'confidence': 99}]).json
    assert b['categories'][0]['picks'] == [{'option_id': fest['hamnet'], 'confidence': 10, 'rank': None}]   # replaced; clamped to 10
    b = discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['laxe']},
                                                {'category_id': 99999, 'option_id': fest['sirat']}]).json
    assert b['categories'][0]['picks'][0]['option_id'] == fest['hamnet']          # another category's nominee: ignored


def test_ballot_refusals(fest):
    r = ballot(fest, fest['poll'], '9903')
    assert r.status_code == 403 and 'not_member' in r.get_data(as_text=True)
    r = ballot(fest, fest['poll'], '9999')
    assert r.status_code == 404 and 'no_account' in r.get_data(as_text=True)
    assert ballot(fest, 99999).status_code == 404


def test_site_votes_follow_the_same_rules(fest):
    cy = client(fest['cy'])
    discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['hamnet'], 'confidence': 10}])
    r = cy.post(f"/api/polls/{fest['poll']}/vote", json={'votes': [{'category_id': fest['bp'], 'option_id': fest['sirat'], 'confidence': 'abc'}]})
    assert r.status_code == 200 and r.json['count'] == 1                         # junk confidence: defaults to 1
    split = cy.get(f"/api/polls/{fest['poll']}").json['categories'][0].get('vote_distribution')
    assert {str(k): v for k, v in split.items()} == {str(fest['sirat']): 1, str(fest['hamnet']): 1}
    assert all('vote_distribution' not in c for c in client(fest['ana']).get(f"/api/polls/{fest['poll']}").json['categories'])
    assert ballot(fest, fest['poll']).json['categories'][0]['voters'] == 2         # Discord sees site votes


def test_ranked_ballots(club):
    a = client(club['ana'])
    r = a.post(f"/api/groups/{club['group']}/polls", json={'title': 'Top 3', 'scoring_mode': 'ranked',
                                                          'categories': [{'title': 'Year best', 'options': [{'text': t} for t in 'ABCDE']}]}).json
    pid, cat = r['id'], r['categories'][0]
    o = [x['id'] for x in cat['options']]
    pick = lambda opt, rank: {'category_id': cat['id'], 'option_id': o[opt], 'rank': rank}
    b = discord_vote(club, pid, votes=[pick(0, 1), pick(0, 2), pick(1, 1), pick(2, 4), pick(3, 2)]).json
    assert [(p['option_id'], p['rank']) for p in b['categories'][0]['picks']] == [(o[0], 1), (o[3], 2)]   # dupes, ranks > 3 dropped
    b = discord_vote(club, pid, clear=[cat['id']]).json
    assert b['categories'][0]['picks'] == [] and b['answered'] == 0
    a.post(f'/api/polls/{pid}/vote', json={'votes': [pick(4, 1)]})
    a.post(f'/api/polls/{pid}/vote', json={'votes': [], 'clear': [cat['id']]})
    assert 'user_votes' not in a.get(f'/api/polls/{pid}').json['categories'][0]     # site: clearing really clears


def test_a_closed_poll(fest):
    a = client(fest['ana'])
    ranked = a.post(f"/api/groups/{fest['group']}/polls", json={'title': 'Top 3', 'scoring_mode': 'ranked',
                    'categories': [{'title': 'Y', 'options': [{'text': t} for t in 'AB']}]}).json['id']
    a.put(f"/api/polls/{fest['poll']}", json={'status': 'closed'})
    r = discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bd'], 'option_id': fest['laxe'], 'confidence': 2}])
    assert r.status_code == 409 and r.json['error'] == 'poll_closed' and r.json['poll']['status'] == 'closed'
    assert 'split' in ballot(fest, fest['poll']).json['categories'][1]              # visible now, even unpicked
    assert client(fest['cy']).post(f"/api/polls/{fest['poll']}/vote",
                                   json={'votes': [{'category_id': fest['bd'], 'option_id': fest['laxe']}]}).status_code == 400
    listed = lambda **q: [p['id'] for p in client().get('/api/internal/polls', query_string={'group_id': fest['group'], **q}, headers=H).json]
    assert listed(include_closed=1) == [ranked, fest['poll']]                       # /vote: open first, then recently closed
    assert listed() == [ranked]                                                     # /polls: open only


@pytest.fixture
def scored(fest):
    """Bo bet 10 on HAMNET (wrong); Cy picked SIRÂT (1) and Zhao (3), both
    right. Closed and scored, results posted."""
    discord_vote(fest, fest['poll'], votes=[{'category_id': fest['bp'], 'option_id': fest['hamnet'], 'confidence': 10}])
    cy = client(fest['cy'])
    cy.post(f"/api/polls/{fest['poll']}/vote", json={'votes': [{'category_id': fest['bp'], 'option_id': fest['sirat'], 'confidence': 1}]})
    cy.post(f"/api/polls/{fest['poll']}/vote", json={'votes': [{'category_id': fest['bd'], 'option_id': fest['zhao'], 'confidence': 3}]})
    a = client(fest['ana'])
    a.put(f"/api/polls/{fest['poll']}", json={'status': 'closed'})
    a.post(f"/api/polls/{fest['poll']}/score", json={'winners': {str(fest['bp']): fest['sirat'], str(fest['bd']): fest['zhao']},
                                                     'post_results': True})
    return fest


def test_scored_ballots_show_winners_and_kernels(scored):
    b = ballot(scored, scored['poll']).json
    assert b['categories'][0]['correct_option_id'] == scored['sirat']
    assert b['categories'][0]['kernels'] == -10 and 'kernels' not in b['categories'][1]    # a wrong 10 loses 10
    assert b['score'] == {'kernels': -10, 'correct': 0, 'place': 2, 'of': 2}


def test_results_are_posted_once_without_pings(scored):
    [post] = posts('poll_results', scored['poll'])
    assert [t['name'] for t in post['top']] == ['Cy', 'Bo'] and post['top'][0]['kernels'] == 4
    assert 'discord_user_id' not in post['top'][0]
    client(scored['ana']).post(f"/api/polls/{scored['poll']}/score",
                               json={'winners': {str(scored['bp']): scored['sirat'], str(scored['bd']): scored['zhao']}})
    assert len(posts('poll_results', scored['poll'])) == 1                       # a correction doesn't post again


def test_leaderboards_agree(scored):
    a = client(scored['ana'])
    lb = a.get(f"/api/polls/{scored['poll']}/leaderboard").json
    assert [(x['user']['name'], x['kernels'], x['correct'], x['total']) for x in lb] == [('Cy', 4, 2, 2), ('Bo', -10, 0, 1)]
    k = a.get(f"/api/users/{scored['cy']}/kernels", query_string={'group_id': scored['group']}).json
    assert k.get('kernels', k.get('total')) == 4

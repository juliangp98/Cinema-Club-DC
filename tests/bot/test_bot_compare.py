"""/compare end to end: the real slash command, its API calls routed into the
Flask test client (no server, no Discord connection). Seeds via test_phase7.py."""
from helpers import H, client, Checks, WORK


def test_bot_compare():
    checks = Checks()
    check = checks.check
    # ── seed ──
    import sys
    from datetime import datetime, timedelta
    from app import (app, db, migrate, User, Group, GroupMembership, RSVP, Showtime, Movie, Theatre, Watchlist,
                     Attendance, INTERNAL_API_TOKEN)

    H = {'X-Internal-Token': INTERNAL_API_TOKEN}

    with app.app_context():
        db.create_all(); migrate()
        now = datetime.now()
        tid = Theatre.query.filter_by(slug='afi').first().id
        from helpers import film_id
        films = {t: film_id(t) for t in ('SIRÂT', 'HAMNET', 'VERTIGO', 'SINNERS', 'KHARTOUM')}
        def show(title, days):
            s = Showtime(movie_id=films[title], theatre_id=tid, start_time=now + timedelta(days=days),
                         end_time=now + timedelta(days=days, hours=2)); db.session.add(s); db.session.flush(); return s.id
        S_BOTH, S_ANA_HAMNET, S_BO_VERTIGO, S_PRIVATE, S_SINNERS_NEXT = show('SIRÂT', 1), show('HAMNET', 2), show('VERTIGO', 3), show('KHARTOUM', 4), show('SINNERS', 5)
        P_TOGETHER, P_ANA_ONLY = show('SIRÂT', -3), show('HAMNET', -4)
        g2 = Group(name='Ana Private', slug='ana-private', is_public=False); db.session.add(g2); db.session.flush()
        ana = User(email='ana7@test.dev', name='Ana', is_active=True, discord_user_id='7701')
        bo = User(email='bo7@test.dev', name='Bo', is_active=True, discord_user_id='7702')
        eve = User(email='eve7@test.dev', name='Eve', is_active=True)
        db.session.add_all([ana, bo, eve]); db.session.flush()
        db.session.add_all([GroupMembership(user_id=ana.id, group_id=1, status='active'),
                            GroupMembership(user_id=ana.id, group_id=g2.id, status='active'),
                            GroupMembership(user_id=bo.id, group_id=1, status='active')])
        rs = [(ana, S_BOTH, 1, 'going'), (bo, S_BOTH, 1, 'maybe'), (ana, S_ANA_HAMNET, 1, 'going'),
              (bo, S_BO_VERTIGO, 1, 'going'), (ana, S_PRIVATE, g2.id, 'going'),
              (ana, P_TOGETHER, 1, 'going'), (bo, P_TOGETHER, 1, 'going'), (ana, P_ANA_ONLY, 1, 'going')]
        for u, sid, gid, st in rs:
            db.session.add(RSVP(user_id=u.id, showtime_id=sid, group_id=gid, status=st))
        for u, t in [(ana, 'SINNERS'), (bo, 'SINNERS'), (bo, 'HAMNET'), (ana, 'VERTIGO'), (ana, 'KHARTOUM')]:
            db.session.add(Watchlist(user_id=u.id, movie_id=films[t]))
        db.session.commit()
        ANA, BO, EVE, G2 = ana.id, bo.id, eve.id, g2.id

    def as_user(uid):
        c = app.test_client()
        with c.session_transaction() as s: s['user_id'] = uid
        return c
    a, b, e = as_user(ANA), as_user(BO), as_user(EVE)

    from helpers import all_linked_present
    all_linked_present()   # R6a.1: they're all in the club's server
    print('--- watchlists ---')
    wl = b.get(f'/api/users/{ANA}/watchlist').get_json()
    titles = {i['movie']['title']: i['next'] for i in wl['items']}
    check("Bo can see Ana's watchlist, each with its next showing", not wl['own'] and set(titles) == {'SINNERS', 'VERTIGO', 'KHARTOUM'}
          and titles['VERTIGO']['showtime_id'] == S_BO_VERTIGO, titles)
    own = a.get(f'/api/users/{ANA}/watchlist').get_json()
    check('own watchlist flagged as own', own['own'])
    check('watchlists need a shared group', e.get(f'/api/users/{ANA}/watchlist').status_code == 403)

    print('--- RSVPs ---')
    theirs = {i['showtime_id']: i['status'] for i in b.get(f'/api/users/{ANA}/rsvps').get_json()['items']}
    check("Bo sees Ana's upcoming RSVPs from their shared group", theirs == {S_BOTH: 'going', S_ANA_HAMNET: 'going'}, theirs)
    check("…but not ones in a group Bo isn't in", S_PRIVATE not in theirs)
    mine = {i['showtime_id'] for i in a.get(f'/api/users/{ANA}/rsvps').get_json()['items']}
    check('Ana sees all her own, including the private group', S_PRIVATE in mine and P_TOGETHER not in mine)
    order = [i['start_time'] for i in a.get(f'/api/users/{ANA}/rsvps').get_json()['items']]
    check('soonest first, past screenings excluded', order == sorted(order) and len(order) == 3)

    print('--- compare (Bo looking at Ana) ---')
    cmp = b.get(f'/api/users/{ANA}/compare').get_json()
    check('both want to see: SINNERS, with its next showing', [x['movie']['title'] for x in cmp['both_want']] == ['SINNERS']
          and cmp['both_want'][0]['next']['showtime_id'] == S_SINNERS_NEXT, cmp['both_want'])
    check("both going: the screening they both RSVP'd (Ana's status shown)", [(x['showtime_id'], x['status']) for x in cmp['both_going']] == [(S_BOTH, 'going')], cmp['both_going'])
    check("they're going to something on your watchlist: Ana → HAMNET", [x['showtime_id'] for x in cmp['they_go_you_want']] == [S_ANA_HAMNET], cmp['they_go_you_want'])
    check("you're going to something on theirs: Bo → VERTIGO", [x['showtime_id'] for x in cmp['you_go_they_want']] == [S_BO_VERTIGO], cmp['you_go_they_want'])
    check('private-group RSVP (KHARTOUM, on Ana\'s list) stays out of it', all(x['showtime_id'] != S_PRIVATE for k in ('both_going', 'they_go_you_want') for x in cmp[k]))
    check('seen together: the past screening both went to', [x['showtime_id'] for x in cmp['seen_together']] == [P_TOGETHER], cmp['seen_together'])
    with app.app_context():
        db.session.add(Attendance(user_id=BO, showtime_id=P_TOGETHER, status='missed', source='site')); db.session.commit()
    check('…and it drops if one of them says they missed it', b.get(f'/api/users/{ANA}/compare').get_json()['seen_together'] == [])
    check('comparing with yourself is refused', a.get(f'/api/users/{ANA}/compare').status_code == 400)
    check('comparing needs a shared group', e.get(f'/api/users/{ANA}/compare').status_code == 403)

    print('--- Discord /compare ---')
    c = app.test_client()
    d = c.get('/api/internal/compare', query_string={'discord_user_id': '7702', 'create': '1', 'group_id': 1, 'member_discord_id': '7701'}, headers=H).get_json()
    check('same answer from Discord', d['name'] == 'Ana' and [x['movie']['title'] for x in d['both_want']] == ['SINNERS']
          and [x['showtime_id'] for x in d['they_go_you_want']] == [S_ANA_HAMNET], d)
    check('member with no account -> 404', c.get('/api/internal/compare', query_string={'discord_user_id': '7702', 'create': '1', 'group_id': 1, 'member_discord_id': '9999'}, headers=H).status_code == 404)
    check('yourself -> 400', c.get('/api/internal/compare', query_string={'discord_user_id': '7702', 'create': '1', 'group_id': 1, 'member_discord_id': '7702'}, headers=H).status_code == 400)
    from helpers import patch_bot_api
    patch_bot_api()
    import asyncio, os, sys, types
    ROOT = '/Users/julianperez/Development/Cinema-Club-DC'
    from app import app, INTERNAL_API_TOKEN
    import bot
    from api import ApiError

    flask = app.test_client()
    async def fake_get(path, **params):
        r = flask.get(path, query_string={k: v for k, v in params.items() if v is not None},
                      headers={'X-Internal-Token': INTERNAL_API_TOKEN})
        if r.status_code >= 400:
            raise ApiError(r.status_code, r.get_data(as_text=True))
        return r.get_json()
    bot.api.get = fake_get

    class Interaction:
        def __init__(self, uid):
            self.log, self.guild_id, self.channel_id = [], None, 1
            self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', mention=f'<@{uid}>',
                                              display_avatar=types.SimpleNamespace(url='https://cdn/x.png'))
            outer = self
            class R:
                async def defer(self, ephemeral=False, **k): outer.log.append(('defer', ephemeral, None, None))
            class F:
                async def send(self, content=None, ephemeral=False, embed=None, **k): outer.log.append(('followup', ephemeral, content, embed))
            self.response, self.followup = R(), F()

    member = lambda uid, name: types.SimpleNamespace(id=uid, display_name=name)

    async def main():
        print('\n--- /compare in Discord (Bo → Ana) ---')
        it = Interaction(7702)
        await bot.compare.callback(it, member(7701, 'Ana'))
        kind, eph, content, emb = it.log[-1]
        check('private reply with an embed', it.log[0] == ('defer', True, None, None) and kind == 'followup' and eph and emb)
        fields = {f.name: f.value for f in emb.fields}
        check('titled for the pair', emb.title == '🤝 You & Ana', emb.title)
        check('both want SINNERS, with its next showing', 'SINNERS' in fields.get('🎯 You both want to see', '')
              and 'next:' in fields['🎯 You both want to see'], fields)
        check("both going / they go / you go sections filled",
              'SIRÂT' in fields.get("🎟️ You're both going", '') and 'HAMNET' in fields.get("👀 Ana's going to something on your watchlist", '')
              and 'VERTIGO' in fields.get("📣 You're going to something on Ana's watchlist", ''), fields)
        check('private-group screening never appears', 'KHARTOUM' not in str(fields))
        check('missed screening not "seen together"', '🍿 Seen together' not in fields)

        print('--- edge cases ---')
        it = Interaction(7702); await bot.compare.callback(it, member(7702, 'Bo'))
        check('yourself: told to pick someone else, no API call', it.log[-1][2] == 'Pick someone other than yourself.')
        it = Interaction(7702); await bot.compare.callback(it, member(9999, 'Zed'))
        check("member who never used the club", it.log[-1][2] == "Zed hasn't used Cinema Club yet.", it.log[-1])
        empty = bot.embeds.compare_embed({'name': 'Cal', 'both_want': [], 'both_going': [], 'they_go_you_want': [],
                                          'you_go_they_want': [], 'seen_together': []})
        check('nothing in common: a friendly hint instead of empty fields', not empty.fields and '/watch' in empty.description)
    asyncio.run(main())
    checks.done()

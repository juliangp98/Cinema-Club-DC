"""Challenges in Discord: /play versus: (one game, random, or a gauntlet),
the buttons — accept, play a private ballot, pick a gauntlet's games — the
channel post, invite DMs and /play challenges:."""
import asyncio
import json
import types

from discord import app_commands

from helpers import FakeInteraction, items_of, press


def pick(v):
    return app_commands.Choice(name=v, value=v)


BEA = types.SimpleNamespace(id=502, display_name='Bea', name='bea', bot=False)


def play(bot, it, **kw):
    asyncio.run(bot.play_cmd.callback(it, **kw))
    return it.last


def ids(view):
    return [getattr(i, 'custom_id', None) for i in items_of(view)]


def right(cid, r, i):
    from app import app, db, Challenge
    with app.app_context():
        return json.loads(db.session.get(Challenge, cid).state_json)['sets'][str(r)][i]['answer']


def test_a_versus_from_play(bot):
    _, _, kw = play(bot, FakeInteraction(501, 'ana'), versus=pick('who_said'), opponent=BEA, questions=2)
    embed, view = kw['embed'], kw['view']
    cid = int(embed.url.rsplit('/', 1)[1])
    assert kw['ephemeral'] and embed.title == '⚔️ 🗣️ Who said it challenge' and '2 questions' in embed.description
    assert 'Bea · invited' in embed.description and f'chal:play:{cid}' in ids(view) and f'chal:accept:{cid}' not in ids(view)

    _, _, kw = press(bot.ChallengeButton, f'chal:accept:{cid}', FakeInteraction(502, 'bea')).last
    assert "You're in" in kw['embed'].description and f'chal:play:{cid}' in ids(kw['view'])

    _, _, kw = press(bot.ChallengeButton, f'chal:play:{cid}', FakeInteraction(501, 'ana')).last
    q = kw['embed']
    assert 'Who says it in' in q.description and "Time's up <t:" in q.description and q.footer.text.startswith('Question 1 of 2')
    assert ids(kw['view']) == [f'chans:{cid}:0:{n}' for n in range(4)]
    it = press(bot.ChallengeAnswer, f'chans:{cid}:0:{right(cid, 0, 0)}', FakeInteraction(501, 'ana'))
    assert it.last[0] == 'edit' and it.last[2]['embed'].description.startswith('✅ Right! +1')
    assert it.last[2]['embed'].footer.text.startswith('Question 2 of 2')
    it = press(bot.ChallengeAnswer, f'chans:{cid}:1:{(right(cid, 0, 1) + 1) % 4}', FakeInteraction(501, 'ana'))
    assert "You've played" in it.last[2]['embed'].description and 'the results come once everyone has' in it.last[2]['embed'].description


def test_a_gauntlet_and_picking_its_games(bot):
    _, _, kw = play(bot, FakeInteraction(501, 'ana'), versus=pick('gauntlet'), games=2, opponent=BEA, questions=3)
    embed, view = kw['embed'], kw['view']
    cid = int(embed.url.rsplit('/', 1)[1])
    assert embed.title == '⚔️ 🧩 Gauntlet' and '2 games:' in embed.description
    select = next(i for i in items_of(view) if (i.custom_id or '').startswith('chgames:'))
    assert select.custom_id == f'chgames:{cid}:3' and {o.value for o in select.options} == {'who_said', 'higher_lower'}
    it = press(bot.ChallengeGamesSelect, select.custom_id, FakeInteraction(501, 'ana'), item=select,
               values=['who_said', 'higher_lower'])
    assert '2 games: 🗣️ Who said it, ↕️ Higher or lower' in it.last[2]['embed'].description
    _, _, kw = press(bot.ChallengeButton, f'chal:play:{cid}', FakeInteraction(501, 'ana')).last
    assert kw['embed'].footer.text.startswith('Game 1 of 2: Who said it · Question 1 of 3')


def test_the_channel_post_names_and_buttons():
    import embeds
    from features import challenges
    p = {'challenge_id': 7, 'game': '🗣️ Who said it', 'kind': 'who_said', 'status': 'open', 'stake': 3, 'pot': 6,
         'seats_left': 1, 'reveal': 'sealed', 'questions': 5, 'games': 1, 'closes_at': '2027-03-15T00:00:00+00:00', 'by': 'Ana',
         'backing': {'open': True, 'total': 4, 'count': 1},
         'players': [{'name': 'Ana', 'status': 'finished', 'score': None, 'winner': False, 'net': None, 'rounds_won': None},
                     {'name': None, 'status': 'accepted', 'score': None, 'winner': False, 'net': None, 'rounds_won': None}]}
    async def render():
        return challenges.post_content(p)
    embed, view = asyncio.run(render())
    assert embed.title == '⚔️ 🗣️ Who said it challenge' and '**Ana**' in embed.description and '*a member*' in embed.description
    assert '<@' not in embed.description and '3 🍿 each, pot 6 🍿' in embed.description
    assert ids(view)[:3] == ['chal:view:7', 'chal:join:7', 'chal:back:7']
    done = embeds.challenge_post_embed({**p, 'status': 'done', 'players': [{**p['players'][0], 'score': 4, 'winner': True, 'net': 3}]})
    assert done.title == '🏆 🗣️ Who said it: results' and '🏆 **Ana**' in done.description and '(+3 🍿)' in done.description


def test_invites_by_dm_and_your_list(bot):
    _, _, kw = play(bot, FakeInteraction(501, 'ana'), versus=pick('who_said'), opponent=BEA)
    cid = int(kw['embed'].url.rsplit('/', 1)[1])
    sent = []

    class Bea:
        async def send(self, content=None, **k):
            sent.append(k)
    asyncio.run(bot.send_invite(Bea(), 502, cid))
    assert "You've been challenged" in sent[0]['embed'].description and f'chal:accept:{cid}' in ids(sent[0]['view'])
    _, content, _ = play(bot, FakeInteraction(502, 'bea'), challenges=pick('mine'))
    assert '🗣️ **Who said it** · Ana, Bea' in content and 'to put in' in content


def test_play_solo_and_help_say_so(bot):
    import embeds
    text = ' '.join(desc for _, rows in embeds.HELP_SECTIONS for name, desc in rows if name == '/play')
    assert '`solo:`' in text and '`versus:`' in text and '`challenges:`' in text

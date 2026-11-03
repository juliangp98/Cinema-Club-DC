"""Tournaments and scouting in Discord: /play tournament: (versus: picks the
game), the buttons — I'm in, start it, ▶ Play your match — the channel post,
and /play challenges: scout with its roasts and one-tap challenges."""
import asyncio
import types

from discord import app_commands

from helpers import FakeInteraction, items_of, press
from test_bot_challenges import BEA, ids, pick, play

CAL = types.SimpleNamespace(id=503, display_name='Cal', name='cal', bot=False)


def choice(v):
    return app_commands.Choice(name=v, value=v)


def test_a_tournament_from_play(bot):
    _, _, kw = play(bot, FakeInteraction(501, 'ana'), tournament=choice('double'), versus=pick('who_said'),
                    opponent=BEA, opponent2=CAL, questions=1, stake=0, payout=choice('top3'))
    embed, view = kw['embed'], kw['view']
    tid = int(embed.url.rsplit('/', 1)[1])
    assert embed.title == '🏆 Taking entries: Double elimination' and 'Needs 3–16 players' in embed.description
    assert f'tour:cancel:{tid}' in ids(view) and f'tour:start:{tid}' not in ids(view)        # only one in so far
    _, _, kw = press(bot.TournamentButton, f'tour:accept:{tid}', FakeInteraction(502, 'bea')).last
    assert "You're in" in kw['embed'].description
    _, _, kw = press(bot.TournamentButton, f'tour:accept:{tid}', FakeInteraction(503, 'cal')).last
    assert kw['embed'].title == '⚔️ Under way: Double elimination' and '**Matches**' in kw['embed'].description
    mine = [FakeInteraction(u, n) for u, n in ((501, 'ana'), (502, 'bea'), (503, 'cal'))]
    views = [press(bot.TournamentButton, f'tour:view:{tid}', it).last[2]['view'] for it in mine]
    plays = [i for v in views for i in ids(v) if (i or '').startswith('chal:play:')]
    assert len(plays) == 2                                                                   # the two in the first match


def test_the_channel_post():
    import embeds
    from features import tournaments
    p = {'tournament_id': 4, 'title': '🏆 Round robin + final', 'format': 'round_robin', 'game': '🗣️ Who said it',
         'status': 'running', 'stake': 2, 'pot': 6, 'payout': 'Winner takes all', 'seats_left': 0,
         'closes_at': '2027-03-15T00:00:00+00:00', 'by': 'Ana', 'places': [None, None, None],
         'backing': {'open': True, 'total': 3, 'count': 1},
         'players': [{'name': 'Ana', 'status': 'accepted', 'seed': 1, 'place': None},
                     {'name': None, 'status': 'accepted', 'seed': 2, 'place': None}],
         'matches': [{'key': 'R1-0', 'label': 'Round 1', 'a': 'Ana', 'b': None, 'winner': 'a', 'status': 'done'}]}

    async def render():
        return tournaments.tournament_post_content(p)
    embed, view = asyncio.run(render())
    assert embed.title == '⚔️ 🏆 Round robin + final: under way' and '✓ Round 1: **Ana** vs a member' in embed.description
    assert '<@' not in embed.description and ids(view)[:2] == ['tour:view:4', 'tour:back:4']
    done = embeds.tournament_post_embed({**p, 'status': 'done', 'places': ['Ana', None, None]})
    assert done.title.endswith('the results') and '🥇 **Ana**' in done.description


def test_who_should_i_challenge(bot, monkeypatch):
    import ai
    monkeypatch.setattr(ai, 'chat', lambda *a, **k: (_ for _ in ()).throw(ai.Unavailable('no AI here')))
    play(bot, FakeInteraction(502, 'bea'), solo=None)                                       # Bea's account exists
    _, _, kw = play(bot, FakeInteraction(501, 'ana'), challenges=pick('scout'))
    assert kw['embed'].title == '🔍 Who should you challenge?' and 'Bea' in kw['embed'].description
    roast = next(i for i in items_of(kw['view']) if (i.custom_id or '').startswith('scout:roast:'))
    fight = next(i for i in items_of(kw['view']) if (i.custom_id or '').startswith('scout:challenge:'))
    it = press(bot.ScoutButton, roast.custom_id, FakeInteraction(501, 'ana'))
    assert it.last[1].startswith('🔥 ') and 'Bea' in it.last[1]
    it = press(bot.ScoutButton, fight.custom_id, FakeInteraction(501, 'ana'))
    assert 'Challenge sent' in it.last[2]['embed'].description and 'Bea · invited' in it.last[2]['embed'].description


def test_help_says_so():
    import embeds
    text = ' '.join(desc for _, rows in embeds.HELP_SECTIONS for name, desc in rows if name == '/play')
    assert '`tournament:`' in text and 'who you should challenge' in text

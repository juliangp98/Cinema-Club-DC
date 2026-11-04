"""Tournaments in Discord: /play tournament start (make one) and list, the
buttons on a tournament (accept, take a seat, back a player, start it), the
channel post (the bracket so far), and invite DMs. Each match is a
challenge: ▶ Play is the challenge's own button. The rules live in the
backend (tournaments.py), the same as the site's.
"""

import discord
from discord import app_commands

import embeds
from api import ApiError
from .challenges import AMOUNTS, ChallengeButton, _error
from .shared import SITE_URL, api, api_failure, discord_identity, register, reply_failure, tell

TOURNAMENT_FORMATS = [app_commands.Choice(name='Double elimination (3–16 players)', value='double'),
           app_commands.Choice(name='Round robin + final (3–6 players)', value='round_robin')]
TOURNAMENT_PAYOUTS = [app_commands.Choice(name='Winner takes all', value='all'),
           app_commands.Choice(name='60 / 30 / 10 to the top three', value='top3')]
TOURNAMENT_MATCH_TIMES = [app_commands.Choice(name=n, value=v) for v, n in (('hour', 'An hour'), ('tonight', 'Till tonight'),
                                                                 ('day', 'A day'))]


def tournament_view(t):
    """The buttons for one member: what they can do with this tournament now."""
    view = discord.ui.View(timeout=None)
    you, tid = t['you'], t['id']
    if you['can_accept']:
        view.add_item(TournamentButton('accept', tid, label=f"✓ I'm in ({t['stake']} 🍿)" if t['stake'] else "✓ I'm in",
                                       style=discord.ButtonStyle.success))
        view.add_item(TournamentButton('decline', tid, label='Decline'))
    if you['can_join']:
        view.add_item(TournamentButton('join', tid, label='🪑 Take a seat', style=discord.ButtonStyle.success))
    if you.get('match'):
        view.add_item(ChallengeButton('play', you['match'], label='▶ Play your match', style=discord.ButtonStyle.primary))
    if you['can_back']:
        view.add_item(TournamentButton('back', tid, label='🍿 Back a player'))
    if you['can_start']:
        view.add_item(TournamentButton('start', tid, label='🏁 Start it now'))
    if you['can_cancel']:
        view.add_item(TournamentButton('cancel', tid, label='Call it off'))
    view.add_item(discord.ui.Button(label='The bracket', url=f"{SITE_URL}/tournaments/{tid}"))
    return view


def tournament_post_view(p):
    """Under a tournament's post: anyone opens it for themselves, takes a seat, or backs a player."""
    view = discord.ui.View(timeout=None)
    if p['status'] in ('open', 'running'):
        view.add_item(TournamentButton('view', p['tournament_id'], label='🏆 Open it', style=discord.ButtonStyle.primary))
        if p['status'] == 'open' and p['seats_left']:
            view.add_item(TournamentButton('join', p['tournament_id'], label='🪑 Join'))
        if p['backing']['open']:
            view.add_item(TournamentButton('back', p['tournament_id'], label='🍿 Back a player'))
    view.add_item(discord.ui.Button(label='The bracket', url=f"{SITE_URL}/tournaments/{p['tournament_id']}"))
    return view


async def _send(interaction, embed, view):
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def tournament_show(interaction, tid, note=None):
    try:
        t = await api.get(f'/api/internal/tournaments/{tid}', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'tournament', missing="That tournament isn't one you can see.")
        return
    await _send(interaction, embeds.tournament_embed(t, note), tournament_view(t))


async def tournament_act(interaction, tid, action, note, **body):
    """A tournament action; then the tournament as it now stands, privately."""
    try:
        t = await api.post('/api/internal/tournaments', {**discord_identity(interaction), 'action': action,
                                                         'tournament_id': tid, **body})
    except ApiError as e:
        await tell(interaction, _error(e, api_failure(e, "Couldn't do that ({status}).")))
        return
    except Exception as e:
        await reply_failure(interaction, e, 'tournament')
        return
    await _send(interaction, embeds.tournament_embed(t, note), tournament_view(t))


class TournamentButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r'tour:(?P<act>view|accept|decline|join|back|start|cancel):(?P<tid>[0-9]+)'):
    """Everything a tournament's buttons do, for whoever taps them."""
    def __init__(self, act, tid, label='🏆 Open it', style=discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label[:80], style=style, custom_id=f'tour:{act}:{tid}'))
        self.act, self.tid = act, int(tid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'], match['tid'], label=getattr(item, 'label', None) or match['act'],
                   style=getattr(item, 'style', None) or discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        a, tid = self.act, self.tid
        if a == 'view':
            await tournament_show(interaction, tid)
        elif a == 'back':
            await tournament_back_flow(interaction, tid)
        elif a in ('accept', 'decline'):
            await tournament_act(interaction, tid, 'respond', "✓ You're in — your first match comes once it starts." if a == 'accept'
                      else 'Declined.', accept=a == 'accept')
        elif a == 'join':
            await tournament_act(interaction, tid, 'join', '🪑 You took a seat — your first match comes once it starts.')
        elif a == 'start':
            await tournament_act(interaction, tid, 'start', '🏁 Started — the first matches are open.')
        else:
            await tournament_act(interaction, tid, 'cancel', 'Called off. Nothing changed hands.')


class TournamentBackSelect(discord.ui.DynamicItem[discord.ui.Select], template=r'tback:(?P<tid>[0-9]+)'):
    """Backing, step one: who wins it all."""
    def __init__(self, tid, options=None):
        super().__init__(discord.ui.Select(custom_id=f'tback:{tid}', placeholder='Who wins it all?',
                                           options=options or [discord.SelectOption(label='—', value='0')]))
        self.tid = int(tid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['tid'], getattr(item, 'options', None))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = int(((interaction.data or {}).get('values') or ['0'])[0])
        view = discord.ui.View(timeout=None)
        for n in AMOUNTS:
            view.add_item(TournamentBet(self.tid, uid, n))
        await interaction.edit_original_response(content='How much? (It comes back with more if they win it all.)', view=view)


class TournamentBet(discord.ui.DynamicItem[discord.ui.Button], template=r'tbet:(?P<tid>[0-9]+):(?P<uid>[0-9]+):(?P<amount>[0-9]+)'):
    """Backing, step two: how much."""
    def __init__(self, tid, uid, amount):
        super().__init__(discord.ui.Button(label=f'{amount} 🍿', custom_id=f'tbet:{tid}:{uid}:{amount}'))
        self.tid, self.uid, self.amount = int(tid), int(uid), int(amount)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['tid'], match['uid'], match['amount'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await tournament_act(interaction, self.tid, 'back', f'🍿 You backed them with {self.amount} 🍿.', user_id=self.uid, amount=self.amount)


async def tournament_back_flow(interaction, tid):
    try:
        t = await api.get(f'/api/internal/tournaments/{tid}', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'tournament')
        return
    if not t['you']['can_back']:
        await tell(interaction, "Backing is closed for this one (or you're playing in it, or you've backed someone).")
        return
    options = [discord.SelectOption(label=p['user']['name'][:100], value=str(p['user']['id']))
               for p in t['players'] if p['status'] == 'accepted'][:25]
    view = discord.ui.View(timeout=None)
    view.add_item(TournamentBackSelect(tid, options))
    await interaction.followup.send(f"Back someone to win **{t['title']}** — {t['backing']['max']} 🍿 at most.",
                                    view=view, ephemeral=True)


async def tournament_flow(interaction, fmt, kind, people, stake=None, seats=None, questions=None, games=None, deadline=None,
                          match_time=None, payout=None, reveal=None, club_visible=None, post=None):
    """Make a tournament (after the command's defer): the game (one, random,
    or a gauntlet of `games` random ones), invitees and seats."""
    invited = [{'discord_user_id': str(m.id), 'discord_name': getattr(m, 'display_name', None) or m.name}
               for m in people if m is not None and not getattr(m, 'bot', False) and m.id != interaction.user.id]
    body = {**discord_identity(interaction), 'action': 'create', 'format': fmt, 'kind': kind or 'random',
            'players': invited, 'stake': stake if stake is not None else 0, 'seats': seats or 0,
            'questions': questions or 5, 'games': games or 3, 'deadline': deadline or 'tonight',
            'match_time': match_time or 'day', 'payout': payout or 'all', 'reveal': reveal or 'sealed',
            'visibility': 'players' if club_visible is False else 'club',
            'announce': None if post is None else ('now' if post else 'none')}
    try:
        t = await api.post('/api/internal/tournaments', body)
    except ApiError as e:
        await interaction.followup.send(_error(e, api_failure(e, "Couldn't start that ({status}).")), ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/play tournament start')
        return
    note = '🏆 Tournament set up' + (' and posted in the channel' if t.get('posted') else '') + \
        '. It starts once everyone has answered and the seats are taken — or tap 🏁 Start it now.'
    await interaction.followup.send(embed=embeds.tournament_embed(t, note), view=tournament_view(t), ephemeral=True)


async def send_tournament_invite(user, discord_user_id, tid):
    """DM an invite (members who chose Discord for challenge invites) with I'm in / Decline."""
    try:
        t = await api.get(f'/api/internal/tournaments/{tid}', discord_user_id=str(discord_user_id))
    except Exception as e:
        print(f'tournament invite {tid}: {e}')
        return
    if t['you']['can_accept']:
        await user.send(embed=embeds.tournament_embed(t, "🏆 You're invited to a tournament!"), view=tournament_view(t))


def tournament_post_content(data):
    """(embed, view) for a tournament's post in the channel (the shared-posts queue)."""
    return embeds.tournament_post_embed(data), tournament_post_view(data)


register(items=(TournamentButton, TournamentBackSelect, TournamentBet))

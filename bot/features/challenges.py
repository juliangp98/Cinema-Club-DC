"""Challenges in Discord: /play challenge start (make one), list (yours, or
the club's open ones) and scout (who you should challenge, with a roast), and
the buttons on a challenge: accept, join an open seat, play (a private ballot,
30 seconds a question), back a player, rematch. The rules live in the backend
(challenges.py, scout.py), the same as the site's. Tournaments:
features/tournaments.py (each match is a challenge, played here).
"""

import discord
from discord import app_commands

import embeds
from api import ApiError
from .shared import SITE_URL, api, api_failure, discord_identity, register, reply_failure, tell

GAMES = (('higher_lower', '↕️ Higher or lower'), ('who_said', '🗣️ Who said it'), ('still', '🖼️ Guess the still'),
         ('reviews', '📝 Guess from the reviews'), ('emoji', '🎭 Emoji plot'), ('trivia', '🧠 Trivia'))
VERSUS_GAMES = [app_commands.Choice(name=n, value=v) for v, n in (
    ('random', '🎲 A random game'), ('gauntlet', '🧩 Gauntlet: several games'), *GAMES)]
DEADLINES = [app_commands.Choice(name=n, value=v) for v, n in (('hour', 'In an hour'), ('tonight', 'Tonight'),
                                                               ('days', 'In 3 days'))]
REVEALS = [app_commands.Choice(name='Sealed until everyone has played', value='sealed'),
           app_commands.Choice(name='Live: as each player finishes', value='live')]
LISTS = [app_commands.Choice(name='Mine', value='mine'), app_commands.Choice(name="The club's open ones", value='open')]
AMOUNTS = (1, 2, 3, 5, 10)


def _error(err, fallback):
    try:
        import json
        return json.loads(err.body or '{}').get('error') or fallback
    except ValueError:
        return fallback


# ─── What a member can do with one ────────────────────────────────────────────

def challenge_view(c):
    """The buttons for one member: what they can do with this challenge now."""
    view = discord.ui.View(timeout=None)
    you, cid = c['you'], c['id']
    if you['can_accept']:
        view.add_item(ChallengeButton('accept', cid, label=f"✓ Accept ({c['stake']} 🍿)" if c['stake'] else '✓ Accept',
                                      style=discord.ButtonStyle.success))
        view.add_item(ChallengeButton('decline', cid, label='Decline'))
    if you['can_join']:
        view.add_item(ChallengeButton('join', cid, label='🪑 Take a seat', style=discord.ButtonStyle.success))
    if you['can_play']:
        view.add_item(ChallengeButton('play', cid, label='▶ Play', style=discord.ButtonStyle.primary))
    if you['can_back']:
        view.add_item(ChallengeButton('back', cid, label='🍿 Back a player'))
    if you['can_rematch'] and not c.get('rematch'):
        view.add_item(ChallengeButton('rematch', cid, label='🔁 Rematch'))
        view.add_item(ChallengeButton('double', cid, label='🔁 Double or nothing'))
    if you['can_end']:
        view.add_item(ChallengeButton('end', cid, label='End it now'))
    if you['can_cancel']:
        view.add_item(ChallengeButton('cancel', cid, label='Call it off'))
    if you.get('can_set_games') and c.get('gauntlet') and c.get('game_choices'):
        each = next((r['questions'] for r in c['rounds'] if r['questions']), 5)
        view.add_item(ChallengeGamesSelect(cid, each, [discord.SelectOption(label=f"{g['emoji']} {g['label']}"[:100], value=g['kind'])
                                                       for g in c['game_choices']]))
    view.add_item(discord.ui.Button(label='On the site', url=f"{SITE_URL}/challenges/{cid}"))
    return view


def post_view(p):
    """Under a challenge's post in the channel: anyone opens it for themselves
    (their own buttons), takes a seat, or backs a player."""
    view = discord.ui.View(timeout=None)
    if p['status'] == 'open':
        view.add_item(ChallengeButton('view', p['challenge_id'], label='⚔️ Open it', style=discord.ButtonStyle.primary))
        if p['seats_left']:
            view.add_item(ChallengeButton('join', p['challenge_id'], label='🪑 Join'))
        if p['backing']['open']:
            view.add_item(ChallengeButton('back', p['challenge_id'], label='🍿 Back a player'))
    view.add_item(discord.ui.Button(label='On the site', url=f"{SITE_URL}/challenges/{p['challenge_id']}"))
    return view


def question_view(q):
    """A challenge question's answers — Before / After, or A–D (and see more)."""
    view = discord.ui.View(timeout=None)
    cid, i = q['id'], q['q']
    if q['kind'] == 'higher_lower':
        y = q['current']['year']
        view.add_item(ChallengeAnswer(cid, i, 'before', label=f'⬅️ Before {y}'))
        view.add_item(ChallengeAnswer(cid, i, 'after', label=f'After {y} ➡️'))
    else:
        for n in range(len(q['options'])):
            view.add_item(ChallengeAnswer(cid, i, str(n), label=embeds.LETTERS[n]))
        if q.get('by_step') and q.get('step', 3) < q.get('steps', 3):
            view.add_item(ChallengeAnswer(cid, i, 'more', label='🔍 Zoom out' if q['kind'] == 'still' else '📝 Another review',
                                          style=discord.ButtonStyle.primary))
    return view


async def _send(interaction, embed, view, edit=False):
    if edit:
        await interaction.edit_original_response(embed=embed, view=view)
    else:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


async def show(interaction, cid, note=None, edit=False):
    try:
        c = await api.get(f'/api/internal/challenges/{cid}', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'challenge', missing="That challenge isn't one you can see.")
        return
    await _send(interaction, embeds.challenge_embed(c, note), challenge_view(c), edit)


async def act(interaction, cid, action, note, **body):
    """A challenge action; then the challenge as it now stands, privately."""
    try:
        c = await api.post('/api/internal/challenges', {**discord_identity(interaction), 'action': action,
                                                        'challenge_id': cid, **body})
    except ApiError as e:
        await tell(interaction, _error(e, api_failure(e, "Couldn't do that ({status}).")))
        return
    except Exception as e:
        await reply_failure(interaction, e, 'challenge')
        return
    await _send(interaction, embeds.challenge_embed(c, note), challenge_view(c))


async def play(interaction, cid, edit=False, answered=None):
    """Your current question (its clock starts now), or how you did."""
    try:
        r = await api.post('/api/internal/challenges', {**discord_identity(interaction), 'action': 'play', 'challenge_id': cid})
    except ApiError as e:
        await tell(interaction, _error(e, api_failure(e, "Couldn't open that ({status}).")))
        return
    except Exception as e:
        await reply_failure(interaction, e, 'challenge')
        return
    await _show_question(interaction, r, edit, answered)


async def _show_question(interaction, r, edit, answered=None):
    q, c = r.get('question'), r['challenge']
    said = ''
    last = (answered or {}).get('last') or {}
    if answered:
        said = ("⏱️ Time ran out on that one." if last.get('timeout') else
                f"✅ Right! +{last.get('points', 0)}" if last.get('right') else '❌ Not quite.')
    if q:
        embed = embeds.challenge_question_embed(q)
        if said:
            embed.description = f"{said}\n\n{embed.description}"[:4000]
        await _send(interaction, embed, question_view(q), edit)
        return
    note = f"{said}\n\n✅ You've played — " + ("the results come once everyone has." if c['status'] == 'open' else 'it\'s decided!')
    await _send(interaction, embeds.challenge_embed(c, note.strip()), challenge_view(c), edit)


# ─── Buttons ──────────────────────────────────────────────────────────────────

class ChallengeButton(discord.ui.DynamicItem[discord.ui.Button],
                      template=r'chal:(?P<act>view|accept|decline|join|play|back|rematch|double|end|cancel):(?P<cid>[0-9]+)'):
    """Everything a challenge's buttons do, for whoever taps them."""
    def __init__(self, act, cid, label='⚔️ Open it', style=discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label[:80], style=style, custom_id=f'chal:{act}:{cid}'))
        self.act, self.cid = act, int(cid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'], match['cid'], label=getattr(item, 'label', None) or match['act'],
                   style=getattr(item, 'style', None) or discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        a, cid = self.act, self.cid
        if a == 'view':
            await show(interaction, cid)
        elif a == 'play':
            await play(interaction, cid)
        elif a == 'back':
            await back_flow(interaction, cid)
        elif a in ('accept', 'decline'):
            await act(interaction, cid, 'respond', "✓ You're in. Tap ▶ Play when you're ready." if a == 'accept' else 'Declined.',
                      accept=a == 'accept')
        elif a == 'join':
            await act(interaction, cid, 'join', "🪑 You took a seat. Tap ▶ Play when you're ready.")
        elif a in ('rematch', 'double'):
            await act(interaction, cid, 'rematch', '🔁 Rematch on. The others are invited.', double=a == 'double')
        elif a == 'end':
            await act(interaction, cid, 'end', 'Ended. Here are the results.')
        else:
            await act(interaction, cid, 'cancel', 'Called off. Nothing changed hands.')


class ChallengeAnswer(discord.ui.DynamicItem[discord.ui.Button],
                      template=r'chans:(?P<cid>[0-9]+):(?P<q>[0-9]+):(?P<choice>[a-z0-9]+)'):
    """An answer to question `q` of a challenge (or "see more")."""
    def __init__(self, cid, q, choice, label='A', style=discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label[:80], style=style, custom_id=f'chans:{cid}:{q}:{choice}'))
        self.cid, self.q, self.choice = int(cid), int(q), choice

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['cid'], match['q'], match['choice'], label=getattr(item, 'label', None) or match['choice'],
                   style=getattr(item, 'style', None) or discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        choice = int(self.choice) if self.choice.isdigit() else self.choice
        try:
            r = await api.post('/api/internal/challenges', {**discord_identity(interaction), 'action': 'answer',
                                                            'challenge_id': self.cid, 'choice': choice})
        except ApiError as e:
            await play(interaction, self.cid, edit=True)              # stale buttons: show where you really are
            await tell(interaction, _error(e, "That one's already answered."))
            return
        except Exception as e:
            await reply_failure(interaction, e, 'challenge')
            return
        await _show_question(interaction, r, True, None if choice == 'more' else r.get('answered'))


class ChallengeBackSelect(discord.ui.DynamicItem[discord.ui.Select], template=r'chback:(?P<cid>[0-9]+)'):
    """Backing, step one: who."""
    def __init__(self, cid, options=None):
        super().__init__(discord.ui.Select(custom_id=f'chback:{cid}', placeholder='Who do you think wins?',
                                           options=options or [discord.SelectOption(label='—', value='0')]))
        self.cid = int(cid)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['cid'], getattr(item, 'options', None))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = int(((interaction.data or {}).get('values') or ['0'])[0])
        view = discord.ui.View(timeout=None)
        for n in AMOUNTS:
            view.add_item(ChallengeBet(self.cid, uid, n))
        await interaction.edit_original_response(content='How much? (It comes back with more if they win.)', view=view)


class ChallengeBet(discord.ui.DynamicItem[discord.ui.Button], template=r'chbet:(?P<cid>[0-9]+):(?P<uid>[0-9]+):(?P<amount>[0-9]+)'):
    """Backing, step two: how much."""
    def __init__(self, cid, uid, amount):
        super().__init__(discord.ui.Button(label=f'{amount} 🍿', custom_id=f'chbet:{cid}:{uid}:{amount}'))
        self.cid, self.uid, self.amount = int(cid), int(uid), int(amount)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['cid'], match['uid'], match['amount'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await act(interaction, self.cid, 'back', f'🍿 You backed them with {self.amount} 🍿.', user_id=self.uid,
                  amount=self.amount)


class ChallengeGamesSelect(discord.ui.DynamicItem[discord.ui.Select], template=r'chgames:(?P<cid>[0-9]+):(?P<each>[0-9]+)'):
    """A gauntlet's creator picks its games instead of random ones (until anyone plays)."""
    def __init__(self, cid, each, options=None):
        options = options or [discord.SelectOption(label='—', value='random')]
        super().__init__(discord.ui.Select(custom_id=f'chgames:{cid}:{each}', placeholder='🧩 Pick the games instead (in this order)',
                                           min_values=min(2, len(options)), max_values=min(6, len(options)),
                                           options=options, row=4))
        self.cid, self.each = int(cid), int(each)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['cid'], match['each'], getattr(item, 'options', None))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        kinds = (interaction.data or {}).get('values') or []
        await act(interaction, self.cid, 'games', '🧩 Games set.',
                  rounds=[{'kind': k, 'questions': self.each} for k in kinds])


async def back_flow(interaction, cid):
    try:
        c = await api.get(f'/api/internal/challenges/{cid}', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'challenge')
        return
    if not c['you']['can_back']:
        await tell(interaction, "Backing is closed for this one (or you're playing in it, or you've backed someone).")
        return
    options = [discord.SelectOption(label=p['user']['name'][:100], value=str(p['user']['id']))
               for p in c['players'] if p['status'] in ('accepted', 'invited')][:25]
    view = discord.ui.View(timeout=None)
    view.add_item(ChallengeBackSelect(cid, options))
    await interaction.followup.send(f"Back a player in **{c['label']}**. You have {c['backing']['max']} 🍿 at most to put on one.",
                                    view=view, ephemeral=True)


# ─── /play challenge start and list, /play tournament list ────────────────────

async def versus_flow(interaction, kind, opponents, stake=None, seats=None, questions=None, deadline=None,
                      reveal=None, club_visible=None, post=None, games=None):
    """Make a challenge (after the command's defer): one game, a random one, or a
    gauntlet of `games` random ones (the creator can pick them instead, after)."""
    people = [{'discord_user_id': str(m.id), 'discord_name': getattr(m, 'display_name', None) or m.name}
              for m in opponents if m is not None and not getattr(m, 'bot', False) and m.id != interaction.user.id]
    body = {**discord_identity(interaction), 'action': 'create', 'kind': kind, 'opponents': people,
            'stake': stake if stake is not None else 0, 'seats': seats or 0, 'questions': questions or 5,
            'games': games or 3,
            'deadline': deadline or 'tonight', 'reveal': reveal or 'sealed',
            'visibility': 'players' if club_visible is False else 'club',
            'announce': None if post is None else ('now' if post else 'none')}
    try:
        c = await api.post('/api/internal/challenges', body)
    except ApiError as e:
        await interaction.followup.send(_error(e, api_failure(e, "Couldn't start that ({status}).")), ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/play challenge start')
        return
    note = '⚔️ Challenge sent' + (' and posted in the channel' if c.get('posted') else '') + ". Tap ▶ Play when you're ready."
    await interaction.followup.send(embed=embeds.challenge_embed(c, note), view=challenge_view(c), ephemeral=True)


async def list_flow(interaction, which, tournaments_only=False):
    """Your challenges and tournaments, or the club's open ones (only
    tournaments, for /play tournament list)."""
    from . import tournaments
    try:
        got = await api.get('/api/internal/challenges', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, '/play tournament list' if tournaments_only else '/play challenge list')
        return
    if not got['enabled']:
        await interaction.followup.send('Challenges are off in this club. An organizer can turn them on in Club settings → Games.',
                                        ephemeral=True)
        return
    rows = [] if tournaments_only else [c for c in got['challenges']
                                        if (c['you']['status'] if which == 'mine' else c['status'] == 'open')]
    cups = [t for t in got.get('tournaments') or [] if (t['you']['status'] if which == 'mine' else t['status'] in ('open', 'running'))]
    if not rows and not cups:
        start = '`/play tournament start`' if tournaments_only else '`/play challenge start` or `/play tournament start`'
        what = 'tournaments' if tournaments_only else 'challenges'
        await interaction.followup.send(f"Nothing here right now. Start one with {start}." if which == 'mine'
                                        else f"No open {what} in the club right now.", ephemeral=True)
        return
    lines, view = [], discord.ui.View(timeout=None)
    for t in cups[:5]:
        state = {'open': 'taking entries', 'running': 'under way', 'done': 'decided', 'cancelled': 'called off'}[t['status']]
        lines.append(f"🏆 **{t['format_label']}** · {t['games_line']} · {len([p for p in t['players'] if p['status'] == 'accepted'])} in · {state}")
    for c in rows[:10]:
        who = ', '.join(p['user']['name'] for p in c['players'] if p['status'] not in ('declined', 'expired'))
        state = {'open': 'open', 'done': 'decided', 'cancelled': 'called off'}[c['status']]
        what = f"🏆 {c['tournament']['match']}" if c.get('tournament') else f"{c['emoji']} **{c['label']}**"
        lines.append(f"{what} · {who} · {c['stake']} 🍿 · {state}")
    for t in cups[:5 if tournaments_only else 2]:
        view.add_item(tournaments.TournamentButton('view', t['id'], label=f"🏆 {t['format_label']}"[:80]))
    for c in rows[:5 - min(2, len(cups))]:
        view.add_item(ChallengeButton('view', c['id'], label=f"{c['emoji']} {c['label']}"[:80]))
    lines.append(f"\nYou have **{got['available']} 🍿** to put in.")
    await interaction.followup.send('\n'.join(lines), view=view, ephemeral=True)


# ─── Who should I challenge? (scout.py) ───────────────────────────────────────

async def scout_flow(interaction):
    """The club's challenge stats, yours, and the three best people to challenge
    — each with 🔥 Roast and ⚔️ Challenge (their suggested game and stake)."""
    try:
        got = await api.get('/api/internal/challenges/scout', **discord_identity(interaction))
    except ApiError as e:
        await tell(interaction, _error(e, api_failure(e, "Couldn't scout the club ({status}).")))
        return
    except Exception as e:
        await reply_failure(interaction, e, '/play challenge scout')
        return
    view = discord.ui.View(timeout=None)
    for n, p in enumerate(got['picks'][:3]):
        name = p['user']['name']
        if p['suggest']['kind']:
            view.add_item(ScoutButton('challenge', p['user']['id'], p['suggest']['kind'], p['suggest']['stake'],
                                      label=f"⚔️ {name}: {p['suggest']['label']}", row=n))
        if p['roastable']:
            view.add_item(ScoutButton('roast', p['user']['id'], label=f'🔥 Roast {name}', row=n))
    await interaction.followup.send(embed=embeds.scout_embed(got), view=view, ephemeral=True)


class ScoutButton(discord.ui.DynamicItem[discord.ui.Button],
                  template=r'scout:(?P<act>roast|again|challenge):(?P<uid>[0-9]+)(?::(?P<kind>[a-z_]+):(?P<stake>[0-9]+))?'):
    """🔥 a roast of their movie habits (again for another) · ⚔️ challenge them to the suggested game."""
    def __init__(self, act, uid, kind=None, stake=0, label='🔥 Roast', row=None):
        cid = f'scout:{act}:{uid}' + (f':{kind}:{stake}' if kind else '')
        super().__init__(discord.ui.Button(label=label[:80], custom_id=cid, row=row,
                                           style=discord.ButtonStyle.primary if act == 'challenge' else discord.ButtonStyle.secondary))
        self.act, self.uid, self.kind, self.stake = act, int(uid), kind, int(stake or 0)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'], match['uid'], match['kind'], match['stake'] or 0, label=getattr(item, 'label', None) or match['act'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        if self.act == 'challenge':
            body = {**discord_identity(interaction), 'action': 'create', 'kind': self.kind, 'opponents': [{'user_id': self.uid}],
                    'stake': self.stake, 'questions': 5, 'deadline': 'tonight', 'reveal': 'sealed', 'visibility': 'club'}
            try:
                c = await api.post('/api/internal/challenges', body)
            except ApiError as e:
                await tell(interaction, _error(e, api_failure(e, "Couldn't start that ({status}).")))
                return
            except Exception as e:
                await reply_failure(interaction, e, 'challenge')
                return
            await interaction.followup.send(embed=embeds.challenge_embed(c, "⚔️ Challenge sent. Tap ▶ Play when you're ready."),
                                            view=challenge_view(c), ephemeral=True)
            return
        try:
            r = await api.post(f'/api/internal/challenges/scout/{self.uid}/roast',
                               {**discord_identity(interaction), 'again': self.act == 'again'})
        except ApiError as e:
            await tell(interaction, _error(e, api_failure(e, "Couldn't roast them ({status}).")))
            return
        except Exception as e:
            await reply_failure(interaction, e, 'roast')
            return
        view = discord.ui.View(timeout=None)
        if r.get('more'):
            view.add_item(ScoutButton('again', self.uid, label='🔥 Another one'))
        await interaction.followup.send(f"🔥 {r['roast']}", view=view, ephemeral=True)


async def send_match(user, discord_user_id, cid):
    """DM a tournament match that's ready (members who chose Discord for challenge invites), with ▶ Play."""
    try:
        c = await api.get(f'/api/internal/challenges/{cid}', discord_user_id=str(discord_user_id))
    except Exception as e:
        print(f'tournament match {cid}: {e}')
        return
    if c['you']['can_play']:
        t = c.get('tournament') or {}
        await user.send(embed=embeds.challenge_embed(c, f"🏆 Your {t.get('match', 'match')} is ready. 30 seconds a question."),
                        view=challenge_view(c))


async def send_invite(user, discord_user_id, cid):
    """DM an invite (members who chose Discord for challenge invites) with Accept / Decline."""
    try:
        c = await api.get(f'/api/internal/challenges/{cid}', discord_user_id=str(discord_user_id))
    except Exception as e:
        print(f'challenge invite {cid}: {e}')
        return
    if c['you']['can_accept']:
        await user.send(embed=embeds.challenge_embed(c, '⚔️ You\'ve been challenged!'), view=challenge_view(c))


def post_content(data):
    """(embed, view) for a challenge's post in the channel (the shared-posts queue)."""
    return embeds.challenge_post_embed(data), post_view(data)


register(items=(ChallengeButton, ChallengeAnswer, ChallengeBackSelect, ChallengeBet, ChallengeGamesSelect, ScoutButton))

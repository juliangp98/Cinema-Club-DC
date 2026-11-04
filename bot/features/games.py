"""Games: trivia, bingo, quiz games, the /play tree (its challenge and tournament
groups call features/challenges.py and tournaments.py), /leaderboard, and game posts in
the channel.
"""

import discord
from discord import app_commands
from discord.ext import tasks
from api import ApiError
import embeds
from .shared import (SITE_URL, api, channel_for, client, club, connected_clubs, discord_identity, register,
                     reply_failure, use_club)
from . import challenges, polls, threads, tournaments      # used at call time, so the order they load in doesn't matter


LEADERBOARD_PERIODS = [app_commands.Choice(name=n, value=v) for v, n in (
    ('all', 'All time'), ('year', 'This year'), ('month', 'This month'))]


@client.tree.command(name='leaderboard', description='Kernel standings 🍿 — all time, this year or this month')
@app_commands.describe(period='Which standings (default: all time)')
@app_commands.choices(period=LEADERBOARD_PERIODS)
async def leaderboard(interaction: discord.Interaction, period: app_commands.Choice[str] = None):
    await interaction.response.defer()
    try:
        board = await api.get('/api/internal/leaderboard', group_id=club(), period=period.value if period else 'all')
    except ApiError:
        board = {}
    rows = board.get('rows') or []
    if not rows:
        await interaction.followup.send('No standings yet for that stretch — vote in a poll, or check in after a screening!')
        return
    lines = []
    for r in rows[:10]:                       # real places (ties share one); members on the site keep theirs
        parts = f" ({embeds.kernel_parts(r['breakdown'])})" if r.get('breakdown') else ''
        lines.append(f"{embeds.medal(r['place'], r['kernels'])} **{r['user']['name']}** — 🍿 {r['kernels']}{parts}")
    embed = discord.Embed(title=f"🍿 Kernel Leaderboard · {period.name if period else 'All time'}", description='\n'.join(lines),
                          colour=embeds.AMBER, url=f'{SITE_URL}/club?tab=leaderboard')
    if board.get('hidden'):
        n = board['hidden']
        embed.set_footer(text=f"+{n} member{'s' if n != 1 else ''} on the site — full standings at {SITE_URL}/club?tab=leaderboard")
    await interaction.followup.send(embed=embed)


# ─── Trivia (R10d) ────────────────────────────────────────────────────────────
# All off unless the club turned it on (a club admin, in Club settings on the
# site): the question of the day, its post in #movies (a second yes), and
# anytime questions. Answers are private.

TRIVIA_OFF_MSG = "Trivia is off for this club — a club admin can turn it on in Club settings on the site."


def trivia_more_view():
    view = discord.ui.View(timeout=None)
    view.add_item(TriviaMoreButton())
    return view


async def send_another(interaction):
    """An anytime question, privately (after a defer)."""
    try:
        q = await api.post('/api/internal/trivia/another', discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'trivia another')
        return
    await interaction.followup.send(embed=embeds.trivia_embed(q, title='🎲 Anytime trivia'), view=trivia_view(q),
                                    ephemeral=True)


class TriviaMoreButton(discord.ui.DynamicItem[discord.ui.Button], template=r'trivia:more'):
    """🎲 Another one — an anytime question (when the club has them on)."""
    def __init__(self):
        super().__init__(discord.ui.Button(label='🎲 Another one', style=discord.ButtonStyle.primary,
                                           custom_id='trivia:more'))

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls()

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_another(interaction)


def trivia_view(q):
    view = discord.ui.View(timeout=None)
    for i in range(len(q['options'])):
        view.add_item(TriviaButton(q['id'], i))
    return view


class TriviaButton(discord.ui.DynamicItem[discord.ui.Button], template=r'trivia:(?P<qid>[0-9]+):(?P<i>[0-3])'):
    """A / B / C / D under a trivia question: answers privately (one try)."""
    def __init__(self, question_id, choice):
        super().__init__(discord.ui.Button(label=embeds.LETTERS[choice], style=discord.ButtonStyle.secondary,
                                           custom_id=f'trivia:{question_id}:{choice}'))
        self.question_id, self.choice = question_id, choice

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match['qid']), int(match['i']))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            q = await api.post('/api/internal/trivia/answer', {**discord_identity(interaction),
                                                                'question_id': self.question_id, 'choice': self.choice})
        except Exception as e:
            await reply_failure(interaction, e, 'trivia answer')
            return
        if q.get('anytime_on'):
            await interaction.followup.send(embeds.trivia_result(q), view=trivia_more_view(), ephemeral=True)
        else:
            await interaction.followup.send(embeds.trivia_result(q), ephemeral=True)


async def trivia_flow(interaction):
    """🧠 Play trivia on /play, after a defer: today's question, then your
    waiting anytime one, then a new one."""
    try:
        t = await api.get('/api/internal/trivia/today', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'play trivia', 'Trivia lookup failed ({status}).')
        return
    daily = t.get('question')
    if not t.get('enabled'):
        await interaction.followup.send(TRIVIA_OFF_MSG, ephemeral=True)
    elif daily and not daily.get('mine'):                       # today's first
        await interaction.followup.send(embed=embeds.trivia_embed(daily, t.get('yesterday'), title='🧠 Question of the day'),
                                        view=trivia_view(daily), ephemeral=True)
    elif t.get('waiting'):                                      # then the one you asked for
        await interaction.followup.send(embed=embeds.trivia_embed(t['waiting'], title='🎲 Anytime trivia'),
                                        view=trivia_view(t['waiting']), ephemeral=True)
    elif t.get('anytime'):                                      # then a new one
        await send_another(interaction)
    elif daily:
        await interaction.followup.send(embeds.trivia_result(daily) + '\n-# Anytime questions are off for this club.',
                                        ephemeral=True)
    else:
        await interaction.followup.send('No trivia question today — check back tomorrow.', ephemeral=True)



# ─── Repertory bingo (R10e) ───────────────────────────────────────────────────

async def bingo_flow(interaction):
    """🎱 My bingo card on /play, after a defer."""
    try:
        b = await api.get('/api/internal/bingo', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'play bingo')
        return
    if not b.get('enabled'):
        await interaction.followup.send(
            "Bingo is off for this club — a club admin can turn it on in Club settings on the site.", ephemeral=True)
        return
    await interaction.followup.send(embed=embeds.bingo_embed(b), ephemeral=True)


# ─── Quiz games (R15) ─────────────────────────────────────────────────────────
# The backend runs the games (quizzes.py): each its own switch in Club
# settings. /play has a button for each one that's on; a round plays out
# privately with buttons — a start, an answer (and for higher or lower, the
# next call).

class QuizButton(discord.ui.DynamicItem[discord.ui.Button],
                 template=r'quiz:(?P<act>start|ans):(?P<ref>[a-z_]+|[0-9]+)(?::(?P<choice>[a-z0-9]+))?'):
    """A game's button on /play (quiz:start:<game>), and the answers under a round
    (quiz:ans:<round>:<choice>) — Before / After, or A–D."""
    def __init__(self, act, ref, choice=None, label=None, style=discord.ButtonStyle.secondary, row=None):
        cid = f'quiz:{act}:{ref}' + (f':{choice}' if choice is not None else '')
        super().__init__(discord.ui.Button(label=label or '▶ Play', style=style, custom_id=cid, row=row))
        self.act, self.ref, self.choice = act, ref, choice

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'], match['ref'], match['choice'], label=item.label, style=item.style)

    async def callback(self, interaction: discord.Interaction):
        if self.act == 'start':
            await interaction.response.defer(ephemeral=True, thinking=True)
            await quiz_start_flow(interaction, self.ref)
            return
        await interaction.response.defer()
        choice = int(self.choice) if str(self.choice).isdigit() else self.choice
        try:
            r = await api.post('/api/internal/quizzes', {**discord_identity(interaction), 'action': 'answer',
                                                         'round_id': int(self.ref), 'choice': choice})
        except Exception as e:
            await reply_failure(interaction, e, 'quiz game')
            return
        await interaction.edit_original_response(embed=embeds.quiz_round_embed(r), view=quiz_round_view(r))


async def quiz_start_flow(interaction, kind):
    """A new round of a quiz game, after a defer (its button, or /play solo)."""
    try:
        r = await api.post('/api/internal/quizzes', {**discord_identity(interaction), 'action': 'start', 'kind': kind})
    except Exception as e:
        await reply_failure(interaction, e, 'quiz game')
        return
    await interaction.followup.send(embed=embeds.quiz_round_embed(r), view=quiz_round_view(r), ephemeral=True)


def quiz_round_view(r):
    """A round's buttons: its answers while it's on; Play again once it's over."""
    view = discord.ui.View(timeout=None)
    if r['done']:
        view.add_item(QuizButton('start', r['kind'], label='🔁 Play again', style=discord.ButtonStyle.primary))
    elif r['kind'] == 'higher_lower':
        y = r['current']['year']
        view.add_item(QuizButton('ans', r['id'], 'before', label=f'⬅️ Before {y}'))
        view.add_item(QuizButton('ans', r['id'], 'after', label=f'After {y} ➡️'))
    else:
        for i in range(len(r['options'])):
            view.add_item(QuizButton('ans', r['id'], str(i), label=embeds.LETTERS[i]))
        if r.get('by_step') and r['step'] < r['steps']:
            view.add_item(QuizButton('ans', r['id'], 'more', label='🔍 Zoom out' if r['kind'] == 'still' else '📝 Another review',
                                     style=discord.ButtonStyle.primary))
    return view


async def kernels_flow(interaction):
    """🍿 My kernels on /play, after a defer: your total, where it came
    from, this week's allowance, and how to earn more."""
    try:
        k = await api.get('/api/internal/kernels', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, 'play kernels', 'Kernel lookup failed ({status}).')
        return
    await interaction.followup.send(embed=embeds.kernels_embed(k), ephemeral=True)


# ─── Play (R10): the one games hub ────────────────────────────────────────────
# Trivia, the bingo card, each quiz game the club has on, polls waiting for
# your vote, and your kernels (with how to earn) — each a button.

PLAY_BUTTONS = {'trivia': ('🧠 Play trivia', discord.ButtonStyle.primary),
                'bingo': ('🎱 My bingo card', discord.ButtonStyle.secondary),
                'kernels': ('🍿 My kernels', discord.ButtonStyle.secondary)}


class PlayButton(discord.ui.DynamicItem[discord.ui.Button], template=r'play:(?P<what>trivia|bingo|kernels)'):
    """🧠 Play trivia / 🎱 My bingo card / 🍿 My kernels under /play."""
    def __init__(self, what, row=None):
        label, style = PLAY_BUTTONS[what]
        super().__init__(discord.ui.Button(label=label, style=style, row=row, custom_id=f'play:{what}'))
        self.what = what

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['what'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        await {'trivia': trivia_flow, 'bingo': bingo_flow, 'kernels': kernels_flow}[self.what](interaction)


def play_view(p):
    view = discord.ui.View(timeout=None)
    if p.get('trivia'):
        view.add_item(PlayButton('trivia', row=0))
    if p.get('bingo'):
        view.add_item(PlayButton('bingo', row=0))
    view.add_item(PlayButton('kernels', row=0))
    for g in (p.get('games') or [])[:5]:
        view.add_item(QuizButton('start', g['kind'], label=f"{g['emoji']} {g['label']}", style=discord.ButtonStyle.primary, row=1))
    for poll in [x for x in p.get('polls', []) if not x['you_voted']][:3]:
        view.add_item(polls.VoteButton('open', poll['id'], label=f"🗳️ Vote: {poll['title']}", row=2))
    ch = p.get('challenges') or {}
    for t in (ch.get('tournaments') or [])[:2]:
        view.add_item(tournaments.TournamentButton('view', t['id'], label=f"🏆 {t['title']}", row=3))
    for c in (ch.get('invites', []) + ch.get('your_turn', []))[:4 - min(2, len(ch.get('tournaments') or []))]:
        view.add_item(challenges.ChallengeButton('view', c['id'], label=f"⚔️ {c['game']}", row=3))
    view.add_item(discord.ui.Button(label='Play on the site', url=f'{SITE_URL}/play', row=2))
    return view


# /play is a tree: today (the hub), solo, kernels, then challenge and
# tournament, each a group. Every subcommand carries only its own options.
# The quiz games are the backend's quizzes.GAMES (a test keeps the two lists
# the same).
QUIZ_GAMES = (('higher_lower', '↕️ Higher or lower'), ('who_said', '🗣️ Who said it'), ('still', '🖼️ Guess the still'),
              ('reviews', '📝 Guess from the reviews'), ('emoji', '🎭 Emoji plot'))
SOLO_GAMES = [app_commands.Choice(name=n, value=v) for v, n in (
    ('trivia', "🧠 Trivia: today's question"), ('bingo', '🎱 My bingo card'), *QUIZ_GAMES)]
V = challenges                     # /play challenge (features/challenges.py)
T = tournaments                    # /play tournament (features/tournaments.py)

play_group = app_commands.Group(name='play', description='Games and kernels: today, solo games, challenges, tournaments')
challenge_group = app_commands.Group(name='challenge', description='Challenge members: start one, yours and the club\'s, '
                                     'who to challenge', parent=play_group)
tournament_group = app_commands.Group(name='tournament', description='Tournaments for 3 or more: start one, yours and '
                                      'the club\'s', parent=play_group)


@play_group.command(name='today', description="What's waiting on you, and every game a tap away")
async def play_today(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        p = await api.get('/api/internal/play', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, '/play today')
        return
    await interaction.followup.send(embed=embeds.play_embed(p), view=play_view(p), ephemeral=True)


@play_group.command(name='solo', description='Play on your own: trivia, your bingo card or a quiz game')
@app_commands.describe(game='Which one')
@app_commands.choices(game=SOLO_GAMES)
async def play_solo(interaction: discord.Interaction, game: app_commands.Choice[str]):
    await interaction.response.defer(ephemeral=True, thinking=True)
    flows = {'trivia': trivia_flow, 'bingo': bingo_flow}
    await (flows[game.value](interaction) if game.value in flows else quiz_start_flow(interaction, game.value))


@play_group.command(name='kernels', description="Your kernels: where they came from, and what's left to earn today")
async def play_kernels(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await kernels_flow(interaction)


@challenge_group.command(name='start', description='Challenge members: one game, a random one, or a gauntlet')
@app_commands.describe(
    game='The game: one, 🎲 a random one, or a 🧩 gauntlet of several',
    opponent='Who you challenge', opponent2='Another player', opponent3='Another player',
    stake='Kernels each player puts in the pot (0 = for bragging rights)',
    seats='Open seats anyone in the club can take',
    questions='Questions in each game, 1–10 (Higher or lower is one run)',
    games='Gauntlet: how many games, 2–6 (random, or pick them after)',
    closes='When it closes (default: tonight)',
    scores='Show scores as each player finishes, or only once everyone has',
    club_visible='The club can see it and back players (default: yes)',
    post='Post it in the channel (default: your sharing setting)')
@app_commands.rename(club_visible='club')
@app_commands.choices(game=V.VERSUS_GAMES, closes=V.DEADLINES, scores=V.REVEALS)
async def challenge_start(interaction: discord.Interaction, game: app_commands.Choice[str],
                          opponent: discord.Member = None, opponent2: discord.Member = None,
                          opponent3: discord.Member = None, stake: app_commands.Range[int, 0, 50] = None,
                          seats: app_commands.Range[int, 0, 6] = None, questions: app_commands.Range[int, 1, 10] = None,
                          games: app_commands.Range[int, 2, 6] = None, closes: app_commands.Choice[str] = None,
                          scores: app_commands.Choice[str] = None, club_visible: bool = None, post: bool = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await V.versus_flow(interaction, game.value, [opponent, opponent2, opponent3], stake, seats, questions,
                        closes.value if closes else None, scores.value if scores else None, club_visible, post, games)


@challenge_group.command(name='list', description="Your challenges and tournaments, or the club's open ones")
@app_commands.describe(which="Yours (default) or the club's open ones")
@app_commands.choices(which=V.LISTS)
async def challenge_list(interaction: discord.Interaction, which: app_commands.Choice[str] = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await V.list_flow(interaction, which.value if which else 'mine')


@challenge_group.command(name='scout', description='Who should you challenge? Their numbers next to yours, and a roast')
async def challenge_scout(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await V.scout_flow(interaction)


@tournament_group.command(name='start', description='A tournament for 3 or more: double elimination, or round robin + a final')
@app_commands.describe(
    fmt='Double elimination (3–16 players) or round robin + a final (3–6)',
    game='The game every match plays: one, 🎲 random (drawn for each match), or a 🧩 gauntlet',
    player='Who you invite', player2='Another player', player3='Another player', player4='Another player',
    player5='Another player',
    entry='Kernels each player puts in the prize pot (0 = for bragging rights)',
    seats='Open seats anyone in the club can take',
    questions='Questions in each game, 1–10 (Higher or lower is one run)',
    games='Gauntlet: how many games, 2–6',
    closes='When entries close (default: tonight)',
    match_time='How long each match stays open (default: a day)',
    prizes='Winner takes all, or 60 / 30 / 10',
    scores="Show each match's scores as each player finishes, or only once both have",
    club_visible='The club can see it and back players (default: yes)',
    post='Post it in the channel (default: your sharing setting)')
@app_commands.rename(fmt='format', club_visible='club')
@app_commands.choices(fmt=T.TOURNAMENT_FORMATS, game=V.VERSUS_GAMES, closes=V.DEADLINES,
                      match_time=T.TOURNAMENT_MATCH_TIMES, prizes=T.TOURNAMENT_PAYOUTS, scores=V.REVEALS)
async def tournament_start(interaction: discord.Interaction, fmt: app_commands.Choice[str],
                           game: app_commands.Choice[str] = None, player: discord.Member = None,
                           player2: discord.Member = None, player3: discord.Member = None,
                           player4: discord.Member = None, player5: discord.Member = None,
                           entry: app_commands.Range[int, 0, 50] = None, seats: app_commands.Range[int, 0, 8] = None,
                           questions: app_commands.Range[int, 1, 10] = None, games: app_commands.Range[int, 2, 6] = None,
                           closes: app_commands.Choice[str] = None, match_time: app_commands.Choice[str] = None,
                           prizes: app_commands.Choice[str] = None, scores: app_commands.Choice[str] = None,
                           club_visible: bool = None, post: bool = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await T.tournament_flow(interaction, fmt.value, game.value if game else None,
                            [player, player2, player3, player4, player5], entry, seats, questions, games,
                            closes.value if closes else None, match_time.value if match_time else None,
                            prizes.value if prizes else None, scores.value if scores else None, club_visible, post)


@tournament_group.command(name='list', description="Your tournaments, or the club's open and running ones")
@app_commands.describe(which="Yours (default) or the club's open ones")
@app_commands.choices(which=V.LISTS)
async def tournament_list(interaction: discord.Interaction, which: app_commands.Choice[str] = None):
    await interaction.response.defer(ephemeral=True, thinking=True)
    await V.list_flow(interaction, which.value if which else 'mine', tournaments_only=True)


client.tree.add_command(play_group)


# ─── Game posts in #movies (R14) ───────────────────────────────────────────────
# The backend decides what's due (game_posts.py: the question of the day, the
# month's card, wins — each Never / Ask first / Always in Club settings); this
# posts what's approved, and gives admins Post / Skip / change buttons in a DM.

def game_post_message(post):
    """(embed, view) for a game post in #movies."""
    if post['kind'] == 'trivia':
        return (embeds.trivia_embed(post['question'], post.get('yesterday'), title='🧠 Question of the day'),
                trivia_view(post['question']))
    if post['kind'] == 'bingo_card':
        return embeds.bingo_card_post_embed(post), None
    return embeds.bingo_win_embed(post), None


@tasks.loop(minutes=1)
async def games_loop():
    """Each connected club's game posts, in its own server."""
    for group_id, _ in connected_clubs():
        channel = channel_for(group_id)
        if channel is None:
            continue
        use_club(group_id)
        try:
            posts = (await api.get('/api/internal/games/posts', group_id=group_id)).get('posts') or []
        except Exception as e:
            print(f'games_loop (club {group_id}): {e}')
            continue
        for post in posts:
            try:
                embed, view = game_post_message(post)
                msg = await channel.send(embed=embed, view=view, allowed_mentions=threads.NO_PINGS)
                await api.post('/api/internal/games/posted', {'post_id': post['id'], 'message_id': str(msg.id)})
            except Exception as e:
                print(f"games_loop: post {post.get('id')} failed: {e}")


@games_loop.before_loop
async def before_games():
    await client.wait_until_ready()


REVIEW_ACTIONS = {'trivia': ('post', 'another', 'skip'), 'bingo_card': ('post', 'reshuffle', 'skip')}
REVIEW_LABELS = {'post': ('Post it', discord.ButtonStyle.success), 'skip': ('Skip', discord.ButtonStyle.secondary),
                 'unskip': ('Post it after all', discord.ButtonStyle.success),
                 'another': ('Try another', discord.ButtonStyle.primary),
                 'reshuffle': ('Reshuffle', discord.ButtonStyle.primary)}


def review_view(post):
    view = discord.ui.View(timeout=None)
    if post.get('status') == 'skipped' and post.get('until'):         # changed your mind (R15)
        view.add_item(GameReviewButton('unskip', post['id']))
    if post.get('status') == 'waiting':
        for action in REVIEW_ACTIONS.get(post['kind'], ()):
            if action == 'another' and not post.get('can_swap'):
                continue
            view.add_item(GameReviewButton(action, post['id']))
    return view


async def send_review(user, discord_user_id, post_id):
    """DM an admin a waiting game post exactly as it'll look, with the buttons."""
    try:
        post = await api.get(f'/api/internal/games/post/{post_id}', discord_user_id=str(discord_user_id))
    except Exception as e:
        print(f'review {post_id}: {e}')
        return
    embed, _ = game_post_message(post)
    await user.send(embeds.review_note(post), embed=embed, view=review_view(post))


class GameReviewButton(discord.ui.DynamicItem[discord.ui.Button], template=r'game:(?P<action>post|skip|another|reshuffle|unskip):(?P<pid>[0-9]+)'):
    """Post it / Try another / Reshuffle / Skip — and, once skipped, Post it
    after all — under a game post in an organizer's or admin's DM."""
    def __init__(self, action, post_id):
        label, style = REVIEW_LABELS[action]
        super().__init__(discord.ui.Button(label=label, style=style, custom_id=f'game:{action}:{post_id}'))
        self.action, self.post_id = action, post_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['action'], int(match['pid']))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            post = await api.post(f'/api/internal/games/post/{self.post_id}',
                                  {**discord_identity(interaction), 'action': 'post' if self.action == 'unskip' else self.action})
        except Exception as e:
            await reply_failure(interaction, e, 'game review')
            return
        embed, _ = game_post_message(post)
        await interaction.edit_original_response(content=embeds.review_note(post, post.get('error')), embed=embed,
                                                 view=review_view(post))


register(items=(TriviaMoreButton, TriviaButton, QuizButton, PlayButton, GameReviewButton,), loops=(games_loop,))

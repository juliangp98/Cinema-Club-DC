"""Games: trivia, bingo, quiz games, the /play hub, /leaderboard, and game posts in
the channel.
"""

import discord
from discord.ext import tasks
from api import ApiError
import embeds
from .shared import DEFAULT_GROUP_ID, SITE_URL, api, client, discord_identity, movies_channel, register, reply_failure
from . import polls, threads      # used at call time, so the order they load in doesn't matter


@client.tree.command(name='leaderboard', description='Season kernel standings 🍿')
async def leaderboard(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        board = await api.get('/api/internal/leaderboard', group_id=DEFAULT_GROUP_ID)
    except ApiError:
        board = {}
    rows = board.get('rows') or []
    if not rows:
        await interaction.followup.send('No standings yet — vote in a poll!')
        return
    lines = []
    for r in rows[:10]:                       # real places (ties share one); members on the site keep theirs
        parts = f" ({embeds.kernel_parts(r['breakdown'])})" if r.get('breakdown') else ''
        lines.append(f"{embeds.medal(r['place'], r['kernels'])} **{r['user']['name']}** — 🍿 {r['kernels']}{parts}")
    embed = discord.Embed(title='🍿 Kernel Leaderboard', description='\n'.join(lines),
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
            payload = {'action': 'start', 'kind': self.ref}
        else:
            await interaction.response.defer()
            choice = int(self.choice) if str(self.choice).isdigit() else self.choice
            payload = {'action': 'answer', 'round_id': int(self.ref), 'choice': choice}
        try:
            r = await api.post('/api/internal/quizzes', {**discord_identity(interaction), **payload})
        except Exception as e:
            await reply_failure(interaction, e, 'quiz game')
            return
        if self.act == 'start':
            await interaction.followup.send(embed=embeds.quiz_round_embed(r), view=quiz_round_view(r), ephemeral=True)
        else:
            await interaction.edit_original_response(embed=embeds.quiz_round_embed(r), view=quiz_round_view(r))


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
    view.add_item(discord.ui.Button(label='Play on the site', url=f'{SITE_URL}/play', row=2))
    return view


@client.tree.command(name='play', description='Games and kernels: trivia, bingo, quiz games, polls to vote in, your kernels')
async def play_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    try:
        p = await api.get('/api/internal/play', **discord_identity(interaction))
    except Exception as e:
        await reply_failure(interaction, e, '/play')
        return
    await interaction.followup.send(embed=embeds.play_embed(p), view=play_view(p), ephemeral=True)


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
    channel = movies_channel()
    if channel is None:
        return
    try:
        posts = (await api.get('/api/internal/games/posts', group_id=DEFAULT_GROUP_ID)).get('posts') or []
    except Exception as e:
        print(f'games_loop: {e}')
        return
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
        post = await api.get(f'/api/internal/games/post/{post_id}', discord_user_id=str(discord_user_id),
                             group_id=DEFAULT_GROUP_ID)
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

"""/poll: list, vote or make (action:).
"""

import json
import discord
from discord import app_commands
from api import ApiError
import embeds
from .shared import SITE_URL, api, api_failure, client, club, discord_identity, register, reply_failure, tell


# ─── /poll vote ───────────────────────────────────────────────────────────────
# A private, paged ballot: one category per page. Every pick saves straight to
# the backend (the same vote rules as the site), so members can stop and finish
# later, here or on the web. All state lives in the component ids and the
# database, so ballots keep working across bot restarts.
# Component ids: vote:<b|s>:<action>:<poll>:<category index>:<arg>:<page>

VOTE_ID = r'vote:(?P<kind>[bs]):(?P<act>[a-z]+):(?P<poll>[0-9]+):(?P<idx>[0-9]+):(?P<arg>[0-9]+):(?P<page>[0-9]+)'
ORDINALS = {1: '1st', 2: '2nd', 3: '3rd'}


def _vote_id(kind, act, poll, idx=0, arg=0, page=0):
    return f'vote:{kind}:{act}:{poll}:{idx}:{arg}:{page}'


class VoteButton(discord.ui.DynamicItem[discord.ui.Button], template=VOTE_ID.replace('[bs]', 'b')):
    def __init__(self, act, poll, idx=0, arg=0, page=0, label='Vote', row=None,
                 style=discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label[:80], style=style, row=row,
                                           custom_id=_vote_id('b', act, poll, idx, arg, page)))
        self.act, self.poll, self.idx, self.arg, self.page = act, poll, idx, arg, page

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'], int(match['poll']), int(match['idx']), int(match['arg']), int(match['page']))

    async def callback(self, interaction: discord.Interaction):
        await handle_vote(interaction, self.act, self.poll, self.idx, self.arg, self.page, [])


class VoteSelect(discord.ui.DynamicItem[discord.ui.Select], template=VOTE_ID.replace('[bs]', 's')):
    def __init__(self, act, poll, idx=0, arg=0, page=0, options=None, placeholder=None, row=None, disabled=False):
        super().__init__(discord.ui.Select(custom_id=_vote_id('s', act, poll, idx, arg, page),
                                           options=options or [], placeholder=(placeholder or '')[:150] or None,
                                           row=row, disabled=disabled))
        self.act, self.poll, self.idx, self.arg, self.page = act, poll, idx, arg, page

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['act'], int(match['poll']), int(match['idx']), int(match['arg']), int(match['page']))

    async def callback(self, interaction: discord.Interaction):
        values = (interaction.data or {}).get('values') or []
        await handle_vote(interaction, self.act, self.poll, self.idx, self.arg, self.page, values)


def vote_open_view(polls):
    """Vote buttons for a list of open polls ({id, title}); each opens a private ballot."""
    view = discord.ui.View(timeout=None)
    for p in polls[:5]:
        label = 'Vote' if len(polls) == 1 else f"Vote · {p['title']}"
        view.add_item(VoteButton('open', p['id'], label=label, style=discord.ButtonStyle.primary))
    return view


def next_unanswered(ballot, after):
    """Index of the next category without a pick after `after` (wrapping), or None."""
    cats = ballot['categories']
    for step in range(1, len(cats) + 1):
        i = (after + step) % len(cats)
        if not cats[i]['picks']:
            return i
    return None


def ballot_view(ballot, idx, page=0):
    poll, cats = ballot['poll'], ballot['categories']
    pid, cat, mode, is_open = poll['id'], cats[idx], poll['scoring_mode'], poll['status'] == 'open'
    size = 24 if mode == 'ranked' else 25            # ranked dropdowns also carry "— none —"
    pages = max(1, -(-len(cat['options']) // size))
    page = min(page, pages - 1)
    chunk = cat['options'][page * size:(page + 1) * size]
    of_pages = f' ({page + 1}/{pages})' if pages > 1 else ''
    view, row = discord.ui.View(timeout=None), 0

    if is_open and chunk:
        if mode == 'ranked':
            by_rank = {p['rank']: p['option_id'] for p in cat['picks']}
            for r in range(1, poll.get('ranked_picks', 3) + 1):
                opts = [discord.SelectOption(label='— none —', value='0')] + [
                    discord.SelectOption(label=o['text'][:100], value=str(o['id']), default=by_rank.get(r) == o['id'])
                    for o in chunk]
                view.add_item(VoteSelect('rank', pid, idx, r, page, opts, f'{ORDINALS.get(r, r)} choice{of_pages}', row))
                row += 1
        else:
            mine = cat['picks'][0] if cat['picks'] else None
            opts = [discord.SelectOption(label=o['text'][:100], value=str(o['id']),
                                         default=bool(mine) and mine['option_id'] == o['id']) for o in chunk]
            view.add_item(VoteSelect('pick', pid, idx, 0, page, opts, f'Pick a nominee{of_pages}', row))
            row += 1
            if mode == 'confidence':
                hints = {1: ' — total guess', 10: ' — sure thing'}
                opts = [discord.SelectOption(label=f'{n} 🍿{hints.get(n, "")}', value=str(n),
                                             default=bool(mine) and mine['confidence'] == n) for n in range(1, 11)]
                view.add_item(VoteSelect('conf', pid, idx, 0, page, opts,
                                         'How sure are you?' if mine else 'Pick a nominee first, then your stake',
                                         row, disabled=not mine))
                row += 1

    if len(cats) > 1:
        start = max(0, min(idx - 12, len(cats) - 25))      # a 25-category window around this one
        opts = [discord.SelectOption(label=f"{i + 1}. {c['title']}"[:100], value=str(i), default=i == idx,
                                     emoji='✅' if c['picks'] else None)
                for i, c in enumerate(cats[start:start + 25], start)]
        view.add_item(VoteSelect('jump', pid, idx, 0, 0, opts, 'Jump to a category', row))
        row += 1
        view.add_item(VoteButton('nav', pid, (idx - 1) % len(cats), 0, label='◀ Prev', row=row))
        view.add_item(VoteButton('nav', pid, (idx + 1) % len(cats), 1, label='Next ▶', row=row))
        nxt = next_unanswered(ballot, idx) if is_open else None
        if nxt is not None and nxt != idx:
            view.add_item(VoteButton('nav', pid, nxt, 2, label='⏭ Next unanswered', row=row,
                                     style=discord.ButtonStyle.primary))
    if is_open and cat['picks'] and mode != 'ranked':
        view.add_item(VoteButton('clear', pid, idx, label='Clear pick', row=row))
    if is_open and pages > 1:
        nxt_page = (page + 1) % pages
        view.add_item(VoteButton('page', pid, idx, 0, nxt_page, row=row,
                                 label=f'More nominees ({nxt_page * size + 1}–{min((nxt_page + 1) * size, len(cat["options"]))})'))
    return view


def _vote_error(err):
    body = err.body or ''
    if 'not_member' in body:
        return "That poll belongs to a group you're not in."
    if 'poll_not_found' in body:
        return 'That poll was deleted.'
    return api_failure(err, "Couldn't load that poll ({status}).")


async def handle_vote(interaction, act, pid, idx, arg, page, values):
    """Every ballot click: open, navigate, pick, stake, rank, clear."""
    opening = act == 'open'
    if interaction.response.is_done():             # /poll vote answered already, while it found the poll
        pass
    elif opening:
        await interaction.response.defer(ephemeral=True, thinking=True)
    else:
        await interaction.response.defer()

    async def show(ballot, i, pg=0, note=None):
        kwargs = {'embed': embeds.ballot_embed(ballot, i, note), 'view': ballot_view(ballot, i, pg)}
        if opening:
            await interaction.followup.send(ephemeral=True, **kwargs)
        else:
            await interaction.edit_original_response(**kwargs)

    ident = discord_identity(interaction)
    path = f'/api/internal/polls/{pid}'
    try:
        ballot = await api.get(f'{path}/ballot', **ident)
        cats = ballot['categories']
        if not cats:
            await interaction.followup.send('That poll has no categories yet.', ephemeral=True)
            return
        if opening:
            first = next_unanswered(ballot, -1) if ballot['poll']['status'] == 'open' else None
            note = ('Welcome back — picking up where you left off.'
                    if first is not None and ballot['answered'] else None)
            await show(ballot, first or 0, note=note)
            return
        idx = min(idx, len(cats) - 1)
        if act == 'jump':
            idx = int(values[0]) if values else idx
        if act in ('nav', 'jump', 'page'):
            await show(ballot, idx, page if act == 'page' else 0)
            return

        cat, mode = cats[idx], ballot['poll']['scoring_mode']
        mine = cat['picks'][0] if cat['picks'] else None
        votes, clear, note = [], [], None
        if act == 'pick' and values:
            stake = mine['confidence'] if mine else 1
            votes = [{'category_id': cat['id'], 'option_id': int(values[0]), 'confidence': stake}]
        elif act == 'conf' and values and mine:
            votes = [{'category_id': cat['id'], 'option_id': mine['option_id'], 'confidence': int(values[0])}]
        elif act == 'rank' and values:
            by_rank = {p['rank']: p['option_id'] for p in cat['picks']}
            choice = int(values[0])
            by_rank.pop(arg, None)
            if choice:
                by_rank = {r: o for r, o in by_rank.items() if o != choice}   # moving it, not duplicating
                by_rank[arg] = choice
            votes = [{'category_id': cat['id'], 'option_id': o, 'rank': r} for r, o in sorted(by_rank.items())]
            clear = [] if votes else [cat['id']]
        elif act == 'clear':
            clear = [cat['id']]
        else:
            await show(ballot, idx, page)
            return
        ballot = await api.post(f'{path}/vote', {**ident, 'votes': votes, 'clear': clear})
    except ApiError as e:
        if e.status == 409:              # voting closed mid-ballot: show it read-only
            try:
                await show(json.loads(e.body), min(idx, len(json.loads(e.body)['categories']) - 1),
                           note='🔒 Voting just closed — your earlier picks stand.')
                return
            except Exception:
                pass
        await interaction.followup.send(_vote_error(e), ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/poll vote')
        return

    # Single-pick polls move on to the next unanswered category; confidence and
    # ranked polls stay so the page can be finished (stake, other ranks).
    if act == 'pick' and mode in ('single', 'none'):
        nxt = next_unanswered(ballot, idx)
        if nxt is None:
            note = f"🎉 All {len(ballot['categories'])} categories answered! Jump back to change any pick."
        else:
            names = {o['id']: o['text'] for o in cat['options']}
            note = f"✅ Saved **{names.get(int(values[0]), 'your pick')}** for {cat['title']}."
            idx, page = nxt, 0
    elif act == 'pick' and mode == 'confidence':
        note = '✅ Saved — now set how sure you are.' if not mine else '✅ Pick changed (same stake).'
    elif act == 'clear':
        note = 'Pick cleared.'
    elif ballot['answered'] == len(ballot['categories']) and act in ('conf', 'rank'):
        note = f"🎉 All {len(ballot['categories'])} categories answered!"
    await show(ballot, idx, page, note)


async def vote_poll_autocomplete(interaction: discord.Interaction, current: str):
    try:
        polls = await api.get('/api/internal/polls', group_id=club(), include_closed=1)
    except Exception:
        return []
    icon = {'open': '🗳️', 'closed': '🔒', 'scored': '🏆'}
    state = {'open': 'open', 'closed': 'closed', 'scored': 'results'}
    current = current.lower()
    return [app_commands.Choice(name=f"{icon.get(p['status'], '')} {p['title']} ({state.get(p['status'], '')})"[:100],
                                value=str(p['id']))
            for p in polls if current in p['title'].lower()][:25]


# ─── /poll make (R6a) ─────────────────────────────────────────────────────────
# Organizers describe a poll; the site's shared AI drafts it. The preview is
# private: "Create now" makes it (announced in #movies like any new poll), or
# "Open in editor" continues on the site.

def draft_embed(d):
    embed = discord.Embed(title=f"📝 Draft: {d['title']}"[:256], colour=embeds.AMBER,
                          description=(d.get('description') or '')[:1000] or None)
    for c in d['categories'][:8]:
        opts = [o['text'] for o in c['options']]
        shown = ', '.join(opts[:8]) + (f" +{len(opts) - 8}" if len(opts) > 8 else '')
        embed.add_field(name=c['title'][:256], value=shown[:1024], inline=False)
    if len(d['categories']) > 8:
        embed.add_field(name='…', value=f"+{len(d['categories']) - 8} more categories", inline=False)
    mode = {'none': 'Plain vote', 'single': 'Predictions · 1 🍿 per correct', 'ranked': 'Ranked top 3',
            'confidence': 'Predictions · confidence-weighted'}.get(d.get('scoring_mode'), '')
    foot = [mode, 'Based on all films' if d.get('scope') == 'all' else 'Based on local showings', 'Draft — not posted yet']
    if d.get('notes'):
        foot.insert(0, f"⚠️ {d['notes']}")
    embed.set_footer(text=' · '.join(f for f in foot if f)[:2048])
    return embed


class DraftCreateButton(discord.ui.DynamicItem[discord.ui.Button], template=r'polldraft:create:(?P<id>[0-9]+)'):
    def __init__(self, draft_id):
        super().__init__(discord.ui.Button(label='✓ Create now', style=discord.ButtonStyle.success,
                                           custom_id=f'polldraft:create:{draft_id}'))
        self.draft_id = draft_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match['id']))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            poll = await api.post(f'/api/internal/poll-drafts/{self.draft_id}/create', discord_identity(interaction))
        except ApiError as e:
            body = e.body or ''
            msg = ("Already created — see it with `/poll`." if 'already_created' in body
                   else "Only organizers and admins can create polls." if e.status == 403
                   else api_failure(e, "Couldn't create it ({status})."))
            await interaction.followup.send(msg, ephemeral=True)
            return
        await interaction.followup.send(
            f"✓ **{poll['title']}** is open — it'll be announced in the club's channel in a moment. {SITE_URL}/polls/{poll['id']}",
            ephemeral=True)


async def poll_make(interaction: discord.Interaction, request: str, based_on: app_commands.Choice[str] = None):
    """Describe a poll; the AI drafts it for you to create or edit (organizers)."""
    await interaction.response.defer(ephemeral=True, thinking=True)
    try:
        d = await api.post('/api/internal/polls/draft', {**discord_identity(interaction), 'prompt': request,
                                                         'scope': based_on.value if based_on else 'playing'})
    except ApiError as e:
        try:
            msg = json.loads(e.body or '{}').get('error')
        except ValueError:
            msg = None
        if e.status == 403:
            msg = 'Only organizers and admins can make polls — ask an admin for the Organizer role.'
        await interaction.followup.send(msg if e.status == 403 else api_failure(e, msg or "Couldn't draft that ({status})."),
                                        ephemeral=True)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/poll make')
        return
    view = discord.ui.View(timeout=None)
    view.add_item(DraftCreateButton(d['id']))
    view.add_item(discord.ui.Button(label='Open in editor', url=f"{SITE_URL}/polls/new?draft={d['id']}"))
    await interaction.followup.send(embed=draft_embed(d), view=view, ephemeral=True)


async def poll_list(interaction: discord.Interaction):
    """Open polls and predictions, posted here with a Vote button for each."""
    await interaction.response.defer()
    try:
        open_polls = await api.get('/api/internal/polls', group_id=club())
    except Exception as e:
        await reply_failure(interaction, e, '/poll list', ephemeral=False)
        return
    if not open_polls:
        await interaction.followup.send(f'No open polls right now. See past results and start one: {SITE_URL}/play#polls')
        return
    lines = [f"🗳️ **[{p['title']}](<{SITE_URL}/polls/{p['id']}>)** — {embeds.plural(p.get('category_count', 0), 'category', 'categories')}"
             for p in open_polls[:10]]
    lines.append('Tap **Vote** for a private ballot (or use `/poll action:Vote`).')
    await interaction.followup.send('\n'.join(lines), view=vote_open_view(open_polls))


async def poll_vote(interaction: discord.Interaction, poll: str = None):
    """Vote in a club poll — a private ballot, one category at a time."""
    if poll is None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            open_polls = await api.get('/api/internal/polls', group_id=club())
        except Exception as e:
            await reply_failure(interaction, e, '/poll vote')
            return
        if not open_polls:
            await tell(interaction, 'No open polls right now. Pick one in `/poll poll:` to look back at recent results.')
            return
        if len(open_polls) > 1:
            await tell(interaction, 'Which poll?', view=vote_open_view(open_polls))
            return
        poll = str(open_polls[0]['id'])
    if not poll.isdigit():
        await tell(interaction, 'Pick a poll from the list.')
        return
    await handle_vote(interaction, 'open', int(poll), 0, 0, 0, [])


POLL_ACTIONS = [app_commands.Choice(name=n, value=v) for v, n in (
    ('list', 'Open polls (posted here)'), ('vote', 'Vote — a private ballot'),
    ('make', 'Make one — describe it and the AI drafts it (organizers)'))]
POLL_BASES = [app_commands.Choice(name='Local showings', value='playing'), app_commands.Choice(name='All films', value='all')]


@client.tree.command(name='poll', description="The club's polls: what's open, your ballot, or make one")
@app_commands.describe(action='What to do (default: vote if you pick a poll, make if you describe one, else list)',
                       poll='Vote: which poll (open ones first; closed ones show your picks and results)',
                       request='Make: e.g. "spookiest Halloween movies" or "the 99th Oscar winners"',
                       based_on="Make: local showings (films at the club's theatres) or all films (default: local)")
@app_commands.choices(action=POLL_ACTIONS, based_on=POLL_BASES)
@app_commands.autocomplete(poll=vote_poll_autocomplete)
async def poll_cmd(interaction: discord.Interaction, action: app_commands.Choice[str] = None, poll: str = None,
                   request: app_commands.Range[str, 3, 300] = None, based_on: app_commands.Choice[str] = None):
    what = action.value if action else 'make' if request else 'vote' if poll else 'list'
    if what == 'make' and not request:
        await interaction.response.send_message('Describe the poll: fill in **request** — e.g. "spookiest Halloween movies".',
                                                ephemeral=True)
    elif what == 'make':
        await poll_make(interaction, request, based_on)
    elif what == 'vote':
        await poll_vote(interaction, poll)
    else:
        await poll_list(interaction)


register(items=(VoteButton, VoteSelect, DraftCreateButton,))

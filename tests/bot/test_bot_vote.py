"""/vote ballots: picking a poll, single-pick, confidence and ranked
ballots built from dropdowns and buttons (within Discord's limits), scored
results, closing mid-ballot, who may vote, and the #movies poll posts."""
import asyncio
import json
import re
import types

import discord
import pytest

from helpers import patch_bot_api, setup_db

VEE, WES, LONE = 9101, 9102, 9109


@pytest.fixture
def polls():
    """Vee and Wes in the server's club (Lone only elsewhere). Open polls:
    Quick picks (single, 3 categories), Oscar stakes (confidence, one category
    with 30 nominees), Top 3 of the year (ranked); Last year is scored (Vee
    picked wrong)."""
    from app import app, db, User, GroupMembership, Poll, PollCategory, PollOption, PollVote, Group
    setup_db()
    with app.app_context():
        Poll.query.filter_by(group_id=1).delete()                                    # a clean slate in the server's club
        db.session.commit()
        for did, name in (('9101', 'Vee'), ('9102', 'Wes')):
            u = User(discord_user_id=did, name=name, is_active=True)
            db.session.add(u)
            db.session.flush()
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
        lone = User(discord_user_id='9109', name='Lone', is_active=True)
        other = Group(name='Elsewhere', slug='elsewhere-9', is_public=False)
        db.session.add_all([lone, other])
        db.session.flush()
        db.session.add(GroupMembership(user_id=lone.id, group_id=other.id, status='active'))
        creator = User.query.filter_by(discord_user_id='9101').first()

        def poll(title, mode, cats, status='open'):
            p = Poll(group_id=1, created_by=creator.id, title=title, scoring_mode=mode, status=status)
            db.session.add(p)
            db.session.flush()
            for i, (ct, opts) in enumerate(cats):
                c = PollCategory(poll_id=p.id, title=ct, sort_order=i)
                db.session.add(c)
                db.session.flush()
                for j, t in enumerate(opts):
                    db.session.add(PollOption(category_id=c.id, text=t, sort_order=j))
            db.session.flush()
            return p
        poll('Quick picks', 'single', [('Best Picture', ['SIRÂT', 'HAMNET', 'SINNERS']), ('Best Score', ['A', 'B']), ('Best Short', ['X', 'Y'])])
        poll('Oscar stakes', 'confidence', [('Best Actress', ['Rose', 'Jessie']), ('Everything', [f'Nominee {n}' for n in range(1, 31)])])
        poll('Top 3 of the year', 'ranked', [('Films', ['One', 'Two', 'Three', 'Four'])])
        done = poll('Last year', 'single', [('Best Picture', ['Anora', 'Brutalist'])], status='scored')
        cat = done.categories[0]
        cat.correct_option_id = cat.options[0].id
        db.session.add(PollVote(category_id=cat.id, user_id=creator.id, option_id=cat.options[1].id))
        db.session.commit()
        pid = {p.title: p.id for p in Poll.query.filter_by(group_id=1)}
    return types.SimpleNamespace(bot=patch_bot_api(), pid=pid, state={})


class Interaction:
    """`log` items: (kind, ephemeral, content, embed, view)."""
    def __init__(self, uid, values=None):
        self.log, self.guild_id, self.channel_id = [], None, 1
        self.data = {'values': values} if values is not None else {}
        self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', mention=f'<@{uid}>',
                                          display_avatar=types.SimpleNamespace(url='https://cdn/x.png'))
        outer = self

        class R:
            async def defer(self, ephemeral=False, thinking=False, **k):
                outer.log.append(('defer', ephemeral))

            async def send_message(self, content=None, ephemeral=False, view=None, embed=None, **k):
                outer.log.append(('reply', ephemeral, content, embed, view))

        class F:
            async def send(self, content=None, ephemeral=False, embed=None, view=None, **k):
                outer.log.append(('followup', ephemeral, content, embed, view))
        self.response, self.followup = R(), F()

    async def edit_original_response(self, embed=None, view=None, **k):
        self.log.append(('edit', None, None, embed, view))

    @property
    def last(self):
        return self.log[-1]


def items(view):
    return [getattr(c, 'item', c) for c in view.children]


def find(w, view, act, **want):
    for it in items(view):
        m = re.fullmatch(w.bot.VOTE_ID, it.custom_id or '')
        if m and m['act'] == act and all(int(m[k]) == v for k, v in want.items()):
            return it
    return None


def run(coro):
    return asyncio.run(coro)


def vote(w, uid, title=None):
    """/vote [poll]; the ballot it opens becomes this member's message."""
    it = Interaction(uid)
    run(w.bot.vote.callback(it, **({'poll': str(w.pid[title])} if title else {})))
    if len(it.last) > 3 and it.last[3] is not None:
        w.state[uid] = it.last[3:5]
    return it


def click(w, uid, item, values=None):
    """Rebuild the component from its custom id (as after a restart) and fire it."""
    m = re.fullmatch(w.bot.VOTE_ID, item.custom_id)
    cls = w.bot.VoteSelect if m['kind'] == 's' else w.bot.VoteButton
    it = Interaction(uid, values)

    async def go():
        comp = await cls.from_custom_id(None, None, m)
        await comp.callback(it)
    run(go())
    if it.last[3] is not None:
        w.state[uid] = it.last[3:5]
    return it


def desc(w, uid):
    return w.state[uid][0].description


def view(w, uid):
    return w.state[uid][1]


def pick(w, uid, index, act='pick', **want):
    sel = find(w, view(w, uid), act, **want)
    return click(w, uid, sel, [sel.options[index].value])


def limits_ok(v):
    """Discord's limits: 5 rows of up to 5 (a dropdown fills its row), ids
    ≤ 100, 1–25 options with labels ≤ 100, button labels ≤ 80."""
    rows = {}
    for it in items(v):
        rows.setdefault(it.row, []).append(it)
        if len(it.custom_id) > 100:
            return False
        if isinstance(it, discord.ui.Select):
            if not 1 <= len(it.options) <= 25 or any(len(o.label) > 100 for o in it.options) or len(rows[it.row]) > 1:
                return False
        elif len(it.label) > 80:
            return False
    return len(rows) <= 5 and all(len(r) <= 5 for r in rows.values())


# ── picking a poll ──

def test_vote_without_a_poll_asks_which(polls):
    kind, eph, content, _, v = vote(polls, VEE).last
    assert eph and content == 'Which poll?'
    assert sorted(c.item.custom_id for c in v.children) == sorted(
        f'vote:b:open:{polls.pid[t]}:0:0:0' for t in ('Quick picks', 'Oscar stakes', 'Top 3 of the year'))


def test_polls_lists_open_polls_with_vote_buttons(polls):
    it = Interaction(VEE)
    run(polls.bot.polls.callback(it))
    assert len(it.last[4].children) == 3 and 'Tap **Vote**' in it.last[2]


def test_autocomplete_lists_open_polls_then_results(polls):
    choices = run(polls.bot.vote_poll_autocomplete(Interaction(VEE), ''))
    assert len(choices) == 4 and choices[-1].name.startswith('🏆')


# ── single pick ──

def test_a_ballot_opens_privately_on_the_first_category(polls):
    kind, eph, _, emb, v = vote(polls, VEE, 'Quick picks').last
    assert kind == 'followup' and eph and '### Best Picture' in emb.description and '0/3 answered' in emb.description
    assert 'Pick yours to see how everyone voted' in emb.description
    assert [o.label for o in find(polls, v, 'pick').options] == ['SIRÂT', 'HAMNET', 'SINNERS']
    assert find(polls, v, 'jump') and all(find(polls, v, 'nav', arg=a) for a in (0, 1, 2))   # jump, Prev/Next/Next unanswered
    assert limits_ok(v)


@pytest.fixture
def answered(polls):
    """Vee answered all of Quick picks: HAMNET, A, Y."""
    vote(polls, VEE, 'Quick picks')
    pick(polls, VEE, 1)
    polls.after_first = desc(polls, VEE)
    pick(polls, VEE, 0)
    pick(polls, VEE, 1)
    return polls


def test_a_pick_saves_and_moves_on(answered):
    d = answered.after_first
    assert '### Best Score' in d and '1/3 answered' in d and 'Saved **HAMNET** for Best Picture' in d
    assert 'All 3 categories answered' in desc(answered, VEE) and '3/3 answered' in desc(answered, VEE)
    jump = find(answered, view(answered, VEE), 'jump')
    assert all(str(o.emoji) == '✅' for o in jump.options)                                     # answered categories marked


def test_after_picking_the_split_shows(answered):
    click(answered, VEE, find(answered, view(answered, VEE), 'jump'), ['0'])
    assert 'How everyone voted' in desc(answered, VEE) and '👉 HAMNET — 100%' in desc(answered, VEE)
    click(answered, VEE, find(answered, view(answered, VEE), 'clear'))
    d = desc(answered, VEE)
    assert 'No pick yet' in d and 'Pick cleared' in d and '2/3 answered' in d


def test_each_member_has_their_own_ballot(answered):
    d = vote(answered, WES, 'Quick picks').last[3].description
    assert '0/3 answered' in d and 'How everyone voted' not in d                              # no split before they pick


# ── confidence ──

def test_a_confidence_ballot(polls):
    vote(polls, VEE, 'Oscar stakes')
    assert find(polls, view(polls, VEE), 'conf').disabled                                     # the stake waits for a pick
    pick(polls, VEE, 0)
    d = desc(polls, VEE)
    assert '### Best Actress' in d and 'now set how sure' in d and not find(polls, view(polls, VEE), 'conf').disabled
    click(polls, VEE, find(polls, view(polls, VEE), 'conf'), ['8'])
    assert '**Rose** · 8 🍿' in desc(polls, VEE)
    pick(polls, VEE, 1)
    assert '**Jessie** · 8 🍿' in desc(polls, VEE) and 'same stake' in desc(polls, VEE)     # a new pick keeps the stake


def test_long_categories_page_through_their_nominees(polls):
    vote(polls, VEE, 'Oscar stakes')
    pick(polls, VEE, 0)
    click(polls, VEE, find(polls, view(polls, VEE), 'nav', arg=1))
    more = find(polls, view(polls, VEE), 'page')
    assert len(find(polls, view(polls, VEE), 'pick').options) == 25 and more and '26–30' in more.label
    assert limits_ok(view(polls, VEE))
    click(polls, VEE, more)
    assert [o.label for o in find(polls, view(polls, VEE), 'pick').options] == [f'Nominee {n}' for n in range(26, 31)]
    pick(polls, VEE, 2)
    d = desc(polls, VEE)
    assert '**Nominee 28** · 1 🍿' in d and '2/2 answered' in d


# ── ranked ──

def test_a_ranked_ballot(polls):
    vote(polls, VEE, 'Top 3 of the year')
    r1, r2, r3 = (find(polls, view(polls, VEE), 'rank', arg=r) for r in (1, 2, 3))
    assert r1 and r2 and r3 and r1.options[0].label == '— none —' and len(r1.options) == 5 and limits_ok(view(polls, VEE))
    val = {o.label: o.value for o in r1.options}
    click(polls, VEE, r1, [val['One']])
    click(polls, VEE, find(polls, view(polls, VEE), 'rank', arg=2), [val['Two']])
    assert '**1.** One  **2.** Two' in desc(polls, VEE)
    click(polls, VEE, find(polls, view(polls, VEE), 'rank', arg=2), [val['One']])
    d = desc(polls, VEE)
    assert '**2.** One' in d and 'Two' not in d.split('Your pick:')[1].split('\n')[0]        # moved, no duplicates
    click(polls, VEE, find(polls, view(polls, VEE), 'rank', arg=2), ['0'])
    assert 'No pick yet' in desc(polls, VEE)                                                  # "— none —" clears it


# ── results, closing, access ──

def test_a_scored_poll_shows_results(polls):
    emb, v = vote(polls, VEE, 'Last year').last[3:5]
    assert '🏆 Anora' in emb.description and '❌ Brutalist' in emb.description
    assert emb.fields and '#1 of 1' in emb.fields[0].value and not find(polls, v, 'pick')


def test_voting_closed_mid_ballot(polls):
    from app import app, db, Poll
    vote(polls, VEE, 'Quick picks')
    with app.app_context():
        db.session.get(Poll, polls.pid['Quick picks']).status = 'closed'
        db.session.commit()
    pick(polls, VEE, 0)
    assert 'Voting just closed' in desc(polls, VEE) and not find(polls, view(polls, VEE), 'pick')


def test_who_may_vote(polls):
    assert "group you're not in" in (vote(polls, LONE, 'Oscar stakes').last[2] or '')
    assert vote(polls, 5555, 'Oscar stakes').last[2] == polls.bot.NO_ACCOUNT_MSG             # no account


# ── #movies posts ──

def test_poll_posts_in_movies(polls, monkeypatch):
    from app import app, db, ActivityEvent
    sent = []

    class Channel:
        async def send(self, content=None, embed=None, view=None, **k):
            sent.append((content, embed, view))
    monkeypatch.setattr(polls.bot, 'movies_channel', lambda: Channel())
    top = [{'name': 'Vee', 'discord_user_id': '9101', 'kernels': 9, 'correct': 2},
           {'name': 'Ann', 'discord_user_id': None, 'kernels': 3, 'correct': 1}]
    with app.app_context():
        for kind, gid in (('poll_opened', 1), ('poll_scored', 1), ('poll_opened', 999)):
            db.session.add(ActivityEvent(kind=kind, payload_json=json.dumps({
                'poll_id': polls.pid['Oscar stakes'], 'group_id': gid, 'title': 'Oscar stakes', 'scoring_mode': 'confidence',
                'categories': 2, 'creator': 'Vee', 'voters': 2, 'top': top})))
        db.session.commit()
    run(polls.bot.announce_loop.coro())
    assert len(sent) == 2                                                                     # only this server's polls
    assert 'New poll: Oscar stakes' in sent[0][1].title
    assert sent[0][2] and items(sent[0][2])[0].custom_id == f"vote:b:open:{polls.pid['Oscar stakes']}:0:0:0"
    assert '🥇 <@9101> — **9 🍿**' in sent[1][1].description and '🥈 **Ann**' in sent[1][1].description   # mention if linked
    with app.app_context():
        assert ActivityEvent.query.filter(ActivityEvent.kind.like('poll_%'), ActivityEvent.announced_at.is_(None)).count() == 0

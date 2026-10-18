"""R6a.1 in the bot: it reports who's in the server, and members who aren't
are only ever counted — in /whosgoing, /rsvp, the leaderboard, thread cards,
invites, poll results and the digest."""
import asyncio
import types
from datetime import datetime, timedelta

import pytest

from helpers import patch_bot_api, setup_db


def member(uid, is_bot=False, gid=900):
    return types.SimpleNamespace(id=uid, bot=is_bot, guild=types.SimpleNamespace(id=gid))


class Guild:
    def __init__(self, members, chunked=True, fail=False):
        self.id, self.members, self.chunked, self.fail, self.chunk_calls = 900, members, chunked, fail, 0

    async def chunk(self):
        self.chunk_calls += 1
        if self.fail:
            raise RuntimeError('gateway hiccup')
        self.chunked = True


class Interaction:
    """Records ('send', content, embed, view, ephemeral)."""
    def __init__(self, uid, guild_id=None):
        self.log, self.guild_id, self.channel_id = [], guild_id, 1
        self.user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'u{uid}', display_avatar=None, mention=f'<@{uid}>')
        outer = self

        class R:
            async def defer(self, **k):
                outer.log.append(('defer', k))

        class F:
            async def send(self, content=None, embed=None, view=None, ephemeral=False, **k):
                outer.log.append(('send', content, embed, view, ephemeral))
        self.response, self.followup = R(), F()

    @property
    def last(self):
        return self.log[-1]


def run(coro):
    return asyncio.run(coro)


def present():
    from app import app, DiscordServerMember
    with app.app_context():
        return sorted(r.discord_user_id for r in DiscordServerMember.query)


@pytest.fixture
def bot():
    """The club: Ana (8801, in the server), Bo (site only), Cy (8803, linked
    but not in the server), all going to OMEGA FILM (Bo said so first). Bo
    won a scored poll (first on the leaderboard), Ana second."""
    from app import app, db, User, GroupMembership, Showtime, Movie, Theatre, RSVP, Poll, PollCategory, PollOption, PollVote
    setup_db()
    with app.app_context():
        th = Theatre.query.filter_by(slug='afi').first()
        ana = User(email='ana@b6d.test', name='Ana', is_active=True, discord_user_id='8801')
        bo = User(email='bo@b6d.test', name='Bo', is_active=True)
        cy = User(email='cy@b6d.test', name='Cy', is_active=True, discord_user_id='8803')
        db.session.add_all([ana, bo, cy])
        db.session.flush()
        m = Movie(title='OMEGA FILM')
        db.session.add(m)
        db.session.flush()
        s = Showtime(movie_id=m.id, theatre_id=th.id,
                     start_time=(datetime.now() + timedelta(days=2)).replace(hour=20, minute=0, second=0, microsecond=0))
        db.session.add(s)
        db.session.flush()
        for u in (bo, ana, cy):                                # Bo first: the trailblazer kernels are his too
            db.session.add(GroupMembership(user_id=u.id, group_id=1, status='active'))
            db.session.add(RSVP(user_id=u.id, showtime_id=s.id, group_id=1, status='going'))
        p = Poll(group_id=1, created_by=ana.id, title='Omega poll', poll_type='prediction', scoring_mode='single', status='scored')
        db.session.add(p)
        db.session.flush()
        cat = PollCategory(poll_id=p.id, title='Winner')
        db.session.add(cat)
        db.session.flush()
        right, wrong = PollOption(category_id=cat.id, text='Right'), PollOption(category_id=cat.id, text='Wrong')
        db.session.add_all([right, wrong])
        db.session.flush()
        cat.correct_option_id = right.id
        db.session.add_all([PollVote(category_id=cat.id, user_id=bo.id, option_id=right.id, confidence=1),
                            PollVote(category_id=cat.id, user_id=ana.id, option_id=wrong.id, confidence=1)])
        db.session.commit()
        sid = s.id
    b = patch_bot_api()
    b.test_showtime = sid
    b.guild = Guild([member(8801), member(4242, is_bot=True), member(5555)])
    b.movies_channel = lambda: types.SimpleNamespace(guild=b.guild)
    return b


@pytest.fixture
def synced(bot):
    run(bot.sync_members())
    return bot


def test_the_bot_reports_whos_in_the_server(bot):
    assert bot.intents.members is True
    run(bot.sync_members())
    assert present() == ['5555', '8801']                                       # bots left out


def test_joins_and_leaves_are_reported(synced):
    run(synced.member_changed(member(8803), 'joined'))
    assert '8803' in present()
    run(synced.member_changed(member(8803), 'left'))
    run(synced.member_changed(member(7777, gid=123), 'joined'))                 # another server: ignored
    assert present() == ['5555', '8801']


def test_an_incomplete_member_list_is_never_sent(synced):
    synced.guild = Guild([member(8801)], chunked=False, fail=True)
    run(synced.sync_members())
    assert synced.guild.chunk_calls == 1 and present() == ['5555', '8801']    # couldn't fetch: nothing sent
    synced.guild = Guild([member(8801)], chunked=False)
    run(synced.sync_members())
    assert synced.guild.chunk_calls == 1 and present() == ['8801']            # fetched first when it can be


def test_whos_going_and_rsvp_count_the_rest(synced):
    it = Interaction(8801)
    run(synced.showtimes.callback(it, days=7, going=True))
    text = ' '.join(f.value for f in it.last[2].fields)
    assert 'Ana' in text and '+2 on the site' in text and 'Bo' not in text and 'Cy' not in text
    it = Interaction(8801, guild_id=900)
    run(synced.rsvp.callback(it, showtime=str(synced.test_showtime), status=None))
    reply = next(x[1] for x in it.log if x[0] == 'send' and 'Going (' in (x[1] or ''))
    assert 'Going (3): Ana · +2 on the site' in reply


def test_the_leaderboard_keeps_real_places(synced):
    it = Interaction(8801)
    run(synced.leaderboard.callback(it))
    e = it.last[2]
    assert 'Bo' not in e.description and '🥇' not in e.description       # Bo (first, site only) left out
    assert 'Ana' in e.description and 'on the site' in e.footer.text


CARD = {'title': 'X', 'start_time': '2026-10-10T20:00:00', 'theatre': 'AFI', 'site_path': '/x',
        'going': [{'name': 'Ana', 'discord_user_id': '8801'}], 'going_more': 2, 'maybe': [], 'maybe_more': 1}


def test_thread_cards_invites_and_poll_results():
    import embeds
    d = embeds.thread_card_embed(CARD).description
    assert '**Going:** <@8801> · +2 on the site' in d and '**Maybe:** 1 on the site' in d
    invite = {'by': None, 'note': None, 'card': {**CARD, 'going': [{'name': 'Ana'}]}, 'started': False}
    assert embeds.invite_message(invite) == "🍿 Who's in?"                            # from someone who left: unsigned
    assert '**Going:** Ana · +2 on the site' in embeds.invite_embed(invite).description
    res = embeds.poll_results_embed({'poll_id': 1, 'title': 'P', 'voters': 2,
                                     'top': [{'name': None, 'kernels': 3, 'correct': 3}, {'name': 'Ana', 'kernels': 1, 'correct': 1}]})
    assert res.description.startswith('🥇 *a member on the site*') and '🥈 **Ana**' in res.description


DIGEST = {'group_name': 'C', 'plans': [], 'rare': [], 'opening': [], 'last_chance': [], 'open_polls': [],
          'whos_going': [{'title': 'X', 'start_time': '2026-10-10T20:00:00', 'theatre': 'AFI', 'going': ['Ana'], 'going_more': 2}],
          'recap': {'poll': {'title': 'P', 'winner': None, 'kernels': 4}},
          'watchlist': [{'title': 'Y', 'start_time': '2026-10-10T20:00:00', 'theatre': 'AFI', 'planned': False, 'more': 2,
                         'quiet_ids': [5, 6], 'watchers': [{'watchlist_id': 1, 'name': 'Ana', 'discord_user_id': '8801', 'fresh': True}]}]}


def test_the_digest_counts_the_rest_and_pings_only_who_said_yes():
    import embeds
    content, embed, tagged, _ = embeds.digest_message(DIGEST, tag_watchers=True)
    fields = {f.name: f.value for f in embed.fields}
    assert 'Ana · +2 on the site' in fields["🎟️ Who's going"] and '<@8801> · +2 on the site' in fields['👀 On your watchlists']
    assert content.count('<@') == 1 and sorted(tagged) == [1, 5, 6]          # quiet ones still marked (for the email)
    assert 'P: a member on the site (4 🍿)' in fields['📊 Last week']
    assert embeds.digest_message(DIGEST)[2] == []                              # a manual digest marks nobody

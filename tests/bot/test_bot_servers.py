"""The bot in several servers: each command is for its server's club (an
unconnected server gets only the public commands; in DMs, a menu when you're in
more than one connected club), each loop posts in each club's own channel,
/setup connects a server, and the bot keeps each server's member list."""
import asyncio
import types

import discord
import pytest

from helpers import H, client, patch_bot, patch_bot_api, setup_db

HOME, OTHER = 900, 777


class Channel:
    def __init__(self, cid, guild):
        self.id, self.guild, self.name, self.sent = cid, guild, f'ch{cid}', []
        self.mention = f'<#{cid}>'

    async def send(self, content=None, embed=None, view=None, **k):
        self.sent.append((content, embed))
        return types.SimpleNamespace(id=len(self.sent), jump_url='https://discord.com/x')

    def permissions_for(self, me):
        return discord.Permissions.all()


class Response:
    def __init__(self, log):
        self.log = log

    async def send_message(self, content=None, ephemeral=False, view=None, embed=None, **k):
        self.log.append(('reply', content, view, ephemeral))

    async def defer(self, ephemeral=False, **k):
        self.log.append(('defer', ephemeral))

    def is_done(self):
        return bool(self.log)


class Followup:
    def __init__(self, log):
        self.log = log

    async def send(self, content=None, embed=None, ephemeral=False, **k):
        self.log.append(('followup', content, embed, ephemeral))


def interaction(uid, guild_id, command='rsvp', kind=discord.InteractionType.application_command, channel=None):
    log = []
    user = types.SimpleNamespace(id=uid, name=f'u{uid}', display_name=f'U{uid}', display_avatar=None, mention=f'<@{uid}>')
    guild = types.SimpleNamespace(id=guild_id, name='Film Friends', member_count=3) if guild_id else None
    return types.SimpleNamespace(
        user=user, guild_id=guild_id, guild=guild, id=uid * 10, data={'name': command}, type=kind, log=log,
        response=Response(log), followup=Followup(log), namespace=types.SimpleNamespace(), command=None,
        channel=channel or Channel(7001, guild), channel_id=7001,
        permissions=discord.Permissions(manage_guild=True))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def two():
    """Club 1 (home: server 900, channel 901) and club 2 "Film Friends" (server 777,
    channel 7001, connected with /setup). Hal (802) is in both servers; Fay (803)
    only in Film Friends'."""
    from app import app, db, Group, GroupMembership, User
    setup_db()
    bot = patch_bot_api()
    with app.app_context():
        g2 = Group(name='Film Friends', slug='film-friends', is_public=False, theatres='afi,suns')
        db.session.add(g2)
        db.session.flush()
        us = {n: User(name=n, email=f'{n.lower()}@bs.test', is_active=True, discord_user_id=d)
              for n, d in (('Hal', '802'), ('Fay', '803'))}
        db.session.add_all(us.values())
        db.session.flush()
        db.session.add(GroupMembership(user_id=us['Hal'].id, group_id=1, status='active'))
        for n, role in (('Hal', 'member'), ('Fay', 'admin')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g2.id, status='active', role=role))
        db.session.commit()
        g2_id, fay = g2.id, us['Fay'].id
    code = client(fay).post('/api/groups/film-friends/discord/code').json['code']
    r = client().post('/api/internal/servers/setup', headers=H, json={
        'guild_id': str(OTHER), 'guild_name': 'Film Friends', 'channel_id': '7001', 'channel_name': 'films',
        'can_manage': True, 'code': code})
    assert r.status_code == 200
    home_guild = types.SimpleNamespace(id=HOME, name='Cinema Club', member_count=40)
    other_guild = types.SimpleNamespace(id=OTHER, name='Film Friends', member_count=3)
    home_ch, other_ch = Channel(901, home_guild), Channel(7001, other_guild)
    patch_bot(movies_channel=lambda: home_ch)
    from features import shared
    run(shared.refresh_servers())
    bot.client.get_channel = lambda cid: {901: home_ch, 7001: other_ch}.get(cid)
    for gid, ids in ((HOME, ['802']), (OTHER, ['802', '803'])):
        client().post('/api/internal/discord/members', headers=H,
                      json={'full': True, 'ids': ids, 'guild_id': str(gid), 'home': gid == HOME})
    return types.SimpleNamespace(bot=bot, G2=g2_id, home_ch=home_ch, other_ch=other_ch, fay=fay)


async def check_then_club(it):
    from features import servers, shared
    ok = await servers.interaction_check(it)
    return ok, shared.club()


def test_each_server_is_its_clubs(two):
    from features import shared
    assert run(check_then_club(interaction(803, OTHER))) == (True, two.G2)
    assert run(check_then_club(interaction(802, HOME))) == (True, 1)       # home: before it registers, via its channel
    assert shared.channel_for(two.G2) is two.other_ch and shared.channel_for(1) is two.home_ch
    assert sorted(g for g, _ in shared.connected_clubs()) == sorted([1, two.G2])
    ident = shared.discord_identity(interaction(803, OTHER))
    assert ident['group_id'] == two.G2 and ident['create'] == '1' and ident['guild_id'] == str(OTHER)


def test_an_unconnected_server_gets_only_the_public_commands(two):
    from features import shared
    it = interaction(803, 4040, 'rsvp')
    assert run(check_then_club(it)) == (False, None)
    assert it.log[0][1] == shared.NOT_CONNECTED_MSG and it.log[0][3] is True
    assert run(check_then_club(interaction(803, 4040, 'showtimes')))[0] is True
    assert shared.discord_identity(interaction(803, 4040))['create'] == '0'        # never makes accounts there


def test_dms_ask_which_club_when_there_are_several(two):
    from features import servers, shared
    assert run(check_then_club(interaction(803, None))) == (True, two.G2)         # one connected club: no question
    it = interaction(802, None, 'leaderboard')
    ran = []

    class Command:
        qualified_name = 'leaderboard'

        async def _invoke_with_namespace(self, picked, namespace):
            ran.append((shared.club(), picked.user.id))
    it.command = Command()
    assert run(servers.interaction_check(it)) is False
    kind, text, view, _ = it.log[0]
    assert text == 'Which club is this for?' and sorted(o.value for o in view.select.options) == sorted(['1', str(two.G2)])

    async def pick(who, value):
        view.select._values = [value]
        await view.picked(interaction(who, None))
    run(pick(803, str(two.G2)))
    assert ran == []                                                                # someone else's menu
    run(pick(802, str(two.G2)))
    assert ran == [(two.G2, 802)]
    assert shared.dm_club(802) == two.G2                                            # buttons in the DM follow the pick


def test_drops_post_only_where_that_theatre_is_on(two):
    from app import app, db, ScrapeEvent, Theatre
    import json
    client().post('/api/internal/alerts', headers=H, json={'group_id': two.G2, 'theatre_slug': 'afi', 'action': 'enable'})
    with app.app_context():
        afi = Theatre.query.filter_by(slug='afi').first()
        db.session.add(ScrapeEvent(theatre_id=afi.id, event_type='new_drop', payload_json=json.dumps(
            {'theatre_slug': 'afi', 'theatre_name': 'AFI Silver', 'new_showtime_count': 12})))
        db.session.commit()
    run(two.bot.announce_loop.coro())
    assert len(two.other_ch.sent) == 1 and 'AFI Silver' in two.other_ch.sent[0][1].title
    assert two.home_ch.sent == []                                                  # club 1 didn't turn AFI on


def test_setup_connects_a_server(two):
    from app import app, db, Group, GroupMembership
    with app.app_context():
        g3 = Group(name='Third Club', slug='third-club', is_public=False)
        db.session.add(g3)
        db.session.flush()
        db.session.add(GroupMembership(user_id=two.fay, group_id=g3.id, status='active', role='admin'))
        db.session.commit()
    code = client(two.fay).post('/api/groups/third-club/discord/code').json['code']
    guild = types.SimpleNamespace(id=555, name='Third', member_count=5, me=None)
    it = interaction(803, 555, 'setup', channel=Channel(5001, guild))
    it.guild = guild
    run(two.bot.setup_cmd.callback(it, code))
    _, _, embed, ephemeral = it.log[-1]
    assert ephemeral and embed.title == '✅ Connected to Third Club'
    from features import shared
    assert shared.club_for_guild(555) is not None                                   # the map knows it right away
    bad = interaction(803, 556, 'setup', channel=Channel(5002, guild))
    run(two.bot.setup_cmd.callback(bad, 'WRONGCODE'))
    assert "That code doesn't work" in bad.log[-1][1]


def test_each_servers_members_are_kept(two):
    from app import app, db, DiscordServerMember
    home_members = [types.SimpleNamespace(id=802, bot=False), types.SimpleNamespace(id=1, bot=True)]
    other_members = [types.SimpleNamespace(id=803, bot=False)]
    guilds = {HOME: types.SimpleNamespace(id=HOME, chunked=True, members=home_members),
              OTHER: types.SimpleNamespace(id=OTHER, chunked=True, members=other_members)}
    two.bot.client.get_guild = lambda gid: guilds.get(gid)
    run(two.bot.sync_members())
    with app.app_context():
        got = sorted((m.guild_id, m.discord_user_id) for m in DiscordServerMember.query)
    assert got == [(str(OTHER), '803'), (str(HOME), '802')]                        # Hal left Film Friends' server


def test_joining_and_leaving_servers(two):
    from app import app, db, DiscordServer
    system = Channel(6001, None)
    guild = types.SimpleNamespace(id=4040, name='New Place', system_channel=system, me=None)
    run(two.bot.on_guild_join(guild))
    assert system.sent and 'connect me to your club' in system.sent[0][1].description
    with app.app_context():
        assert db.session.get(DiscordServer, '4040').group_id is None               # there, not connected
    run(two.bot.on_guild_remove(types.SimpleNamespace(id=OTHER)))
    from features import shared
    with app.app_context():
        assert db.session.get(DiscordServer, str(OTHER)) is None
    assert shared.club_for_guild(OTHER) is None


def test_the_digest_posts_only_for_clubs_that_have_it_on(two):
    from features import alerts, shared
    shared.use_club(two.G2)                                                          # new clubs start with it off
    assert run(alerts.post_digest(two.other_ch, tag_watchers=True)) == alerts.DIGEST_OFF
    assert two.other_ch.sent == []
    shared.use_club(1)                                                               # the home club always had it
    assert run(alerts.post_digest(two.home_ch)) is True and len(two.home_ch.sent) == 1

    shared.use_club(two.G2)                                                          # what interaction_check sets
    it = interaction(803, OTHER, 'digest')
    run(two.bot.digest_now.callback(it, False))
    assert it.log[-1][1] == shared.DIGEST_OFF_MSG and it.channel.sent == []         # posting: off
    it = interaction(803, OTHER, 'digest')
    run(two.bot.digest_now.callback(it, True))
    _, _, embed, ephemeral = it.log[-1]
    assert ephemeral and embed.title.startswith('🍿 This week at the movies')       # a preview still works

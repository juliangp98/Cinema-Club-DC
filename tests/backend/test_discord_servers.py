"""The bot in other servers: one server, one club. A club admin makes a code
in Club settings and a server admin runs /setup with it; the home server
registers itself; everything about "who's in the server" is per club; quotes
are the classics plus each club's own; the AI models change only from home."""
import datetime

import pytest

from helpers import H, client, setup_db

HOME_GUILD, OTHER_GUILD = '900', '777'


def bot_post(path, **body):
    return client().post(path, json=body, headers=H)


def setup(code, guild=OTHER_GUILD, can_manage=True, channel='7001'):
    return bot_post('/api/internal/servers/setup', guild_id=guild, guild_name='Film Friends', channel_id=channel,
                    channel_name='films', can_manage=can_manage, code=code)


@pytest.fixture
def clubs():
    """Club 1 (home) and club 2 "Film Friends" (Fay its admin, Gus an organizer, Hal a
    member). Ana (Discord 801) is in club 1, Hal (Discord 802) in both."""
    from app import app, db, Group, GroupMembership, User
    setup_db()
    with app.app_context():
        g2 = Group(name='Film Friends', slug='film-friends', is_public=False)
        db.session.add(g2)
        db.session.flush()
        us = {n: User(name=n, email=f'{n.lower()}@srv.test', is_active=True, discord_user_id=d)
              for n, d in (('Ana', '801'), ('Fay', '803'), ('Gus', None), ('Hal', '802'))}
        db.session.add_all(us.values())
        db.session.flush()
        db.session.add(GroupMembership(user_id=us['Ana'].id, group_id=1, status='active', role='member'))
        db.session.add(GroupMembership(user_id=us['Hal'].id, group_id=1, status='active', role='member'))
        for n, role in (('Fay', 'admin'), ('Gus', 'organizer'), ('Hal', 'member')):
            db.session.add(GroupMembership(user_id=us[n].id, group_id=g2.id, status='active', role=role))
        db.session.commit()
        return {'G2': g2.id, 'slug': g2.slug, **{n: u.id for n, u in us.items()}}


def code_for(clubs, who='Fay'):
    r = client(clubs[who]).post(f"/api/groups/{clubs['slug']}/discord/code")
    assert r.status_code == 200, r.json
    return r.json['code']


def connect(clubs):
    assert setup(code_for(clubs)).status_code == 200


# ─── Connecting ───────────────────────────────────────────────────────────────

def test_a_club_admin_connects_their_server_with_a_code(clubs):
    from app import app, db, DiscordServer
    assert client(clubs['Gus']).post(f"/api/groups/{clubs['slug']}/discord/code").status_code == 403   # organizers can't
    assert client(clubs['Hal']).get(f"/api/groups/{clubs['slug']}/discord").status_code == 403         # members don't see it
    status = client(clubs['Gus']).get(f"/api/groups/{clubs['slug']}/discord").json
    assert status['connected'] is False and status['home'] is False
    code = code_for(clubs)
    assert len(code) == 8 and not set(code) & set('01OI')
    assert setup(code.lower(), can_manage=False).json['error'].startswith('Only someone who can manage')
    r = setup(f'{code[:4].lower()}-{code[4:]}')                                      # typed loosely: still works
    assert r.status_code == 200 and r.json['server']['group_id'] == clubs['G2']
    assert setup(code).json['error'].startswith("That code doesn't work")            # once only
    with app.app_context():
        s = db.session.get(DiscordServer, OTHER_GUILD)
        assert s.group_id == clubs['G2'] and s.channel_id == '7001' and s.linked_by == clubs['Fay'] and not s.home
    status = client(clubs['Gus']).get(f"/api/groups/{clubs['slug']}/discord").json
    assert status['connected'] and status['server']['name'] == 'Film Friends' and status['server']['channel'] == 'films'
    assert client(clubs['Fay']).get('/api/groups/by-id/%d' % clubs['G2']).json['discord'] is True   # its Discord settings show


def test_codes_expire_and_conflicts_are_refused(clubs):
    from app import app, db, DiscordSetupCode
    code = code_for(clubs)
    with app.app_context():
        db.session.get(DiscordSetupCode, code).expires_at -= datetime.timedelta(hours=1)
        db.session.commit()
    assert setup(code).status_code == 400
    connect(clubs)
    # Another club can't take this server, and this club can't add a second one.
    with app.app_context():
        from app import Group, GroupMembership
        g3 = Group(name='Third', slug='third', is_public=False)
        db.session.add(g3)
        db.session.flush()
        db.session.add(GroupMembership(user_id=clubs['Fay'], group_id=g3.id, status='active', role='admin'))
        db.session.commit()
    third = client(clubs['Fay']).post('/api/groups/third/discord/code').json['code']
    assert 'already connected to Film Friends' in setup(third).json['error']
    assert 'already connected to another server' in setup(code_for(clubs), guild='555').json['error']


def test_moving_the_channel_and_disconnecting(clubs):
    from app import app, db, DiscordServer
    assert 'connect' in setup(None).json['error']                                   # no code, not connected
    connect(clubs)
    assert setup(None, channel='7002').json['server']['channel_id'] == '7002'
    bot_post('/api/internal/discord/members', guild_id=OTHER_GUILD, full=True, ids=['802'])
    assert client(clubs['Gus']).delete(f"/api/groups/{clubs['slug']}/discord").status_code == 403      # admins only
    after = client(clubs['Fay']).delete(f"/api/groups/{clubs['slug']}/discord").json
    assert after['connected'] is False
    with app.app_context():
        from app import DiscordServerMember
        assert db.session.get(DiscordServer, OTHER_GUILD).group_id is None             # the bot is still there
        assert DiscordServerMember.query.filter_by(guild_id=OTHER_GUILD).count() == 0


def test_removing_the_bot_forgets_the_server(clubs):
    from app import app, db, DiscordServer
    connect(clubs)
    bot_post(f'/api/internal/servers/{OTHER_GUILD}/left')
    with app.app_context():
        assert db.session.get(DiscordServer, OTHER_GUILD) is None
    assert client(clubs['Fay']).get(f"/api/groups/{clubs['slug']}/discord").json['connected'] is False


# ─── The home server ──────────────────────────────────────────────────────────

def test_the_home_server_registers_itself_and_keeps_its_members(clubs):
    from app import app, db, DiscordServer, DiscordServerMember, User, on_discord
    bot_post('/api/internal/discord/members', full=True, ids=['801'])               # an old bot: no server id (home)
    with app.app_context():
        ana = db.session.get(User, clubs['Ana'])
        assert on_discord(ana, 1) and not on_discord(ana, clubs['G2'])
    r = bot_post('/api/internal/servers/hello', application_id='123456',
                 home={'guild_id': HOME_GUILD, 'channel_id': '901', 'name': 'Cinema Club', 'channel_name': 'movies'})
    assert r.json == [{'guild_id': HOME_GUILD, 'group_id': 1, 'channel_id': '901', 'home': True}]
    with app.app_context():
        assert db.session.get(DiscordServer, HOME_GUILD).home
        assert [m.guild_id for m in DiscordServerMember.query] == [HOME_GUILD]          # moved to it
        assert on_discord(db.session.get(User, clubs['Ana']), 1)
    status = client(clubs['Fay']).get(f"/api/groups/{clubs['slug']}/discord").json
    assert status['invite_url'].startswith('https://discord.com/oauth2/authorize?client_id=123456&permissions=')
    # The home club can't be taken over by a code from another server.
    bot_post('/api/internal/servers/hello', home={'guild_id': '999', 'channel_id': '1'})
    with app.app_context():
        assert DiscordServer.query.filter_by(group_id=1).one().guild_id == HOME_GUILD


def test_old_member_rows_move_to_per_server(clubs):
    """The migration: one server's list (keyed by Discord id) becomes per server."""
    from app import app, db, migrate, DiscordServerMember
    with app.app_context():
        db.session.execute(db.text('DROP TABLE discord_server_member'))
        db.session.execute(db.text('CREATE TABLE discord_server_member (discord_user_id VARCHAR(30) PRIMARY KEY, seen_at DATETIME)'))
        db.session.execute(db.text("INSERT INTO discord_server_member VALUES ('801', NULL), ('802', NULL)"))
        db.session.commit()
        migrate()
        assert sorted((m.guild_id, m.discord_user_id) for m in DiscordServerMember.query) == [(None, '801'), (None, '802')]


# ─── Who's in which server ────────────────────────────────────────────────────

def test_being_in_one_server_doesnt_count_in_another_club(clubs):
    from app import app, db, User, discord_clubs, on_discord, split_present
    connect(clubs)
    bot_post('/api/internal/discord/members', full=True, ids=['801'], guild_id=HOME_GUILD, home=True)
    bot_post('/api/internal/discord/members', full=True, ids=['802', '803'], guild_id=OTHER_GUILD)
    with app.app_context():
        ana, hal, fay = (db.session.get(User, clubs[n]) for n in ('Ana', 'Hal', 'Fay'))
        assert on_discord(ana, 1) and not on_discord(ana, clubs['G2'])
        assert on_discord(hal, clubs['G2']) and not on_discord(hal, 1)               # Hal's in club 1, not its server
        assert split_present([ana, hal, fay], clubs['G2']) == ([hal, fay], 1)
        assert discord_clubs(hal) == [clubs['G2']] and discord_clubs(ana) == [1]
    named = client().get('/api/internal/club', query_string={'group_id': clubs['G2']}, headers=H).json['named']
    assert named == ['Fay', 'Hal']
    me = client(clubs['Hal']).get('/api/auth/me').json['user']
    assert me['discord_clubs'] == [clubs['G2']]
    assert client(clubs['Hal']).get('/api/discord/prefs').json['available']           # in a connected club's server
    unknown = bot_post('/api/internal/discord/members', full=True, ids=['1'], guild_id='4040')
    assert unknown.status_code == 404                                                 # not connected: not stored


def test_using_a_command_in_a_server_joins_its_club(clubs):
    from app import app, GroupMembership, User, DiscordServerMember
    connect(clubs)
    r = client().get('/api/internal/profile', query_string={
        'discord_user_id': '804', 'discord_name': 'Ivy', 'create': '1', 'group_id': clubs['G2'], 'guild_id': OTHER_GUILD},
        headers=H)
    assert r.status_code == 200
    with app.app_context():
        ivy = User.query.filter_by(discord_user_id='804').one()
        assert {m.group_id for m in GroupMembership.query.filter_by(user_id=ivy.id)} == {clubs['G2']}
        assert [(m.guild_id, m.discord_user_id) for m in DiscordServerMember.query] == [(OTHER_GUILD, '804')]


def test_the_dm_club_list(clubs):
    connect(clubs)
    bot_post('/api/internal/discord/members', full=True, ids=['802'], guild_id=HOME_GUILD, home=True)
    bot_post('/api/internal/discord/members', full=True, ids=['802'], guild_id=OTHER_GUILD)
    got = client().get('/api/internal/clubs', query_string={'discord_user_id': '802'}, headers=H).json
    assert sorted(c['id'] for c in got) == sorted([1, clubs['G2']])
    assert client().get('/api/internal/clubs', query_string={'discord_user_id': '999'}, headers=H).json == []


# ─── What the bot reports ─────────────────────────────────────────────────────

def test_missing_permissions_reach_whoever_connected_it_once(clubs):
    connect(clubs)
    report = lambda missing: bot_post(f'/api/internal/servers/{OTHER_GUILD}/report', name='Film Friends',
                                      channel_name='films', missing=missing, member_count=12).json
    assert report(['Manage Webhooks'])['notify_discord_user_id'] == '803'               # Fay
    assert report(['Manage Webhooks'])['notify_discord_user_id'] is None                 # same as before: not again
    status = client(clubs['Fay']).get(f"/api/groups/{clubs['slug']}/discord").json
    assert status['server']['missing'] == ['Manage Webhooks']
    assert report([])['notify_discord_user_id'] is None
    assert client(clubs['Fay']).get(f"/api/groups/{clubs['slug']}/discord").json['server']['missing'] == []


def test_the_ai_models_change_only_from_home(clubs):
    connect(clubs)
    bot_post('/api/internal/servers/hello', home={'guild_id': HOME_GUILD, 'channel_id': '901'})
    assert bot_post('/api/internal/settings', key='llm_primary', value='x', guild_id=OTHER_GUILD).status_code == 403
    assert bot_post('/api/internal/settings', key='llm_primary', value='x', guild_id=HOME_GUILD).status_code == 200


# ─── Quotes ───────────────────────────────────────────────────────────────────

def test_classics_everywhere_club_quotes_only_in_their_club(clubs):
    from app import app, db, Quote
    connect(clubs)
    with app.app_context():
        db.session.add(Quote(text='A classic line.', movie='Classic'))
        db.session.commit()
    me = {'discord_user_id': '803', 'discord_name': 'Fay', 'create': '1', 'guild_id': OTHER_GUILD}
    added = bot_post('/api/internal/quotes', **me, group_id=clubs['G2'], text='Only in Film Friends.', movie='X')
    assert added.status_code == 201 and added.json['classic'] is False
    texts = lambda gid: {q['text'] for q in client().get('/api/internal/quotes', query_string={'group_id': gid}, headers=H).json}
    assert texts(clubs['G2']) == {'A classic line.', 'Only in Film Friends.'}
    assert texts(1) == {'A classic line.'}
    qid = added.json['id']
    assert client().get(f'/api/internal/quotes/{qid}', query_string={'group_id': 1}, headers=H).status_code == 404
    # The same line can be added in another club (it isn't theirs to see), not twice in one.
    assert bot_post('/api/internal/quotes', **me, group_id=clubs['G2'], text='Only in Film Friends.', movie='X').status_code == 409
    assert bot_post('/api/internal/quotes', **{**me, 'create': '0'}, text='No club', movie='X').status_code == 400


def test_who_may_change_a_quote(clubs):
    from app import app, db, Quote
    connect(clubs)
    with app.app_context():
        db.session.add(Quote(text='A classic line.', movie='Classic'))
        db.session.commit()
        classic = Quote.query.filter_by(text='A classic line.').one().id
    fay = {'discord_user_id': '803', 'discord_name': 'Fay', 'create': '1', 'guild_id': OTHER_GUILD, 'group_id': clubs['G2']}
    hal = {**fay, 'discord_user_id': '802', 'discord_name': 'Hal'}
    mine = bot_post('/api/internal/quotes', **fay, text='Fay says.', movie='X').json['id']
    edit = lambda who, qid, **extra: client().put(f'/api/internal/quotes/{qid}', headers=H,
                                                 json={**who, **extra, 'text': 'Changed.', 'movie': 'X'})
    remove = lambda who, qid, **extra: client().delete(f'/api/internal/quotes/{qid}', headers=H, json={**who, **extra})
    assert edit(hal, mine).status_code == 200                                       # members correct their club's quotes
    assert edit(fay, classic).status_code == 403 and edit(fay, classic).json['error'] == 'classic'
    assert remove(fay, classic, is_admin=True).json['error'] == 'classic'           # not even an admin elsewhere
    assert remove(hal, mine).status_code == 403                                     # not Hal's
    assert remove(hal, mine, is_admin=True).status_code == 200                      # that server's admin may
    home_admin = {'discord_user_id': '801', 'discord_name': 'Ana', 'create': '1', 'guild_id': HOME_GUILD, 'group_id': 1}
    assert remove(home_admin, classic, is_admin=True).status_code == 200            # classics: from home

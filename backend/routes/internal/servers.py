"""The bot's servers: which club each connected server belongs to (the bot's
map), /setup, the bot joining or leaving a server, what it reports about
each, and the clubs a member can pick from in DMs (discord_servers.py)."""
from app import BotSetting, User, app, db, discord_clubs, jsonify, request, Group
from routes.internal.common import require_internal
import discord_servers


@app.route('/api/internal/servers')
@require_internal
def internal_servers():
    """[{guild_id, group_id, channel_id, home}] — every connected server."""
    return jsonify(discord_servers.servers())


@app.route('/api/internal/servers/hello', methods=['POST'])
@require_internal
def internal_servers_hello():
    """The bot started: {application_id, home: {guild_id, channel_id, name,
    channel_name}} — remember its id (for the invite link) and register its
    own server as the home club's."""
    data = request.json or {}
    app_id = str(data.get('application_id') or '')
    if app_id.isdigit():
        row = db.session.get(BotSetting, 'discord_application_id') or BotSetting(key='discord_application_id')
        row.value = app_id
        db.session.add(row)
        db.session.commit()
    home = data.get('home') or {}
    if str(home.get('guild_id') or '').isdigit():
        discord_servers.adopt_home(home['guild_id'], home.get('channel_id'), home.get('name'), home.get('channel_name'))
    return jsonify(discord_servers.servers())


@app.route('/api/internal/servers/setup', methods=['POST'])
@require_internal
def internal_servers_setup():
    """/setup: {guild_id, guild_name, channel_id, channel_name, can_manage,
    code?} — connect the server with a code, or (no code, already connected)
    move it to this channel. {server: {group_id, group_name, …}} or {error}."""
    d = request.json or {}
    if not str(d.get('guild_id') or '').isdigit() or not str(d.get('channel_id') or '').isdigit():
        return jsonify({'error': 'Run /setup in a channel of the server.'}), 400
    can = bool(d.get('can_manage'))
    if d.get('code'):
        server, err = discord_servers.connect(d['code'], d['guild_id'], d.get('guild_name'), d['channel_id'],
                                              d.get('channel_name'), can)
    else:
        server, err = discord_servers.move_channel(d['guild_id'], d['channel_id'], d.get('channel_name'), can)
    if err:
        return jsonify({'error': err}), 400
    group = db.session.get(Group, server.group_id)
    return jsonify({'server': {'guild_id': server.guild_id, 'group_id': group.id, 'group_name': group.name,
                               'group_slug': group.slug, 'channel_id': server.channel_id}})


@app.route('/api/internal/servers/<guild_id>/joined', methods=['POST'])
@require_internal
def internal_server_joined(guild_id):
    discord_servers.joined(guild_id, (request.json or {}).get('name'))
    return jsonify({'ok': True})


@app.route('/api/internal/servers/<guild_id>/left', methods=['POST'])
@require_internal
def internal_server_left(guild_id):
    discord_servers.left(guild_id)
    return jsonify({'ok': True})


@app.route('/api/internal/servers/<guild_id>/report', methods=['POST'])
@require_internal
def internal_server_report(guild_id):
    """What the bot sees: {name, channel_name, missing: [permission names], member_count}."""
    d = request.json or {}
    missing = d.get('missing')
    server = discord_servers.report(guild_id, d.get('name'), d.get('channel_name'),
                                    [str(m) for m in missing] if isinstance(missing, list) else None,
                                    d.get('member_count') if isinstance(d.get('member_count'), int) else None)
    if not server:
        return jsonify({'error': 'Unknown server'}), 404
    # Something new the bot can't do: tell whoever connected the server (once per change).
    admin = db.session.get(User, server.linked_by) if server.linked_by and server.missing_changed else None
    return jsonify({'ok': True, 'notify_discord_user_id': admin.discord_user_id if admin else None})


@app.route('/api/internal/clubs')
@require_internal
def internal_clubs():
    """The clubs whose server a member is in — for the club picker in DMs."""
    user = User.query.filter_by(discord_user_id=str(request.args.get('discord_user_id') or '')).first()
    if not user or not user.is_active:
        return jsonify([])
    return jsonify([{'id': g.id, 'name': g.name} for g in
                    (db.session.get(Group, gid) for gid in discord_clubs(user)) if g])

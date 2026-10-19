"""Discord servers and the clubs they belong to: one server, one club.

A club admin connects their server from Club settings: they add the bot
(Discord's invite, built from the bot's application id), make a one-time code
here, and run /setup code:… in the channel the bot should use — Discord checks
that whoever runs it can manage the server, and the code proves a club admin
made it. Running /setup again in another channel moves it. The home server
(the bot's first: DEFAULT_GROUP_ID's, DISCORD_CHANNEL_ID's) is registered by
the bot itself (adopt_home). Removing the bot from a server disconnects it.
"""
import secrets
from datetime import timedelta

CODE_TTL = timedelta(minutes=30)
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'      # no 0/O or 1/I
# What the bot needs in its channel (Discord's permission names, as shown in
# Server Settings); the invite asks for exactly these.
BOT_PERMISSIONS = 0x400 | 0x800 | 0x4000 | 0x10000 | 0x20000000 | 0x800000000 | 0x4000000000
# View Channel, Send Messages, Embed Links, Read Message History, Manage
# Webhooks, Create Public Threads, Send Messages in Threads


def _now():
    from app import _utcnow_naive
    return _utcnow_naive()


def _changed():
    """Forget this request's cached server and member lookups."""
    from flask import g, has_request_context
    if has_request_context():
        g.discord_servers = None
        g.discord_present = None


def new_code(group, user):
    """A fresh one-time code for `group` (older unused ones stop working)."""
    from app import db, DiscordSetupCode
    DiscordSetupCode.query.filter_by(group_id=group.id, used_at=None).delete()
    code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    db.session.add(DiscordSetupCode(code=code, group_id=group.id, created_by=user.id, expires_at=_now() + CODE_TTL))
    db.session.commit()
    return code


def clean_code(raw):
    return ''.join(c for c in (raw or '').upper() if c in CODE_ALPHABET)


def _members_to(guild_id, group_id):
    """The home server's members from before it reported its id (guild None)
    become this server's."""
    from app import HOME_GROUP_ID, db, DiscordServerMember
    if group_id != HOME_GROUP_ID:
        return
    taken = {r[0] for r in db.session.query(DiscordServerMember.discord_user_id)
             .filter(DiscordServerMember.guild_id == guild_id)}
    for m in DiscordServerMember.query.filter(DiscordServerMember.guild_id.is_(None)).all():
        if m.discord_user_id in taken:
            db.session.delete(m)
        else:
            m.guild_id = guild_id


def adopt_home(guild_id, channel_id=None, name=None, channel_name=None, _retry=True):
    """The bot's own server (from its settings) is the home club's. Runs at the
    bot's start and on the first command there; a no-op once it's known. The
    bot's start-up calls can arrive together (two workers): the one that loses
    the race finds the row the other made and carries on."""
    from sqlalchemy.exc import IntegrityError
    from app import HOME_GROUP_ID, db, DiscordServer, Group
    guild_id = str(guild_id)
    if not db.session.get(Group, HOME_GROUP_ID):
        return None
    home = DiscordServer.query.filter_by(group_id=HOME_GROUP_ID).first()
    if home and home.guild_id != guild_id:
        return home                              # the home club moved to another server: leave it
    server = home or db.session.get(DiscordServer, guild_id) or DiscordServer(guild_id=guild_id)
    if server.group_id not in (None, HOME_GROUP_ID):
        return server                            # another club's server: never taken over
    server.group_id, server.home = HOME_GROUP_ID, True
    server.channel_id = server.channel_id or (str(channel_id) if channel_id else None)
    server.name = name or server.name
    server.channel_name = channel_name or server.channel_name
    server.linked_at = server.linked_at or _now()
    try:
        db.session.add(server)
        _members_to(guild_id, HOME_GROUP_ID)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        if not _retry:
            raise
        return adopt_home(guild_id, channel_id, name, channel_name, _retry=False)
    _changed()
    return server


def connect(code, guild_id, guild_name, channel_id, channel_name, can_manage):
    """/setup code:… — connect this server to the code's club, posting in this
    channel. Returns (server, None) or (None, an error to show)."""
    from app import db, DiscordServer, DiscordSetupCode, Group
    if not can_manage:
        return None, 'Only someone who can manage this server can connect it.'
    row = db.session.get(DiscordSetupCode, clean_code(code))
    if not row or row.used_at or row.expires_at < _now():
        return None, ("That code doesn't work — it may have expired (codes last 30 minutes). "
                      "Make a new one in Club settings → Discord on the site.")
    group = db.session.get(Group, row.group_id)
    guild_id = str(guild_id)
    server = db.session.get(DiscordServer, guild_id)
    if server and server.group_id not in (None, group.id):
        other = db.session.get(Group, server.group_id)
        return None, (f"This server is already connected to {other.name if other else 'another club'}. "
                      "One of its admins can disconnect it in Club settings first.")
    current = DiscordServer.query.filter_by(group_id=group.id).first()
    if current and current.guild_id != guild_id:
        return None, (f"{group.name} is already connected to another server ({current.name or 'unnamed'}). "
                      "Disconnect it in Club settings first.")
    server = server or DiscordServer(guild_id=guild_id)
    server.group_id, server.channel_id = group.id, str(channel_id)
    server.name, server.channel_name = (guild_name or '')[:100], (channel_name or '')[:100]
    server.linked_by, server.linked_at, server.missing_perms = row.created_by, _now(), None
    row.used_at = _now()
    db.session.add(server)
    _members_to(guild_id, group.id)
    db.session.commit()
    _changed()
    return server, None


def move_channel(guild_id, channel_id, channel_name, can_manage):
    """/setup with no code in a connected server: post in this channel instead."""
    from app import db, DiscordServer
    if not can_manage:
        return None, 'Only someone who can manage this server can change its channel.'
    server = db.session.get(DiscordServer, str(guild_id))
    if not server or not server.group_id:
        return None, "This server isn't connected to a club yet — run /setup with a code from Club settings on the site."
    server.channel_id, server.channel_name, server.missing_perms = str(channel_id), (channel_name or '')[:100], None
    db.session.commit()
    _changed()
    return server, None


def disconnect(group_id):
    """From Club settings: the club's server is no longer connected (the bot
    stays there, unconnected; the club's Discord settings are kept)."""
    from app import db, DiscordServer, DiscordServerMember
    server = DiscordServer.query.filter_by(group_id=group_id).first()
    if not server:
        return False
    DiscordServerMember.query.filter_by(guild_id=server.guild_id).delete()
    server.group_id, server.home, server.channel_id = None, False, None
    db.session.commit()
    _changed()
    return True


def left(guild_id):
    """The bot was removed from a server: forget it."""
    from app import db, DiscordServer, DiscordServerMember
    DiscordServerMember.query.filter_by(guild_id=str(guild_id)).delete()
    server = db.session.get(DiscordServer, str(guild_id))
    if server:
        db.session.delete(server)
    db.session.commit()
    _changed()


def joined(guild_id, name):
    """The bot was added to a server (not connected until /setup)."""
    from app import db, DiscordServer
    server = db.session.get(DiscordServer, str(guild_id)) or DiscordServer(guild_id=str(guild_id))
    server.name = (name or '')[:100]
    db.session.add(server)
    db.session.commit()


def report(guild_id, name=None, channel_name=None, missing=None, member_count=None):
    """What the bot sees in a server: its name, the channel's, what it can't do there."""
    from app import db, DiscordServer
    server = db.session.get(DiscordServer, str(guild_id))
    if not server:
        return None
    if name:
        server.name = name[:100]
    if channel_name:
        server.channel_name = channel_name[:100]
    server.missing_changed = False
    if missing is not None:
        now_missing = ', '.join(missing)[:300] or None
        server.missing_changed = bool(now_missing) and now_missing != server.missing_perms
        server.missing_perms = now_missing
    if member_count is not None:
        server.member_count = member_count
    server.reported_at = _now()
    db.session.commit()
    return server


def servers():
    """The connected servers, for the bot: [{guild_id, group_id, channel_id, home}]."""
    from app import DiscordServer
    return [{'guild_id': s.guild_id, 'group_id': s.group_id, 'channel_id': s.channel_id, 'home': bool(s.home)}
            for s in DiscordServer.query.filter(DiscordServer.group_id.isnot(None))]


def invite_url():
    """Discord's "add this bot" link with the permissions it needs, or None
    until the bot has reported its application id."""
    from app import db, BotSetting
    row = db.session.get(BotSetting, 'discord_application_id')
    if not row or not row.value:
        return None
    return (f'https://discord.com/oauth2/authorize?client_id={row.value}'
            f'&permissions={BOT_PERMISSIONS}&scope=bot%20applications.commands')


def status(group):
    """Club settings → Discord: connected?, where, what's missing, and how to connect."""
    from app import HOME_GROUP_ID, DiscordServer, present_user_ids
    server = DiscordServer.query.filter_by(group_id=group.id).first()
    out = {'connected': server is not None or group.id == HOME_GROUP_ID, 'invite_url': invite_url(),
           'home': group.id == HOME_GROUP_ID}
    if server:
        out.update(server={'name': server.name, 'channel': server.channel_name, 'channel_id': server.channel_id,
                           'missing': [p for p in (server.missing_perms or '').split(', ') if p],
                           'members': server.member_count, 'linked': len(present_user_ids(group.id))})
    return out

"""What every part of the bot's API uses: the internal-token check and the
account behind a Discord user (made on first use in a club's server).
"""
from app import (AVATAR_COLORS, DiscordServerMember, Group, GroupMembership, HOME_GROUP_ID, INTERNAL_API_TOKEN,
    IntegrityError, User, _as_int, db, follow_discord_avatar, jsonify, on_discord, random, request, secrets, wraps)


def resolve_discord_user(data):
    """The account behind a Discord user, for the bot's internal endpoints.

    Discord members don't need a site account: the first time someone uses a
    personal command in a connected club's server (the bot sends create=True
    only there, with that club and server), they get a Discord-only account —
    no email, no site login unless they "Sign in with Discord" — and join that
    server's club. Discord-only accounts follow the member's current Discord
    name. Returns (user, error).
    """
    discord_id = str(data.get('discord_user_id') or '').strip()
    if not discord_id.isdigit():
        return None, (jsonify({'error': 'discord_user_id required'}), 400)
    create = str(data.get('create', '')).lower() in ('1', 'true')
    name = (data.get('discord_name') or '').strip()[:100]

    user = User.query.filter_by(discord_user_id=discord_id).first()
    if user is None:
        if not create:
            return None, (jsonify({'error': 'no_account'}), 404)
        user = User(discord_user_id=discord_id, name=name or 'Discord member',
                    avatar_color=random.choice(AVATAR_COLORS), is_active=True)
        db.session.add(user)
        try:
            db.session.flush()
        except IntegrityError:        # created by a simultaneous command
            db.session.rollback()
            user = User.query.filter_by(discord_user_id=discord_id).first()
    if not user or not user.is_active:
        return None, (jsonify({'error': 'no_account'}), 404)

    if user.email is None and name:
        user.name = name
    if data.get('discord_username'):
        user.discord_username = str(data['discord_username'])[:40]
    if data.get('discord_avatar'):
        follow_discord_avatar(user, str(data['discord_avatar']))

    # Being in a club's server is membership of its club.
    group = db.session.get(Group, _as_int(data.get('group_id'))) if create else None
    if group:
        membership = GroupMembership.query.filter_by(user_id=user.id, group_id=group.id).first()
        if not membership:
            db.session.add(GroupMembership(user_id=user.id, group_id=group.id, role='member', status='active'))
        elif membership.status != 'active':
            membership.status = 'active'
        guild = str(data.get('guild_id') or '') or None
        if guild and group.id == HOME_GROUP_ID:          # the home server's first use registers it
            import discord_servers
            db.session.flush()
            discord_servers.adopt_home(guild)
        # They're using it there, so they're in that server. (No server id: the
        # home server from before servers were per club — never another club's.)
        if (guild or group.id == HOME_GROUP_ID) and \
                not DiscordServerMember.query.filter_by(guild_id=guild, discord_user_id=discord_id).first():
            db.session.add(DiscordServerMember(guild_id=guild, discord_user_id=discord_id))
            _present_changed()
    db.session.commit()
    return user, None

def require_internal(f):
    """Auth for /api/internal/* — shared-secret header used by the Discord bot
    over the Docker network. Rejects everything when the token is unset."""
    @wraps(f)
    def decorated(*args, **kwargs):
        supplied = request.headers.get('X-Internal-Token', '')
        if not INTERNAL_API_TOKEN or not secrets.compare_digest(supplied, INTERNAL_API_TOKEN):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated


def _present_changed():
    from flask import g, has_request_context
    if has_request_context():
        g.discord_present = None


def _discord_member(discord_id, group_id):
    """Someone else, by Discord id: an active account in this club's server."""
    user = User.query.filter_by(discord_user_id=str(discord_id or '')).first()
    return user if user and user.is_active and on_discord(user, group_id) else None


def request_scope():
    """What a bot request is about: its club (?group_id), or — in a server
    that isn't connected — the city it names (?city=), as a places.CityScope."""
    import places
    group_id = request.args.get('group_id', type=int)
    group = db.session.get(Group, group_id) if group_id else None
    return group if group else places.scope(None, None, request.args.get('city'))


def request_group():
    """The club a bot request is for (its group_id; the home club if none)."""
    body = request.get_json(silent=True) if request.method != 'GET' else None
    return _as_int((body or {}).get('group_id')) or request.args.get('group_id', type=int) or HOME_GROUP_ID

"""Servers: connecting a server to its club (/setup), the bot joining and
leaving servers, keeping the server map current, and which club a command is
for — its server's, or in DMs the one picked from a menu when you're in more
than one connected club.
"""

import time

import discord
from discord import app_commands
from discord.ext import tasks

import embeds
from api import ApiError
from .shared import (DEFAULT_GROUP_ID, NOT_CONNECTED_MSG, UNREACHABLE_MSG, _dm_last, api, api_error_text, client,
                     club_for_guild, club_of, movies_channel, refresh_servers, register, tell, use_club)

# Work in a server that isn't connected yet (everything they show is public).
PUBLIC_COMMANDS = {'showtimes', 'movie', 'find', 'surprise', 'theatre', 'help', 'setup'}
NO_CLUB_COMMANDS = {'help', 'setup'}            # never about a club: no menu in DMs
DM_CLUBS_KEEP = 5 * 60                          # seconds a member's club list is remembered
# What the bot needs in its channel (Discord's names for them, as Server Settings shows them).
NEEDED = (('view_channel', 'View Channel'), ('send_messages', 'Send Messages'), ('embed_links', 'Embed Links'),
          ('read_message_history', 'Read Message History'), ('manage_webhooks', 'Manage Webhooks'),
          ('create_public_threads', 'Create Public Threads'), ('send_messages_in_threads', 'Send Messages in Threads'))

_dm_clubs = {}                                   # Discord user id → (when, [{id, name}])


async def dm_clubs(user_id):
    """The connected clubs a member is in (whose servers they're in)."""
    hit = _dm_clubs.get(user_id)
    if hit and time.monotonic() - hit[0] < DM_CLUBS_KEEP:
        return hit[1]
    try:
        clubs = await api.get('/api/internal/clubs', discord_user_id=str(user_id))
    except Exception:
        clubs = []
    _dm_clubs[user_id] = (time.monotonic(), clubs)
    return clubs


class ClubPicker(discord.ui.View):
    """"Which club is this for?" — in DMs, for members in more than one
    connected club. Picking runs the command for that club."""
    def __init__(self, clubs, command, namespace, owner_id):
        super().__init__(timeout=120)
        self.command, self.namespace, self.owner_id = command, namespace, owner_id
        self.select = discord.ui.Select(placeholder='Which club is this for?',
                                        options=[discord.SelectOption(label=c['name'][:100], value=str(c['id']))
                                                 for c in clubs[:25]])
        self.select.callback = self.picked
        self.add_item(self.select)

    async def picked(self, interaction: discord.Interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("That menu isn't yours.", ephemeral=True)
            return
        group_id = int(self.select.values[0])
        _dm_last[interaction.user.id] = (group_id, time.monotonic())
        use_club(group_id)
        self.stop()
        try:
            await self.command._invoke_with_namespace(interaction, self.namespace)
        except Exception as e:
            print(f'club picker: /{self.command.qualified_name} failed: {e}')
            await tell(interaction, "Something went wrong running that command — try again in a bit.")


async def interaction_check(interaction: discord.Interaction) -> bool:
    """Before every command (and its autocomplete): which club it's for. In a
    server, its club — or, not connected, only the public commands. In DMs,
    your one connected club, or a menu when you're in several."""
    name = (interaction.data or {}).get('name')
    is_command = interaction.type is discord.InteractionType.application_command
    if interaction.guild_id:
        group_id = club_for_guild(interaction.guild_id)
        use_club(group_id)
        if group_id is None and name not in PUBLIC_COMMANDS:
            if is_command:
                await interaction.response.send_message(NOT_CONNECTED_MSG, ephemeral=True)
            return False
        return True
    if name in NO_CLUB_COMMANDS:
        return True
    clubs = await dm_clubs(interaction.user.id)
    if len(clubs) <= 1 or not is_command:            # autocomplete can't ask: the last pick (club_of) decides
        use_club(clubs[0]['id'] if len(clubs) == 1 else club_of(interaction))
        return True
    await interaction.response.send_message(
        'Which club is this for?', view=ClubPicker(clubs, interaction.command, interaction.namespace, interaction.user.id))
    return False


client.tree.interaction_check = interaction_check


def missing_permissions(channel):
    """What the bot can't do in this channel (Discord's names)."""
    me = getattr(getattr(channel, 'guild', None), 'me', None)
    if channel is None or me is None:
        return []
    perms = channel.permissions_for(me)
    return [label for attr, label in NEEDED if not getattr(perms, attr, False)]


@client.tree.command(name='setup', description="Connect this server to your club, posting in this channel (server admins)")
@app_commands.describe(code='The code from Club settings → Discord on the site (not needed to move the channel)')
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def setup_cmd(interaction: discord.Interaction, code: str = None):
    await interaction.response.defer(ephemeral=True)
    channel, guild = interaction.channel, interaction.guild
    perms = getattr(interaction, 'permissions', None)
    try:
        r = await api.post('/api/internal/servers/setup', {
            'guild_id': str(interaction.guild_id), 'guild_name': getattr(guild, 'name', None),
            'channel_id': str(channel.id), 'channel_name': getattr(channel, 'name', None),
            'can_manage': bool(perms and perms.manage_guild), 'code': code})
    except ApiError as e:
        await interaction.followup.send(api_error_text(e), ephemeral=True)
        return
    except Exception as e:
        print(f'/setup failed: {e}')
        await interaction.followup.send(UNREACHABLE_MSG, ephemeral=True)
        return
    await refresh_servers()
    server = r['server']
    missing = missing_permissions(channel)
    await _report(interaction.guild_id, guild, channel, missing)
    await interaction.followup.send(embed=embeds.setup_done_embed(server['group_name'], channel, missing,
                                                                  code is not None), ephemeral=True)


async def _report(guild_id, guild, channel, missing):
    """Tell the backend what the bot sees; DM whoever connected the server
    when something new is missing."""
    try:
        r = await api.post(f'/api/internal/servers/{guild_id}/report', {
            'name': getattr(guild, 'name', None), 'channel_name': getattr(channel, 'name', None),
            'missing': missing, 'member_count': getattr(guild, 'member_count', None)})
    except Exception as e:
        print(f'servers: report for {guild_id} failed: {e}')
        return
    admin = r.get('notify_discord_user_id')
    if admin and missing:
        try:
            user = client.get_user(int(admin)) or await client.fetch_user(int(admin))
            await user.send(embeds.missing_permissions_message(getattr(guild, 'name', 'your server'), channel, missing))
        except Exception as e:
            print(f'servers: permissions DM failed: {e}')


async def report_club(group_id):
    """Report a club's server now (e.g. threads just hit a missing permission)."""
    from .shared import _servers
    for guild_id, s in list(_servers.items()):
        if s['group_id'] == group_id:
            channel = client.get_channel(s['channel_id']) if s['channel_id'] else None
            await _report(guild_id, client.get_guild(guild_id), channel, missing_permissions(channel))


@tasks.loop(minutes=30)
async def servers_loop():
    """Keep the map current and tell the backend what the bot sees in each server."""
    await refresh_servers()
    from .shared import _servers
    for guild_id, s in list(_servers.items()):
        guild = client.get_guild(guild_id)
        channel = client.get_channel(s['channel_id']) if s['channel_id'] else None
        if guild is not None:
            await _report(guild_id, guild, channel, missing_permissions(channel))


@servers_loop.before_loop
async def before_servers():
    await client.wait_until_ready()


@client.event
async def on_ready():
    """Register the home server (the bot's own, from its settings) and load the map."""
    channel = movies_channel()
    home = {'guild_id': str(channel.guild.id), 'channel_id': str(channel.id), 'name': channel.guild.name,
            'channel_name': getattr(channel, 'name', None)} if channel is not None else {}
    try:
        await api.post('/api/internal/servers/hello', {'application_id': str(client.application_id or ''), 'home': home})
    except Exception as e:
        print(f'servers: hello failed: {e}')
    await refresh_servers()
    print(f'Logged in as {client.user} — home channel {getattr(channel, "id", None)}, '
          f'club {DEFAULT_GROUP_ID}; {len(client.guilds)} server(s)')


@client.event
async def on_guild_join(guild):
    try:
        await api.post(f'/api/internal/servers/{guild.id}/joined', {'name': guild.name})
    except Exception as e:
        print(f'servers: joined {guild.id} failed: {e}')
    channel = guild.system_channel
    if channel is not None and channel.permissions_for(guild.me).send_messages:
        try:
            await channel.send(embed=embeds.joined_server_embed())
        except Exception:
            pass


@client.event
async def on_guild_remove(guild):
    try:
        await api.post(f'/api/internal/servers/{guild.id}/left', {})
    except Exception as e:
        print(f'servers: left {guild.id} failed: {e}')
    await refresh_servers()


register(loops=(servers_loop,))

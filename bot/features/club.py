"""The club: /club, /help, and who's in the server (joins, leaves, the sync
with the site).
"""

import discord
from discord.ext import tasks
import embeds
from .shared import (DEFAULT_GROUP_ID, SITE_URL, api, backend_ready, client, club, club_for_guild, connected_clubs,
                     is_home_guild, movies_channel, register, reply_failure)


@client.tree.command(name='help', description='A quick guide to the club bot’s commands')
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=embeds.help_embed(), ephemeral=True)


@client.tree.command(name='club', description="The club at a glance: members, theatres, this month's numbers")
async def club_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        c = await api.get('/api/internal/club', group_id=club())
    except Exception as e:
        await reply_failure(interaction, e, '/club', ephemeral=False)
        return
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label='Club page', url=f'{SITE_URL}/club'))
    view.add_item(discord.ui.Button(label='Leaderboard', url=f'{SITE_URL}/club?tab=leaderboard'))
    await interaction.followup.send(embed=embeds.club_embed(c), view=view)


# ─── Who's in the server ──────────────────────────────────────────────────────
# The site only ever names (or posts for) members who've linked Discord and are
# in a club's server, so it needs each connected server's list: the whole of
# it once the bot is ready and every half hour after (member_sync_loop), and
# joins/leaves as they happen. Until a server's first sync, the site posts
# nothing there.

def home_guild():
    return getattr(movies_channel(), 'guild', None)


async def sync_members():
    for group_id, guild_id in connected_clubs():
        guild = client.get_guild(guild_id) if guild_id else None
        if guild is None and group_id == DEFAULT_GROUP_ID:
            guild = home_guild()
        if guild is None:
            continue
        if not guild.chunked:                 # never send a partial list as the whole one
            try:
                await guild.chunk()
            except Exception as e:
                print(f'member sync: fetching members of {guild.id} failed: {e}')
                continue
        try:
            r = await api.post('/api/internal/discord/members', {
                'full': True, 'ids': [str(m.id) for m in guild.members if not m.bot],
                'guild_id': str(guild.id), 'home': group_id == DEFAULT_GROUP_ID})
            if r.get('joined') or r.get('left'):
                print(f"member sync: {r['members']} in {guild.id} (+{r['joined']} / -{r['left']})")
        except Exception as e:
            print(f'member sync for {guild.id} failed: {e}')


@tasks.loop(minutes=30)
async def member_sync_loop():
    await sync_members()


@member_sync_loop.before_loop
async def before_member_sync():
    await client.wait_until_ready()
    await backend_ready()


async def member_changed(member, key):
    if member.bot or club_for_guild(member.guild.id) is None:     # only connected servers
        return
    try:
        await api.post('/api/internal/discord/members', {key: [str(member.id)], 'guild_id': str(member.guild.id),
                                                         'home': is_home_guild(member.guild.id)})
    except Exception as e:                    # the half-hourly sync catches up
        print(f'member sync ({key}) failed: {e}')


@client.event
async def on_member_join(member):
    await member_changed(member, 'joined')


@client.event
async def on_member_remove(member):
    await member_changed(member, 'left')


register(loops=(member_sync_loop,))

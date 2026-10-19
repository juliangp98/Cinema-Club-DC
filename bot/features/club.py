"""The club: /club, /help, and who's in the server (joins, leaves, the sync
with the site).
"""

import discord
from discord.ext import tasks
import embeds
from .shared import DEFAULT_GROUP_ID, SITE_URL, api, client, movies_channel, register, reply_failure


@client.tree.command(name='help', description='A quick guide to the club bot’s commands')
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.send_message(embed=embeds.help_embed(), ephemeral=True)


@client.tree.command(name='club', description="The club at a glance: members, theatres, this month's numbers")
async def club_cmd(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        c = await api.get('/api/internal/club', group_id=DEFAULT_GROUP_ID)
    except Exception as e:
        await reply_failure(interaction, e, '/club', ephemeral=False)
        return
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label='Club page', url=f'{SITE_URL}/club'))
    view.add_item(discord.ui.Button(label='Leaderboard', url=f'{SITE_URL}/club?tab=leaderboard'))
    await interaction.followup.send(embed=embeds.club_embed(c), view=view)


# ─── Who's in the server ──────────────────────────────────────────────────────
# The site only ever names (or posts for) members who've linked Discord and are
# in the club's server, so it needs that list: the whole of it once the bot is
# ready and every half hour after (member_sync_loop), and joins/leaves as they
# happen. Until the first sync, the site posts nothing.

def home_guild():
    return getattr(movies_channel(), 'guild', None)


async def sync_members():
    guild = home_guild()
    if guild is None:
        return
    if not guild.chunked:                     # never send a partial list as the whole one
        try:
            await guild.chunk()
        except Exception as e:
            print(f'member sync: fetching members failed: {e}')
            return
    try:
        r = await api.post('/api/internal/discord/members',
                           {'full': True, 'ids': [str(m.id) for m in guild.members if not m.bot]})
        if r.get('joined') or r.get('left'):
            print(f"member sync: {r['members']} in the server (+{r['joined']} / -{r['left']})")
    except Exception as e:
        print(f'member sync failed: {e}')


@tasks.loop(minutes=30)
async def member_sync_loop():
    await sync_members()


@member_sync_loop.before_loop
async def before_member_sync():
    await client.wait_until_ready()


async def member_changed(member, key):
    guild = home_guild()
    if guild is None or member.guild.id != guild.id or member.bot:
        return
    try:
        await api.post('/api/internal/discord/members', {key: [str(member.id)]})
    except Exception as e:                    # the half-hourly sync catches up
        print(f'member sync ({key}) failed: {e}')


@client.event
async def on_member_join(member):
    await member_changed(member, 'joined')


@client.event
async def on_member_remove(member):
    await member_changed(member, 'left')


register(loops=(member_sync_loop,))

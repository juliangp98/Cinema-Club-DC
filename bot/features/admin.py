"""/llm — the AI models (server admins of the home server only: the AI is the
whole site's, so other clubs' servers can't change it).
"""

import discord
from discord import app_commands
import llm
from .shared import api, client, is_home_guild


# ─── /llm (server admins) ────────────────────────────────────────────────────
# Hidden from members without Manage Server by default; admins can grant it to
# other roles in Server Settings → Integrations.

llm_admin = app_commands.Group(
    name='llm', description="The chatbot's AI models (server admins)",
    default_permissions=discord.Permissions(manage_guild=True), guild_only=True)

HOME_ONLY_MSG = "The AI models are the whole site's — they're changed from the Cinema Club DC server."


async def home_only(interaction):
    """True in the home server; elsewhere says why not."""
    if is_home_guild(interaction.guild_id):
        return True
    await interaction.response.send_message(HOME_ONLY_MSG, ephemeral=True)
    return False


@llm_admin.command(name='show', description='Which models the chatbot uses, and what Groq offers')
async def llm_show(interaction: discord.Interaction):
    if not await home_only(interaction):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        s = await llm.status()
    except Exception as e:
        print(f'/llm show failed: {e}')
        await interaction.followup.send("Couldn't reach the site's AI settings — try again in a bit.", ephemeral=True)
        return
    how = s['how']
    lines = [
        f"**Primary:** `{s['primary'] or '—'}` ({how.get('primary') or 'not chosen yet'})",
        f"**Fallback:** `{s['fallback'] or 'none'}` ({how.get('fallback') or '—'})",
        f"Overrides: primary `{s['overrides']['primary'] or 'auto'}` · fallback `{s['overrides']['fallback'] or 'auto'}`",
        f"Env pins: primary `{s['env']['primary'] or '—'}` · fallback `{s['env']['fallback'] or '—'}`",
        'Groq chat models, best first: ' + (', '.join(f'`{m}`' for m in s['available']) or '—'),
        '_Shared by the chatbot and the site (poll drafts). Re-checked daily and whenever a model is retired; '
        'you get a DM if they change._',
    ]
    await interaction.followup.send('\n'.join(lines), ephemeral=True)


@llm_admin.command(name='set', description='Pin the chatbot to a model, or "auto" to let it choose')
@app_commands.describe(slot='Which model to set',
                       model='A model Groq serves, "auto" to clear the pin, or "none" (fallback only) to disable it')
@app_commands.choices(slot=[
    app_commands.Choice(name='Primary', value='primary'),
    app_commands.Choice(name='Fallback', value='fallback'),
])
async def llm_set(interaction: discord.Interaction, slot: app_commands.Choice[str], model: str):
    if not await home_only(interaction):
        return
    value = model.strip()
    value = '' if value.lower() == 'auto' else value
    if value == 'none' and slot.value == 'primary':
        await interaction.response.send_message("The primary can't be `none`.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    if value and value != 'none' and value not in (await llm.status())['available']:
        await interaction.followup.send(
            f"`{value}` isn't a chat model Groq serves right now — pick one from the list.", ephemeral=True)
        return
    try:
        await api.post('/api/internal/settings', {'key': f'llm_{slot.value}', 'value': value,
                                                  'guild_id': str(interaction.guild_id)})
    except Exception as e:
        print(f'/llm set failed to save: {e}')
        await interaction.followup.send("Couldn't save that setting — try again in a bit.", ephemeral=True)
        return
    s = await llm.refresh(f'/llm set by {interaction.user.display_name}')
    chosen = s[slot.value]
    note = (f"\n⚠️ `{value}` didn't answer a test call, so `{chosen}` is being used instead."
            if value and value != 'none' and chosen != value else '')
    await interaction.followup.send(f"✓ {slot.name} model: `{chosen or 'none'}`{note}", ephemeral=True)


@llm_set.autocomplete('model')
async def llm_model_autocomplete(interaction: discord.Interaction, current: str):
    try:
        options = ['auto'] + (await llm.status())['available']
    except Exception:
        options = ['auto']
    if getattr(interaction.namespace, 'slot', None) == 'fallback':
        options.append('none')
    cur = (current or '').lower()
    return [app_commands.Choice(name=o, value=o) for o in options if cur in o.lower()][:25]


client.tree.add_command(llm_admin)

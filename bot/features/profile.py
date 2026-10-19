"""/profile and giving kernels.
"""

from datetime import datetime
import discord
from discord import app_commands
from api import ApiError
import embeds
from .shared import NO_ACCOUNT_MSG, SITE_URL, api, client, club, discord_identity, register, reply_failure, tell
from . import alerts      # used at call time, so the order they load in doesn't matter


# ─── /profile ─────────────────────────────────────────────────────────────────

class ProfileModal(discord.ui.Modal, title='Your Cinema Club profile'):
    def __init__(self, ident, profile):
        super().__init__()
        self.ident = ident
        u = profile['user']
        self.bio = discord.ui.TextInput(label='Bio', style=discord.TextStyle.paragraph,
                                        required=False, max_length=500, default=u.get('bio') or None)
        self.letterboxd = discord.ui.TextInput(label='Letterboxd username', required=False,
                                               max_length=60, default=u.get('letterboxd_username') or None)
        self.add_item(self.bio)
        self.add_item(self.letterboxd)

    async def on_submit(self, interaction: discord.Interaction):
        await ProfileView.save(interaction, self.ident, {
            'bio': self.bio.value, 'letterboxd_username': self.letterboxd.value})


class ProfileView(discord.ui.View):
    """Edit controls under your own /profile card (only you see them), and
    your History and Watchlist."""

    def __init__(self, ident, profile):
        super().__init__(timeout=600)
        self.ident, self.profile = ident, profile
        mine = {g['key'] for g in profile['genres']}
        options = [discord.SelectOption(label=g['label'], value=g['key'], default=g['key'] in mine)
                   for g in profile['genre_options'][:25]]
        self.genres = discord.ui.Select(placeholder='Favorite genres (for recommendations)',
                                        min_values=0, max_values=len(options), options=options, row=0)
        self.genres.callback = self.on_genres
        self.add_item(self.genres)
        for what in ('hist', 'watch'):
            self.add_item(ProfileButton(what, ident['discord_user_id'], row=1))
        self.add_item(discord.ui.Button(label='✨ Your taste on the site', url=f'{SITE_URL}/me?tab=settings#settings-taste', row=2))

    async def on_genres(self, interaction: discord.Interaction):
        await self.save(interaction, self.ident, {'genres': self.genres.values})

    @discord.ui.button(label='Edit bio & Letterboxd', emoji='✏️', style=discord.ButtonStyle.secondary, row=1)
    async def edit_text(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ProfileModal(self.ident, self.profile))

    @staticmethod
    async def save(interaction, ident, fields):
        await interaction.response.defer()
        try:
            profile = await api.post('/api/internal/profile', {**ident, **fields})
        except Exception as e:
            print(f'/profile save failed: {e}')
            await tell(interaction, "Couldn't save that — try again in a bit.")
            return
        await interaction.edit_original_response(embed=embeds.profile_embed(profile, own=True),
                                                 view=ProfileView(ident, profile))


def member_profile_view(member_discord_id, profile):
    """Under someone else's /profile: their History and Watchlist, Compare,
    Give kernels, and their page on the site."""
    view = discord.ui.View(timeout=None)
    for what in ('hist', 'watch', 'cmp', 'give'):
        view.add_item(ProfileButton(what, member_discord_id))
    view.add_item(discord.ui.Button(label='Profile on the site', url=f"{SITE_URL}/people/{profile['user']['id']}"))
    return view


PROFILE_BUTTONS = {'hist': ('🎞️ History', discord.ButtonStyle.secondary),
                   'watch': ('📋 Watchlist', discord.ButtonStyle.secondary),
                   'cmp': ('🤝 Compare', discord.ButtonStyle.secondary),
                   'give': ('🍿 Give kernels', discord.ButtonStyle.primary)}


class ProfileButton(discord.ui.DynamicItem[discord.ui.Button], template=r'prof:(?P<what>hist|watch|cmp|give):(?P<did>[0-9]+)'):
    """History / Watchlist / Compare / Give kernels under a /profile card —
    for the person the card is about (custom id: their Discord id)."""
    def __init__(self, what, discord_id, row=None):
        label, style = PROFILE_BUTTONS[what]
        super().__init__(discord.ui.Button(label=label, style=style, row=row, custom_id=f'prof:{what}:{discord_id}'))
        self.what, self.discord_id = what, str(discord_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['what'], match['did'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        own = self.discord_id == str(interaction.user.id)
        if own and self.what in ('cmp', 'give'):
            await tell(interaction, "That's you — pick someone else's profile.")
            return
        await {'hist': send_history, 'watch': send_watchlist, 'cmp': send_compare,
               'give': send_give}[self.what](interaction, None if own else self.discord_id)


async def member_failure(interaction, e, what, member_discord_id, missing, fallback=None):
    """A failed lookup from someone's /profile buttons: a 404 is about them
    (`missing`), not you; anything else is api_failure's wording."""
    if member_discord_id and isinstance(e, ApiError) and e.status == 404:
        await tell(interaction, missing)
    else:
        await reply_failure(interaction, e, what, fallback)


async def send_history(interaction, member_discord_id=None):
    """A watch history, privately (after a defer). Your own has Went /
    Didn't go buttons for the latest screenings you haven't checked in to."""
    try:
        if member_discord_id:
            data = await api.get('/api/internal/history', member_discord_id=member_discord_id, group_id=club())
        else:
            data = await api.get('/api/internal/history', **discord_identity(interaction))
    except Exception as e:
        await member_failure(interaction, e, 'profile history', member_discord_id,
                             "They haven't been to anything with the club yet.", 'History lookup failed ({status}).')
        return
    now = datetime.now().isoformat()
    unchecked = [i for i in data.get('items') or [] if data.get('own') and i['status'] == 'going' and i['start_time'] < now][:4]
    view = alerts.attendance_view(unchecked) if unchecked else discord.ui.View()
    view.add_item(discord.ui.Button(label='On the site', row=len(unchecked), url=f"{SITE_URL}/me" if data.get('own')
                                    else f"{SITE_URL}/people/{data['user_id']}"))
    await interaction.followup.send(embed=embeds.history_embed(data, check_in=bool(unchecked)), view=view, ephemeral=True)


async def send_watchlist(interaction, member_discord_id=None):
    try:
        data = await api.get('/api/internal/watchlist', **discord_identity(interaction), member_discord_id=member_discord_id)
    except Exception as e:
        await member_failure(interaction, e, 'profile watchlist', member_discord_id,
                             "They haven't used Cinema Club yet.", 'Watchlist lookup failed ({status}).')
        return
    await interaction.followup.send(embed=embeds.watchlist_embed(data.get('items', []), data.get('owner', 'Someone')),
                                    ephemeral=True)


async def send_compare(interaction, member_discord_id):
    try:
        data = await api.get('/api/internal/compare', **discord_identity(interaction), member_discord_id=member_discord_id)
    except Exception as e:
        await member_failure(interaction, e, 'profile compare', member_discord_id,
                             "They haven't used Cinema Club yet.", 'Compare failed ({status}).')
        return
    await interaction.followup.send(embed=embeds.compare_embed(data), ephemeral=True)


@client.tree.command(name='profile', description="Your profile — or a member's: history, watchlist, compare, give kernels")
@app_commands.describe(member='Whose profile to see (default: yours, with edit controls)')
async def profile(interaction: discord.Interaction, member: discord.User = None):
    await interaction.response.defer(ephemeral=True)
    try:
        if member and member.id != interaction.user.id:
            data = await api.get('/api/internal/profile', member_discord_id=str(member.id))
            await interaction.followup.send(embed=embeds.profile_embed(data), view=member_profile_view(member.id, data),
                                            ephemeral=True)
            return
        ident = discord_identity(interaction)
        data = await api.get('/api/internal/profile', **ident)
    except ApiError as e:
        if e.status == 404 and member and member.id != interaction.user.id:     # about them, not you
            await interaction.followup.send(f"{member.display_name} hasn't used Cinema Club yet.", ephemeral=True)
        else:
            await reply_failure(interaction, e, '/profile', 'Profile lookup failed ({status}).', NO_ACCOUNT_MSG)
        return
    except Exception as e:
        await reply_failure(interaction, e, '/profile')
        return
    await interaction.followup.send(embed=embeds.profile_embed(data, own=True),
                                    view=ProfileView(ident, data), ephemeral=True)


# ─── Give kernels (R10b, from /profile) ───────────────────────────────────────
# The feed's 🍿 buttons in Discord: pick one of a member's screenings from
# lately (what they did on it), then +1 / −1 — the same weekly allowance and
# rules as the site (kernels.toss).

def give_view(member_discord_id, data, showtime_id=None):
    view = discord.ui.View(timeout=None)
    cards = data.get('cards') or []
    if not cards:
        return view
    view.add_item(GiveSelect(member_discord_id, [
        discord.SelectOption(label=f"{c['screening']['title']} · {embeds.short_day(c['screening']['start_time'])}"[:100],
                             description=embeds.GIVE_DID.get(c['did'], c['did'])[:100], value=str(c['screening']['showtime_id']),
                             default=c['screening']['showtime_id'] == showtime_id)
        for c in cards[:25]]))
    if showtime_id:
        view.add_item(GiveButton('up', member_discord_id, showtime_id))
        view.add_item(GiveButton('down', member_discord_id, showtime_id))
    return view


async def send_give(interaction, member_discord_id):
    try:
        data = await api.get('/api/internal/kernels/cards', **discord_identity(interaction), member_discord_id=member_discord_id)
    except Exception as e:
        await member_failure(interaction, e, 'give kernels', member_discord_id, "They haven't used Cinema Club yet.")
        return
    await interaction.followup.send(embed=embeds.give_embed(data), view=give_view(member_discord_id, data), ephemeral=True)


class GiveSelect(discord.ui.DynamicItem[discord.ui.Select], template=r'give:pick:(?P<did>[0-9]+)'):
    """Which of their screenings to give a kernel for."""
    def __init__(self, member_discord_id, options=None):
        super().__init__(discord.ui.Select(custom_id=f'give:pick:{member_discord_id}', placeholder='Pick a screening…',
                                           options=options or [discord.SelectOption(label='—', value='0')]))
        self.member_discord_id = str(member_discord_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['did'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        values = (interaction.data or {}).get('values') or []
        sid = int(values[0]) if values and values[0].isdigit() else None
        try:
            data = await api.get('/api/internal/kernels/cards', **discord_identity(interaction),
                                 member_discord_id=self.member_discord_id)
        except Exception as e:
            await reply_failure(interaction, e, 'give kernels')
            return
        await interaction.edit_original_response(embed=embeds.give_embed(data, sid),
                                                 view=give_view(self.member_discord_id, data, sid))


class GiveButton(discord.ui.DynamicItem[discord.ui.Button], template=r'give:(?P<d>up|down):(?P<did>[0-9]+):(?P<sid>[0-9]+)'):
    """+1 🍿 / −1 for the picked screening (the opposite undoes one)."""
    def __init__(self, direction, member_discord_id, showtime_id):
        up = direction == 'up'
        super().__init__(discord.ui.Button(label='+1 🍿' if up else '−1', custom_id=f'give:{direction}:{member_discord_id}:{showtime_id}',
                                           style=discord.ButtonStyle.success if up else discord.ButtonStyle.secondary))
        self.direction, self.member_discord_id, self.showtime_id = direction, str(member_discord_id), int(showtime_id)

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match['d'], match['did'], match['sid'])

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await api.post('/api/internal/kernels/toss', {
                **discord_identity(interaction), 'member_discord_id': self.member_discord_id,
                'showtime_id': self.showtime_id, 'delta': 1 if self.direction == 'up' else -1})
        except Exception as e:
            await reply_failure(interaction, e, 'give kernels')
            return
        await interaction.edit_original_response(embed=embeds.give_embed(data, self.showtime_id),
                                                 view=give_view(self.member_discord_id, data, self.showtime_id))


register(items=(ProfileButton, GiveSelect, GiveButton,))

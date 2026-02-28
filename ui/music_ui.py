import discord
import logging
from database import queries

log = logging.getLogger(__name__)

def generate_edit_embed(musics: list, current_page: int, items_per_page: int) -> discord.Embed:
    """Builds the visual embed for the paginated list."""
    embed = discord.Embed(title="⚙️ Modify Music Library", color=discord.Color.orange())

    start_idx = current_page * items_per_page
    end_idx = start_idx + items_per_page
    page_items = musics[start_idx:end_idx]

    desc = "**Select a track from the dropdown below to edit its properties.**\n\n"
    for item in page_items:
        vol = item.get('volume', 1.0)
        themes = item['themes'] if item['themes'] else "None"
        desc += f"`{item['id']}.` **{item['name']}** *(Vol: {vol} | Themes: {themes})*\n"

    total_pages = (len(musics) - 1) // items_per_page + 1
    desc += f"\n*Page {current_page + 1} of {total_pages} | Total Tracks: {len(musics)}*"
    embed.description = desc
    return embed


class EditMusicModal(discord.ui.Modal):
    """A modal popup to edit the properties of a selected music track."""
    def __init__(self, bot, music_data):
        super().__init__(title=f"Edit: {music_data['name'][:30]}")
        self.bot = bot
        self.music_id = music_data['id']

        self.music_name = discord.ui.TextInput(
            label="Music Name",
            default=music_data['name'],
            max_length=200
        )
        self.themes = discord.ui.TextInput(
            label="Themes (comma-separated)",
            default=music_data['themes'] or "",
            max_length=300
        )
        self.intensity = discord.ui.TextInput(
            label="Intensity (0-100)",
            default=str(music_data['intensity']) if music_data['intensity'] is not None else "",
            required=False
        )
        self.volume = discord.ui.TextInput(
            label="Volume (e.g., 0.5, 1.0)",
            default=str(music_data['volume']) if music_data.get('volume') is not None else "1.0",
            required=False
        )

        self.add_item(self.music_name)
        self.add_item(self.themes)
        self.add_item(self.intensity)
        self.add_item(self.volume)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            try:
                intensity_val = int(self.intensity.value) if self.intensity.value else None
                volume_val = float(self.volume.value) if self.volume.value else 1.0
            except ValueError:
                await interaction.followup.send("❌ Intensity must be an integer and Volume must be a number.", ephemeral=True)
                return

            themes_list = [t.strip().upper() for t in self.themes.value.split(',') if t.strip()]

            success, msg = await queries.update_music(
                self.bot.db_pool,
                self.music_id,
                self.music_name.value,
                themes_list,
                intensity_val,
                volume_val
            )

            if success:
                await interaction.followup.send(f"✅ {msg}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)

        except Exception as e:
            log.error(f"Unhandled exception in EditMusicModal.on_submit: {e}", exc_info=True)
            await interaction.followup.send("❌ An unexpected error occurred while processing the modal.", ephemeral=True)


class EditMusicSelectView(discord.ui.View):
    """An interactive paginated dropdown menu to select a track to edit."""
    def __init__(self, bot, musics, current_page=0):
        super().__init__(timeout=None)
        self.bot = bot
        self.musics = musics
        self.current_page = current_page
        self.items_per_page = 25

        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.musics[start_idx:end_idx]

        options = []
        for item in page_items:
            options.append(discord.SelectOption(
                label=item['name'][:100],
                value=str(item['id']),
                description=f"Themes: {item['themes'][:40] if item['themes'] else 'None'}"
            ))

        if options:
            select = discord.ui.Select(
                placeholder="Select a music track to edit...",
                options=options,
                row=0
            )
            select.callback = self.select_callback
            self.add_item(select)

        total_pages = (len(self.musics) - 1) // self.items_per_page + 1
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="Prev Page", style=discord.ButtonStyle.secondary, row=1, disabled=(self.current_page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(label="Next Page", style=discord.ButtonStyle.secondary, row=1, disabled=(self.current_page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        music_id = int(interaction.data["values"][0])
        music_data = next((m for m in self.musics if m['id'] == music_id), None)
        if music_data:
            await interaction.response.send_modal(EditMusicModal(self.bot, music_data))
        else:
            await interaction.response.send_message("Music not found.", ephemeral=True)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        await self.update_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        embed = generate_edit_embed(self.musics, self.current_page, self.items_per_page)
        await interaction.response.edit_message(embed=embed, view=EditMusicSelectView(self.bot, self.musics, self.current_page))
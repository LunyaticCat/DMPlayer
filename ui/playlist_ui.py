import discord

ITEMS_PER_PAGE = 25

class PlaylistView(discord.ui.View):
    """An interactive UI View that attaches to the playlist embed."""
    def __init__(self, cog, guild_id: int, queue_data: dict):
        super().__init__(timeout=None)
        self.cog = cog
        self.guild_id = guild_id
        self.queue_data = queue_data

        playlist = queue_data['playlist']
        current_index = queue_data['current_index']
        current_page = queue_data['current_page']
        is_stopped = queue_data['is_stopped']

        start_idx = current_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = playlist[start_idx:end_idx]

        options = []
        for i, (url, title, track_vol) in enumerate(page_items):
            absolute_idx = start_idx + i
            is_playing = (absolute_idx == current_index and not is_stopped)
            options.append(discord.SelectOption(
                label=title[:100],
                value=str(absolute_idx),
                description="Currently Playing" if is_playing else None,
                emoji="▶️" if is_playing else None
            ))

        if options:
            select = discord.ui.Select(
                placeholder="Select a song to play...",
                options=options,
                row=0
            )
            select.callback = self.select_callback
            self.add_item(select)

        total_pages = (len(playlist) - 1) // ITEMS_PER_PAGE + 1
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="Prev Page", style=discord.ButtonStyle.secondary, row=1, disabled=(current_page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(label="Next Page", style=discord.ButtonStyle.secondary, row=1, disabled=(current_page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        index = int(interaction.data["values"][0])
        await self.cog.jump_to_song(interaction.guild, index)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, emoji="⏭️", row=2)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.skip_logic(interaction.guild)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="🛑", row=2)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await self.cog.stop_logic(interaction.guild)

    async def prev_page(self, interaction: discord.Interaction):
        self.queue_data['current_page'] -= 1
        await interaction.response.edit_message(embed=self.cog.generate_embed(self.queue_data), view=PlaylistView(self.cog, self.guild_id, self.queue_data))

    async def next_page(self, interaction: discord.Interaction):
        self.queue_data['current_page'] += 1
        await interaction.response.edit_message(embed=self.cog.generate_embed(self.queue_data), view=PlaylistView(self.cog, self.guild_id, self.queue_data))
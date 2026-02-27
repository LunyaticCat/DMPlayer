import asyncio
import logging
import os
from typing import List, Optional, Dict, Tuple

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

FADE_DURATION_S = float(os.getenv('FADE_DURATION', '2.0'))
FADE_STEPS = int(os.getenv('FADE_STEPS', '20'))
DEFAULT_VOLUME = float(os.getenv('DEFAULT_VOLUME', '0.5'))
ITEMS_PER_PAGE = 25

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


async def _fade_out(guild: discord.Guild):
    """
    Gradually decreases the volume of the active voice client to zero over a set duration,
    then completely stops playback.

    :param guild: The Discord guild where the voice client is active.
    """
    voice_client = guild.voice_client
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'volume'):
        current_player = voice_client.source
        for i in range(FADE_STEPS, -1, -1):
            volume = DEFAULT_VOLUME * (i / FADE_STEPS)
            current_player.volume = max(0.0, volume)
            await asyncio.sleep(FADE_DURATION_S / FADE_STEPS)
        voice_client.stop()


async def _fade_in(guild: discord.Guild):
    """
    Gradually increases the volume of the newly started voice client up to the default volume.

    :param guild: The Discord guild where the voice client is active.
    """
    voice_client = guild.voice_client
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'volume'):
        player = voice_client.source
        for i in range(FADE_STEPS + 1):
            volume = DEFAULT_VOLUME * (i / FADE_STEPS)
            player.volume = min(DEFAULT_VOLUME, volume)
            await asyncio.sleep(FADE_DURATION_S / FADE_STEPS)


class PlaylistView(discord.ui.View):
    """
    An interactive UI View that attaches to the playlist embed.
    It provides a dropdown menu to select specific songs, alongside playback and pagination controls.
    """
    def __init__(self, cog: "AutoMusicCog", guild_id: int, queue_data: dict):
        """
        Initializes the PlaylistView components based on the current state of the queue.

        :param cog: The AutoMusicCog instance managing the playback.
        :param guild_id: The ID of the guild this UI belongs to.
        :param queue_data: The dictionary containing the playlist, page state, and current index.
        """
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
        for i, (url, title) in enumerate(page_items):
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
            prev_btn = discord.ui.Button(label="Prev Page", style=discord.ButtonStyle.secondary, row=1,
                                         disabled=(current_page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(label="Next Page", style=discord.ButtonStyle.secondary, row=1,
                                         disabled=(current_page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        """
        Handles the event when a user selects a song from the dropdown menu.
        """
        await interaction.response.defer()
        index = int(interaction.data["values"][0])
        await self.cog.jump_to_song(interaction.guild, index)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary, emoji="⏭️", row=2)
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Handles the event when a user clicks the skip button.
        """
        await interaction.response.defer()
        await self.cog.skip_logic(interaction.guild)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="🛑", row=2)
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """
        Handles the event when a user clicks the stop button.
        """
        await interaction.response.defer()
        await self.cog.stop_logic(interaction.guild)

    async def prev_page(self, interaction: discord.Interaction):
        """
        Handles flipping to the previous page of the playlist.
        """
        self.queue_data['current_page'] -= 1
        await interaction.response.edit_message(embed=self.cog.generate_embed(self.queue_data),
                                                view=PlaylistView(self.cog, self.guild_id, self.queue_data))

    async def next_page(self, interaction: discord.Interaction):
        """
        Handles flipping to the next page of the playlist.
        """
        self.queue_data['current_page'] += 1
        await interaction.response.edit_message(embed=self.cog.generate_embed(self.queue_data),
                                                view=PlaylistView(self.cog, self.guild_id, self.queue_data))


class AutoMusicCog(commands.Cog):
    """
    A Discord cog that manages automated music playback based on database-driven themes.
    It handles audio streaming, smooth transitions, and an interactive UI.
    """
    def __init__(self, bot: commands.Bot):
        """
        Initializes the AutoMusicCog.

        :param bot: The main Discord bot instance.
        """
        self.bot = bot
        self.queues: Dict[int, Dict] = {}
        self.transition_lock = asyncio.Lock()

    def generate_embed(self, queue_data: dict) -> discord.Embed:
        """
        Builds the Discord embed that visually represents the current playlist state,
        including the active track, playback status, and pagination indicators.

        :param queue_data: The dictionary containing the playlist and pagination data.
        :return: A fully constructed discord.Embed object.
        """
        playlist = queue_data['playlist']
        current_index = queue_data['current_index']
        current_page = queue_data['current_page']
        is_stopped = queue_data['is_stopped']
        theme_str = queue_data.get('theme_str', 'Custom')

        status = "🛑 Stopped" if is_stopped else "▶️ Playing"
        embed = discord.Embed(title=f"🎶 AutoPlay Playlist: {theme_str.title()}",
                              description=f"**Status:** {status}\n\n", color=discord.Color.blurple())

        start_idx = current_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = playlist[start_idx:end_idx]

        desc = embed.description
        for i, (url, title) in enumerate(page_items):
            absolute_idx = start_idx + i
            if absolute_idx == current_index and not is_stopped:
                desc += f"▶️ **{title}**\n"
            else:
                desc += f"`{absolute_idx + 1}.` {title}\n"

        total_pages = (len(playlist) - 1) // ITEMS_PER_PAGE + 1
        desc += f"\n*Page {current_page + 1} of {total_pages} | Total Tracks: {len(playlist)}*"

        embed.description = desc
        return embed

    async def update_player_ui(self, guild_id: int):
        """
        Edits the existing playlist message to reflect the current state of playback.

        :param guild_id: The ID of the guild where the UI needs updating.
        """
        queue_data = self.queues.get(guild_id)
        if not queue_data or not queue_data.get('message'):
            return

        embed = self.generate_embed(queue_data)
        view = PlaylistView(self, guild_id, queue_data)

        try:
            await queue_data['message'].edit(embed=embed, view=view)
        except discord.HTTPException as e:
            log.warning(f"Failed to update player UI: {e}")

    async def _fetch_music_urls(self, themes: List[str], min_intensity: Optional[int], max_intensity: Optional[int]) -> List[Tuple[str, str]]:
        """
        Queries the database to fetch music URLs and titles matching the provided themes and intensity ranges.

        :param themes: A list of theme strings to filter the database query.
        :param min_intensity: The minimum intensity value for the music.
        :param max_intensity: The maximum intensity value for the music.
        :return: A list of tuples containing (url, title).
        :raises RuntimeError: If the bot does not have a connected database pool.
        """
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            raise RuntimeError("Database connection pool not found on bot.")

        def _query():
            num_themes = len(themes)
            if num_themes == 0:
                return []
            theme_placeholders = ', '.join(['%s'] * num_themes)
            sql_query = f"""
                SELECT m.url, m.name
                FROM musics m
                         JOIN themes_list tl ON m.id = tl.music_id
                         JOIN themes t ON tl.theme_id = t.id
                WHERE t.name IN ({theme_placeholders})
            """
            params = themes.copy()
            if min_intensity is not None:
                sql_query += " AND m.intensity >= %s"
                params.append(min_intensity)
            if max_intensity is not None:
                sql_query += " AND m.intensity <= %s"
                params.append(max_intensity)
            sql_query += " GROUP BY m.id, m.url, m.name"
            sql_query += " HAVING COUNT(DISTINCT t.id) = %s"
            params.append(num_themes)
            sql_query += " ORDER BY RAND()"

            conn = pool.get_connection()
            cursor = conn.cursor()
            cursor.execute(sql_query, tuple(params))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [(row[0], row[1]) for row in rows]

        return await asyncio.to_thread(_query)

    async def _fade_transition(self, guild: discord.Guild, new_source: discord.AudioSource):
        """
        Orchestrates the smooth audio crossfade transition between two tracks.

        :param guild: The Discord guild where playback is occurring.
        :param new_source: The audio source intended to play next.
        """
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return

        await _fade_out(guild)

        if not voice_client or not voice_client.is_connected():
            return

        player = discord.PCMVolumeTransformer(new_source, volume=0.0)

        def after_callback(err):
            if err:
                log.error(f"Playback error: {err}")
            queue_data = self.queues.get(guild.id)
            if not queue_data or queue_data.get('is_stopped'):
                return
            self.bot.loop.create_task(self._play_next_song(guild))

        try:
            voice_client.play(player, after=after_callback)
        except discord.errors.ClientException as e:
            log.warning(f"Aborted playback: Bot disconnected during transition. ({e})")
            return

        await _fade_in(guild)

    async def _play_next_song(self, guild: discord.Guild):
        """
        The core background loop that processes the queue, handles end-of-playlist events,
        and triggers the transition function for the next audio track.

        :param guild: The Discord guild where playback is occurring.
        """
        async with self.transition_lock:
            guild_id = guild.id
            voice_client = guild.voice_client

            if not voice_client or not voice_client.is_connected():
                if guild_id in self.queues:
                    del self.queues[guild_id]
                return

            queue_data = self.queues.get(guild_id)
            if not queue_data or queue_data.get('is_stopped'):
                return

            queue_data['current_index'] += 1

            if queue_data['current_index'] >= len(queue_data['playlist']):
                await queue_data['channel'].send("✅ Playlist finished.")
                try:
                    await queue_data['message'].edit(view=None)
                except:
                    pass
                del self.queues[guild_id]
                return

            try:
                url, title = queue_data['playlist'][queue_data['current_index']]
                if not url.startswith(('http://', 'https://')):
                    url = f'https://{url}'

                source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
                await self._fade_transition(guild, source)

                if voice_client and voice_client.is_connected():
                    if queue_data['current_index'] >= (queue_data['current_page'] + 1) * ITEMS_PER_PAGE:
                        queue_data['current_page'] += 1

                    self.bot.loop.create_task(self.update_player_ui(guild_id))

            except Exception as e:
                log.error(f"Failed to play next song: {e}", exc_info=True)
                if voice_client and voice_client.is_connected() and not queue_data.get('is_stopped'):
                    await asyncio.sleep(1)
                    await self._play_next_song(guild)

    async def jump_to_song(self, guild: discord.Guild, index: int):
        """
        Forces the player to jump to a specific index in the active playlist.

        :param guild: The Discord guild where playback is occurring.
        :param index: The integer index of the song to jump to.
        """
        if guild.id not in self.queues: return
        voice_client = guild.voice_client
        if not voice_client: return

        queue_data = self.queues[guild.id]
        queue_data['is_stopped'] = False
        queue_data['current_index'] = index - 1

        if voice_client.is_playing() or voice_client.is_paused():
            voice_client.stop()
        else:
            self.bot.loop.create_task(self._play_next_song(guild))

    async def skip_logic(self, guild: discord.Guild):
        """
        Stops the current track, immediately firing the callback to start the next song.

        :param guild: The Discord guild where playback is occurring.
        """
        voice_client = guild.voice_client
        if voice_client and voice_client.is_playing() and not self.transition_lock.locked():
            voice_client.stop()

    async def stop_logic(self, guild: discord.Guild):
        """
        Fades out the current track, sets the queue to a stopped state, and updates the UI.

        :param guild: The Discord guild where playback is occurring.
        """
        if guild.id not in self.queues: return

        queue_data = self.queues[guild.id]
        queue_data['is_stopped'] = True

        await _fade_out(guild)
        self.bot.loop.create_task(self.update_player_ui(guild.id))

    @app_commands.command(name="auto_play", description="Plays a playlist of music based on a theme and intensity.")
    @app_commands.describe(
        theme="A comma-separated list of themes to match (e.g., 'Combat, Boss').",
        min_intensity="The minimum intensity.",
        max_intensity="The maximum intensity."
    )
    async def auto_play(self, interaction: discord.Interaction, theme: str, min_intensity: Optional[int] = None,
                        max_intensity: Optional[int] = None):
        """
        Discord slash command that fetches music matching user criteria, establishes a voice connection,
        creates the interactive playlist UI, and initiates playback.
        """
        await interaction.response.defer()
        if not interaction.user.voice:
            await interaction.followup.send("You must be in a voice channel.", ephemeral=True)
            return

        themes_list = [t.strip().lower() for t in theme.split(',') if t.strip()]
        if not themes_list:
            await interaction.followup.send("Please provide at least one valid theme.", ephemeral=True)
            return

        try:
            songs_to_queue = await self._fetch_music_urls(themes_list, min_intensity, max_intensity)
            if not songs_to_queue:
                theme_str = "', '".join(themes_list)
                await interaction.followup.send(f"No music found matching all themes: '**{theme_str}**'.",
                                                ephemeral=True)
                return
        except Exception as e:
            log.error(f"Database error in auto_play: {e}", exc_info=True)
            await interaction.followup.send(f"A database error occurred.", ephemeral=True)
            return

        voice_client = interaction.guild.voice_client
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()

        guild_id = interaction.guild.id
        theme_str = ", ".join(themes_list)

        self.queues[guild_id] = {
            'playlist': songs_to_queue,
            'current_index': -1,
            'current_page': 0,
            'is_stopped': False,
            'channel': interaction.channel,
            'theme_str': theme_str
        }

        embed = self.generate_embed(self.queues[guild_id])
        view = PlaylistView(self, guild_id, self.queues[guild_id])
        message = await interaction.followup.send(embed=embed, view=view, wait=True)
        self.queues[guild_id]['message'] = message

        if not voice_client.is_playing() and not self.transition_lock.locked():
            await self._play_next_song(interaction.guild)

    @app_commands.command(name="skip", description="Skips the current song and plays the next in the queue.")
    async def skip(self, interaction: discord.Interaction):
        """
        Discord slash command to manually skip the currently playing track.
        """
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            await interaction.response.send_message("I'm not playing anything right now.", ephemeral=True)
            return
        if self.transition_lock.locked():
            await interaction.response.send_message("Please wait for the transition to finish.", ephemeral=True)
            return

        await interaction.response.send_message("⏭️ Skipping song...", ephemeral=True)
        await self.skip_logic(interaction.guild)

    @app_commands.command(name="stop", description="Stops the current playback but keeps the queue active.")
    async def stop(self, interaction: discord.Interaction):
        """
        Discord slash command to manually stop playback while preserving the interactive playlist menu.
        """
        await interaction.response.send_message("🛑 Stopping playback...", ephemeral=True)
        await self.stop_logic(interaction.guild)


async def setup(bot: commands.Bot):
    """
    Standard function required by discord.ext.commands to load the cog into the bot.
    """
    await bot.add_cog(AutoMusicCog(bot))
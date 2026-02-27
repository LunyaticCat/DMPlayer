# music_cog.py
import asyncio
import logging
import os
from collections import deque
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

# --- Configuration for playback ---
FADE_DURATION_S = float(os.getenv('FADE_DURATION', '2.0'))
FADE_STEPS = int(os.getenv('FADE_STEPS', '20'))
DEFAULT_VOLUME = float(os.getenv('DEFAULT_VOLUME', '0.5'))

# --- FFmpeg options for playing audio ---
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


async def _fade_out(interaction: discord.Interaction):
    """Fades out the current song and stops playback."""
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'volume'):
        current_player = voice_client.source
        for i in range(FADE_STEPS, -1, -1):
            volume = DEFAULT_VOLUME * (i / FADE_STEPS)
            # Ensure volume doesn't go below 0 due to float inaccuracies
            current_player.volume = max(0.0, volume)
            await asyncio.sleep(FADE_DURATION_S / FADE_STEPS)
        voice_client.stop()


async def _fade_in(interaction: discord.Interaction):
    """Fades in the currently playing song."""
    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'volume'):
        player = voice_client.source
        for i in range(FADE_STEPS + 1):
            volume = DEFAULT_VOLUME * (i / FADE_STEPS)
            # Ensure volume doesn't exceed the default
            player.volume = min(DEFAULT_VOLUME, volume)
            await asyncio.sleep(FADE_DURATION_S / FADE_STEPS)


class AutoMusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: Dict[int, Dict] = {}
        self.transition_lock = asyncio.Lock()

    async def _fetch_music_urls(self, themes: List[str], min_intensity: Optional[int], max_intensity: Optional[int]) -> \
    List[Tuple[str, str]]:
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

    async def _fade_transition(self, interaction: discord.Interaction, new_source: discord.AudioSource):
        """Handles the smooth transition between two songs."""
        voice_client = interaction.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return

        await _fade_out(interaction)

        if not voice_client or not voice_client.is_connected():
            return

        player = discord.PCMVolumeTransformer(new_source, volume=0.0)

        def after_callback(err):
            if err:
                log.error(f"Playback error: {err}")
            self.bot.loop.create_task(self._play_next_song(interaction))

        try:
            voice_client.play(player, after=after_callback)
        except discord.errors.ClientException as e:
            log.warning(f"Aborted playback: Bot disconnected during transition. ({e})")
            return

        await _fade_in(interaction)

    async def _play_next_song(self, interaction: discord.Interaction, from_queue: bool = True):
        """The core playback loop. Gets the next URL and calls the transition handler."""
        async with self.transition_lock:
            guild_id = interaction.guild.id
            voice_client = interaction.guild.voice_client

            if not voice_client or not voice_client.is_connected():
                if guild_id in self.queues:
                    self.queues[guild_id]['queue'].clear()
                    del self.queues[guild_id]
                return

            if from_queue and (guild_id not in self.queues or not self.queues[guild_id]['queue']):
                if guild_id in self.queues:
                    await self.queues[guild_id]['channel'].send("✅ Queue finished.")
                    del self.queues[guild_id]
                return

            try:
                url, title = self.queues[guild_id]['queue'].popleft()
                if not url.startswith(('http://', 'https://')):
                    url = f'https://{url}'

                source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
                await self._fade_transition(interaction, source)

                if voice_client and voice_client.is_connected():
                    await self.queues[guild_id]['channel'].send(f"▶️ Now playing: **{title}**")

            except Exception as e:
                log.error(f"Failed to play next song: {e}", exc_info=True)
                if voice_client and voice_client.is_connected():
                    if guild_id in self.queues:
                        await self.queues[guild_id]['channel'].send(f"❌ An error occurred. Skipping to the next song.")
                        await asyncio.sleep(1)
                        await self._play_next_song(interaction)



    @app_commands.command(name="auto_play", description="Plays a playlist of music based on a theme and intensity.")
    @app_commands.describe(
        theme="A comma-separated list of themes to match (e.g., 'Combat, Boss').",
        min_intensity="The minimum intensity.",
        max_intensity="The maximum intensity."
    )
    async def auto_play(self, interaction: discord.Interaction, theme: str, min_intensity: Optional[int] = None,
                        max_intensity: Optional[int] = None):
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
        if guild_id not in self.queues:
            self.queues[guild_id] = {'queue': deque(), 'channel': interaction.channel}

        self.queues[guild_id]['queue'].extend(songs_to_queue)
        theme_str = "', '".join(themes_list)
        await interaction.followup.send(
            f"✅ Added **{len(songs_to_queue)}** songs for themes '**{theme_str}**' to the queue.")

        if not voice_client.is_playing() and not self.transition_lock.locked():
            await self._play_next_song(interaction)

    @app_commands.command(name="skip", description="Skips the current song and plays the next in the queue.")
    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        guild_id = interaction.guild.id

        if not voice_client or not voice_client.is_playing():
            await interaction.response.send_message("I'm not playing anything right now.", ephemeral=True)
            return

        if guild_id not in self.queues or not self.queues[guild_id]['queue']:
            await interaction.response.send_message("The queue is empty, I can't skip.", ephemeral=True)
            return

        if self.transition_lock.locked():
            await interaction.response.send_message("Please wait for the current transition to finish.", ephemeral=True)
            return

        await interaction.response.send_message("⏭️ Skipping song...")
        voice_client.stop()

    @app_commands.command(name="stop", description="Stops the music, clears the queue, and disconnects.")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_id = interaction.guild.id
        if guild_id in self.queues:
            self.queues[guild_id]['queue'].clear()

        await _fade_out(interaction)

        await interaction.followup.send("⏹️ Music stopped and queue cleared.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMusicCog(bot))
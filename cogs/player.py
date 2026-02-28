import asyncio
import logging
import random
from typing import Optional, Dict

import discord
from discord import app_commands
from discord.ext import commands

from database import queries
from ui.playlist_ui import PlaylistView, ITEMS_PER_PAGE
from utils.audio_utils import fade_out, fade_in, FFMPEG_OPTIONS, DEFAULT_VOLUME

log = logging.getLogger(__name__)


class PlayerCog(commands.Cog):
    """A unified Discord cog that manages both Manual and Auto playback."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queues: Dict[int, Dict] = {}
        self.transition_lock = asyncio.Lock()

    def generate_embed(self, queue_data: dict) -> discord.Embed:
        """Builds the dynamic Discord embed based on the active play mode."""
        playlist = queue_data['playlist']
        current_index = queue_data['current_index']
        current_page = queue_data['current_page']
        is_stopped = queue_data['is_stopped']
        theme_str = queue_data.get('theme_str', 'All Tracks')
        is_auto = queue_data.get('auto_advance', True)

        title = "📻 AutoPlay Playlist" if is_auto else "🎧 Manual Library"
        status = "🛑 Stopped" if is_stopped else "▶️ Playing"

        embed = discord.Embed(title=f"{title}: {theme_str.title()}",
                              description=f"**Status:** {status}\n\n", color=discord.Color.blurple())

        start_idx = current_page * ITEMS_PER_PAGE
        end_idx = start_idx + ITEMS_PER_PAGE
        page_items = playlist[start_idx:end_idx]

        desc = embed.description
        for i, (url, title_str, track_vol) in enumerate(page_items):
            absolute_idx = start_idx + i
            if absolute_idx == current_index and not is_stopped:
                desc += f"▶️ **{title_str}**\n"
            else:
                desc += f"`{absolute_idx + 1}.` {title_str}\n"

        total_pages = max(1, (len(playlist) - 1) // ITEMS_PER_PAGE + 1)
        desc += f"\n*Page {current_page + 1} of {total_pages} | Total Tracks: {len(playlist)}*"

        embed.description = desc
        return embed

    async def update_player_ui(self, guild_id: int):
        queue_data = self.queues.get(guild_id)
        if not queue_data or not queue_data.get('message'):
            return

        embed = self.generate_embed(queue_data)
        view = PlaylistView(self, guild_id, queue_data)

        try:
            await queue_data['message'].edit(embed=embed, view=view)
        except discord.HTTPException as e:
            log.warning(f"Failed to update player UI: {e}")

    async def _fade_transition(self, guild: discord.Guild, new_source: discord.AudioSource, target_volume: float):
        voice_client = guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return

        await fade_out(guild)

        if not voice_client or not voice_client.is_connected():
            return

        player = discord.PCMVolumeTransformer(new_source, volume=0.0)

        def after_callback(err):
            if err:
                log.error(f"Playback error: {err}")
            queue_data = self.queues.get(guild.id)
            if not queue_data or queue_data.get('is_stopped'):
                return

            if queue_data.get('auto_advance'):
                self.bot.loop.create_task(self._play_next_song(guild))
            else:
                queue_data['is_stopped'] = True
                self.bot.loop.create_task(self.update_player_ui(guild.id))

        try:
            voice_client.play(player, after=after_callback)
        except discord.errors.ClientException as e:
            log.warning(f"Aborted playback: Bot disconnected during transition. ({e})")
            return

        await fade_in(guild, target_volume)

    async def _play_next_song(self, guild: discord.Guild):
        async with self.transition_lock:
            guild_id = guild.id
            voice_client = guild.voice_client

            if not voice_client or not voice_client.is_connected():
                if guild_id in self.queues: del self.queues[guild_id]
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
                url, title, track_vol = queue_data['playlist'][queue_data['current_index']]
                if not url.startswith(('http://', 'https://')):
                    url = f'https://{url}'

                target_volume = float(track_vol) if track_vol is not None else DEFAULT_VOLUME

                source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)

                await self._fade_transition(guild, source, target_volume)

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
        """Forces the player to jump to a specific index in the active playlist."""
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
        voice_client = guild.voice_client
        if voice_client and voice_client.is_playing() and not self.transition_lock.locked():
            voice_client.stop()

    async def stop_logic(self, guild: discord.Guild):
        if guild.id not in self.queues: return
        self.queues[guild.id]['is_stopped'] = True
        await fade_out(guild)
        self.bot.loop.create_task(self.update_player_ui(guild.id))

    async def _init_player(self, interaction: discord.Interaction, mode: str, theme: Optional[str],
                           min_intensity: Optional[int], max_intensity: Optional[int]):
        """The master bootstrapper for both manual and auto playback."""
        await interaction.response.defer()

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        if not interaction.user.voice:
            await interaction.followup.send("You must be in a voice channel.", ephemeral=True)
            return

        themes_list = [t.strip().lower() for t in theme.split(',')] if theme else None

        try:
            songs_to_queue = await queries.fetch_tracks(self.bot.db_pool, themes_list, min_intensity, max_intensity)
            if not songs_to_queue:
                await interaction.followup.send("No music found matching those filters.", ephemeral=True)
                return
        except Exception as e:
            log.error(f"Database error initializing player: {e}", exc_info=True)
            await interaction.followup.send(f"A database error occurred.", ephemeral=True)
            return

        is_auto = (mode == "auto")
        if is_auto:
            random.shuffle(songs_to_queue)

        voice_client = interaction.guild.voice_client
        if not voice_client:
            voice_client = await interaction.user.voice.channel.connect()

        guild_id = interaction.guild.id
        theme_str = f"{', '.join(themes_list) if themes_list else 'All'}"
        if min_intensity is not None or max_intensity is not None:
            theme_str += f" (Int: {min_intensity or 0}-{max_intensity or 100})"

        self.queues[guild_id] = {
            'playlist': songs_to_queue,
            'current_index': -1 if is_auto else 0,
            'current_page': 0,
            'is_stopped': not is_auto,
            'auto_advance': is_auto,
            'channel': interaction.channel,
            'theme_str': theme_str
        }

        embed = self.generate_embed(self.queues[guild_id])
        view = PlaylistView(self, guild_id, self.queues[guild_id])
        message = await interaction.followup.send(embed=embed, view=view, wait=True)
        self.queues[guild_id]['message'] = message

        if is_auto and not voice_client.is_playing() and not self.transition_lock.locked():
            await self._play_next_song(interaction.guild)

    @app_commands.command(name="auto_play", description="Plays a shuffled endless playlist based on filters.")
    @app_commands.describe(theme="Optional themes (comma-separated)", min_intensity="Min intensity",
                           max_intensity="Max intensity")
    async def auto_play(self, interaction: discord.Interaction, theme: Optional[str] = None,
                        min_intensity: Optional[int] = None, max_intensity: Optional[int] = None):
        await self._init_player(interaction, "auto", theme, min_intensity, max_intensity)

    @app_commands.command(name="manual_play", description="Choose a specific track to play from your library.")
    @app_commands.describe(theme="Optional themes (comma-separated)", min_intensity="Min intensity",
                           max_intensity="Max intensity")
    async def manual_play(self, interaction: discord.Interaction, theme: Optional[str] = None,
                          min_intensity: Optional[int] = None, max_intensity: Optional[int] = None):
        await self._init_player(interaction, "manual", theme, min_intensity, max_intensity)

    @app_commands.command(name="skip", description="Skips the current song.")
    async def skip(self, interaction: discord.Interaction):
        if not interaction.guild.voice_client or not interaction.guild.voice_client.is_playing():
            await interaction.response.send_message("I'm not playing anything right now.", ephemeral=True)
            return
        await interaction.response.send_message("⏭️ Skipping song...", ephemeral=True)
        await self.skip_logic(interaction.guild)

    @app_commands.command(name="stop", description="Stops the current playback but keeps the queue active.")
    async def stop(self, interaction: discord.Interaction):
        await interaction.response.send_message("🛑 Stopping playback...", ephemeral=True)
        await self.stop_logic(interaction.guild)


async def setup(bot: commands.Bot):
    await bot.add_cog(PlayerCog(bot))
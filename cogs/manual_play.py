# music_cog.py
import logging
import os
from urllib.parse import urlparse

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

DEFAULT_VOLUME = os.getenv('DEFAULT_VOLUME', '0.5')

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}


class ManualMusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="manual_play", description="Plays audio from a direct URL in your voice channel.")
    @app_commands.describe(url="The direct URL to the audio file (e.g., .mp3, .wav).")
    async def manual_play(self, interaction: discord.Interaction, url: str):
        """Plays audio from a given direct URL."""
        await interaction.response.defer()

        if not interaction.user or not getattr(interaction.user, "voice", None):
            await interaction.followup.send("You must be in a voice channel to use this command.")
            return
        channel = interaction.user.voice.channel
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Command must be used in a guild.")
            return

        me = guild.me or await guild.fetch_member(self.bot.user.id)
        perms = channel.permissions_for(me)
        if not perms.connect:
            await interaction.followup.send("I don't have permission to connect to your voice channel.")
            return
        if not perms.speak:
            await interaction.followup.send("I don't have permission to speak in your voice channel.")
            return

        voice_client = guild.voice_client
        try:
            if not voice_client:
                voice_client = await channel.connect()
            elif voice_client.channel != channel:
                await voice_client.move_to(channel)
        except Exception as e:
            log.exception("Failed to connect/move to voice channel")
            await interaction.followup.send(f"Could not connect to voice channel: {e}")
            return

        if voice_client.is_playing():
            voice_client.stop()

        try:
            source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
            player = discord.PCMVolumeTransformer(source, volume=float(DEFAULT_VOLUME))

            def after_play(err):
                if err:
                    log.error("Error in playback: %s", err)

            voice_client.play(player, after=after_play)

        except Exception as e:
            log.exception("Failed to start playback")
            await interaction.followup.send(f"Failed to play audio: {e}")
            return

        try:
            path = urlparse(url).path
            filename = os.path.basename(path)
        except Exception:
            filename = "Unknown Track"

        await interaction.followup.send(f"Now playing: **{filename}**")


async def setup(bot: commands.Bot):
    await bot.add_cog(ManualMusicCog(bot))
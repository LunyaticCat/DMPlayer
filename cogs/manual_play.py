# music_cog.py
import logging
import os

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()

DEFAULT_VOLUME = os.getenv('DEFAULT_VOLUME')
COOKIE_FILE_PATH = os.getenv('COOKIE_FILE_PATH')

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    #"quiet": True,
    "cookiefile": COOKIE_FILE_PATH,
    "verbose": True
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

class ManualMusicCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="manual_play", description="Plays audio from a YouTube URL in your current voice channel.")
    @app_commands.describe(url="The YouTube URL of the video to play.")
    async def manual_play(self, interaction: discord.Interaction, url: str):
        """Plays audio from a given YouTube URL."""
        await interaction.response.defer()

        if not interaction.user or not getattr(interaction.user, "voice", None):
            await interaction.followup.send("You must be in a voice channel to use this command.")
            return
        channel = interaction.user.voice.channel
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Command must be used in a guild.")
            return

        me = guild.me or guild.get_member(self.bot.user.id)
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

        try:
            if voice_client.is_playing():
                voice_client.stop()
        except Exception:
            print("Failed to stop playing")

        try:
            with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if "entries" in info:
                    info = info["entries"][0]
                audio_url = info.get("url")
                title = info.get("title", "Unknown title")
                if not audio_url:
                    raise RuntimeError("Couldn't extract a direct audio URL from yt-dlp.")
        except Exception as e:
            log.exception("yt-dlp error")
            await interaction.followup.send(f"Failed to fetch audio: {e}")
            return

        try:
            source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS)
            player = discord.PCMVolumeTransformer(source, volume=float(DEFAULT_VOLUME))

            def after_play(err):
                if err:
                    log.error("Error in playback: %s", err)

            voice_client.play(player, after=after_play)
        except Exception as e:
            log.exception("Failed to start playback")
            await interaction.followup.send(f"Failed to play audio: {e}")
            return

        await interaction.followup.send(f"Now playing: **{title}**")

async def setup(bot: commands.Bot):
    await bot.add_cog(ManualMusicCog(bot))

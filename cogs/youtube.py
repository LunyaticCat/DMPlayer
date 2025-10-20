import asyncio
import logging
import os

import discord
import yt_dlp
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

log = logging.getLogger(__name__)

load_dotenv()
DOWNLOAD_PATH = os.environ.get("DOWNLOAD_PATH")

class YoutubeCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="download", description="Downloads audio from a YouTube URL to the bot's local storage.")
    @app_commands.describe(url="The YouTube URL to download from.")
    async def download(self, interaction: discord.Interaction, url: str):
        """Downloads a YouTube video's audio and saves it locally as an MP3."""
        # Defer ephemerally so the response is only visible to the command user
        await interaction.response.defer(ephemeral=True)

        # Create the downloads directory if it doesn't exist
        os.makedirs(DOWNLOAD_PATH, exist_ok=True)

        # Configure yt-dlp to download and convert to MP3
        ydl_opts = {
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192', # Standard quality
            }],
            # Save files to the 'downloads' folder with a clean name
            'outtmpl': os.path.join(DOWNLOAD_PATH, '%(title)s.%(ext)s'),
            'noplaylist': True,
        }

        try:
            # yt-dlp's download process is blocking, so we run it in a separate thread
            # to avoid freezing the bot.
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await asyncio.to_thread(ydl.extract_info, url, download=True)
                title = info.get('title', 'Unknown Title')
                filename = f"{title}.mp3"

            # Send the success message with the required warning
            await interaction.followup.send(
                f"✅ **Download Complete!**\n"
                f"Saved as: `{filename}`\n\n"
                f"⚠️ **Warning:** This file was saved locally in the `{DOWNLOAD_PATH}` folder "
                f"on the machine hosting the bot. It has **not** been sent to you."
            )

        except Exception as e:
            log.error(f"yt-dlp download error: {e}")
            await interaction.followup.send(
                f"❌ **Download Failed.**\n"
                f"Could not process the URL. Please check the link or the bot's logs for more details."
            )

async def setup(bot: commands.Bot):
    await bot.add_cog(YoutubeCog(bot))
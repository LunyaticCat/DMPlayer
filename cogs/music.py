import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.app_commands import Range

from database import queries
from ui.music_ui import EditMusicSelectView, generate_edit_embed
from utils.drive_api import process_and_upload_mp3

log = logging.getLogger(__name__)

class MusicCog(commands.Cog):
    """A cog for managing the music library in the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="modify_music", description="Select and edit an existing music track's details.")
    @app_commands.checks.has_permissions(administrator=True)
    async def modify_music(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        try:
            musics = await queries.fetch_all_musics(self.bot.db_pool)
            if not musics:
                await interaction.followup.send("No music found in the database or database error occurred.", ephemeral=True)
                return

            embed = generate_edit_embed(musics, 0, 25)
            view = EditMusicSelectView(self.bot, musics, 0)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            log.error(f"Error executing modify_music command: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred while generating the music list.", ephemeral=True)

    @app_commands.command(name="add_music", description="Adds a music track and links it to one or more themes.")
    @app_commands.describe(
        name="Name to register the music under.",
        attachment="The MP3 file to upload.",
        theme="A comma-separated list of themes to link the music to.",
        intensity="The intensity of the music for these themes (0-100)."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_music(
            self,
            interaction: discord.Interaction,
            name: str,
            attachment: discord.Attachment,
            theme: str,
            intensity: Optional[Range[int, 0, 100]] = None
    ):
        await interaction.response.defer(ephemeral=True)

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        if not attachment.filename.lower().endswith('.mp3'):
            await interaction.followup.send("❌ Please upload a valid `.mp3` file.", ephemeral=True)
            return

        themes_list = [t.strip().upper() for t in theme.split(',') if t.strip()]
        if not themes_list:
            await interaction.followup.send("❌ At least one Theme is required.", ephemeral=True)
            return

        await interaction.followup.send("⏳ Processing your file... This may take a moment.", ephemeral=True)

        upload_success, result_or_error = await process_and_upload_mp3(attachment)

        if not upload_success:
            await interaction.edit_original_response(content=f"❌ {result_or_error}")
            return

        db_success, db_message = await queries.add_music_to_themes(
            self.bot.db_pool,
            name,
            result_or_error,
            themes_list,
            intensity
        )

        if db_success:
            await interaction.edit_original_response(content=f"✅ {db_message}")
        else:
            await interaction.edit_original_response(content=f"❌ {db_message}")

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
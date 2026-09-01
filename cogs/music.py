import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands
from discord.app_commands import Range

from database import queries
from ui.music_ui import EditMusicSelectView, generate_edit_embed
from utils import drive_api
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

    @app_commands.command(name="delete_music", description="Deletes a music track from the database and Google Drive.")
    @app_commands.describe(music_id="The ID of the music track to delete.")
    @app_commands.checks.has_permissions(administrator=True)
    async def delete_music(self, interaction: discord.Interaction, music_id: int):
        """
        Deletes a music track via Discord slash command and removes it from Google Drive.

        Parameters
        ----------
        interaction : discord.Interaction
            The interaction object.
        music_id : int
            The database ID of the music track.
        """
        await interaction.response.defer(ephemeral=True)

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        try:
            db_success, db_message, url = await queries.delete_music(self.bot.db_pool, music_id)

            if not db_success:
                await interaction.followup.send(f"❌ {db_message}")
                return

            response_msg = f"✅ {db_message}"

            if url and ("drive.google.com" in url or "googleapis.com" in url):
                drive_success, drive_message = await drive_api.delete_file_from_drive(url)
                if not drive_success:
                    response_msg += f"\n⚠️ {drive_message}"
                else:
                    response_msg += "\n✅ Successfully removed the file from Google Drive."
            else:
                response_msg += "\nℹ️ No valid Google Drive URL found, skipped cloud deletion."

            await interaction.followup.send(response_msg)

        except Exception as e:
            log.error(f"Failed to delete music '{music_id}': {e}", exc_info=True)
            await interaction.followup.send(f"An unexpected error occurred: `{e}`")

    @app_commands.command(name="list_unlisted", description="Lists all music tracks that have no associated themes.")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_unlisted(self, interaction: discord.Interaction):
        """
        Retrieves and displays a list of unlisted music tracks via Discord slash command.

        Parameters
        ----------
        interaction : discord.Interaction
            The interaction object.
        """
        await interaction.response.defer(ephemeral=True)

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        try:
            unlisted = await queries.fetch_unlisted_musics(self.bot.db_pool)

            if not unlisted:
                await interaction.followup.send("✅ No unlisted music found. Every track is properly linked!")
                return

            description = "\n".join([f"`{m['id']}` - **{m['name']}**" for m in unlisted])

            if len(description) > 4096:
                description = description[:4090] + "..."

            embed = discord.Embed(
                title="Unlisted Musics",
                description=description,
                color=discord.Color.orange()
            )
            await interaction.followup.send(embed=embed)

        except Exception as e:
            log.error(f"Failed to fetch unlisted musics: {e}", exc_info=True)
            await interaction.followup.send(f"❌ An unexpected error occurred: `{e}`")

async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))
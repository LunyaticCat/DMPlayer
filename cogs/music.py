import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from typing import Tuple, List, Optional
from discord.app_commands import Range

log = logging.getLogger(__name__)


class MusicCog(commands.Cog):
    """A cog for managing the music library in the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _add_music_to_themes(self, music_name: str, url: str, theme_names: List[str], intensity: Optional[int]) -> \
    Tuple[bool, str]:
        """
        Handles the database transaction to link one named music with URL to MULTIPLE themes with an optional intensity.
        """
        url = url.lower()
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            raise RuntimeError("Database connection pool not found on bot (bot.db_pool).")

        def _db_transaction():
            conn = pool.get_connection()
            cursor = conn.cursor()
            try:
                # Step 1: Verify all themes exist and collect their IDs.
                theme_ids = []
                for theme_name in theme_names:
                    cursor.execute("SELECT id FROM themes WHERE name = %s", (theme_name,))
                    theme_result = cursor.fetchone()
                    if not theme_result:
                        conn.rollback()
                        return False, f"The theme '**{theme_name}**' does not exist. No links were created."
                    theme_ids.append(theme_result[0])

                # Step 2: Get or create the music ID from the URL.
                cursor.execute("SELECT id FROM musics WHERE url = %s", (url,))
                music_result = cursor.fetchone()
                if music_result:
                    music_id = music_result[0]
                else:
                    cursor.execute("INSERT INTO musics (name, url, intensity) VALUES (%s, %s, %s)", (music_name, url, intensity,))
                    music_id = cursor.lastrowid
                    if not music_id:
                        raise RuntimeError("Failed to retrieve last inserted ID for new music.")

                # Step 3: Link the music to each theme, now including intensity.
                new_links = 0
                skipped_links = 0
                for theme_id in theme_ids:
                    try:
                        cursor.execute(
                            "INSERT INTO themes_list (theme_id, music_id) VALUES (%s, %s)",
                            (theme_id, music_id,)
                        )
                        new_links += 1
                    except Exception:
                        skipped_links += 1

                conn.commit()

                # Step 4: Construct a more detailed response message.
                message_parts = []
                if new_links > 0:
                    message_parts.append(f"Successfully created **{new_links}** new link(s).")
                if skipped_links > 0:
                    message_parts.append(f"Skipped **{skipped_links}** link(s) that already existed.")

                final_message = " ".join(message_parts)
                if intensity is not None:
                    final_message += f" with an intensity of **{intensity}**."
                else:
                    final_message += " with the default intensity of **50**."

                return True, final_message

            except Exception as e:
                conn.rollback()
                log.error(f"Database transaction failed in _add_music_to_themes: {e}")
                return False, "An unexpected database error occurred."
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_db_transaction)

    @app_commands.command(name="add_music", description="Adds a music track and links it to one or more themes.")
    @app_commands.describe(
        name="Name to register the music under.",
        url="The YouTube URL of the music.",
        theme="A comma-separated list of themes to link the music to.",
        intensity="The intensity of the music for these themes (0-100)."  # NEW
    )
    async def add_music(
            self,
            interaction: discord.Interaction,
            name: str,
            url: str,
            theme: str,
            intensity: Optional[Range[int, 0, 100]] = None
    ):
        await interaction.response.defer(ephemeral=True)
        themes_list = [t.strip().upper() for t in theme.split(',') if t.strip()]

        if not url.strip() or not themes_list:
            await interaction.followup.send("URL and at least one Theme are required.")
            return

        success, message = await self._add_music_to_themes(name, url.strip(), themes_list, intensity)

        if success:
            await interaction.followup.send(f"✅ {message}")
        else:
            await interaction.followup.send(f"❌ {message}")


async def setup(bot: commands.Bot):
    """Setup function to add the cog to the bot."""
    await bot.add_cog(MusicCog(bot))
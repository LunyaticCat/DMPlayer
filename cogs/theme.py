import asyncio
import logging
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Dict
log = logging.getLogger(__name__)


class ThemesCog(commands.Cog):
    """List and manage themes from the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _insert_theme(self, name: str) -> bool:
        """Inserts a new theme into the database. Returns True on success, False on failure."""

        name = name.upper()
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            raise RuntimeError("No MariaDB connection pool found on bot (bot.db_pool)")

        def _db_insert():
            conn = pool.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("INSERT INTO themes (name) VALUES (%s)", (name,))
                conn.commit()
                return True
            except Exception as e:
                log.error(f"Database error while inserting theme '{name}': {e}")
                conn.rollback()
                return False
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_db_insert)

    async def fetch_themes(self) -> List[Dict]:
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            raise RuntimeError("No MariaDB connection pool found on bot (bot.db_pool)")

        def _query():
            conn = pool.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, name FROM themes ORDER BY id")
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [{"id": r[0], "name": r[1]} for r in rows]

        return await asyncio.to_thread(_query)

    @app_commands.command(name="list_themes", description="List all themes from the database.")
    async def themes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            rows = await self.fetch_themes()
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch themes: `{e}`")
            return

        if not rows:
            await interaction.followup.send("No themes found.")
            return

        description = "\n".join(f"`{r['id']}` - **{r['name']}**" for r in rows)
        embed = discord.Embed(title="Themes", description=description, color=discord.Color.blurple())
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="add_theme", description="Adds a new theme to the database.")
    @app_commands.describe(name="The name of the new theme to add (e.g., 'Combat', 'Exploration').")
    async def add_theme(self, interaction: discord.Interaction, name: str):
        # Defer ensures Discord doesn't time out while we wait for the database
        await interaction.response.defer(ephemeral=True)

        if not name or not name.strip():
            await interaction.followup.send("Theme name cannot be empty.")
            return

        try:
            success = await self._insert_theme(name.strip())
            if success:
                await interaction.followup.send(f"✅ Theme '**{name}**' was added successfully!")
            else:
                await interaction.followup.send(f"❌ Failed to add theme '**{name}**'.")
        except Exception as e:
            await interaction.followup.send(f"An unexpected error occurred: `{e}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(ThemesCog(bot))
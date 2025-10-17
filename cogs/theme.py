import asyncio
import discord
from discord import app_commands
from discord.ext import commands
from typing import List, Dict


class ThemesCog(commands.Cog):
    """List themes from the database (using a mariadb.ConnectionPool)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

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

        # Run blocking query in a thread
        return await asyncio.to_thread(_query)

    @app_commands.command(name="themes", description="List all themes from the database.")
    async def themes(self, interaction: discord.Interaction):
        await interaction.response.defer()
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
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(ThemesCog(bot))

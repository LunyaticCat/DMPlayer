import logging
import discord
from discord import app_commands
from discord.ext import commands

from database import queries

log = logging.getLogger(__name__)


class ThemesCog(commands.Cog):
    """List and manage themes from the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="list_themes", description="List all themes from the database.")
    async def themes(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        try:
            rows = await queries.fetch_all_themes(self.bot.db_pool)
        except Exception as e:
            log.error(f"Failed to fetch themes: {e}", exc_info=True)
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
    @app_commands.checks.has_permissions(administrator=True)
    async def add_theme(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)

        if not name or not name.strip():
            await interaction.followup.send("Theme name cannot be empty.")
            return

        if not hasattr(self.bot, "db_pool"):
            await interaction.followup.send("❌ Database connection missing.", ephemeral=True)
            return

        clean_name = name.strip().upper()

        try:
            success = await queries.insert_theme(self.bot.db_pool, clean_name)
            if success:
                await interaction.followup.send(f"✅ Theme '**{clean_name}**' was added successfully!")
            else:
                await interaction.followup.send(f"❌ Failed to add theme '**{clean_name}**'. It might already exist.")
        except Exception as e:
            log.error(f"Failed to add theme '{clean_name}': {e}", exc_info=True)
            await interaction.followup.send(f"An unexpected error occurred: `{e}`")


async def setup(bot: commands.Bot):
    await bot.add_cog(ThemesCog(bot))
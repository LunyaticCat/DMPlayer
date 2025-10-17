import discord
from discord import app_commands
from discord.ext import commands

class PingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="ping",
        description="Should answer Pong, verify if everything works"
    )
    async def ping_command(self, interaction: discord.Interaction):
        """Responds with Pong!"""
        await interaction.response.send_message("Pong!", ephemeral=True)

async def setup(bot: commands.Bot):
    """Setup function called on self.load_extension() use"""
    await bot.add_cog(PingCog(bot))

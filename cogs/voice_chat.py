import discord
from discord import app_commands
from discord.ext import commands

class VoiceChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="join",
        description="Makes the bot join the voice channel you are currently in."
    )
    async def join_command(self, interaction: discord.Interaction):
        """Join the voice channel currently used by the member calling the function."""
        # Check if the user is in a voice channel.
        if interaction.user.voice and interaction.user.voice.channel:
            channel = interaction.user.voice.channel

            # Check if the bot is already connected to a voice channel in this guild.
            if interaction.guild.voice_client:
                # If it is, move to the user's channel.
                await interaction.guild.voice_client.move_to(channel)
                await interaction.response.send_message("Moving to your channel !", ephemeral=True)
            else:
                # If not, connect to the user's channel.
                await channel.connect()
                await interaction.response.send_message("Connecting to your channel !", ephemeral=True)
        else:
            await interaction.response.send_message("You need to be in a voice channel to use this command.", ephemeral=True)

    @app_commands.command(
        name="leave",
        description="Makes the bot leave its current voice channel."
    )
    async def leave_command(self, interaction: discord.Interaction):
        """Leave the voice channel the bot is currently in."""
        # Check if the bot is in a voice channel in this guild.
        if interaction.guild.voice_client:
            # Disconnect from the voice channel.
            await interaction.guild.voice_client.disconnect(force=False)
            await interaction.response.send_message("Disconnected from the voice channel.", ephemeral=True)
        else:
            # If the bot is not in a voice channel, inform the user.
            await interaction.response.send_message("I'm not in a voice channel.", ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function called on self.load_extension() use"""
    await bot.add_cog(VoiceChatCog(bot))
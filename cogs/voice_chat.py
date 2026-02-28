import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger(__name__)


class VoiceChatCog(commands.Cog):
    """Commands for manually controlling the bot's voice presence."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="join",
        description="Makes the bot join the voice channel you are currently in."
    )
    async def join_command(self, interaction: discord.Interaction):
        """Join the voice channel currently used by the member calling the function."""
        if not interaction.user.voice or not interaction.user.voice.channel:
            await interaction.response.send_message("❌ You need to be in a voice channel to use this command.",
                                                    ephemeral=True)
            return

        channel = interaction.user.voice.channel
        guild = interaction.guild
        me = guild.me or await guild.fetch_member(self.bot.user.id)

        perms = channel.permissions_for(me)
        if not perms.connect:
            await interaction.response.send_message("❌ I don't have permission to connect to your voice channel.",
                                                    ephemeral=True)
            return

        try:
            if guild.voice_client:
                if guild.voice_client.channel != channel:
                    await guild.voice_client.move_to(channel)
                    await interaction.response.send_message(f"✅ Moved to **{channel.name}**!", ephemeral=True)
                else:
                    await interaction.response.send_message("I'm already in your channel!", ephemeral=True)
            else:
                await channel.connect()
                await interaction.response.send_message(f"✅ Connected to **{channel.name}**!", ephemeral=True)

        except discord.ClientException as e:
            log.error(f"Voice client error: {e}")
            await interaction.response.send_message("❌ A client error occurred while connecting.", ephemeral=True)
        except Exception as e:
            log.exception("Failed to connect/move to voice channel")
            await interaction.response.send_message(f"❌ Could not connect: {e}", ephemeral=True)

    @app_commands.command(
        name="leave",
        description="Makes the bot leave its current voice channel."
    )
    async def leave_command(self, interaction: discord.Interaction):
        """Leave the voice channel the bot is currently in."""
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.disconnect(force=False)
            await interaction.response.send_message("👋 Disconnected from the voice channel.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ I'm not in a voice channel.", ephemeral=True)


async def setup(bot: commands.Bot):
    """Setup function called on self.load_extension() use"""
    await bot.add_cog(VoiceChatCog(bot))
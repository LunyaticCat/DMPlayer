import asyncio
import os
import discord

FADE_DURATION_S = float(os.getenv('FADE_DURATION', '2.0'))
FADE_STEPS = int(os.getenv('FADE_STEPS', '20'))
DEFAULT_VOLUME = float(os.getenv('DEFAULT_VOLUME', '0.5'))

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

async def fade_out(guild: discord.Guild):
    """Gradually decreases the volume of the active voice client to zero."""
    voice_client = guild.voice_client
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'volume'):
        current_player = voice_client.source
        for i in range(FADE_STEPS, -1, -1):
            volume = DEFAULT_VOLUME * (i / FADE_STEPS)
            current_player.volume = max(0.0, volume)
            await asyncio.sleep(FADE_DURATION_S / FADE_STEPS)
        voice_client.stop()

async def fade_in(guild: discord.Guild):
    """Gradually increases the volume of the newly started voice client."""
    voice_client = guild.voice_client
    if voice_client and voice_client.is_playing() and hasattr(voice_client.source, 'volume'):
        player = voice_client.source
        for i in range(FADE_STEPS + 1):
            volume = DEFAULT_VOLUME * (i / FADE_STEPS)
            player.volume = min(DEFAULT_VOLUME, volume)
            await asyncio.sleep(FADE_DURATION_S / FADE_STEPS)
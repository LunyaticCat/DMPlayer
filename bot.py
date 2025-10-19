import asyncio
import signal

import discord
import os
from dotenv import load_dotenv
from discord.ext import commands

from database.db_connect import create_mariadb_pool

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID'))
global db_conn


async def main():
    """The main entry point for running the bot."""
    bot = DMPlayer()

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    try:
        if TOKEN:
            await bot.start(TOKEN)
        else:
            print("ERROR: DISCORD_TOKEN not found in .env file.")
    finally:
        print("Closing resources...")
        if bot.db_pool:
            bot.db_pool.close()
            await bot.db_pool.wait_closed()
            print("MariaDB pool closed.")

        if not bot.is_closed():
            await bot.close()
            print("Bot client closed.")

class DMPlayer(commands.Bot):
    def __init__(self):
        self.db_pool = None
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        """Register each command file in the cogs directory and sync commands."""
        print("DEBUG: GUILD_ID env value:", GUILD_ID)
        # load cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"Loaded cog: {filename}")
                except Exception as e:
                    print(f"Failed to load cog {filename}: {e}")

        # try to sync to the guild specified by GUILD_ID
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} commands to guild {GUILD_ID}.")
        except Exception as e:
            print(f"Guild sync failed: {e} — trying global sync as fallback.")
            try:
                synced_global = await self.tree.sync()
                print(f"Global sync complete: {len(synced_global)} commands registered.")
            except Exception as e2:
                print(f"Global sync failed: {e2}")

        print("Commands after sync:", [c.name for c in self.tree.walk_commands()])


    async def on_ready(self):
        global db_conn

        self.db_pool = await asyncio.to_thread(create_mariadb_pool, "bot_pool", 5)
        print("MariaDB pool created")

        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print("Bot is ready and connected to the server!")
        print('------')


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shut down by KeyboardInterrupt.")
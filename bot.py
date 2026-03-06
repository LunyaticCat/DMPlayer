import asyncio
import logging
import signal
import discord
import os
from dotenv import load_dotenv
from discord.ext import commands

# Assuming db_connect.py is in a 'database' folder
from database.db_connect import create_mariadb_pool

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD_ID = int(os.getenv('DISCORD_GUILD_ID'))

async def main():
    """The main entry point for running the bot."""
    db_pool = None
    try:
        db_pool = await asyncio.to_thread(create_mariadb_pool, "bot_pool", 5)
        print("MariaDB pool created")
    except Exception as e:
        print(f"Failed to create MariaDB pool: {e}")
        return

    bot = DMPlayer(db_pool=db_pool)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    try:
        if not TOKEN:
            print("ERROR: DISCORD_TOKEN not found in .env file.")
            return

        bot_task = asyncio.create_task(bot.start(TOKEN))
        discord.utils.setup_logging(level=logging.INFO)
        print("Bot task started.")

        await asyncio.wait([bot_task, stop], return_when=asyncio.FIRST_COMPLETED)

    finally:
        print("Shutdown signal received, closing resources...")

        if not bot.is_closed():
            await bot.close()
            print("Bot client closed.")

        if bot.db_pool:
            bot.db_pool.close()

class DMPlayer(commands.Bot):
    def __init__(self, db_pool):
        self.db_pool = db_pool
        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        """Register each command file in the cogs directory and sync commands."""
        print(f"DEBUG: GUILD_ID env value: {GUILD_ID}")

        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    print(f"Loaded cog: {filename}")
                except Exception as e:
                    print(f"Failed to load cog {filename}: {e}")

        try:
            guild = discord.Object(id=GUILD_ID)
            self.tree.clear_commands(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"Cleared guild-specific commands for {GUILD_ID} to remove duplicates.")
        except Exception as e:
            print(f"Failed to clear guild commands: {e}")

        try:
            synced = await self.tree.sync()
            print(f"Successfully synced {len(synced)} commands globally.")
        except Exception as e:
            print(f"Global sync failed: {e}")

        print("Commands after sync:", [c.name for c in self.tree.walk_commands()])

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print("Bot is ready and connected to the server!")
        print('------')


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot shut down by KeyboardInterrupt.")
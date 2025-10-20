import asyncio
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

    # CHANGED: Create the database pool ONCE, before the bot starts.
    db_pool = None
    try:
        db_pool = await asyncio.to_thread(create_mariadb_pool, "bot_pool", 5)
        print("MariaDB pool created")
    except Exception as e:
        print(f"Failed to create MariaDB pool: {e}")
        return # Exit if the database can't be reached

    # CHANGED: Pass the database pool to the bot during initialization.
    bot = DMPlayer(db_pool=db_pool)

    loop = asyncio.get_running_loop()
    stop = loop.create_future()
    loop.add_signal_handler(signal.SIGINT, stop.set_result, None)
    loop.add_signal_handler(signal.SIGTERM, stop.set_result, None)

    try:
        if not TOKEN:
            print("ERROR: DISCORD_TOKEN not found in .env file.")
            return

        # CHANGED: Start the bot as a background task instead of blocking.
        bot_task = asyncio.create_task(bot.start(TOKEN))
        print("Bot task started.")

        # Wait for either the bot task to complete (e.g., on error) or for the shutdown signal.
        await asyncio.wait([bot_task, stop], return_when=asyncio.FIRST_COMPLETED)

    finally:
        print("Shutdown signal received, closing resources...")

        # Gracefully close the bot client.
        if not bot.is_closed():
            await bot.close()
            print("Bot client closed.")

        # Close the database pool after the bot is fully closed.
        if bot.db_pool:
            bot.db_pool.close()
            # wait_closed is a coroutine, so it needs to be awaited
            await bot.db_pool.wait_closed()
            print("MariaDB pool closed.")

class DMPlayer(commands.Bot):
    # CHANGED: The bot now accepts the db_pool during initialization.
    def __init__(self, db_pool):
        self.db_pool = db_pool # Attach the pool to the bot instance
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
        # CHANGED: The database pool is already created and available as self.db_pool.
        # No need to do anything here.
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print("Bot is ready and connected to the server!")
        print('------')


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # This is now handled by the signal handler, but we'll leave this as a final fallback.
        print("\nBot shut down by KeyboardInterrupt.")
import discord
import os
import sys
import mariadb
from dotenv import load_dotenv

# Load environment variables from the .env file
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# --- Database Credentials from .env ---
DB_HOST = os.getenv('DB_HOST')
DB_PORT = int(os.getenv('DB_PORT', 3306))
DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_DATABASE = os.getenv('DB_DATABASE')

# --- Bot Setup ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

client = discord.Client(intents=intents)
db_conn = None  # Global variable for the database connection


def create_mariadb_pool(pool_name="bot_pool", pool_size: int = 5) -> mariadb.ConnectionPool:
    """
    Create and return a mariadb.ConnectionPool.
    Raises mariadb.Error on failure; caller should handle it.
    """
    pool = mariadb.ConnectionPool(
        pool_name=pool_name,
        pool_size=pool_size,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=DB_PORT,
        database=DB_DATABASE
    )
    return pool


import asyncio
import logging
import discord
import os
from discord import app_commands
from discord.ext import commands
from typing import Tuple, Optional
from discord.app_commands import Range
from dotenv import load_dotenv

from pydub import AudioSegment
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

log = logging.getLogger(__name__)

load_dotenv()

# OAuth 2.0 client secret (from Google Cloud Console)
OAUTH_CREDENTIALS_FILE = os.getenv('DRIVE_SECRET_PATH')
TOKEN_PATH = os.getenv('GOOGLE_OAUTH_TOKEN')
GDRIVE_FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER')
SCOPES = ['https://www.googleapis.com/auth/drive']



class MusicCog(commands.Cog):
    """A cog for managing the music library in the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _add_music_to_themes(self, music_name: str, url: str, theme_names: list[str], intensity: Optional[int]) -> \
    Tuple[bool, str]:
        """
        Handles the database transaction to link one named music with URL to MULTIPLE themes with an optional intensity.
        """
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            log.error("Database connection pool not found on bot (bot.db_pool).")
            return False, "Database connection is not configured."

        def _db_transaction():
            conn = pool.get_connection()
            cursor = conn.cursor()
            try:
                theme_ids = []
                for theme_name in theme_names:
                    cursor.execute("SELECT id FROM themes WHERE name = %s", (theme_name,))
                    theme_result = cursor.fetchone()
                    if not theme_result:
                        conn.rollback()
                        return False, f"The theme '**{theme_name}**' does not exist. No links were created."
                    theme_ids.append(theme_result[0])

                cursor.execute("SELECT id FROM musics WHERE url = %s", (url,))
                music_result = cursor.fetchone()
                if music_result:
                    music_id = music_result[0]
                else:
                    cursor.execute("INSERT INTO musics (name, url, intensity) VALUES (%s, %s, %s)",
                                   (music_name, url, intensity,))
                    music_id = cursor.lastrowid
                    if not music_id:
                        raise RuntimeError("Failed to retrieve last inserted ID for new music.")

                new_links = 0
                skipped_links = 0
                for theme_id in theme_ids:
                    try:
                        cursor.execute(
                            "INSERT INTO themes_list (theme_id, music_id) VALUES (%s, %s)",
                            (theme_id, music_id,)
                        )
                        new_links += 1
                    except Exception:
                        skipped_links += 1

                conn.commit()

                message_parts = []
                if new_links > 0:
                    message_parts.append(f"Successfully created **{new_links}** new link(s).")
                if skipped_links > 0:
                    message_parts.append(f"Skipped **{skipped_links}** link(s) that already existed.")

                final_message = " ".join(message_parts)
                final_message += f" for music '{music_name}'."

                return True, final_message

            except Exception as e:
                conn.rollback()
                log.error(f"Database transaction failed in _add_music_to_themes: {e}")
                return False, "An unexpected database error occurred."
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_db_transaction)

    async def _get_gdrive_credentials(self) -> Credentials:
        """
        Retrieves or refreshes stored OAuth 2.0 credentials.
        """
        creds = None

        if os.path.exists(TOKEN_PATH):
            creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDENTIALS_FILE, SCOPES)
                creds = flow.run_local_server(port=0)
            with open(TOKEN_PATH, 'w') as token:
                token.write(creds.to_json())

        return creds

    async def _process_and_upload_mp3(self, attachment: discord.Attachment) -> Tuple[bool, str]:
        """
        Downloads, compresses, and uploads an MP3 attachment to Google Drive using OAuth2 credentials.
        """
        original_path = f"temp_{attachment.id}_{attachment.filename}"
        compressed_path = f"compressed_{attachment.id}_{attachment.filename}"

        try:
            await attachment.save(original_path)

            def _compress_file():
                audio = AudioSegment.from_mp3(original_path)
                audio.export(compressed_path, format="mp3", bitrate="128k")

            await asyncio.to_thread(_compress_file)
            log.info(f"Compressed '{original_path}' to '{compressed_path}'.")

            def _upload_to_drive():
                creds = asyncio.run(self._get_gdrive_credentials())
                service = build('drive', 'v3', credentials=creds)

                file_metadata = {
                    'name': attachment.filename,
                    'parents': [GDRIVE_FOLDER_ID]
                }
                media = MediaFileUpload(compressed_path, mimetype='audio/mpeg')

                file = service.files().create(
                    body=file_metadata,
                    media_body=media,
                    fields='id',
                    supportsAllDrives=True
                ).execute()

                file_id = file.get('id')
                if not file_id:
                    return None

                permission = {'type': 'anyone', 'role': 'reader'}
                service.permissions().create(
                    fileId=file_id,
                    body=permission,
                    supportsAllDrives=True
                ).execute()

                file_with_link = service.files().get(
                    fileId=file_id,
                    fields='webContentLink',
                    supportsAllDrives=True
                ).execute()

                return file_with_link.get('webContentLink')

            direct_url = await asyncio.to_thread(_upload_to_drive)
            if not direct_url:
                return False, "Failed to upload to Google Drive or retrieve a public download link."

            log.info(f"Uploaded file to Google Drive with URL: {direct_url} and set to public.")

            return True, direct_url

        except HttpError as e:
            log.error(f"Google Drive API Error: {e}")
            return False, f"A Google Drive API error occurred. Make sure the OAuth user has access to the target folder."
        except Exception as e:
            log.error(f"An error occurred in file processing/upload: {e}")
            return False, "An unexpected error occurred while processing the file."
        finally:
            if os.path.exists(original_path):
                os.remove(original_path)
            if os.path.exists(compressed_path):
                os.remove(compressed_path)

    @app_commands.command(name="add_music", description="Adds a music track and links it to one or more themes.")
    @app_commands.describe(
        name="Name to register the music under.",
        attachment="The MP3 file to upload.",
        theme="A comma-separated list of themes to link the music to.",
        intensity="The intensity of the music for these themes (0-100)."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def add_music(
            self,
            interaction: discord.Interaction,
            name: str,
            attachment: discord.Attachment,
            theme: str,
            intensity: Optional[Range[int, 0, 100]] = None
    ):
        await interaction.response.defer(ephemeral=True)

        if not attachment.filename.lower().endswith('.mp3'):
            await interaction.followup.send("❌ Please upload a valid `.mp3` file.", ephemeral=True)
            return

        themes_list = [t.strip().upper() for t in theme.split(',') if t.strip()]
        if not themes_list:
            await interaction.followup.send("❌ At least one Theme is required.", ephemeral=True)
            return

        await interaction.followup.send("⏳ Processing your file... This may take a moment.", ephemeral=True)

        upload_success, result_or_error = await self._process_and_upload_mp3(attachment)

        if not upload_success:
            await interaction.edit_original_response(content=f"❌ {result_or_error}")
            return

        drive_url = result_or_error
        db_success, db_message = await self._add_music_to_themes(name, drive_url, themes_list, intensity)

        if db_success:
            await interaction.edit_original_response(content=f"✅ {db_message}")
        else:
            await interaction.edit_original_response(content=f"❌ {db_message}")


async def setup(bot: commands.Bot):
    await bot.add_cog(MusicCog(bot))

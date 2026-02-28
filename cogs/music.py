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

OAUTH_CREDENTIALS_FILE = os.getenv('DRIVE_SECRET_PATH')
TOKEN_PATH = os.getenv('GOOGLE_OAUTH_TOKEN')
GDRIVE_FOLDER_ID = os.getenv('GOOGLE_DRIVE_FOLDER')
SCOPES = ['https://www.googleapis.com/auth/drive']

class EditMusicModal(discord.ui.Modal):
    """A modal popup to edit the properties of a selected music track."""
    def __init__(self, cog, music_data):
        super().__init__(title=f"Edit: {music_data['name'][:30]}")
        self.cog = cog
        self.music_id = music_data['id']

        # Pre-fill the modal with the current database values
        self.music_name = discord.ui.TextInput(
            label="Music Name",
            default=music_data['name'],
            max_length=200
        )
        self.themes = discord.ui.TextInput(
            label="Themes (comma-separated)",
            default=music_data['themes'] or "",
            max_length=300
        )
        self.intensity = discord.ui.TextInput(
            label="Intensity (0-100)",
            default=str(music_data['intensity']) if music_data['intensity'] is not None else "",
            required=False
        )
        self.volume = discord.ui.TextInput(
            label="Volume (e.g., 0.5, 1.0)",
            default=str(music_data['volume']) if music_data.get('volume') is not None else "1.0",
            required=False
        )

        self.add_item(self.music_name)
        self.add_item(self.themes)
        self.add_item(self.intensity)
        self.add_item(self.volume)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            try:
                intensity_val = int(self.intensity.value) if self.intensity.value else None
                volume_val = float(self.volume.value) if self.volume.value else 1.0
            except ValueError:
                await interaction.followup.send("❌ Intensity must be an integer and Volume must be a number.",
                                                ephemeral=True)
                return

            # Pass the updated data back to the cog's database function
            success, msg = await self.cog._update_music(
                self.music_id,
                self.music_name.value,
                self.themes.value,
                intensity_val,
                volume_val
            )

            if success:
                await interaction.followup.send(f"✅ {msg}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {msg}", ephemeral=True)

        except Exception as e:
            log.error(f"Unhandled exception in EditMusicModal.on_submit: {e}", exc_info=True)
            await interaction.followup.send("❌ An unexpected error occurred while processing the modal.",
                                            ephemeral=True)


class EditMusicSelectView(discord.ui.View):
    """An interactive paginated dropdown menu to select a track to edit."""
    def __init__(self, cog, musics, current_page=0):
        super().__init__(timeout=None)
        self.cog = cog
        self.musics = musics
        self.current_page = current_page
        self.items_per_page = 25

        start_idx = self.current_page * self.items_per_page
        end_idx = start_idx + self.items_per_page
        page_items = self.musics[start_idx:end_idx]

        options = []
        for item in page_items:
            options.append(discord.SelectOption(
                label=item['name'][:100],
                value=str(item['id']),
                description=f"Themes: {item['themes'][:40] if item['themes'] else 'None'}"
            ))

        if options:
            select = discord.ui.Select(
                placeholder="Select a music track to edit...",
                options=options,
                row=0
            )
            select.callback = self.select_callback
            self.add_item(select)

        # Pagination controls
        total_pages = (len(self.musics) - 1) // self.items_per_page + 1
        if total_pages > 1:
            prev_btn = discord.ui.Button(label="Prev Page", style=discord.ButtonStyle.secondary, row=1, disabled=(self.current_page == 0))
            prev_btn.callback = self.prev_page
            self.add_item(prev_btn)

            next_btn = discord.ui.Button(label="Next Page", style=discord.ButtonStyle.secondary, row=1, disabled=(self.current_page == total_pages - 1))
            next_btn.callback = self.next_page
            self.add_item(next_btn)

    async def select_callback(self, interaction: discord.Interaction):
        # Fetch the selected music's data and open the modal
        music_id = int(interaction.data["values"][0])
        music_data = next((m for m in self.musics if m['id'] == music_id), None)
        if music_data:
            await interaction.response.send_modal(EditMusicModal(self.cog, music_data))
        else:
            await interaction.response.send_message("Music not found.", ephemeral=True)

    async def prev_page(self, interaction: discord.Interaction):
        self.current_page -= 1
        await self.update_view(interaction)

    async def next_page(self, interaction: discord.Interaction):
        self.current_page += 1
        await self.update_view(interaction)

    async def update_view(self, interaction: discord.Interaction):
        embed = self.cog._generate_edit_embed(self.musics, self.current_page, self.items_per_page)
        await interaction.response.edit_message(embed=embed, view=EditMusicSelectView(self.cog, self.musics, self.current_page))

class MusicCog(commands.Cog):
    """A cog for managing the music library in the database."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _fetch_all_musics(self) -> list:
        """Fetches all musics and their attached themes from the database."""
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            log.error("Database connection pool not found in _fetch_all_musics.")
            return []

        def _query():
            conn = pool.get_connection()
            cursor = conn.cursor()
            try:
                # Groups the themes so we can display them together and pre-fill the modal
                # Changed ORDER BY m.name to ORDER BY m.id
                cursor.execute("""
                               SELECT m.id, m.name, m.intensity, m.volume, GROUP_CONCAT(t.name) as themes
                               FROM musics m
                                        LEFT JOIN themes_list tl ON m.id = tl.music_id
                                        LEFT JOIN themes t ON tl.theme_id = t.id
                               GROUP BY m.id
                               ORDER BY m.id
                               """)
                rows = cursor.fetchall()
                return [{"id": r[0], "name": r[1], "intensity": r[2], "volume": r[3], "themes": r[4]} for r in rows]
            except Exception as e:
                log.error(f"Database query failed in _fetch_all_musics: {e}", exc_info=True)
                return []
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_query)

    async def _update_music(self, music_id: int, name: str, themes_str: str, intensity: Optional[int], volume: float) -> \
    Tuple[bool, str]:
        """Handles the database transaction to update a music track's details."""
        pool = getattr(self.bot, "db_pool", None)
        if pool is None:
            return False, "Database connection not found."

        themes_list = [t.strip().upper() for t in themes_str.split(',') if t.strip()]

        def _transaction():
            conn = pool.get_connection()
            cursor = conn.cursor()
            try:
                cursor.execute("""
                               UPDATE musics
                               SET name      = %s,
                                   intensity = %s,
                                   volume    = %s
                               WHERE id = %s
                               """, (name, intensity, volume, music_id))

                theme_ids = []
                for t_name in themes_list:
                    cursor.execute("SELECT id FROM themes WHERE name = %s", (t_name,))
                    res = cursor.fetchone()
                    if res:
                        theme_ids.append(res[0])
                    else:
                        cursor.execute("INSERT INTO themes (name) VALUES (%s)", (t_name,))
                        theme_ids.append(cursor.lastrowid)

                cursor.execute("DELETE FROM themes_list WHERE music_id = %s", (music_id,))
                for t_id in theme_ids:
                    cursor.execute("INSERT INTO themes_list (theme_id, music_id) VALUES (%s, %s)", (t_id, music_id))

                conn.commit()
                return True, f"Successfully updated '**{name}**'."
            except Exception as e:
                conn.rollback()
                log.error(f"Error updating music in database: {e}", exc_info=True)
                return False, "An unexpected database error occurred."
            finally:
                cursor.close()
                conn.close()

        return await asyncio.to_thread(_transaction)

    def _generate_edit_embed(self, musics: list, current_page: int, items_per_page: int) -> discord.Embed:
        """Builds the visual embed for the paginated list."""
        embed = discord.Embed(title="⚙️ Modify Music Library", color=discord.Color.orange())

        start_idx = current_page * items_per_page
        end_idx = start_idx + items_per_page
        page_items = musics[start_idx:end_idx]

        desc = "**Select a track from the dropdown below to edit its properties.**\n\n"
        for item in page_items:
            vol = item.get('volume', 1.0)
            themes = item['themes'] if item['themes'] else "None"
            desc += f"`{item['id']}.` **{item['name']}** *(Vol: {vol} | Themes: {themes})*\n"

        total_pages = (len(musics) - 1) // items_per_page + 1
        desc += f"\n*Page {current_page + 1} of {total_pages} | Total Tracks: {len(musics)}*"
        embed.description = desc
        return embed

    @app_commands.command(name="modify_music", description="Select and edit an existing music track's details.")
    @app_commands.checks.has_permissions(administrator=True)
    async def modify_music(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        try:
            musics = await self._fetch_all_musics()
            if not musics:
                await interaction.followup.send("No music found in the database or database error occurred.",
                                                ephemeral=True)
                return

            embed = self._generate_edit_embed(musics, 0, 25)
            view = EditMusicSelectView(self, musics, 0)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
        except Exception as e:
            log.error(f"Error executing modify_music command: {e}", exc_info=True)
            await interaction.followup.send("❌ An error occurred while generating the music list.", ephemeral=True)

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

                return f"https://drive.google.com/uc?id={file_id}&export=download"

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

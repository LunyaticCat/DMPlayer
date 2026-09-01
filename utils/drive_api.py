import asyncio
import logging
import os
import discord
from typing import Tuple
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


async def get_gdrive_credentials() -> Credentials:
    """Retrieves or refreshes stored OAuth 2.0 credentials."""
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


async def process_and_upload_mp3(attachment: discord.Attachment) -> Tuple[bool, str]:
    """Downloads, compresses, and uploads an MP3 attachment to Google Drive."""
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
            creds = asyncio.run(get_gdrive_credentials())
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

        return True, direct_url

    except HttpError as e:
        log.error(f"Google Drive API Error: {e}")
        return False, f"A Google Drive API error occurred. Make sure the OAuth user has access."
    except Exception as e:
        log.error(f"An error occurred in file processing/upload: {e}")
        return False, "An unexpected error occurred while processing the file."
    finally:
        if os.path.exists(original_path):
            os.remove(original_path)
        if os.path.exists(compressed_path):
            os.remove(compressed_path)


async def delete_file_from_drive(url: str) -> Tuple[bool, str]:
    """
    Deletes a file from Google Drive based on its URL.

    Parameters
    ----------
    url : str
        The Google Drive direct download URL or view URL containing the file ID.

    Returns
    -------
    Tuple[bool, str]
        A boolean indicating if the deletion was successful and a status message.
    """
    import re

    match = re.search(r"id=([a-zA-Z0-9_-]+)", url)
    if not match:
        match = re.search(r"/d/([a-zA-Z0-9_-]+)", url)

    if not match:
        return False, "Could not extract Google Drive file ID from URL."

    file_id = match.group(1)

    def _delete_action():
        try:
            creds = asyncio.run(get_gdrive_credentials())
            service = build('drive', 'v3', credentials=creds)

            service.files().delete(
                fileId=file_id,
                supportsAllDrives=True
            ).execute()

            return True, "Successfully deleted file from Google Drive."
        except HttpError as e:
            log.error(f"Google Drive API Error during deletion: {e}")
            if e.resp.status == 404:
                return True, "File not found on Google Drive, it may have already been deleted."
            return False, "A Google Drive API error occurred during deletion."
        except Exception as e:
            log.error(f"An error occurred during file deletion: {e}")
            return False, "An unexpected error occurred while deleting the file."

    return await asyncio.to_thread(_delete_action)
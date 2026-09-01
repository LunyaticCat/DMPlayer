import asyncio
import logging
from typing import List, Dict, Tuple, Optional

log = logging.getLogger(__name__)


async def fetch_all_themes(pool) -> List[Dict]:
    """Fetches all themes from the database."""

    def _query():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id, name FROM themes ORDER BY id")
            rows = cursor.fetchall()
            return [{"id": r[0], "name": r[1]} for r in rows]
        except Exception as e:
            log.error(f"Database error in fetch_all_themes: {e}", exc_info=True)
            return []
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_query)


async def insert_theme(pool, name: str) -> bool:
    """Inserts a new theme into the database."""

    def _db_insert():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO themes (name) VALUES (%s)", (name,))
            conn.commit()
            return True
        except Exception as e:
            log.error(f"Database error while inserting theme '{name}': {e}", exc_info=True)
            conn.rollback()
            return False
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_db_insert)


async def fetch_all_musics(pool) -> List[Dict]:
    """Fetches all musics and their attached themes."""

    def _query():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
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
            log.error(f"Database query failed in fetch_all_musics: {e}", exc_info=True)
            return []
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_query)


async def update_music(pool, music_id: int, name: str, themes_list: List[str], intensity: Optional[int],
                       volume: float) -> Tuple[bool, str]:
    """Updates a music track's details and synchronizes its themes."""

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


async def add_music_to_themes(pool, music_name: str, url: str, theme_names: List[str], intensity: Optional[int]) -> \
Tuple[bool, str]:
    """Links one named music with URL to multiple themes with an optional intensity."""

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

            new_links, skipped_links = 0, 0
            for theme_id in theme_ids:
                try:
                    cursor.execute("INSERT INTO themes_list (theme_id, music_id) VALUES (%s, %s)",
                                   (theme_id, music_id,))
                    new_links += 1
                except Exception:
                    skipped_links += 1

            conn.commit()

            message_parts = []
            if new_links > 0: message_parts.append(f"Successfully created **{new_links}** new link(s).")
            if skipped_links > 0: message_parts.append(f"Skipped **{skipped_links}** link(s) that already existed.")
            return True, " ".join(message_parts) + f" for music '{music_name}'."

        except Exception as e:
            conn.rollback()
            log.error(f"Database transaction failed in add_music_to_themes: {e}")
            return False, "An unexpected database error occurred."
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_db_transaction)


async def fetch_tracks(pool, themes: Optional[list] = None, min_intensity: Optional[int] = None,
                       max_intensity: Optional[int] = None) -> list:
    """Fetches a list of (url, name) tuples based on optional filters."""

    def _query():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT m.url, m.name, m.volume FROM musics m"
            params = []
            joins = []
            conditions = []

            if themes:
                joins.append("JOIN themes_list tl ON m.id = tl.music_id")
                joins.append("JOIN themes t ON tl.theme_id = t.id")
                theme_placeholders = ', '.join(['%s'] * len(themes))
                conditions.append(f"t.name IN ({theme_placeholders})")
                params.extend(themes)

            if min_intensity is not None:
                conditions.append("m.intensity >= %s")
                params.append(min_intensity)
            if max_intensity is not None:
                conditions.append("m.intensity <= %s")
                params.append(max_intensity)

            if joins:
                query += " " + " ".join(joins)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            if themes:
                query += " GROUP BY m.id, m.url, m.name, m.volume HAVING COUNT(DISTINCT t.id) = %s"
                params.append(len(themes))

            query += " ORDER BY m.name"

            cursor.execute(query, tuple(params))
            return cursor.fetchall()

        except Exception as e:
            log.error(f"Database error in fetch_tracks: {e}", exc_info=True)
            return []
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_query)


async def fetch_filtered_playable_musics(pool, themes: Optional[List[str]] = None, min_intensity: Optional[int] = None,
                                         max_intensity: Optional[int] = None) -> list:
    """Fetches playable musics based on optional theme and intensity filters."""

    def _query():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            query = "SELECT m.id, m.name, m.url, m.volume FROM musics m"
            params = []
            joins = []
            conditions = []

            if themes:
                joins.append("JOIN themes_list tl ON m.id = tl.music_id")
                joins.append("JOIN themes t ON tl.theme_id = t.id")
                theme_placeholders = ', '.join(['%s'] * len(themes))
                conditions.append(f"t.name IN ({theme_placeholders})")
                params.extend(themes)

            if min_intensity is not None:
                conditions.append("m.intensity >= %s")
                params.append(min_intensity)
            if max_intensity is not None:
                conditions.append("m.intensity <= %s")
                params.append(max_intensity)

            if joins:
                query += " " + " ".join(joins)
            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            if themes:
                query += " GROUP BY m.id HAVING COUNT(DISTINCT t.id) = %s"
                params.append(len(themes))

            query += " ORDER BY m.name"

            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()
            return [{"id": r[0], "name": r[1], "url": r[2], "volume": r[3]} for r in rows]

        except Exception as e:
            log.error(f"Database error in fetch_filtered_playable_musics: {e}", exc_info=True)
            return []
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_query)


async def delete_theme(pool, theme_name: str) -> Tuple[bool, str]:
    """
    Deletes a theme from the database and removes its music associations.

    Parameters
    ----------
    pool : object
        The database connection pool.
    theme_name : str
        The exact name of the theme to delete.

    Returns
    -------
    Tuple[bool, str]
        A boolean indicating success and a status message.
    """

    def _db_delete():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT id FROM themes WHERE name = %s", (theme_name,))
            res = cursor.fetchone()
            if not res:
                return False, f"Theme '{theme_name}' not found."

            theme_id = res[0]
            cursor.execute("DELETE FROM themes_list WHERE theme_id = %s", (theme_id,))
            cursor.execute("DELETE FROM themes WHERE id = %s", (theme_id,))
            conn.commit()
            return True, f"Successfully deleted theme '{theme_name}'."
        except Exception as e:
            log.error(f"Database error while deleting theme '{theme_name}': {e}", exc_info=True)
            conn.rollback()
            return False, "An unexpected database error occurred."
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_db_delete)


async def delete_music(pool, music_id: int) -> Tuple[bool, str, Optional[str]]:
    """
    Deletes a music track from the database and retrieves its URL.

    Parameters
    ----------
    pool : object
        The database connection pool.
    music_id : int
        The ID of the music track to delete.

    Returns
    -------
    Tuple[bool, str, Optional[str]]
        Success status, a message, and the URL of the deleted music track if successful.
    """

    def _db_delete():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT name, url FROM musics WHERE id = %s", (music_id,))
            res = cursor.fetchone()
            if not res:
                return False, f"Music with ID {music_id} not found.", None

            music_name, url = res[0], res[1]

            cursor.execute("DELETE FROM themes_list WHERE music_id = %s", (music_id,))
            cursor.execute("DELETE FROM musics WHERE id = %s", (music_id,))
            conn.commit()
            return True, f"Successfully deleted music '{music_name}'.", url
        except Exception as e:
            log.error(f"Database error while deleting music ID {music_id}: {e}", exc_info=True)
            conn.rollback()
            return False, "An unexpected database error occurred.", None
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_db_delete)

async def fetch_unlisted_musics(pool) -> list:
    """
    Fetches all music tracks that are not associated with any theme.

    Parameters
    ----------
    pool : object
        The database connection pool.

    Returns
    -------
    list of dict
        A list of dictionaries representing the unlisted musics, containing 'id' and 'name'.
    """
    def _query():
        conn = pool.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("""
                           SELECT m.id, m.name 
                           FROM musics m
                           LEFT JOIN themes_list tl ON m.id = tl.music_id
                           WHERE tl.theme_id IS NULL
                           ORDER BY m.id
                           """)
            rows = cursor.fetchall()
            return [{"id": r[0], "name": r[1]} for r in rows]
        except Exception as e:
            log.error(f"Database error in fetch_unlisted_musics: {e}", exc_info=True)
            return []
        finally:
            cursor.close()
            conn.close()

    return await asyncio.to_thread(_query)
import sqlite3
import os
import json
import logging
from datetime import datetime

class WatchStatusManager:
    def __init__(self, db_path="watch_status.db"):
        self.db_path = db_path
        self.init_db()

    def init_db(self):
        """Initialize SQLite database and create tables if they don't exist"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS watch_status (
                        file_path TEXT PRIMARY KEY,
                        watched BOOLEAN,
                        progress FLOAT,
                        last_watched TEXT,
                        media_length INTEGER
                    )
                ''')
                # Index to speed up recently-watched queries
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_watch_status_last_watched ON watch_status(last_watched)')
                # Bookmarks table to store user bookmarks for episodes/files
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS bookmarks (
                        file_path TEXT PRIMARY KEY,
                        created TEXT,
                        note TEXT
                    )
                ''')
                conn.commit()
        except Exception as e:
            logging.error(f"Error initializing watch status database: {str(e)}")

    # Bookmark methods
    def add_bookmark(self, file_path, note=None):
        """Add or update a bookmark for a file."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO bookmarks (file_path, created, note)
                    VALUES (?, ?, ?)
                ''', (file_path, datetime.now().isoformat(), note))
                conn.commit()
        except Exception as e:
            logging.error(f"Error adding bookmark: {str(e)}")

    def remove_bookmark(self, file_path):
        """Remove a bookmark for a file."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM bookmarks WHERE file_path = ?', (file_path,))
                conn.commit()
        except Exception as e:
            logging.error(f"Error removing bookmark: {str(e)}")

    def is_bookmarked(self, file_path):
        """Return True if file is bookmarked."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM bookmarks WHERE file_path = ? LIMIT 1', (file_path,))
                return cursor.fetchone() is not None
        except Exception as e:
            logging.error(f"Error checking bookmark: {str(e)}")
            return False

    def get_bookmarks(self):
        """Return a list of bookmark records as dicts."""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT file_path, created, note FROM bookmarks ORDER BY created DESC')
                rows = cursor.fetchall()
                return [{'file_path': r[0], 'created': r[1], 'note': r[2]} for r in rows]
        except Exception as e:
            logging.error(f"Error getting bookmarks: {str(e)}")
            return []

    def get_recently_watched(self, limit=12):
        """Return a list of recently watched files ordered by last_watched desc.
        Each item is a dict with 'file_path' and 'last_watched'.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT file_path, last_watched FROM watch_status
                    WHERE last_watched IS NOT NULL
                    ORDER BY last_watched DESC
                    LIMIT ?
                ''', (limit,))
                rows = cursor.fetchall()
                result = []
                for r in rows:
                    fp = r[0]
                    ts = r[1]
                    # Only include files that still exist on disk
                    if not os.path.exists(fp):
                        continue
                    # Parse ISO timestamp into epoch seconds for consistent display
                    try:
                        dt = datetime.fromisoformat(ts)
                        epoch = dt.timestamp()
                    except Exception:
                        try:
                            # fallback: attempt to parse common formats
                            epoch = float(ts)
                        except Exception:
                            epoch = None
                    result.append({'file_path': fp, 'last_watched': epoch})
                return result
        except Exception as e:
            logging.error(f"Error getting recently watched: {str(e)}")
            return []

    def mark_watched(self, file_path, watched=True, progress=1.0, media_length=None):
        """Mark a file as watched/unwatched"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO watch_status 
                    (file_path, watched, progress, last_watched, media_length)
                    VALUES (?, ?, ?, ?, ?)
                ''', (file_path, watched, progress, datetime.now().isoformat(), media_length))
                conn.commit()
        except Exception as e:
            logging.error(f"Error marking watch status: {str(e)}")

    def get_status(self, file_path):
        """Get watch status for a file"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT * FROM watch_status WHERE file_path = ?', (file_path,))
                result = cursor.fetchone()
                if result:
                    return {
                        'file_path': result[0],
                        'watched': bool(result[1]),
                        'progress': float(result[2]),
                        'last_watched': result[3],
                        'media_length': result[4]
                    }
                return None
        except Exception as e:
            logging.error(f"Error getting watch status: {str(e)}")
            return None

    def update_progress(self, file_path, progress, media_length=None):
        """Update watch progress for a file"""
        try:
            # Mark as watched if progress is >= 90%
            watched = progress >= 0.9
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO watch_status 
                    (file_path, watched, progress, last_watched, media_length)
                    VALUES (?, ?, ?, ?, ?)
                ''', (file_path, watched, progress, datetime.now().isoformat(), media_length))
                conn.commit()
        except Exception as e:
            logging.error(f"Error updating watch progress: {str(e)}")

    def touch_last_watched(self, file_path, timestamp=None):
        """Update only the last_watched timestamp for a file without changing watched/progress unless necessary.

        If the row exists, preserve watched, progress and media_length fields. If not, insert a new row with defaults.
        """
        try:
            ts = timestamp or datetime.now().isoformat()
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT watched, progress, media_length FROM watch_status WHERE file_path = ?', (file_path,))
                row = cursor.fetchone()
                if row:
                    watched = bool(row[0])
                    progress = float(row[1]) if row[1] is not None else 0.0
                    media_length = row[2]
                else:
                    watched = False
                    progress = 0.0
                    media_length = None
                cursor.execute('''
                    INSERT OR REPLACE INTO watch_status
                    (file_path, watched, progress, last_watched, media_length)
                    VALUES (?, ?, ?, ?, ?)
                ''', (file_path, watched, progress, ts, media_length))
                conn.commit()
        except Exception as e:
            logging.error(f"Error touching last_watched for {file_path}: {str(e)}")

    def clear_all_last_watched(self):
        """Clear the last_watched timestamp for all entries in the DB.

        This keeps watch progress/watched flags intact but removes the ordering
        so Recently Watched will no longer show items from the DB.
        """
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('UPDATE watch_status SET last_watched = NULL')
                conn.commit()
        except Exception as e:
            logging.error(f"Error clearing last_watched timestamps: {str(e)}")

    def is_watched(self, file_path):
        """Return True if the file is marked watched in DB, False otherwise."""
        try:
            status = self.get_status(file_path)
            return bool(status and status.get('watched'))
        except Exception as e:
            logging.error(f"Error checking watched status: {str(e)}")
            return False

    def mark_as_watched(self, file_path, watched=True, progress=1.0, media_length=None):
        """Compatibility wrapper around mark_watched"""
        try:
            return self.mark_watched(file_path, watched=watched, progress=progress, media_length=media_length)
        except Exception as e:
            logging.error(f"Error in mark_as_watched wrapper: {str(e)}")

    def get_watched_files(self, file_paths):
        """Given an iterable of file paths, return a set of those that are marked watched.

        This performs a single DB query (with chunking) for efficiency when building lists.
        """
        try:
            paths = list(file_paths)
            watched_set = set()
            if not paths:
                return watched_set
            # Query in chunks to avoid SQLite parameter limits
            chunk_size = 500
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                for i in range(0, len(paths), chunk_size):
                    chunk = paths[i:i+chunk_size]
                    placeholders = ','.join('?' for _ in chunk)
                    query = f"SELECT file_path FROM watch_status WHERE file_path IN ({placeholders}) AND watched = 1"
                    cursor.execute(query, chunk)
                    rows = cursor.fetchall()
                    for r in rows:
                        watched_set.add(r[0])
            return watched_set
        except Exception as e:
            logging.error(f"Error getting watched files in batch: {str(e)}")
            return set()

    def get_unwatched_count(self, directory):
        """Get count of unwatched files in a directory"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT COUNT(*) FROM watch_status 
                    WHERE file_path LIKE ? AND watched = 0
                ''', (f"{directory}%",))
                return cursor.fetchone()[0]
        except Exception as e:
            logging.error(f"Error getting unwatched count: {str(e)}")
            return 0
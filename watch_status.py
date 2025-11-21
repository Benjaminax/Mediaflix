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
                conn.commit()
        except Exception as e:
            logging.error(f"Error initializing watch status database: {str(e)}")

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
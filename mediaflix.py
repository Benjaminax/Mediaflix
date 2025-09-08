#from curses.ascii import US
import os
import shutil
import re
import logging
import time
import sys
import requests
from urllib.parse import quote
from io import BytesIO
from PIL import Image
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                            QLabel, QPushButton, QListWidget, QListWidgetItem, QFileDialog,
                            QMessageBox, QStackedWidget, QScrollArea, QFrame, QDialog, QLineEdit,
                            QSizePolicy, QSpacerItem, QTextEdit, QComboBox, QGroupBox, QGridLayout, QMenu,
                            QRadioButton, QCheckBox, QProgressBar)

# --- Global error handling and startup checks ---
import traceback

def show_critical_error(message, details=None):
    msg = QMessageBox()
    msg.setIcon(QMessageBox.Critical)
    msg.setWindowTitle("Mediaflix - Error")
    msg.setText(message)
    if details:
        msg.setDetailedText(details)
    msg.exec_()

def check_tmdb_api_key():
    global TMDB_API_KEY
    if 'TMDB_API_KEY' not in globals() or not TMDB_API_KEY or TMDB_API_KEY.strip() == "":
        show_critical_error(
            "TMDB API Key is missing!\nPlease set the TMDB_API_KEY in your environment or configuration.",
            "The application cannot run without a valid TMDB API Key."
        )
        sys.exit(1)

def excepthook(type, value, tb):
    tb_str = ''.join(traceback.format_exception(type, value, tb))
    show_critical_error("A fatal error occurred and the app must close.", tb_str)
    sys.exit(1)

sys.excepthook = excepthook
from PyQt5.QtCore import Qt, QSize, QTimer, QPoint, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QPalette, QPainter, QFontDatabase, QLinearGradient, QPainterPath
import subprocess
from concurrent.futures import ThreadPoolExecutor
import threading

# Dynamically get the user's home directory
home_directory = os.path.expanduser("~")
downloads_folders = [
    os.path.join(home_directory, "Downloads"),
    os.path.join(home_directory, "Downloads", "Telegram Desktop")
]
movies_folder = os.path.join(home_directory, "Videos", "Movies")
series_folder = os.path.join(home_directory, "Videos", "Series")

# Define file extensions
media_extensions = ['.mp4', '.mkv', '.avi', '.mov']

# TMDB API Configuration
TMDB_API_KEY = "875bd4ff3b965afae93faa3d789f6d7e"  # Get one from https://www.themoviedb.org/
TMDB_API_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"
TMDB_BACKDROP_URL = "https://image.tmdb.org/t/p/original"  # Higher resolution for backdrops
POSTER_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "posters")
BACKDROP_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "backdrops")
SYNOPSIS_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "synopsis")

# Set up logging
log_file = os.path.join(home_directory, "media_organizer.log")
logging.basicConfig(filename=log_file, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def extract_year(name):
    """Extract year from filename with improved pattern matching"""
    patterns = [
        r'(?:^|\D)(19[0-9]{2}|20[0-2][0-9])(?:\D|$)',  # Years 1900-2029
        r'\[(19[0-9]{2}|20[0-2][0-9])\]',  # Years in brackets
        r'\((19[0-9]{2}|20[0-2][0-9])\)'   # Years in parentheses
    ]
    
    for pattern in patterns:
        match = re.search(pattern, name)
        if match:
            return match.group(1)
    return None

def extract_series_info(filename):
    """Improved series info extraction with year support"""
    # First try to extract season/episode info
    season_ep_match = re.search(r'[Ss](\d+)[Ee](\d+)', filename, re.IGNORECASE)
    if not season_ep_match:
        return None, None, None
    
    season_num = int(season_ep_match.group(1))
    episode_num = int(season_ep_match.group(2))
    
    # Extract series name and year
    base_name = filename[:season_ep_match.start()]
    year = extract_year(base_name)
    
    # Clean up the series name
    series_name = re.sub(r'[._]', ' ', base_name).strip()
    
    # Remove quality indicators (1080p, 720p, etc.)
    series_name = re.sub(r'\b(1080|720|480)p\b', '', series_name, flags=re.IGNORECASE).strip()
    
    # Remove release group names in brackets
    series_name = re.sub(r'\[.*?\]', '', series_name).strip()
    
    # Remove year if it's at the end
    if year and series_name.endswith(year):
        series_name = series_name[:-len(year)].strip()
    
    # Remove any remaining special characters
    series_name = re.sub(r'[^a-zA-Z0-9\s]', '', series_name).strip()
    
    return series_name, f"Season {season_num}", year

class CacheClearThread(QThread):
    finished = pyqtSignal()
    def run(self):
        def delete_file(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logging.error(f"Error deleting file {file_path}: {str(e)}")
        for cache_dir in [POSTER_CACHE_DIR, BACKDROP_CACHE_DIR, SYNOPSIS_CACHE_DIR]:
            if os.path.exists(cache_dir):
                files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
                with ThreadPoolExecutor(max_workers=8) as executor:
                    executor.map(delete_file, files)
        self.finished.emit()

class ImageItem(QListWidgetItem):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.display_name = os.path.splitext(self.file_name)[0]
        self.search_title = self.extract_movie_title(self.display_name)
        self.search_year = extract_year(self.display_name)
        self.setText(self.display_name)
        self.setSizeHint(QSize(200, 300))
        self.setToolTip(self.display_name)

        # Metadata fields
        self.imdb_rating = None
        self.genres = []
        self.release_year = self.search_year
        self.synopsis = ""
        
        # Start with a placeholder icon
        self.setIcon(QIcon(self.create_placeholder_image()))
        
        # Load data in background
        self.load_data_async()

    def extract_movie_title(self, name):
        clean = name.replace('.', ' ').replace('_', ' ')
        match = re.search(r'(19|20)\d{2}', clean)
        if match:
            return clean[:match.start()].strip()
        return clean.strip()

    def create_placeholder_image(self):
        pixmap = QPixmap(150, 225)
        pixmap.fill(QColor(20, 20, 20))
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        gradient = QLinearGradient(0, 0, 0, pixmap.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 150))
        gradient.setColorAt(1, QColor(0, 0, 0, 50))
        painter.fillRect(pixmap.rect(), gradient)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(55, 30, 40, 165)
        painter.setBrush(QColor(140, 0, 0))
        painter.drawRect(65, 30, 20, 165)
        
        painter.setPen(QColor(255, 255, 255))
        font = QFont('Netflix Sans Bold', 10, QFont.Bold)
        font.setHintingPreference(QFont.PreferFullHinting)
        font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
        painter.setFont(font)
        # Enable text antialiasing for crisp rendering
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = pixmap.rect().adjusted(10, 180, -10, -10)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self.search_title)
        
        painter.end()
        return pixmap

    def load_data_async(self):
        """Load both poster and metadata in parallel"""
        self.load_poster()
        self.load_metadata()

    def load_poster(self):
        try:
            cache_name = f"{self.search_title}"
            if self.search_year:
                cache_name += f" {self.search_year}"
            cache_file = f"{quote(cache_name)}.jpg"
            cache_path = os.path.join(POSTER_CACHE_DIR, cache_file)
            os.makedirs(POSTER_CACHE_DIR, exist_ok=True)

            # Try cache first
            if os.path.exists(cache_path):
                pixmap = QPixmap(cache_path)
                if not pixmap.isNull():
                    self.setIcon(QIcon(self._apply_poster_overlay(pixmap)))
                    return

            # Try similar cached posters
            closest_year_diff = float('inf')
            closest_path = None
            for fname in os.listdir(POSTER_CACHE_DIR):
                if fname.lower().startswith(quote(self.search_title).lower()):
                    match = re.search(r'(19|20)\d{2}', fname)
                    if match and self.search_year:
                        year = int(match.group(0))
                        diff = abs(year - int(self.search_year))
                        if diff < closest_year_diff:
                            closest_year_diff = diff
                            closest_path = os.path.join(POSTER_CACHE_DIR, fname)
                    elif not self.search_year:
                        closest_path = os.path.join(POSTER_CACHE_DIR, fname)
                        break
            if closest_path:
                pixmap = QPixmap(closest_path)
                if not pixmap.isNull():
                    self.setIcon(QIcon(self._apply_poster_overlay(pixmap)))
                    return

            # Fetch from TMDB
            params = {"api_key": TMDB_API_KEY, "query": self.search_title}
            params["region"] = "US"
            if self.search_year:
                params["year"] = self.search_year

            search_url = f"{TMDB_API_URL}/search/multi"
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            poster_path = None
            for result in data.get("results", []):
                result_year = result.get("release_date", "")[:4] or result.get("first_air_date", "")[:4]
                if self.search_year and result_year == self.search_year:
                    poster_path = result.get("poster_path") or result.get("backdrop_path")
                    if poster_path:
                        break
            if not poster_path:
                for result in data.get("results", []):
                    poster_path = result.get("poster_path") or result.get("backdrop_path")
                    if poster_path:
                        break

            if poster_path:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                image_data = requests.get(image_url, timeout=10).content
                with open(cache_path, "wb") as f:
                    f.write(image_data)
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                if not pixmap.isNull():
                    self.setIcon(QIcon(self._apply_poster_overlay(pixmap)))
        except Exception as e:
            logging.error(f"Error loading image for {self.display_name}: {str(e)}")

    def _apply_poster_overlay(self, pixmap):
        overlay = QPixmap(pixmap.size())
        overlay.fill(Qt.transparent)
        painter = QPainter(overlay)
        gradient = QLinearGradient(0, 0, 0, pixmap.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 150))
        gradient.setColorAt(1, QColor(0, 0, 0, 50))
        painter.fillRect(overlay.rect(), gradient)
        painter.end()
        
        combined = QPixmap(pixmap)
        combined_painter = QPainter(combined)
        combined_painter.drawPixmap(0, 0, overlay)
        combined_painter.end()
        return combined

    def load_metadata(self):
        try:
            cache_name = f"{self.search_title}"
            if self.search_year:
                cache_name += f" {self.search_year}"
            cache_file = f"{quote(cache_name)}.txt"
            cache_path = os.path.join(SYNOPSIS_CACHE_DIR, cache_file)
            meta_file = cache_file.replace('.txt', '_meta.txt')
            meta_path = os.path.join(SYNOPSIS_CACHE_DIR, meta_file)
            
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.synopsis = f.read()
                if os.path.exists(meta_path):
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = f.read().split('|')
                        if len(meta) == 3:
                            self.imdb_rating = float(meta[0]) if meta[0] != "None" else None
                            self.genres = meta[1].split(',') if meta[1] else []
                            self.release_year = meta[2] if meta[2] else self.search_year
                return

            params = {"api_key": TMDB_API_KEY, "query": self.search_title}
            if self.search_year:
                params["year"] = self.search_year

            search_url = f"{TMDB_API_URL}/search/multi"
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()

            overview = ""
            imdb_rating = None
            genres = []
            release_year = self.search_year

            for result in data.get("results", []):
                result_year = result.get("release_date", "")[:4] or result.get("first_air_date", "")[:4]
                if self.search_year and result_year == self.search_year:
                    overview = result.get("overview", "")
                    imdb_rating = result.get("vote_average", None)
                    if "genre_ids" in result:
                        genres = [str(gid) for gid in result["genre_ids"]]
                    release_year = result_year
                    if overview:
                        break
            if not overview:
                for result in data.get("results", []):
                    overview = result.get("overview", "")
                    imdb_rating = result.get("vote_average", None)
                    if "genre_ids" in result:
                        genres = [str(gid) for gid in result["genre_ids"]]
                    release_year = result.get("release_date", "")[:4] or result.get("first_air_date", "")[:4]
                    if overview:
                        break

            genre_map = {
                28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
                18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
                9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller",
                10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
                10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
            }
            genres_named = [genre_map.get(int(gid), "") for gid in genres if gid]
            genres_named = [g for g in genres_named if g]

            self.imdb_rating = imdb_rating
            self.genres = genres_named
            self.release_year = release_year
            self.synopsis = overview

            if overview:
                os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(overview)
                with open(meta_path, 'w', encoding='utf-8') as f:
                    f.write(f"{imdb_rating}|{','.join(genres_named)}|{release_year}")
        except Exception as e:
            logging.error(f"Error loading metadata for {self.display_name}: {str(e)}")
            self.synopsis = "Synopsis not available"

class PosterLoader(QObject):
    """Thread-safe poster and backdrop loader with signals and caching"""
    poster_loaded = pyqtSignal(object, QPixmap)  # label, pixmap
    poster_failed = pyqtSignal(object, str)      # label, fallback_icon
    poster_offline = pyqtSignal(object, str)     # label, fallback_icon 
    backdrop_loaded = pyqtSignal(object, QPixmap)  # label, pixmap
    backdrop_failed = pyqtSignal(object, str)      # label, fallback_icon
    backdrop_offline = pyqtSignal(object, str)     # label, title
    
    def load_poster(self, label, poster_path, fallback_icon):
        """Load poster in background thread and emit signal when done"""
        def load_image():
            try:
                # Create cache filename based on poster path
                cache_filename = f"{poster_path.strip('/').replace('/', '_')}.jpg"
                cache_path = os.path.join(POSTER_CACHE_DIR, cache_filename)
                os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
                
                # Try loading from cache first
                if os.path.exists(cache_path):
                    pixmap = QPixmap(cache_path)
                    if not pixmap.isNull():
                        self.poster_loaded.emit(label, pixmap)
                        return
                
                # Check internet connection before attempting download
                try:
                    requests.get("https://api.themoviedb.org/3", timeout=1)
                    internet_available = True
                except (requests.ConnectionError, requests.Timeout, Exception):
                    internet_available = False
                
                if not internet_available:
                    # For posters, we can use the standard fallback since they're smaller UI elements
                    self.poster_offline.emit(label, fallback_icon)
                    return
                
                # Download if not cached and internet is available
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    success = pixmap.loadFromData(response.content)
                    
                    if success and not pixmap.isNull():
                        # Save to cache
                        try:
                            pixmap.save(cache_path, "JPG")
                        except Exception:
                            pass  # Cache save failed, but continue
                        
                        self.poster_loaded.emit(label, pixmap)
                        return
                
                self.poster_failed.emit(label, fallback_icon)
                
            except Exception as e:
                self.poster_failed.emit(label, fallback_icon)
        
        threading.Thread(target=load_image, daemon=True).start()

    def load_backdrop(self, label, backdrop_path, fallback_icon, title=""):
        """Load backdrop in background thread with caching and emit signal when done"""
        def load_backdrop_image():
            try:
                # Create cache filename based on backdrop path and title
                safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
                cache_filename = f"{backdrop_path.strip('/').replace('/', '_')}_{safe_title}.jpg".replace(' ', '_')
                cache_path = os.path.join(BACKDROP_CACHE_DIR, cache_filename)
                os.makedirs(BACKDROP_CACHE_DIR, exist_ok=True)
                
                # Try loading from cache first (original cache)
                if os.path.exists(cache_path):
                    pixmap = QPixmap(cache_path)
                    if not pixmap.isNull():
                        self.backdrop_loaded.emit(label, pixmap)
                        return
                
                # Try loading from preloaded cache (movie or TV) with multiple fallback strategies
                backdrop_found = False
                
                # Strategy 1: Check for movie cache format (with and without year)
                for year_suffix in ["_no_year", ""]:
                    movie_cache_filename = f"movie_{safe_title}{year_suffix}.jpg".replace(' ', '_')
                    movie_cache_path = os.path.join(BACKDROP_CACHE_DIR, movie_cache_filename)
                    if os.path.exists(movie_cache_path):
                        pixmap = QPixmap(movie_cache_path)
                        if not pixmap.isNull():
                            self.backdrop_loaded.emit(label, pixmap)
                            backdrop_found = True
                            break
                
                if not backdrop_found:
                    # Strategy 2: Check for TV cache format (with and without year)
                    for year_suffix in ["_no_year", ""]:
                        tv_cache_filename = f"tv_{safe_title}{year_suffix}.jpg".replace(' ', '_')
                        tv_cache_path = os.path.join(BACKDROP_CACHE_DIR, tv_cache_filename)
                        if os.path.exists(tv_cache_path):
                            pixmap = QPixmap(tv_cache_path)
                            if not pixmap.isNull():
                                self.backdrop_loaded.emit(label, pixmap)
                                backdrop_found = True
                                break
                
                if not backdrop_found:
                    # Strategy 3: Fuzzy search - find any similar cached files
                    try:
                        # Clean the title for better matching
                        clean_title = safe_title.lower().replace(' ', '').replace('-', '').replace('_', '')
                        
                        for cached_file in os.listdir(BACKDROP_CACHE_DIR):
                            if cached_file.endswith('.jpg'):
                                # Extract the title part from cached filename
                                if cached_file.startswith('movie_') or cached_file.startswith('tv_'):
                                    cached_title_part = cached_file[6:] if cached_file.startswith('movie_') else cached_file[3:]
                                    cached_title_part = cached_title_part.split('_')[0].lower()  # Get title before year/extension
                                    
                                    # Check if titles are similar (contains or partial match)
                                    if (clean_title in cached_title_part or 
                                        cached_title_part in clean_title or
                                        len(set(clean_title.split()) & set(cached_title_part.split())) > 0):
                                        
                                        similar_cache_path = os.path.join(BACKDROP_CACHE_DIR, cached_file)
                                        pixmap = QPixmap(similar_cache_path)
                                        if not pixmap.isNull():
                                            self.backdrop_loaded.emit(label, pixmap)
                                            backdrop_found = True
                                            logging.info(f"Found similar backdrop: {cached_file} for {title}")
                                            break
                    except Exception as e:
                        logging.error(f"Error in fuzzy backdrop search: {str(e)}")
                
                # If still no backdrop found, check internet and try download
                if not backdrop_found:
                    # Check internet connection before attempting download
                    try:
                        requests.get("https://api.themoviedb.org/3", timeout=1)
                        internet_available = True
                    except (requests.ConnectionError, requests.Timeout, Exception):
                        internet_available = False
                    
                    if not internet_available:
                        # Emit special offline signal instead of fallback
                        self.backdrop_offline.emit(label, title)
                        return
                
                # Download if not cached and internet is available
                image_url = f"{TMDB_BACKDROP_URL}{backdrop_path}"
                response = requests.get(image_url, timeout=15)  # Longer timeout for larger images
                if response.status_code == 200:
                    pixmap = QPixmap()
                    success = pixmap.loadFromData(response.content)
                    
                    if success and not pixmap.isNull():
                        # Save to cache
                        try:
                            # Save at high quality for backdrops
                            pixmap.save(cache_path, "JPG", 90)
                        except Exception:
                            pass  # Cache save failed, but continue
                        
                        self.backdrop_loaded.emit(label, pixmap)
                        return
                
                self.backdrop_failed.emit(label, fallback_icon)
                
            except Exception as e:
                self.backdrop_failed.emit(label, fallback_icon)
        
        threading.Thread(target=load_backdrop_image, daemon=True).start()

class BackdropCachePreloader(QThread):
    """
    Background thread to preload backdrops for all movies and series.
    
    This class scans the movies and series folders, identifies all media files,
    extracts titles and metadata, searches TMDB for backdrop images, and downloads
    them to cache for offline viewing. The process runs in the background and
    provides progress updates.
    
    Features:
    - Automatically detects movies and TV series
    - Downloads high-quality backdrop images
    - Caches with organized naming for fast lookup
    - Respects API rate limits with delays
    - Provides progress feedback
    - Can be stopped gracefully
    """
    progress_updated = pyqtSignal(str, int, int)  # status, current, total
    cache_completed = pyqtSignal()
    
    def __init__(self):
        super().__init__()
        self.should_stop = False
        
    def stop(self):
        self.should_stop = True
        
    def run(self):
        """Run the backdrop preloading in background"""
        try:
            # Don't check internet here - assume it's already checked by caller
            logging.info("Backdrop cache preloader started")
            
            # Create cache directories
            os.makedirs(BACKDROP_CACHE_DIR, exist_ok=True)
            os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
            
            # Get all media files
            all_media_files = []
            
            # Scan movies folder
            if os.path.exists(movies_folder):
                for file_name in os.listdir(movies_folder):
                    if any(file_name.lower().endswith(ext) for ext in media_extensions):
                        all_media_files.append(('movie', os.path.join(movies_folder, file_name)))
            
            # Scan series folder
            if os.path.exists(series_folder):
                for root, dirs, files in os.walk(series_folder):
                    for file_name in files:
                        if any(file_name.lower().endswith(ext) for ext in media_extensions):
                            all_media_files.append(('series', os.path.join(root, file_name)))
            
            if not all_media_files:
                self.progress_updated.emit("No media files found", 0, 0)
                return
            
            total_files = len(all_media_files)
            self.progress_updated.emit(f"Starting backdrop cache for {total_files} media files", 0, total_files)
            
            # Process each media file
            processed = 0
            cached_count = 0
            
            for media_type, file_path in all_media_files:
                if self.should_stop:
                    break
                    
                try:
                    processed += 1
                    file_name = os.path.basename(file_path)
                    display_name = os.path.splitext(file_name)[0]
                    
                    if media_type == 'movie':
                        # Process movie
                        search_title = self.extract_movie_title(display_name)
                        search_year = extract_year(display_name)
                        if self.cache_movie_backdrop(search_title, search_year):
                            cached_count += 1
                        self.progress_updated.emit(f"Cached movie: {search_title}", processed, total_files)
                    else:
                        # Process series
                        series_info = extract_series_info(file_name)
                        if series_info[0]:  # If series name found
                            series_name = series_info[0]
                            year = series_info[2]
                            if self.cache_series_backdrop(series_name, year):
                                cached_count += 1
                            self.progress_updated.emit(f"Cached series: {series_name}", processed, total_files)
                    
                    # Reduce delay to speed up caching - but prevent overwhelming the API
                    time.sleep(0.05)  # Reduced from 0.1 to 0.05 seconds
                    
                except Exception as e:
                    logging.error(f"Error caching backdrop for {file_path}: {str(e)}")
                    continue
            
            completion_msg = f"Backdrop cache complete! Cached {cached_count} new backdrops from {processed} media files"
            self.progress_updated.emit(completion_msg, processed, total_files)
            self.cache_completed.emit()
            
        except Exception as e:
            logging.error(f"Error in backdrop cache preloader: {str(e)}")
            self.progress_updated.emit(f"Cache error: {str(e)}", 0, 0)
    
    def extract_movie_title(self, name):
        """Extract movie title by removing file extensions and year"""
        clean = name.replace('.', ' ').replace('_', ' ')
        match = re.search(r'(19|20)\d{2}', clean)
        if match:
            return clean[:match.start()].strip()
        return clean.strip()
    
    def cache_movie_backdrop(self, title, year=None):
        """Cache backdrop for a movie - returns True if cached, False if skipped"""
        try:
            # Check if already cached
            safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
            cache_filename = f"movie_{safe_title}_{year or 'no_year'}.jpg".replace(' ', '_')
            cache_path = os.path.join(BACKDROP_CACHE_DIR, cache_filename)
            
            if os.path.exists(cache_path):
                return False  # Already cached, skip
            
            # Search TMDB
            params = {"api_key": TMDB_API_KEY, "query": title}
            if year:
                params["year"] = year
            
            search_url = f"{TMDB_API_URL}/search/movie"
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            backdrop_path = None
            for result in data.get("results", [])[:1]:  # Just take first result
                backdrop_path = result.get("backdrop_path")
                if backdrop_path:
                    break
            
            if backdrop_path:
                success = self.download_and_cache_backdrop(backdrop_path, cache_path)
                return success
                
        except Exception as e:
            logging.error(f"Error caching movie backdrop for {title}: {str(e)}")
        
        return False
    
    def cache_series_backdrop(self, series_name, year=None):
        """Cache backdrop for a TV series - returns True if cached, False if skipped"""
        try:
            # Check if already cached
            safe_title = "".join(c for c in series_name if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
            cache_filename = f"tv_{safe_title}_{year or 'no_year'}.jpg".replace(' ', '_')
            cache_path = os.path.join(BACKDROP_CACHE_DIR, cache_filename)
            
            if os.path.exists(cache_path):
                return False  # Already cached, skip
            
            # Search TMDB
            params = {"api_key": TMDB_API_KEY, "query": series_name}
            if year:
                params["first_air_date_year"] = year
            
            search_url = f"{TMDB_API_URL}/search/tv"
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            backdrop_path = None
            for result in data.get("results", [])[:1]:  # Just take first result
                backdrop_path = result.get("backdrop_path")
                if backdrop_path:
                    break
            
            if backdrop_path:
                success = self.download_and_cache_backdrop(backdrop_path, cache_path)
                return success
                
        except Exception as e:
            logging.error(f"Error caching series backdrop for {series_name}: {str(e)}")
        
        return False
    
    def download_and_cache_backdrop(self, backdrop_path, cache_path):
        """Download and save backdrop to cache - returns True on success"""
        try:
            image_url = f"{TMDB_BACKDROP_URL}{backdrop_path}"
            response = requests.get(image_url, timeout=15)
            
            if response.status_code == 200:
                # Save directly to file
                with open(cache_path, 'wb') as f:
                    f.write(response.content)
                return True
                    
        except Exception as e:
            logging.error(f"Error downloading backdrop {backdrop_path}: {str(e)}")
        
        return False

class MediaOrganizerApp(QMainWindow):

    def show_episode_details(self, episode_item, parent_series_path=None):
        # Show details for a single episode file
        for i in reversed(range(self.details_layout.count())):
            widget = self.details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        back_button = QPushButton("Back")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        if parent_series_path:
            back_button.clicked.connect(lambda: self.show_series_episodes(self._make_series_item(parent_series_path)))
        else:
            back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))
        self.details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # --- Caching logic for episode synopsis and backdrop ---
        import os
        from urllib.parse import quote
        # Determine series name
        series_name = None
        if parent_series_path:
            series_name = os.path.basename(parent_series_path)
        else:
            if hasattr(episode_item, 'text'):
                ep_path = episode_item.text()
                if os.path.sep in ep_path:
                    series_name = os.path.basename(os.path.dirname(os.path.dirname(ep_path)))
        filename = episode_item.text()
        season_episode = self.extract_season_episode(filename)
        season_num, episode_num = (season_episode if season_episode else (1, 1))
        cache_base = f"{series_name}_S{season_num:02d}E{episode_num:02d}"
        cache_synopsis_file = os.path.join(SYNOPSIS_CACHE_DIR, f"{quote(cache_base)}_ep.txt")
        cache_backdrop_file = os.path.join(BACKDROP_CACHE_DIR, f"{quote(cache_base)}_ep.jpg")

        # Try to load cached synopsis and backdrop first
        episode_synopsis = None
        episode_title = filename
        backdrop_pixmap = None
        if os.path.exists(cache_synopsis_file):
            try:
                with open(cache_synopsis_file, 'r', encoding='utf-8') as f:
                    episode_synopsis = f.read().strip()
            except Exception:
                episode_synopsis = None
        if os.path.exists(cache_backdrop_file):
            try:
                pixmap = QPixmap(cache_backdrop_file)
                if not pixmap.isNull():
                    backdrop_pixmap = pixmap
            except Exception:
                backdrop_pixmap = None

        fetched_online = False
        # If not cached, fetch from TMDB
        if episode_synopsis is None or backdrop_pixmap is None:
            try:
                import requests
                import re
                TMDB_API_KEY = globals().get('TMDB_API_KEY', None)
                TMDB_API_URL = globals().get('TMDB_API_URL', 'https://api.themoviedb.org/3')
                if TMDB_API_KEY and series_name:
                    params = {"api_key": TMDB_API_KEY, "query": series_name}
                    search_url = f"{TMDB_API_URL}/search/tv"
                    resp = requests.get(search_url, params=params, timeout=5)
                    resp.raise_for_status()
                    data = resp.json()
                    best_match = None
                    best_score = -1
                    for result in data.get("results", []):
                        title = result.get("name", "")
                        score = 0
                        if title.lower() == series_name.lower():
                            score += 10
                        if re.sub(r'[^\w]', '', title.lower()) == re.sub(r'[^\w]', '', series_name.lower()):
                            score += 5
                        if score > best_score:
                            best_score = score
                            best_match = result
                    if best_match:
                        tmdb_id = best_match.get("id")
                        if tmdb_id:
                            ep_url = f"{TMDB_API_URL}/tv/{tmdb_id}/season/{season_num}/episode/{episode_num}"
                            ep_params = {"api_key": TMDB_API_KEY}
                            ep_resp = requests.get(ep_url, params=ep_params, timeout=5)
                            if ep_resp.status_code == 200:
                                ep_data = ep_resp.json()
                                episode_synopsis = ep_data.get("overview") or episode_synopsis
                                episode_title = ep_data.get("name") or episode_title
                                # Save synopsis to cache
                                if episode_synopsis:
                                    try:
                                        os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
                                        with open(cache_synopsis_file, 'w', encoding='utf-8') as f:
                                            f.write(episode_synopsis)
                                    except Exception:
                                        pass
                                # Download and cache backdrop if available
                                still_path = ep_data.get("still_path")
                                if still_path:
                                    try:
                                        TMDB_BACKDROP_URL = globals().get('TMDB_BACKDROP_URL', 'https://image.tmdb.org/t/p/original')
                                        img_url = f"{TMDB_BACKDROP_URL}{still_path}"
                                        img_resp = requests.get(img_url, timeout=10)
                                        if img_resp.status_code == 200:
                                            from PIL import Image
                                            from io import BytesIO
                                            img = Image.open(BytesIO(img_resp.content))
                                            os.makedirs(BACKDROP_CACHE_DIR, exist_ok=True)
                                            img.save(cache_backdrop_file, format='JPEG')
                                            pixmap = QPixmap(cache_backdrop_file)
                                            if not pixmap.isNull():
                                                backdrop_pixmap = pixmap
                                    except Exception:
                                        pass
                                fetched_online = True
            except Exception as e:
                import logging
                logging.error(f"Error fetching episode synopsis/backdrop from TMDB: {str(e)}")

        # Banner: show episode backdrop if available, else placeholder
        banner_label = QLabel()
        banner_label.setFixedHeight(380)
        banner_label.setMinimumHeight(300)
        banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        banner_label.setAlignment(Qt.AlignCenter)
        if backdrop_pixmap:
            # Use the same create_poster_banner logic as movies for gradient overlay and scaling
            banner_label.original_pixmap = backdrop_pixmap
            banner = self.create_poster_banner(backdrop_pixmap, width=self.details_view.width() or 900, height=380)
            banner_label.setPixmap(banner)
            # Attach resize event for responsive resizing
            def resize_banner_event(event, label=banner_label):
                self.resize_banner(label, event)
            banner_label.resizeEvent = resize_banner_event
        else:
            banner_label.setText("📺")
            banner_label.setStyleSheet("font-size: 64px; color: #888; background: #222; border-radius: 8px;")
        self.details_layout.addWidget(banner_label)

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)

        # If still no synopsis, fallback
        if not episode_synopsis:
            episode_synopsis = "Synopsis not available"

        # Title
        title_label = QLabel(episode_title)
        title_label.setStyleSheet("font-size: 22px; font-weight: bold; color: white; margin-bottom: 10px;")
        details_layout.addWidget(title_label)

        # Metadata (season/episode number)
        meta_label = QLabel(f"Season {season_num}, Episode {episode_num}")
        meta_label.setStyleSheet("font-size: 14px; color: #AAAAAA; margin-bottom: 10px;")
        details_layout.addWidget(meta_label)

        # Synopsis
        synopsis_label = QLabel("Synopsis")
        synopsis_label.setStyleSheet("font-size: 16px; font-weight: bold; color: white; margin-bottom: 5px;")
        details_layout.addWidget(synopsis_label)
        synopsis_text = QTextEdit()
        synopsis_text.setPlainText(episode_synopsis)
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("background: transparent; color: white; border: none; font-size: 13px;")
        synopsis_text.setFixedHeight(100)
        details_layout.addWidget(synopsis_text)

        # Play button
        play_button = QPushButton("Play")
        play_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 16px;
                border-radius: 4px;
                margin-top: 20px;
                max-width: 150px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        play_button.clicked.connect(lambda: self.play_media(episode_item))
        details_layout.addWidget(play_button)

        details_layout.addStretch()
        self.details_layout.addWidget(details_widget)
        self.stacked_widget.setCurrentIndex(4)
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mediiaflix")
        
        # Set minimum size and initial size, but allow full resizing
        self.setMinimumSize(800, 600)  # Minimum usable size
        self.resize(1200, 800)  # Initial size
        
        self.current_season = None
        self.active_tab = None  # Track the active tab
        self.current_content_filter = "movie"  # Default content filter for home tab (Movies)
        
        # Navigation tracking for cast views
        self.previous_view_stack = []  # Stack to track navigation history
        self.current_movie_data = None  # Track current movie/series data
        self.current_series_data = None
        
        # Loading state flags
        self.media_lists_loaded = False
        self.home_content_loaded = False
        self.media_loading_in_progress = False  # Prevent duplicate loading
        
        # Content rotation for variety
        self.content_rotation_page = 1
        
        # Create poster loader with signal connections
        self.poster_loader = PosterLoader()
        self.poster_loader.poster_loaded.connect(self.on_poster_loaded)
        self.poster_loader.poster_failed.connect(self.on_poster_failed)
        self.poster_loader.poster_offline.connect(self.on_poster_offline)
        self.poster_loader.backdrop_loaded.connect(self.on_backdrop_loaded)
        self.poster_loader.backdrop_failed.connect(self.on_backdrop_failed)
        self.poster_loader.backdrop_offline.connect(self.on_backdrop_offline)
        
        # Initialize backdrop cache preloader
        self.backdrop_preloader = BackdropCachePreloader()
        self.backdrop_preloader.progress_updated.connect(self.on_cache_progress_updated)
        self.backdrop_preloader.cache_completed.connect(self.on_cache_completed)
        
        # self.load_custom_fonts()  # Disabled for EXE stability
        self.set_dark_theme()
        # self.optimize_font_rendering()  # Disabled for EXE stability
        
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QHBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.create_sidebar()
        self.create_main_content()
        
        # Show app immediately, then load content asynchronously
        self.show()
        QApplication.processEvents()  # Process the show event
        
        # Load media lists in background
        QTimer.singleShot(100, self.update_media_lists_async)
        
        # Start backdrop cache preloading immediately when internet is available
        QTimer.singleShot(500, self.check_internet_and_start_cache)  # Start checking after 0.5 seconds
        
        # Setup automatic content rotation timer (refresh every 20 minutes)
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(self.auto_refresh_home_content)
        self.auto_refresh_timer.start(1200000)  # 20 minutes = 1,200,000 milliseconds
        
        self.setWindowIcon(QIcon(self.create_netflix_icon()))

    def closeEvent(self, event):
        """Handle app closing - cleanup backdrop preloader"""
        if hasattr(self, 'backdrop_preloader'):
            self.stop_backdrop_cache_preload()
        super().closeEvent(event)

    def resizeEvent(self, event):
        """Handle window resize events and update banner sizes accordingly"""
        super().resizeEvent(event)
        # Update all banner labels when window is resized
        self.update_all_banners()

    def update_all_banners(self):
        """Update all visible banner labels to match new window size"""
        # Find all banner labels in current views and resize them
        for view in [self.details_view, self.episodes_view, self.home_details_view]:
            for i in range(view.layout().count()):
                widget = view.layout().itemAt(i).widget()
                if isinstance(widget, QLabel) and hasattr(widget, 'original_pixmap'):
                    # Trigger resize for this banner
                    QTimer.singleShot(10, lambda w=widget: self.resize_banner(w, None))
    
    def load_custom_fonts(self):
        # Disabled custom font loading for EXE stability
        pass

    def set_dark_theme(self):
        dark_palette = QPalette()
        dark_palette.setColor(QPalette.Window, QColor(20, 20, 20))
        dark_palette.setColor(QPalette.WindowText, Qt.white)
        dark_palette.setColor(QPalette.Base, QColor(30, 30, 30))
        dark_palette.setColor(QPalette.AlternateBase, QColor(40, 40, 40))
        dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
        dark_palette.setColor(QPalette.ToolTipText, Qt.white)
        dark_palette.setColor(QPalette.Text, Qt.white)
        dark_palette.setColor(QPalette.Button, QColor(50, 50, 50))
        dark_palette.setColor(QPalette.ButtonText, Qt.white)
        dark_palette.setColor(QPalette.BrightText, Qt.red)
        dark_palette.setColor(QPalette.Highlight, QColor(229, 9, 20))
        dark_palette.setColor(QPalette.HighlightedText, Qt.white)
        self.setPalette(dark_palette)
        
        dark_stylesheet = """
QWidget {
    background-color: #181818;
    color: #ffffff;
    font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
    font-size: 11px;
}
QLineEdit, QListWidget, QTextEdit {
    background-color: #222222;
    color: #ffffff;
    border: 1px solid #444444;
    font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
    font-size: 12px;
}
QPushButton {
    background-color: #e50914;
    color: #ffffff;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #b00610;
}
QGroupBox, QLabel {
    color: #ffffff;
    font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
}
/* Modern scroll bars */
QScrollBar:vertical {
    border: none;
    background: #222222;
    width: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:vertical {
    background: #555555;
    min-height: 20px;
    border-radius: 5px;
}
QScrollBar::handle:vertical:hover {
    background: #777777;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
    background: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
}
QScrollBar:horizontal {
    border: none;
    background: #222222;
    height: 10px;
    margin: 0px 0px 0px 0px;
}
QScrollBar::handle:horizontal {
    background: #555555;
    min-width: 20px;
    border-radius: 5px;
}
QScrollBar::handle:horizontal:hover {
    background: #777777;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
    background: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
}
"""

        self.setStyleSheet(dark_stylesheet)

    def create_crisp_font(self, family="Netflix Sans Medium", size=10, weight=QFont.Normal, bold=False):
        """Create a font with optimal rendering settings for crisp text display"""
        # Try the preferred font first, fall back to system fonts if needed
        font_families = [family, "Netflix Sans", "Segoe UI", "Arial", "sans-serif"]
        
        font = None
        for font_family in font_families:
            font = QFont(font_family, size, weight)
            # Check if the font family is actually available
            font_info = QFontDatabase()
            available_families = font_info.families()
            if font_family in available_families or font_family in ["Arial", "sans-serif"]:
                break
        
        if not font:
            font = QFont("Arial", size, weight)
        
        # Enable font hinting for crisp edges
        font.setHintingPreference(QFont.PreferFullHinting)
        
        # Set style strategy for better rendering
        font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
        
        # Set weight if bold is requested
        if bold:
            font.setBold(True)
            
        return font

    def optimize_font_rendering(self):
        # Disabled font rendering optimization for EXE stability
        pass

    def create_netflix_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(229, 9, 20))
        painter.setBrush(QColor(229, 9, 20))
        points = [
            QPoint(10, 10),
            QPoint(20, 10),
            QPoint(40, 50),
            QPoint(50, 50),
            QPoint(30, 10),
            QPoint(54, 10),
            QPoint(54, 54),
            QPoint(44, 54),
            QPoint(24, 14),
            QPoint(10, 54),
            QPoint(10, 10)
        ]
        painter.drawPolygon(points)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(120, 10, 60, 5)
        painter.end()
        return pixmap

    def extract_movie_title(self, name):
        """Extract movie title by removing file extensions, year, and quality indicators"""
        # Remove file extension
        clean = os.path.splitext(name)[0]
        
        # Replace dots and underscores with spaces
        clean = clean.replace('.', ' ').replace('_', ' ')
        
        # Remove common quality indicators
        quality_patterns = [
            r'\b(1080p?|720p?|480p?|2160p?|4K|UHD|HD|SD)\b',
            r'\b(x264|x265|h264|h265|HEVC|AVC)\b',
            r'\b(BluRay|BRRip|DVDRip|WEBRip|WEB-DL|HDTV|CAM|TS)\b',
            r'\b(AAC|AC3|DTS|MP3)\b',
            r'\[(.*?)\]',  # Remove content in square brackets
            r'\((.*?)\)',  # Remove content in parentheses (but keep years)
        ]
        
        for pattern in quality_patterns[:-1]:  # Skip parentheses pattern for now
            clean = re.sub(pattern, '', clean, flags=re.IGNORECASE)
        
        # Remove release group tags (usually at the end after a dash)
        clean = re.sub(r'-[A-Za-z0-9]+$', '', clean)
        
        # Remove year (but keep track of it)
        year_match = re.search(r'\b(19|20)\d{2}\b', clean)
        if year_match:
            clean = clean[:year_match.start()].strip()
        
        # Clean up extra spaces
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        return clean

    def resize_banner(self, banner_label, event):
        """Dynamically resize banner with gradient overlay to match window width"""
        if hasattr(banner_label, 'original_pixmap') and banner_label.original_pixmap:
            # Get current label dimensions
            label_width = banner_label.width()
            label_height = banner_label.height()
            
            if label_width > 0 and label_height > 0:
                # Create new banner with current dimensions
                banner = self.create_poster_banner(banner_label.original_pixmap, width=label_width, height=label_height)
                banner_label.setPixmap(banner)

    def create_sidebar(self):
        self.sidebar = QFrame()
        # Use minimum and maximum width instead of fixed width for better responsiveness
        self.sidebar.setMinimumWidth(200)
        self.sidebar.setMaximumWidth(250)
        self.sidebar.setStyleSheet("background-color: #000000;")
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(20, 30, 20, 30)
        self.sidebar_layout.setSpacing(30)
        
        logo = QLabel()
        logo_pixmap = QPixmap(180, 50)
        logo_pixmap.fill(Qt.transparent)
        painter = QPainter(logo_pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(229, 9, 20))
        painter.setBrush(QColor(229, 9, 20))
        points = [
            QPoint(10, 10),
            QPoint(20, 10),
            QPoint(40, 40),
            QPoint(50, 40),
            QPoint(30, 10),
            QPoint(54, 10),
            QPoint(54, 40),
            QPoint(44, 40),
            QPoint(24, 20),
            QPoint(10, 40),
            QPoint(10, 10)
        ]
        painter.drawPolygon(points)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(120, 10, 60, 5)
        painter.end()
        logo.setPixmap(logo_pixmap)
        logo.setAlignment(Qt.AlignCenter)
        self.sidebar_layout.addWidget(logo)
        
        # Create nav buttons and store them as instance variables
        self.home_button = QPushButton("Home")
        self.movies_button = QPushButton("Movies")
        self.series_button = QPushButton("TV Series")
        self.sort_button = QPushButton("Sort Files")
        
        # Navigation buttons that can remain highlighted (Home, Movies and Series)
        nav_buttons = [
            (self.home_button, self.show_home_tab),
            (self.movies_button, self.show_movies_tab),
            (self.series_button, self.show_series_tab),
        ]
        
        for btn, callback in nav_buttons:
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(self.create_tab_handler(btn, callback))
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding: 12px 20px;
                    font-size: 16px;
                    border-radius: 0;
                    background-color: transparent;
                    font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
                    font-weight: 500;
                    letter-spacing: 0.1px;
                }
                QPushButton:hover {
                    background-color: #2D2D2D;
                }
                QPushButton:checked {
                    background-color: #E50914;
                    font-weight: 600;
                }
            """)
            btn.setCheckable(True)
            # Apply crisp font to navigation buttons
            nav_font = self.create_crisp_font("Netflix Sans Medium", 16)
            btn.setFont(nav_font)
            self.sidebar_layout.addWidget(btn)

        # Sort button with special behavior (temporary highlight only)
        self.sort_button.setCursor(Qt.PointingHandCursor)
        self.sort_button.clicked.connect(self.create_sort_handler())
        self.sort_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 12px 20px;
                font-size: 16px;
                border-radius: 0;
                background-color: transparent;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
                font-weight: 500;
                letter-spacing: 0.1px;
            }
            QPushButton:hover {
                background-color: #2D2D2D;
            }
        """)
        self.sort_button.setCheckable(False)  # Don't allow persistent checking
        # Apply crisp font to sort button
        sort_font = self.create_crisp_font("Netflix Sans Medium", 16)
        self.sort_button.setFont(sort_font)
        self.sidebar_layout.addWidget(self.sort_button)

        self.sidebar_layout.addStretch()
        
        self.settings_button = QPushButton("Settings")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.clicked.connect(self.show_settings)
        self.settings_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 12px 20px;
                font-size: 16px;
                border-radius: 0;
                background-color: transparent;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
                font-weight: 500;
                letter-spacing: 0.1px;
            }
            QPushButton:hover {
                background-color: #2D2D2D;
            }
        """)
        # Apply crisp font to settings button
        settings_font = self.create_crisp_font("Netflix Sans Medium", 16)
        self.settings_button.setFont(settings_font)
        self.sidebar_layout.addWidget(self.settings_button)
        
        self.main_layout.addWidget(self.sidebar)
        
        # Set home as default active tab
        self.set_active_tab(self.home_button)
    
    def create_tab_handler(self, button, callback):
        def handler():
            self.set_active_tab(button)
            callback()
            
            # Trigger async loading if needed based on which tab was clicked
            if button == self.home_button and not self.home_content_loaded:
                QTimer.singleShot(50, self.load_home_content_async)
            elif button == self.movies_button and not self.media_lists_loaded:
                # Only start loading if not already in progress
                QTimer.singleShot(50, self.update_media_lists_async)
                
        return handler
    
    def create_sort_handler(self):
        def handler():
            # Temporarily highlight the sort button
            self.sort_button.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding: 12px 20px;
                    font-size: 16px;
                    border-radius: 0;
                    background-color: #E50914;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #F40612;
                }
            """)
            
            # Reset the style after a short delay
            QTimer.singleShot(200, self.reset_sort_button_style)
            
            # Call the sort confirmation
            self.show_sort_confirmation()
        return handler
    
    def reset_sort_button_style(self):
        self.sort_button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 12px 20px;
                font-size: 16px;
                border-radius: 0;
                background-color: transparent;
            }
            QPushButton:hover {
                background-color: #2D2D2D;
            }
        """)
    
    def set_active_tab(self, button):
        # Only allow Home, Movies and Series buttons to remain highlighted
        if button not in [self.home_button, self.movies_button, self.series_button]:
            return
            
        # Reset Home, Movies and Series buttons to inactive state
        for btn in [self.home_button, self.movies_button, self.series_button]:
            btn.setChecked(False)
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding: 12px 20px;
                    font-size: 16px;
                    border-radius: 0;
                    background-color: transparent;
                }
                QPushButton:hover {
                    background-color: #2D2D2D;
                }
            """)
        
        # Set the clicked button as active
        button.setChecked(True)
        button.setStyleSheet("""
            QPushButton {
                text-align: left;
                padding: 12px 20px;
                font-size: 16px;
                border-radius: 0;
                background-color: #E50914;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        
        self.active_tab = button

    def refresh_all(self):
        self.setEnabled(False)
        self.cache_thread = CacheClearThread()
        self.cache_thread.finished.connect(self._on_refresh_done)
        self.cache_thread.start()

    def _on_refresh_done(self):
        # Reset loading flags to allow fresh loading
        self.media_lists_loaded = False
        self.media_loading_in_progress = False
        self.home_content_loaded = False
        
        # Use async loading for better performance
        self.update_media_lists_async()
        self.populate_series_list()
        self.setEnabled(True)
        QMessageBox.information(self, "Refreshed", "Cache cleared and media lists refreshed!")
    
    def start_backdrop_cache_preload(self):
        """Start the backdrop cache preloading in background"""
        if not self.backdrop_preloader.isRunning():
            logging.info("Starting backdrop cache preload...")
            self.backdrop_preloader.start()
    
    def check_internet_and_start_cache(self):
        """Check for internet connection and start backdrop caching immediately"""
        try:
            # Quick internet check with TMDB API key
            response = requests.get(
                "https://api.themoviedb.org/3/configuration", 
                params={"api_key": TMDB_API_KEY},
                timeout=5
            )
            if response.status_code == 200:
                # Internet is available, start backdrop caching immediately
                logging.info("Internet detected - starting immediate backdrop cache preload")
                self.start_backdrop_cache_preload()
            else:
                # Retry after 5 seconds
                logging.info(f"Internet check failed (status {response.status_code}) - retrying in 5 seconds")
                QTimer.singleShot(5000, self.check_internet_and_start_cache)
        except requests.ConnectionError as e:
            # No internet, retry after 5 seconds
            logging.info("Internet not available - retrying in 5 seconds")
            QTimer.singleShot(5000, self.check_internet_and_start_cache)
        except requests.Timeout as e:
            # Timeout, retry after 5 seconds
            logging.info("Internet check timeout - retrying in 5 seconds")
            QTimer.singleShot(5000, self.check_internet_and_start_cache)
        except Exception as e:
            # Other error, retry after 5 seconds
            logging.info(f"Internet check error: {str(e)} - retrying in 5 seconds")
            QTimer.singleShot(5000, self.check_internet_and_start_cache)
    
    def on_cache_progress_updated(self, status, current, total):
        """Handle backdrop cache progress updates"""
        if total > 0:
            progress_percent = int((current / total) * 100)
            # Update window title with progress (more detailed indication)
            if progress_percent < 100:
                self.setWindowTitle(f"Mediaflix - Downloading backdrops {progress_percent}% ({current}/{total})")
            else:
                self.setWindowTitle("Mediaflix - Backdrop download complete!")
                # Reset title after 5 seconds
                QTimer.singleShot(5000, lambda: self.setWindowTitle("Mediaflix"))
            logging.info(f"Backdrop cache: {status} ({current}/{total}) - {progress_percent}%")
        else:
            logging.info(f"Backdrop cache: {status}")
            # Show status in title for non-progress messages
            if "error" not in status.lower():
                self.setWindowTitle(f"Mediaflix - {status}")
                QTimer.singleShot(3000, lambda: self.setWindowTitle("Mediaflix"))
    
    def on_cache_completed(self):
        """Handle backdrop cache completion"""
        logging.info("Backdrop cache preload completed!")
        # Show completion in title briefly
        self.setWindowTitle("Mediaflix - All backdrops ready for offline viewing!")
        # Reset window title after 5 seconds
        QTimer.singleShot(5000, lambda: self.setWindowTitle("Mediaflix"))
        
    def stop_backdrop_cache_preload(self):
        """Stop the backdrop cache preloading"""
        if self.backdrop_preloader.isRunning():
            self.backdrop_preloader.stop()
            self.backdrop_preloader.wait(5000)  # Wait up to 5 seconds for cleanup
    
    def manual_backdrop_preload(self, button):
        """Manually trigger backdrop preload from settings"""
        if self.backdrop_preloader.isRunning():
            # Stop current preload
            self.stop_backdrop_cache_preload()
            button.setText("🚀 Start Cache")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 10px 18px;
                    font-size: 13px;
                    border-radius: 6px;
                    font-weight: 600;
                    min-width: 100px;
                }
                QPushButton:hover {
                    background-color: #F40612;
                }
                QPushButton:pressed {
                    background-color: #B00710;
                }
            """)
        else:
            # Start preload
            self.backdrop_preloader = BackdropCachePreloader()
            self.backdrop_preloader.progress_updated.connect(self.on_cache_progress_updated)
            self.backdrop_preloader.cache_completed.connect(lambda: self.manual_cache_completed(button))
            self.backdrop_preloader.start()
            
            button.setText("⏹️ Stop")
            button.setStyleSheet("""
                QPushButton {
                    background-color: #666666;
                    color: white;
                    border: none;
                    padding: 10px 18px;
                    font-size: 13px;
                    border-radius: 6px;
                    font-weight: 600;
                    min-width: 100px;
                }
                QPushButton:hover {
                    background-color: #777777;
                }
            """)
    
    def manual_cache_completed(self, button):
        """Handle manual cache completion"""
        self.on_cache_completed()
        button.setText("✅ Done")
        button.setStyleSheet("""
            QPushButton {
                background-color: #28A745;
                color: white;
                border: none;
                padding: 10px 18px;
                font-size: 13px;
                border-radius: 6px;
                font-weight: 600;
                min-width: 100px;
            }
        """)
        button.setEnabled(False)
        
        # Reset button after 3 seconds
        QTimer.singleShot(3000, lambda: self.reset_cache_button(button))
    
    def reset_cache_button(self, button):
        """Reset the cache button to original state"""
        button.setText("🚀 Start Cache")
        button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 10px 18px;
                font-size: 13px;
                border-radius: 6px;
                font-weight: 600;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)
        button.setEnabled(True)
    
    def get_cached_backdrop_count(self):
        """Get count of cached backdrop images"""
        if not os.path.exists(BACKDROP_CACHE_DIR):
            return 0
        try:
            backdrop_files = [f for f in os.listdir(BACKDROP_CACHE_DIR) if f.endswith('.jpg')]
            return len(backdrop_files)
        except Exception:
            return 0
    
    def show_cache_status(self):
        """Show current cache status"""
        cached_count = self.get_cached_backdrop_count()
        QMessageBox.information(
            self, 
            "Cache Status", 
            f"Currently cached: {cached_count} backdrop images\nCache location: {BACKDROP_CACHE_DIR}"
        )

    def create_main_content(self):
        self.content_area = QFrame()
        self.content_area.setStyleSheet("background-color: #141414;")
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("border: none;")
        
        # Home view (index 0)
        self.home_view = self.create_home_view()
        self.stacked_widget.addWidget(self.home_view)
        
        # Movies view (index 1)
        self.movies_view = self.create_media_view("Movies")
        self.stacked_widget.addWidget(self.movies_view)
        
        # Series list view (index 2)
        self.series_list_view = self.create_series_list_view()
        self.stacked_widget.addWidget(self.series_list_view)
        
        # Episodes view (index 3)
        self.episodes_view = QWidget()
        self.episodes_layout = QVBoxLayout(self.episodes_view)
        self.episodes_layout.setContentsMargins(20, 15, 20, 15)
        self.episodes_layout.setSpacing(20)
        self.stacked_widget.addWidget(self.episodes_view)
        
        # Details view (index 4)
        self.details_view = QWidget()
        self.details_layout = QVBoxLayout(self.details_view)
        self.details_layout.setContentsMargins(20, 15, 20, 15)
        self.details_layout.setSpacing(20)
        self.stacked_widget.addWidget(self.details_view)
        
        # Home details view (index 5) - for discovered movies
        self.home_details_view = QWidget()
        self.home_details_layout = QVBoxLayout(self.home_details_view)
        self.home_details_layout.setContentsMargins(20, 15, 20, 15)
        self.home_details_layout.setSpacing(20)
        self.stacked_widget.addWidget(self.home_details_view)
        
        self.content_layout.addWidget(self.stacked_widget)
        self.main_layout.addWidget(self.content_area, 1)

    def create_home_view(self):
        """Create the Netflix-style home discovery view with movies by genre and search bar"""
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(30)
        
        # Search Bar Container (curved corners)
        search_container = QWidget()
        search_container.setFixedHeight(60)
        search_layout = QHBoxLayout(search_container)
        search_layout.setContentsMargins(0, 0, 0, 0)
        search_layout.setSpacing(0)

        # Search Input Field - More rounded corners
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search movies, TV shows...")
        self.search_input.setStyleSheet("""
            QLineEdit {
                background-color: #2D2D2D;
                color: white;
                border: 2px solid #444;
                border-radius: 25px;
                padding: 12px 32px;
                font-size: 16px;
                font-family: 'Netflix Sans Medium', 'Segoe UI', 'Arial', sans-serif;
                min-width: 700px;
                max-width: 1200px;
            }
            QLineEdit:focus {
                border: 2px solid #E50914;
            }
        """)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.handle_search_input_changed)
        self.search_input.returnPressed.connect(self.perform_search)

        search_layout.addWidget(self.search_input)
        search_layout.setAlignment(self.search_input, Qt.AlignHCenter)
        self.search_input.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(search_container)
        
        # Title
        title_container = QWidget()
        title_container.setFixedHeight(60)
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("Discover Movies & Shows")
        title_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: 700; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
            letter-spacing: -0.5px;
        """)
        title_font = self.create_crisp_font("Netflix Sans Bold", 28, bold=True)
        title_label.setFont(title_font)
        title_layout.addWidget(title_label)
        
        underline = QWidget()
        underline.setFixedHeight(3)
        underline.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #E50914, stop:0.5 #B00710, stop:1 #E50914);
        """)
        title_layout.addWidget(underline)
        
        layout.addWidget(title_container)
        
        # Content filter widget - Toggle between Movies and TV Series
        filter_container = QWidget()
        filter_layout = QHBoxLayout(filter_container)
        filter_layout.setContentsMargins(0, 0, 0, 25)
        filter_layout.setSpacing(0)
        
        # Create toggle button container
        toggle_container = QWidget()
        toggle_container.setFixedHeight(45)
        toggle_container.setStyleSheet("""
            QWidget {
                background-color: #2D2D2D;
                border-radius: 22px;
            }
        """)
        toggle_layout = QHBoxLayout(toggle_container)
        toggle_layout.setContentsMargins(3, 3, 3, 3)
        toggle_layout.setSpacing(0)
        
        # Movies button
        self.movies_filter_btn = QPushButton("Movies")
        self.movies_filter_btn.setCheckable(True)
        self.movies_filter_btn.setFixedHeight(39)
        self.movies_filter_btn.setFixedWidth(120)
        self.movies_filter_btn.clicked.connect(lambda: self.filter_home_content("movie"))
        
        # TV Series button
        self.series_filter_btn = QPushButton("TV Series")
        self.series_filter_btn.setCheckable(True)
        self.series_filter_btn.setFixedHeight(39)
        self.series_filter_btn.setFixedWidth(120)
        self.series_filter_btn.clicked.connect(lambda: self.filter_home_content("tv"))
        
        # Style for toggle buttons
        toggle_button_style = """
            QPushButton {
                background-color: transparent;
                color: #AAAAAA;
                border: none;
                padding: 8px 16px;
                font-size: 15px;
                font-weight: 500;
                border-radius: 19px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
                letter-spacing: 0.2px;
            }
            QPushButton:hover {
                color: white;
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:checked {
                background-color: #E50914;
                color: white;
                font-weight: 600;
            }
        """
        
        self.movies_filter_btn.setStyleSheet(toggle_button_style)
        self.series_filter_btn.setStyleSheet(toggle_button_style)
        
        # Apply crisp fonts to filter buttons
        filter_font = self.create_crisp_font("Netflix Sans Medium", 15)
        self.movies_filter_btn.setFont(filter_font)
        self.series_filter_btn.setFont(filter_font)
        
        toggle_layout.addWidget(self.movies_filter_btn)
        toggle_layout.addWidget(self.series_filter_btn)
        
        # Set Movies as default
        self.movies_filter_btn.setChecked(True)
        self.current_content_filter = "movie"
        
        filter_layout.addWidget(toggle_container)
        
        # Add stretch to push refresh button to far right
        filter_layout.addStretch()
        
        # Add reload button on the far right
        self.reload_home_btn = QPushButton("⟳")
        self.reload_home_btn.setFixedHeight(45)
        self.reload_home_btn.setFixedWidth(45)
        self.reload_home_btn.clicked.connect(self.reload_home_content)
        self.reload_home_btn.setToolTip("Refresh content")
        self.reload_home_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: #FFFFFF;
                border: none;
                padding: 0px;
                font-size: 18px;
                font-weight: 600;
                border-radius: 22px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
            }
            QPushButton:hover {
                background-color: #E50914;
                color: white;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)
        reload_font = self.create_crisp_font("Netflix Sans Medium", 18)
        self.reload_home_btn.setFont(reload_font)
        
        filter_layout.addWidget(self.reload_home_btn)
        
        layout.addWidget(filter_container)
        
        # Create content area that will be populated asynchronously
        self.home_content_area = QWidget()
        self.home_content_layout = QVBoxLayout(self.home_content_area)
        self.home_content_layout.setContentsMargins(0, 0, 0, 0)
        self.home_content_layout.setSpacing(30)
        
        # Show initial loading state
        self.show_home_loading()
        
        layout.addWidget(self.home_content_area)
        layout.addStretch()
        
        scroll_area.setWidget(container)
        
        # Load content asynchronously immediately
        QTimer.singleShot(10, self.load_home_content_async)
        
        return scroll_area

    def handle_search_input_changed(self, text):
        """Handle changes in the search input field"""
        # When search is cleared, return to current content filter
        if not text.strip():
            self.current_content_filter = "movie" if self.movies_filter_btn.isChecked() else "tv"
            self.load_home_content_async()
            return
        # Use a timer to debounce the search
        if hasattr(self, 'search_timer'):
            self.search_timer.stop()
        self.search_timer = QTimer()
        self.search_timer.setSingleShot(True)
        self.search_timer.timeout.connect(lambda: self.perform_search(text))
        self.search_timer.start(500)  # Wait 500ms after last keystroke

    def perform_search(self, query=None):
        """Perform search based on the search input"""
        if query is None:
            query = self.search_input.text().strip()
        if not query:
            # If empty query, show normal home content
            self.current_content_filter = "movie" if self.movies_filter_btn.isChecked() else "tv"
            self.load_home_content_async()
            return
        # Clear current content
        for i in reversed(range(self.home_content_layout.count())):
            widget = self.home_content_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        # Show loading state
        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setContentsMargins(50, 50, 50, 50)
        loading_layout.setSpacing(20)
        loading_label = QLabel("🔍 Searching...")
        loading_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        loading_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(loading_label)
        self.home_content_layout.addWidget(loading_widget)
        # Perform search asynchronously
        QTimer.singleShot(50, lambda: self.execute_search(query))

    def execute_search(self, query):
        """Execute the search with the given query"""
        try:
            # Clear loading widget
            for i in reversed(range(self.home_content_layout.count())):
                widget = self.home_content_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            # Determine content type based on current filter
            content_type = "movie" if self.movies_filter_btn.isChecked() else "tv"
            # Search based on current filter
            params = {
                "api_key": TMDB_API_KEY,
                "query": query,
                "page": 1,
                "include_adult": "false"
            }
            if content_type == "movie":
                url = f"{TMDB_API_URL}/search/movie"
                title = f"Movies matching '{query}'"
            else:
                url = f"{TMDB_API_URL}/search/tv"
                title = f"TV Shows matching '{query}'"
            response = requests.get(url, params=params, timeout=5)
            data = response.json().get("results", [])[:15]  # Limit to 15 results
            # Create results container
            results_container = QWidget()
            results_layout = QVBoxLayout(results_container)
            results_layout.setContentsMargins(0, 0, 0, 0)
            results_layout.setSpacing(30)
            # Add results if found
            if data:
                results_label = QLabel(title)
                results_label.setStyleSheet("""
                    font-size: 22px; 
                    font-weight: bold; 
                    color: white;
                    font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
                """)
                results_layout.addWidget(results_label)
                # Horizontal scroll area for results
                scroll = QScrollArea()
                scroll.setWidgetResizable(False)
                scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
                scroll.setFixedHeight(280)
                scroll.setStyleSheet("""
                    QScrollArea {
                        border: none;
                        background: transparent;
                    }
                """)
                container = QWidget()
                layout = QHBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(15)
                for item in data:
                    if content_type == "movie":
                        widget = self.create_home_movie_item_fast(item)
                    else:
                        widget = self.create_home_series_item_fast(item)
                    layout.addWidget(widget)
                layout.addStretch()
                scroll.setWidget(container)
                results_layout.addWidget(scroll)
            # If no results found
            if not data:
                no_results = QLabel(f"No {content_type} results found for '{query}'")
                no_results.setStyleSheet("""
                    font-size: 18px; 
                    color: #AAAAAA;
                    font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
                    padding: 40px;
                """)
                no_results.setAlignment(Qt.AlignCenter)
                results_layout.addWidget(no_results)
            results_layout.addStretch()
            self.home_content_layout.addWidget(results_container)
        except Exception as e:
            error_label = QLabel("Error performing search")
            error_label.setStyleSheet("""
                font-size: 18px; 
                color: #E50914;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
                padding: 40px;
            """)
            error_label.setAlignment(Qt.AlignCenter)
            self.home_content_layout.addWidget(error_label)
            logging.error(f"Search error: {str(e)}")

    def filter_home_content(self, filter_type):
        """Filter home content by type (movie, tv) - optimized for speed"""
        # Update button states - only one can be active at a time
        self.movies_filter_btn.setChecked(filter_type == "movie")
        self.series_filter_btn.setChecked(filter_type == "tv")
        self.current_content_filter = filter_type
        # If there's a search query, perform search with new filter
        if self.search_input.text().strip():
            self.perform_search()
        else:
            # Otherwise, reset home content loaded flag and reload asynchronously
            self.home_content_loaded = False
            self.show_home_loading()
            QTimer.singleShot(10, self.load_home_content_async)

    def show_home_loading(self):
        """Show loading state in home tab"""
        # Clear existing content
        for i in reversed(range(self.home_content_layout.count())):
            widget = self.home_content_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        
        # Create loading widget
        loading_widget = QWidget()
        loading_layout = QVBoxLayout(loading_widget)
        loading_layout.setContentsMargins(50, 50, 50, 50)
        loading_layout.setSpacing(20)
        
        # Loading animation placeholder
        loading_label = QLabel("🎬")
        loading_label.setStyleSheet("""
            font-size: 48px;
            color: #E50914;
        """)
        loading_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(loading_label)
        
        # Loading text
        text_label = QLabel("Loading Amazing Content...")
        text_label.setStyleSheet("""
            font-size: 20px; 
            font-weight: 700; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
            letter-spacing: -0.3px;
        """)
        text_label.setAlignment(Qt.AlignCenter)
        # Apply crisp font
        loading_font = self.create_crisp_font("Netflix Sans Bold", 20, bold=True)
        text_label.setFont(loading_font)
        loading_layout.addWidget(text_label)
        
        # Sub text
        sub_label = QLabel("Discovering the best movies and shows for you")
        sub_label.setStyleSheet("""
            font-size: 14px; 
            color: #AAAAAA;
            font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
            letter-spacing: 0.1px;
        """)
        sub_label.setAlignment(Qt.AlignCenter)
        # Apply crisp font
        sub_font = self.create_crisp_font("Netflix Sans Medium", 14)
        sub_label.setFont(sub_font)
        loading_layout.addWidget(sub_label)
        
        loading_layout.addStretch()
        self.home_content_layout.addWidget(loading_widget)
        
        # Animate the loading icon faster
        self.loading_timer = QTimer()
        self.loading_icons = ["🎬", "🍿", "📽️", "🎭"]
        self.loading_icon_index = 0
        self.loading_timer.timeout.connect(lambda: self.animate_loading_icon(loading_label))
        self.loading_timer.start(300)  # Change icon every 300ms (faster)

    def animate_loading_icon(self, label):
        """Animate the loading icon"""
        self.loading_icon_index = (self.loading_icon_index + 1) % len(self.loading_icons)
        label.setText(self.loading_icons[self.loading_icon_index])

    def load_home_content_async(self):
        """Load home content asynchronously"""
        if self.home_content_loaded:
            return
        
        # Stop loading animation
        if hasattr(self, 'loading_timer'):
            self.loading_timer.stop()
        
        # Check internet connection first
        if self.check_internet_connection():
            # Clear loading content
            for i in reversed(range(self.home_content_layout.count())):
                widget = self.home_content_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            
            # Load genre sections asynchronously
            self.create_genre_sections_async(self.home_content_layout)
        else:
            # Show no internet message
            for i in reversed(range(self.home_content_layout.count())):
                widget = self.home_content_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            self.create_no_internet_message(self.home_content_layout)
        
        self.home_content_loaded = True

    def check_internet_connection(self):
        """Check if internet connection is available - optimized for speed"""
        try:
            response = requests.get("https://api.themoviedb.org/3", timeout=2)  # Reduced from 3s to 2s
            return True
        except (requests.ConnectionError, requests.Timeout, Exception):
            return False

    def create_no_internet_message(self, layout):
        """Create a message for when there's no internet connection"""
        message_container = QWidget()
        message_layout = QVBoxLayout(message_container)
        message_layout.setContentsMargins(50, 100, 50, 100)
        message_layout.setSpacing(20)
        
        # Icon
        icon_label = QLabel("📡")
        icon_label.setStyleSheet("""
            font-size: 64px;
            color: #666;
        """)
        icon_label.setAlignment(Qt.AlignCenter)
        message_layout.addWidget(icon_label)
        
        # Main message
        no_wifi_label = QLabel("Not Connected to Internet")
        no_wifi_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        no_wifi_label.setAlignment(Qt.AlignCenter)
        message_layout.addWidget(no_wifi_label)
        
        # Sub message
        sub_message = QLabel("Please check your internet connection to discover new movies and shows.")
        sub_message.setStyleSheet("""
            font-size: 16px; 
            color: #AAAAAA;
            font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
        """)
        sub_message.setAlignment(Qt.AlignCenter)
        sub_message.setWordWrap(True)
        message_layout.addWidget(sub_message)
        
        # Retry button
        retry_button = QPushButton("Retry Connection")
        retry_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 16px;
                border-radius: 4px;
                font-weight: bold;
                max-width: 200px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        retry_button.clicked.connect(self.retry_home_connection)
        retry_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        message_layout.addWidget(retry_button, alignment=Qt.AlignCenter)
        
        message_layout.addStretch()
        layout.addWidget(message_container)

    def retry_home_connection(self):
        """Retry loading the home view"""
        # Clear current home view content
        for i in reversed(range(self.home_view.widget().layout().count())):
            item = self.home_view.widget().layout().itemAt(i)
            if item:
                widget = item.widget()
                if widget:
                    widget.setParent(None)
        
        # Recreate the home view
        new_home_view = self.create_home_view()
        self.stacked_widget.removeWidget(self.home_view)
        self.home_view = new_home_view
        self.stacked_widget.insertWidget(0, self.home_view)
        self.stacked_widget.setCurrentIndex(0)

    def filter_home_content(self, filter_type):
        """Filter home content by type (movie, tv) - optimized for speed"""
        # Update button states - only one can be active at a time
        self.movies_filter_btn.setChecked(filter_type == "movie")
        self.series_filter_btn.setChecked(filter_type == "tv")
        
        self.current_content_filter = filter_type
        
        # Reset home content loaded flag and reload asynchronously
        self.home_content_loaded = False
        
        # Show loading state and reload content immediately - faster switching
        self.show_home_loading()
        QTimer.singleShot(10, self.load_home_content_async)  # Reduced from 30ms to 10ms for faster response

    def reload_home_content(self):
        """Reload home content with fresh data and rotate content over time"""
        # Update reload button to show loading state
        self.reload_home_btn.setText("⟲")  # Loading refresh symbol
        self.reload_home_btn.setEnabled(False)
        self.reload_home_btn.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: #AAAAAA;
                border: none;
                padding: 0px;
                font-size: 18px;
                font-weight: bold;
                border-radius: 22px;
                font-family: Arial, sans-serif;
            }
        """)
        
        # Reset content loaded flags to force fresh loading
        self.home_content_loaded = False
        
        # Increment page numbers for different content rotation
        if not hasattr(self, 'content_rotation_page'):
            self.content_rotation_page = 1
        self.content_rotation_page = (self.content_rotation_page % 3) + 1  # Rotate between pages 1-3
        
        # Show loading state
        self.show_home_loading()
        
        # Load fresh content with a slight delay
        QTimer.singleShot(500, self.load_fresh_home_content)

    def load_fresh_home_content(self):
        """Load fresh home content with rotation"""
        # Load content with current rotation page
        self.load_home_content_async()
        
        # Reset reload button after loading
        QTimer.singleShot(2000, self.reset_reload_button)

    def reset_reload_button(self):
        """Reset the reload button to its normal state"""
        self.reload_home_btn.setText("⟳")  # Standard refresh symbol
        self.reload_home_btn.setEnabled(True)
        self.reload_home_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: #FFFFFF;
                border: none;
                padding: 0px;
                font-size: 18px;
                font-weight: bold;
                border-radius: 22px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
            QPushButton:hover {
                background-color: #E50914;
                color: white;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)

    def auto_refresh_home_content(self):
        """Automatically refresh home content every 10 minutes for variety"""
        # Only auto-refresh if we're currently on the home tab
        if (hasattr(self, 'stacked_widget') and 
            self.stacked_widget.currentIndex() == 0 and 
            hasattr(self, 'home_content_loaded') and 
            self.home_content_loaded):
            
            print("Auto-refreshing home content for variety...")
            
            # Rotate to next page of content
            self.content_rotation_page = (self.content_rotation_page % 3) + 1
            
            # Reset and reload content silently (without loading animation)
            self.home_content_loaded = False
            
            # Clear current content
            for i in reversed(range(self.home_content_layout.count())):
                widget = self.home_content_layout.itemAt(i).widget()
                if widget:
                    widget.setParent(None)
            
            # Load fresh content
            self.load_home_content_async()

    def create_genre_sections(self, parent_layout):
        """Create horizontal scrollable sections for each genre"""
        # Get current filter (default to "movie" if not set)
        current_filter = getattr(self, 'current_content_filter', 'movie')
        
        # Movie genres
        movie_genres = [
            ("Popular Movies", 28),  # Action
            ("Action Movies", 28),
            ("Comedy Movies", 35),
            ("Drama Movies", 18),
            ("Horror Movies", 27),
            ("Sci-Fi Movies", 878),
            ("Romance Movies", 10749),
            ("Thriller Movies", 53),
            ("Animation Movies", 16),
            ("Adventure Movies", 12),
            ("Crime Movies", 80),
            ("Fantasy Movies", 14),
            ("Mystery Movies", 9648),
            ("War Movies", 10752),
            ("Western Movies", 37)
        ]
        
        # TV Series genres
        tv_genres = [
            ("Popular TV Shows", 28),  # Action & Adventure
            ("Action TV Shows", 10759),
            ("Comedy TV Shows", 35),
            ("Drama TV Shows", 18),
            ("Sci-Fi TV Shows", 10765),
            ("Crime TV Shows", 80),
            ("Reality TV Shows", 10764),
            ("Documentary TV Shows", 99),
            ("Animation TV Shows", 16),
            ("Mystery TV Shows", 9648),
            ("Family TV Shows", 10751),
            ("Talk TV Shows", 10767),
            ("News TV Shows", 10763),
            ("Kids TV Shows", 10762)
        ]
        
        # Add sections based on filter
        if current_filter == "movie":
            for genre_name, genre_id in movie_genres:
                genre_widget = self.create_genre_row(genre_name, genre_id, content_type="movie")
                parent_layout.addWidget(genre_widget)
        elif current_filter == "tv":
            for genre_name, genre_id in tv_genres:
                genre_widget = self.create_genre_row(genre_name, genre_id, content_type="tv")
                parent_layout.addWidget(genre_widget)
        
        parent_layout.addStretch()

    def create_genre_sections_async(self, parent_layout):
        """Create horizontal scrollable sections for each genre asynchronously"""
        # Get current filter (default to "movie" if not set)
        current_filter = getattr(self, 'current_content_filter', 'movie')
        
        # Netflix-style genre names with engaging descriptions
        movie_genres = [
            ("🔥 Trending Now", "trending"),  # Use "trending" instead of genre ID
            ("💥 Explosive Action", 28),
            ("😂 Laugh Out Loud", 35),
            ("🎭 Award-Winning Dramas", 18),
            ("👻 Horror & Thrills", 27),
            ("🚀 Sci-Fi Adventures", 878),
            ("💕 Romance & Love Stories", 10749),
            ("🔪 Edge-of-Your-Seat Thrillers", 53),
            ("🎨 Animated Masterpieces", 16),
            ("🗺️ Epic Adventures", 12),
            ("🔫 Crime & Heists", 80),
            ("🐉 Fantasy Worlds", 14),
            ("🕵️ Mystery & Detective", 9648),
            ("⚔️ War & Combat", 10752),
            ("🤠 Wild West", 37),
            ("📚 True Stories", 99),
            ("👨‍👩‍👧‍👦 Family Fun", 10751),
            ("🎵 Music & Musicals", 10402),
            ("🏛️ Historical Epics", 36)
        ]
        
        # TV Series genres - All standard TMDB TV genres
        tv_genres = [
            ("🔥 Trending Series", "trending"),  # Use "trending" instead of genre ID
            ("💖 Romance & Love Stories", 10749),  # Romance (using movie genre ID as TV doesn't have dedicated romance)
            ("😱 Horror & Supernatural", 27),  # Horror (using movie genre ID)
            ("🎵 Music & Musicals", 10402),  # Music (using movie genre ID)
            ("⚡ Action & Adventure", 10759),  # Action & Adventure
            ("🎭 Animation", 16),  # Animation
            ("😄 Comedy", 35),  # Comedy
            ("🚔 Crime", 80),  # Crime
            ("📚 Documentary", 99),  # Documentary
            ("🎬 Drama", 18),  # Drama
            ("👨‍👩‍👧‍👦 Family", 10751),  # Family
            ("👶 Kids", 10762),  # Kids
            ("🔍 Mystery", 9648),  # Mystery
            ("📺 Reality", 10764),  # Reality
            ("🌌 Sci-Fi & Fantasy", 10765),  # Sci-Fi & Fantasy
            ("🧼 Soap", 10766),  # Soap
            ("💬 Talk", 10767),  # Talk
            ("⚔️ War & Politics", 10768),  # War & Politics
            ("🤠 Western", 37),  # Western
            ("🎪 Variety Show", 10767),  # Using Talk genre for variety shows
            ("🏥 Medical Drama", 18),  # Using Drama genre for medical shows
            ("🎓 Educational", 99),  # Using Documentary for educational content
            ("🎮 Game Show", 10764),  # Using Reality for game shows
            ("🌍 Travel", 99),  # Using Documentary for travel shows
            ("🍳 Cooking", 10764),  # Using Reality for cooking shows
            ("🏠 Home & Garden", 10764),  # Using Reality for home improvement
            ("🧠 Psychological Thriller", 9648)  # Using Mystery for psychological content
        ]
        
        # Load more genres initially to show variety, then load remaining - optimized for speed
        if current_filter == "movie":
            self.load_priority_genres(parent_layout, movie_genres[:4], "movie")  # Reduced from 6 to 4 for faster initial load
            # Load remaining genres after a delay
            QTimer.singleShot(500, lambda: self.load_remaining_genres(parent_layout, movie_genres[4:], "movie"))
        elif current_filter == "tv":
            # Prioritize Romance, Horror, and Music by loading them first (positions 1, 2, 3)
            self.load_priority_genres(parent_layout, tv_genres[:7], "tv")  # Increased from 5 to 7 to include more priority genres
            # Load remaining genres after a delay
            QTimer.singleShot(500, lambda: self.load_remaining_genres(parent_layout, tv_genres[7:], "tv"))

    def load_priority_genres(self, parent_layout, genres, content_type):
        """Load priority genres immediately for faster initial display - optimized"""
        # Load different counts based on content type - more for TV to include Romance, Horror, Music
        priority_count = 4 if content_type == "movie" else 7  # Increased TV from 5 to 7 to match the slice in create_genre_sections_async
        for i, (genre_name, genre_id) in enumerate(genres[:priority_count]):
            # Create genre widget immediately
            genre_widget = self.create_fast_genre_row(genre_name, genre_id, content_type=content_type)
            parent_layout.addWidget(genre_widget)
            
            # Process events more frequently for responsiveness
            if i % 2 == 0:  # Process events every 2 genres instead of every genre
                QApplication.processEvents()
        
        # Load remaining genres with delay
        if len(genres) > priority_count:
            QTimer.singleShot(300, lambda: self.load_additional_priority_genres(parent_layout, genres[priority_count:], content_type))  # Reduced delay from 500ms to 300ms

    def load_additional_priority_genres(self, parent_layout, genres, content_type):
        """Load additional priority genres after initial load - optimized for speed"""
        # Load remaining genres with faster intervals
        for i, (genre_name, genre_id) in enumerate(genres):
            # Use timer to spread out loading with faster intervals
            QTimer.singleShot(i * 100, lambda gn=genre_name, gi=genre_id: self.add_genre_widget(parent_layout, gn, gi, content_type))  # Reduced from 200ms to 100ms

    def add_genre_widget(self, parent_layout, genre_name, genre_id, content_type):
        """Add a single genre widget"""
        genre_widget = self.create_fast_genre_row(genre_name, genre_id, content_type=content_type)
        parent_layout.addWidget(genre_widget)
        QApplication.processEvents()

    def load_remaining_genres(self, parent_layout, genres, content_type):
        """Load remaining genres after initial load"""
        # Remove "Load More" button if it exists
        if hasattr(self, 'load_more_button'):
            parent_layout.removeWidget(self.load_more_button)
            self.load_more_button.setParent(None)
        
        # Load remaining genres
        for genre_name, genre_id in genres:
            genre_widget = self.create_fast_genre_row(genre_name, genre_id, content_type=content_type)
            parent_layout.addWidget(genre_widget)
        
        parent_layout.addStretch()

    def create_fast_genre_row(self, genre_name, genre_id, content_type="movie"):
        """Create a genre row with faster loading - fewer items"""
        genre_container = QWidget()
        genre_layout = QVBoxLayout(genre_container)
        genre_layout.setContentsMargins(0, 0, 0, 0)
        genre_layout.setSpacing(10)
        
        # Genre title
        genre_title = QLabel(genre_name)
        genre_title.setStyleSheet("""
            font-size: 20px; 
            font-weight: 700; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Segoe UI', 'Arial', sans-serif;
            margin-bottom: 5px;
            letter-spacing: -0.2px;
        """)
        # Apply crisp font to genre title
        genre_font = self.create_crisp_font("Netflix Sans Bold", 20, bold=True)
        genre_title.setFont(genre_font)
        genre_layout.addWidget(genre_title)
        
        # Horizontal scroll area for movie/series posters
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(False)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFixedHeight(280)  # Increased from 240 to accommodate titles
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        
        # Container for movie/series posters
        content_container = QWidget()
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)
        
        # Load content for this genre based on type - with faster loading
        if content_type == "tv":
            self.load_genre_series_fast(content_layout, genre_id)
        else:
            self.load_genre_movies_fast(content_layout, genre_id)
        
        content_layout.addStretch()
        scroll_area.setWidget(content_container)
        genre_layout.addWidget(scroll_area)
        
        return genre_container
    
    def get_similar_content(self, content_id, content_type="movie", limit=10):
        """Get enhanced similar movies or TV series using multiple recommendation strategies"""
        try:
            # First, get basic details about the current content
            content_details = self.get_content_details(content_id, content_type)
            if not content_details:
                return []
            
            # Strategy 1: TMDB Similar API (primary source)
            similar_from_api = self.get_tmdb_similar_content(content_id, content_type, limit=15)
            
            # Strategy 2: Genre-based recommendations
            genre_based = self.get_genre_based_recommendations(content_details, content_type, limit=15)
            
            # Strategy 3: Cast/Director-based recommendations  
            cast_based = self.get_cast_based_recommendations(content_details, content_type, limit=10)
            
            # Strategy 4: Get trending content in same genres as backup
            trending_backup = self.get_trending_in_genres(content_details.get('genre_ids', []), content_type, limit=10)
            
            # Combine and rank all recommendations
            all_recommendations = []
            
            # Add TMDB similar content with high priority
            for item in similar_from_api:
                if item.get('id') != content_id:  # Don't recommend the same content
                    score = self.calculate_recommendation_score(item, content_details, 'tmdb_similar')
                    all_recommendations.append((item, score, 'tmdb_similar'))
            
            # Add genre-based recommendations with medium priority
            for item in genre_based:
                if item.get('id') != content_id and not self.is_duplicate_recommendation(item, all_recommendations):
                    score = self.calculate_recommendation_score(item, content_details, 'genre_based')
                    all_recommendations.append((item, score, 'genre_based'))
            
            # Add cast-based recommendations with medium priority
            for item in cast_based:
                if item.get('id') != content_id and not self.is_duplicate_recommendation(item, all_recommendations):
                    score = self.calculate_recommendation_score(item, content_details, 'cast_based')
                    all_recommendations.append((item, score, 'cast_based'))
            
            # Add trending backup with lower priority
            for item in trending_backup:
                if item.get('id') != content_id and not self.is_duplicate_recommendation(item, all_recommendations):
                    score = self.calculate_recommendation_score(item, content_details, 'trending')
                    all_recommendations.append((item, score, 'trending'))
            
            # Sort by score (highest first) and return top recommendations
            all_recommendations.sort(key=lambda x: x[1], reverse=True)
            
            # Ensure diversity in recommendations (avoid too many from same genre/year)
            diverse_recommendations = self.ensure_recommendation_diversity(all_recommendations, limit)
            
            # Return just the content items
            return [rec[0] for rec in diverse_recommendations]
                
        except Exception as e:
            logging.error(f"Error getting enhanced similar content: {str(e)}")
            # Fallback to basic TMDB similar if enhanced method fails
            return self.get_tmdb_similar_content(content_id, content_type, limit)

    def get_content_details(self, content_id, content_type="movie"):
        """Get detailed information about content for better recommendations"""
        try:
            if content_type == "movie":
                url = f"https://api.themoviedb.org/3/movie/{content_id}"
            else:
                url = f"https://api.themoviedb.org/3/tv/{content_id}"
            
            response = requests.get(url, params={
                "api_key": TMDB_API_KEY,
                "append_to_response": "credits,keywords"
            }, timeout=5)
            
            if response.status_code == 200:
                return response.json()
            return None
                
        except Exception as e:
            logging.error(f"Error getting content details: {str(e)}")
            return None

    def get_tmdb_similar_content(self, content_id, content_type="movie", limit=10):
        """Get similar content from TMDB API (original method)"""
        try:
            if content_type == "movie":
                url = f"https://api.themoviedb.org/3/movie/{content_id}/similar"
            else:
                url = f"https://api.themoviedb.org/3/tv/{content_id}/similar"
            
            response = requests.get(url, params={
                "api_key": TMDB_API_KEY,
                "page": 1
            }, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])[:limit]
                return results
            return []
                
        except Exception as e:
            logging.error(f"Error getting TMDB similar content: {str(e)}")
            return []

    def get_genre_based_recommendations(self, content_details, content_type="movie", limit=15):
        """Get recommendations based on matching genres"""
        try:
            genre_ids = content_details.get('genre_ids', content_details.get('genres', []))
            if isinstance(genre_ids, list) and len(genre_ids) > 0:
                # If genres is a list of objects, extract IDs
                if isinstance(genre_ids[0], dict):
                    genre_ids = [g['id'] for g in genre_ids]
                
                # Get content from same genres, sorted by popularity
                if content_type == "movie":
                    url = "https://api.themoviedb.org/3/discover/movie"
                else:
                    url = "https://api.themoviedb.org/3/discover/tv"
                
                response = requests.get(url, params={
                    "api_key": TMDB_API_KEY,
                    "with_genres": ",".join(map(str, genre_ids[:3])),  # Use top 3 genres
                    "sort_by": "vote_average.desc",
                    "vote_count.gte": 100,  # Ensure quality content
                    "page": 1
                }, timeout=5)
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("results", [])[:limit]
            return []
                
        except Exception as e:
            logging.error(f"Error getting genre-based recommendations: {str(e)}")
            return []

    def get_cast_based_recommendations(self, content_details, content_type="movie", limit=10):
        """Get recommendations based on cast and crew"""
        try:
            recommendations = []
            credits = content_details.get('credits', {})
            
            # Get recommendations based on main actors (top 3)
            cast = credits.get('cast', [])[:3]
            for actor in cast:
                actor_id = actor.get('id')
                if actor_id:
                    actor_content = self.get_content_by_person(actor_id, content_type, limit=5)
                    recommendations.extend(actor_content)
            
            # Get recommendations based on director/creator
            crew = credits.get('crew', [])
            directors = [c for c in crew if c.get('job') in ['Director', 'Creator']][:2]
            for director in directors:
                director_id = director.get('id')
                if director_id:
                    director_content = self.get_content_by_person(director_id, content_type, limit=5)
                    recommendations.extend(director_content)
            
            return recommendations[:limit]
                
        except Exception as e:
            logging.error(f"Error getting cast-based recommendations: {str(e)}")
            return []

    def get_content_by_person(self, person_id, content_type="movie", limit=5):
        """Get content featuring a specific person"""
        try:
            if content_type == "movie":
                url = f"https://api.themoviedb.org/3/person/{person_id}/movie_credits"
            else:
                url = f"https://api.themoviedb.org/3/person/{person_id}/tv_credits"
            
            response = requests.get(url, params={
                "api_key": TMDB_API_KEY
            }, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                if content_type == "movie":
                    results = data.get("cast", []) + data.get("crew", [])
                else:
                    results = data.get("cast", []) + data.get("crew", [])
                
                # Sort by popularity and rating
                results.sort(key=lambda x: (x.get('popularity', 0), x.get('vote_average', 0)), reverse=True)
                return results[:limit]
            return []
                
        except Exception as e:
            logging.error(f"Error getting content by person: {str(e)}")
            return []

    def get_trending_in_genres(self, genre_ids, content_type="movie", limit=10):
        """Get trending content in specific genres as backup"""
        try:
            if not genre_ids:
                return []
                
            if content_type == "movie":
                url = "https://api.themoviedb.org/3/trending/movie/week"
            else:
                url = "https://api.themoviedb.org/3/trending/tv/week"
            
            response = requests.get(url, params={
                "api_key": TMDB_API_KEY
            }, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                
                # Filter by matching genres
                filtered_results = []
                for item in results:
                    item_genres = item.get('genre_ids', [])
                    if any(genre in genre_ids for genre in item_genres):
                        filtered_results.append(item)
                
                return filtered_results[:limit]
            return []
                
        except Exception as e:
            logging.error(f"Error getting trending in genres: {str(e)}")
            return []

    def calculate_recommendation_score(self, item, original_content, source_type):
        """Calculate a score for how good a recommendation is"""
        score = 0
        
        # Base score by source type
        source_weights = {
            'tmdb_similar': 100,      # Highest weight for TMDB similar
            'genre_based': 80,        # High weight for genre matches
            'cast_based': 70,         # Good weight for cast matches  
            'trending': 50            # Lower weight for trending
        }
        score += source_weights.get(source_type, 50)
        
        # Bonus for higher ratings
        vote_average = item.get('vote_average', 0)
        score += vote_average * 10  # 0-100 bonus based on rating
        
        # Bonus for more votes (indicates popularity)
        vote_count = item.get('vote_count', 0)
        if vote_count > 1000:
            score += 20
        elif vote_count > 500:
            score += 10
        elif vote_count > 100:
            score += 5
        
        # Bonus for genre overlap
        original_genres = set(original_content.get('genre_ids', []))
        item_genres = set(item.get('genre_ids', []))
        genre_overlap = len(original_genres.intersection(item_genres))
        score += genre_overlap * 15  # 15 points per matching genre
        
        # Slight penalty for very old content (unless it's a classic)
        current_year = 2025
        if 'release_date' in item:
            release_year = int(item['release_date'][:4]) if item['release_date'] else current_year
        elif 'first_air_date' in item:
            release_year = int(item['first_air_date'][:4]) if item['first_air_date'] else current_year
        else:
            release_year = current_year
        
        age = current_year - release_year
        if age > 20 and vote_average < 7.5:  # Penalize old content unless it's highly rated
            score -= age * 0.5
        
        return score

    def is_duplicate_recommendation(self, item, existing_recommendations):
        """Check if this item is already in recommendations"""
        item_id = item.get('id')
        for existing_item, _, _ in existing_recommendations:
            if existing_item.get('id') == item_id:
                return True
        return False

    def ensure_recommendation_diversity(self, recommendations, limit):
        """Ensure diversity in recommendations to avoid repetitive suggestions"""
        if not recommendations:
            return []
        
        diverse_recs = []
        genre_counts = {}
        year_counts = {}
        
        for item, score, source in recommendations:
            if len(diverse_recs) >= limit:
                break
                
            # Get item genres and year
            item_genres = item.get('genre_ids', [])
            if 'release_date' in item and item['release_date']:
                item_year = item['release_date'][:4]
            elif 'first_air_date' in item and item['first_air_date']:
                item_year = item['first_air_date'][:4]
            else:
                item_year = "unknown"
            
            # Check if we have too many from same genre or year
            dominant_genre = item_genres[0] if item_genres else None
            
            genre_limit = max(1, limit // 3)  # At most 1/3 from same genre
            year_limit = max(1, limit // 4)   # At most 1/4 from same year
            
            genre_ok = not dominant_genre or genre_counts.get(dominant_genre, 0) < genre_limit
            year_ok = year_counts.get(item_year, 0) < year_limit
            
            if genre_ok and year_ok:
                diverse_recs.append((item, score, source))
                
                # Update counts
                if dominant_genre:
                    genre_counts[dominant_genre] = genre_counts.get(dominant_genre, 0) + 1
                year_counts[item_year] = year_counts.get(item_year, 0) + 1
        
        # If we don't have enough diverse recommendations, fill with remaining high-scored ones
        if len(diverse_recs) < limit:
            for item, score, source in recommendations:
                if len(diverse_recs) >= limit:
                    break
                if not self.is_in_diverse_recs(item, diverse_recs):
                    diverse_recs.append((item, score, source))
        
        return diverse_recs

    def is_in_diverse_recs(self, item, diverse_recs):
        """Check if item is already in diverse recommendations"""
        item_id = item.get('id')
        for existing_item, _, _ in diverse_recs:
            if existing_item.get('id') == item_id:
                return True
        return False
    
    def get_cast_info(self, content_id, content_type="movie", limit=8):
        """Get cast information for movies or TV series using TMDB API"""
        try:
            if content_type == "movie":
                url = f"https://api.themoviedb.org/3/movie/{content_id}/credits"
            else:
                url = f"https://api.themoviedb.org/3/tv/{content_id}/credits"
            
            response = requests.get(url, params={
                "api_key": TMDB_API_KEY
            }, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                cast = data.get("cast", [])
                # Return top cast members with profile photos
                return [actor for actor in cast[:limit] if actor.get("profile_path")]
            else:
                logging.warning(f"TMDB API returned status {response.status_code} for cast")
                return []
                
        except (requests.ConnectionError, requests.Timeout):
            logging.warning("No internet connection for cast info")
            return []
        except Exception as e:
            logging.error(f"Error getting cast info: {str(e)}")
            return []
    
    def get_actor_movies(self, actor_id, limit=12):
        """Get movies that an actor has appeared in"""
        try:
            url = f"https://api.themoviedb.org/3/person/{actor_id}/movie_credits"
            
            response = requests.get(url, params={
                "api_key": TMDB_API_KEY
            }, timeout=5)
            
            if response.status_code == 200:
                data = response.json()
                cast_movies = data.get("cast", [])
                # Sort by popularity and release date, filter out movies without posters
                movies = [movie for movie in cast_movies if movie.get("poster_path")]
                movies = sorted(movies, key=lambda x: (x.get("popularity", 0), x.get("release_date", "")), reverse=True)
                return movies[:limit]
            else:
                logging.warning(f"TMDB API returned status {response.status_code} for actor movies")
                return []
                
        except (requests.ConnectionError, requests.Timeout):
            logging.warning("No internet connection for actor movies")
            return []
        except Exception as e:
            logging.error(f"Error getting actor movies: {str(e)}")
            return []
    
    def create_cast_section(self, content_id, content_type="movie"):
        """Create a horizontal scrollable cast section with circular actor photos"""
        cast_info = self.get_cast_info(content_id, content_type, limit=8)
        
        if not cast_info:
            return None
        
        # Container for the cast section
        cast_container = QWidget()
        cast_layout = QVBoxLayout(cast_container)
        cast_layout.setContentsMargins(0, 15, 0, 15)
        cast_layout.setSpacing(15)
        
        # Cast section title
        cast_title = QLabel("Cast")
        cast_title.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        cast_layout.addWidget(cast_title)
        
        # Horizontal scroll area for cast
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(False)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFixedHeight(140)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        
        # Container for cast members
        cast_members_container = QWidget()
        cast_members_layout = QHBoxLayout(cast_members_container)
        cast_members_layout.setContentsMargins(0, 0, 0, 0)
        cast_members_layout.setSpacing(15)
        
        # Create cast member widgets
        for actor in cast_info:
            actor_widget = self.create_actor_widget(actor)
            cast_members_layout.addWidget(actor_widget)
        
        cast_members_layout.addStretch()
        scroll_area.setWidget(cast_members_container)
        cast_layout.addWidget(scroll_area)
        
        return cast_container
    
    def create_actor_widget(self, actor_data):
        """Create a clickable circular actor widget"""
        actor_widget = QWidget()
        actor_widget.setFixedSize(90, 120)
        actor_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(actor_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Circular profile photo
        profile_label = QLabel()
        profile_label.setFixedSize(90, 90)
        profile_label.setScaledContents(True)
        profile_label.setAlignment(Qt.AlignCenter)
        profile_label.setStyleSheet("""
            QLabel {
                background-color: #333;
                border-radius: 45px;
                border: 2px solid #555;
            }
            QLabel:hover {
                border: 2px solid #E50914;
            }
        """)
        
        # Show placeholder immediately
        profile_label.setText("👤")
        profile_label.setStyleSheet("""
            color: #666; 
            font-size: 30px; 
            background-color: #333;
            border-radius: 45px;
            border: 2px solid #555;
        """)
        
        layout.addWidget(profile_label)
        
        # Actor name
        name_text = actor_data.get("name", "Unknown Actor")
        name_label = QLabel(name_text)
        name_label.setStyleSheet("""
            color: white;
            font-size: 10px;
            font-weight: 500;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            background-color: transparent;
        """)
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setWordWrap(True)
        name_label.setMaximumHeight(22)
        layout.addWidget(name_label)
        
        # Store actor data and add click handler
        actor_widget.actor_data = actor_data
        actor_widget.mousePressEvent = lambda event: self.show_actor_movies(actor_data)
        
        # Load profile image asynchronously
        profile_path = actor_data.get("profile_path")
        if profile_path:
            QTimer.singleShot(50, lambda: self.load_actor_profile_async(profile_label, profile_path))
        
        return actor_widget
    
    def load_actor_profile_async(self, label, profile_path):
        """Load actor profile image asynchronously and make it circular"""
        try:
            # Use higher resolution image for better quality
            profile_url = f"https://image.tmdb.org/t/p/w500{profile_path}"
            response = requests.get(profile_url, timeout=5)
            response.raise_for_status()
            
            # Load image
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            
            if not pixmap.isNull():
                # Scale to fit while maintaining aspect ratio, then crop center
                target_size = 90
                
                # Use higher resolution for smoother scaling
                temp_size = target_size * 2  # 2x resolution for better quality
                
                # Scale to fill the target size (larger dimension will be cropped)
                scale_factor = temp_size / min(pixmap.width(), pixmap.height())
                scaled_pixmap = pixmap.scaled(
                    int(pixmap.width() * scale_factor), 
                    int(pixmap.height() * scale_factor), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                
                # Create square crop from center
                x_offset = (scaled_pixmap.width() - temp_size) // 2
                y_offset = (scaled_pixmap.height() - temp_size) // 2
                square_pixmap = scaled_pixmap.copy(x_offset, y_offset, temp_size, temp_size)
                
                # Create circular pixmap at high resolution
                circular_pixmap = QPixmap(temp_size, temp_size)
                circular_pixmap.fill(Qt.transparent)
                
                painter = QPainter(circular_pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                
                # Create circular path
                path = QPainterPath()
                path.addEllipse(0, 0, temp_size, temp_size)
                painter.setClipPath(path)
                
                # Draw the square cropped image
                painter.drawPixmap(0, 0, square_pixmap)
                painter.end()
                
                # Scale down to final size for crisp display
                final_pixmap = circular_pixmap.scaled(target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                
                # Set the circular image
                if label and not label.isHidden():
                    label.setPixmap(final_pixmap)
                    label.setStyleSheet("""
                        QLabel {
                            background-color: transparent;
                            border-radius: 45px;
                            border: 2px solid #555;
                        }
                        QLabel:hover {
                            border: 2px solid #E50914;
                        }
                    """)
            else:
                self.on_actor_profile_failed(label)
                
        except (requests.ConnectionError, requests.Timeout):
            self.on_actor_profile_offline(label)
        except Exception as e:
            logging.error(f"Error loading actor profile: {str(e)}")
            self.on_actor_profile_failed(label)
    
    def on_actor_profile_failed(self, label):
        """Handle failed actor profile loading"""
        try:
            if label and not label.isHidden():
                label.setText("👤")
                label.setStyleSheet("""
                    color: #666; 
                    font-size: 30px; 
                    background-color: #333;
                    border-radius: 45px;
                    border: 2px solid #555;
                """)
        except Exception as e:
            pass
    
    def on_actor_profile_offline(self, label):
        """Handle offline actor profile loading"""
        try:
            if label and not label.isHidden():
                label.setText("📡")
                label.setStyleSheet("""
                    color: #666; 
                    font-size: 24px; 
                    background-color: #333;
                    border-radius: 45px;
                    border: 2px solid #444;
                """)
        except Exception as e:
            self.on_actor_profile_failed(label)
    
    def show_home_tab(self):
        """Navigate to home tab and clear navigation stack"""
        self.stacked_widget.setCurrentIndex(0)
        self.previous_view_stack.clear()
    
    def show_movies_tab(self):
        """Navigate to movies tab and clear navigation stack"""
        self.stacked_widget.setCurrentIndex(1)
        self.previous_view_stack.clear()
    
    def show_series_tab(self):
        """Navigate to series tab and clear navigation stack"""
        self.show_series_window()
        self.previous_view_stack.clear()
    
    def navigate_back(self):
        """Navigate back to the previous view in the stack"""
        if len(self.previous_view_stack) > 1:
            # Remove current view from stack
            self.previous_view_stack.pop()
            
            # Get previous view
            view_type, view_data = self.previous_view_stack[-1]
            
            # Navigate to the appropriate view
            if view_type == "movie_details":
                self.show_home_movie_details(view_data)
            elif view_type == "series_details":
                self.show_home_series_details(view_data)
            else:
                # Fallback to home if we can't determine the previous view
                self.stacked_widget.setCurrentIndex(0)
                self.previous_view_stack.clear()
        else:
            # No previous view, go to home
            self.stacked_widget.setCurrentIndex(0)
            self.previous_view_stack.clear()
    
    def show_actor_movies(self, actor_data):
        """Show movies that the selected actor has appeared in"""
        actor_name = actor_data.get("name", "Unknown Actor")
        actor_id = actor_data.get("id")
        
        if not actor_id:
            return
        
        # Add actor view to navigation stack
        self.previous_view_stack.append(("actor_movies", actor_data))
        
        # Clear previous content
        for i in reversed(range(self.home_details_layout.count())):
            widget = self.home_details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Create scroll area for the entire content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        # Container widget for all content
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 15, 20, 20)
        container_layout.setSpacing(20)

        # Back button - now navigates to the previous view properly
        back_button = QPushButton("← Back")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        back_button.clicked.connect(self.navigate_back)
        container_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Actor info section
        actor_info_widget = QWidget()
        actor_info_layout = QHBoxLayout(actor_info_widget)
        actor_info_layout.setContentsMargins(0, 0, 0, 0)
        actor_info_layout.setSpacing(20)
        
        # Actor profile photo (larger)
        profile_label = QLabel()
        profile_label.setFixedSize(120, 120)
        profile_label.setScaledContents(True)
        profile_label.setAlignment(Qt.AlignCenter)
        profile_label.setStyleSheet("""
            QLabel {
                background-color: #333;
                border-radius: 60px;
                border: 3px solid #555;
            }
        """)
        profile_label.setText("👤")
        profile_label.setStyleSheet("""
            color: #666; 
            font-size: 40px; 
            background-color: #333;
            border-radius: 60px;
            border: 3px solid #555;
        """)
        actor_info_layout.addWidget(profile_label)
        
        # Load actor profile
        profile_path = actor_data.get("profile_path")
        if profile_path:
            QTimer.singleShot(50, lambda: self.load_large_actor_profile_async(profile_label, profile_path))
        
        # Actor details
        actor_details_widget = QWidget()
        actor_details_layout = QVBoxLayout(actor_details_widget)
        actor_details_layout.setContentsMargins(0, 0, 0, 0)
        actor_details_layout.setSpacing(10)
        
        # Actor name
        name_label = QLabel(actor_name)
        name_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        actor_details_layout.addWidget(name_label)
        
        # Known for
        if actor_data.get("known_for_department"):
            known_for_label = QLabel(f"Known for: {actor_data['known_for_department']}")
            known_for_label.setStyleSheet("""
                font-size: 16px; 
                color: #AAAAAA;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            """)
            actor_details_layout.addWidget(known_for_label)
        
        actor_details_layout.addStretch()
        actor_info_layout.addWidget(actor_details_widget)
        actor_info_layout.addStretch()
        
        container_layout.addWidget(actor_info_widget)
        
        # Movies section
        movies_label = QLabel(f"Movies featuring {actor_name}")
        movies_label.setStyleSheet("""
            font-size: 22px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-top: 20px;
            margin-bottom: 15px;
        """)
        container_layout.addWidget(movies_label)
        
        # Get and display actor's movies
        actor_movies = self.get_actor_movies(actor_id, limit=15)
        
        if actor_movies:
            # Create horizontal scroll area for movies
            movies_scroll_area = QScrollArea()
            movies_scroll_area.setWidgetResizable(False)
            movies_scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            movies_scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            movies_scroll_area.setFixedHeight(280)
            movies_scroll_area.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background: transparent;
                }
            """)
            
            # Container for movies
            movies_container = QWidget()
            movies_layout = QHBoxLayout(movies_container)
            movies_layout.setContentsMargins(0, 0, 0, 0)
            movies_layout.setSpacing(15)
            
            # Create movie widgets
            for movie in actor_movies:
                movie_widget = self.create_actor_movie_item(movie)
                movies_layout.addWidget(movie_widget)
            
            movies_layout.addStretch()
            movies_scroll_area.setWidget(movies_container)
            container_layout.addWidget(movies_scroll_area)
        else:
            no_movies_label = QLabel("No movies found for this actor")
            no_movies_label.setStyleSheet("""
                color: #666; 
                font-size: 16px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
                padding: 20px;
            """)
            no_movies_label.setAlignment(Qt.AlignCenter)
            container_layout.addWidget(no_movies_label)
        
        container_layout.addStretch()
        
        # Set up scroll area and add to main layout
        scroll_area.setWidget(container)
        self.home_details_layout.addWidget(scroll_area)
        self.stacked_widget.setCurrentIndex(5)
    
    def load_large_actor_profile_async(self, label, profile_path):
        """Load larger actor profile image asynchronously and make it circular"""
        try:
            # Use higher resolution image for better quality
            profile_url = f"https://image.tmdb.org/t/p/w500{profile_path}"
            response = requests.get(profile_url, timeout=5)
            response.raise_for_status()
            
            # Load image
            pixmap = QPixmap()
            pixmap.loadFromData(response.content)
            
            if not pixmap.isNull():
                # Scale to fit while maintaining aspect ratio, then crop center
                target_size = 120
                
                # Use higher resolution for smoother scaling
                temp_size = target_size * 2  # 2x resolution for better quality
                
                # Scale to fill the target size (larger dimension will be cropped)
                scale_factor = temp_size / min(pixmap.width(), pixmap.height())
                scaled_pixmap = pixmap.scaled(
                    int(pixmap.width() * scale_factor), 
                    int(pixmap.height() * scale_factor), 
                    Qt.KeepAspectRatio, 
                    Qt.SmoothTransformation
                )
                
                # Create square crop from center
                x_offset = (scaled_pixmap.width() - temp_size) // 2
                y_offset = (scaled_pixmap.height() - temp_size) // 2
                square_pixmap = scaled_pixmap.copy(x_offset, y_offset, temp_size, temp_size)
                
                # Create circular pixmap at high resolution
                circular_pixmap = QPixmap(temp_size, temp_size)
                circular_pixmap.fill(Qt.transparent)
                
                painter = QPainter(circular_pixmap)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                
                # Create circular path
                path = QPainterPath()
                path.addEllipse(0, 0, temp_size, temp_size)
                painter.setClipPath(path)
                
                # Draw the square cropped image
                painter.drawPixmap(0, 0, square_pixmap)
                painter.end()
                
                # Scale down to final size for crisp display
                final_pixmap = circular_pixmap.scaled(target_size, target_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                
                # Set the circular image
                if label and not label.isHidden():
                    label.setPixmap(final_pixmap)
                    label.setStyleSheet("""
                        QLabel {
                            background-color: transparent;
                            border-radius: 60px;
                            border: 3px solid #555;
                        }
                    """)
            else:
                self.on_large_actor_profile_failed(label)
                
        except (requests.ConnectionError, requests.Timeout):
            self.on_large_actor_profile_offline(label)
        except Exception as e:
            logging.error(f"Error loading large actor profile: {str(e)}")
            self.on_large_actor_profile_failed(label)
    
    def on_large_actor_profile_failed(self, label):
        """Handle failed large actor profile loading"""
        try:
            if label and not label.isHidden():
                label.setText("👤")
                label.setStyleSheet("""
                    color: #666; 
                    font-size: 40px; 
                    background-color: #333;
                    border-radius: 60px;
                    border: 3px solid #555;
                """)
        except Exception as e:
            pass
    
    def on_large_actor_profile_offline(self, label):
        """Handle offline large actor profile loading"""
        try:
            if label and not label.isHidden():
                label.setText("📡")
                label.setStyleSheet("""
                    color: #666; 
                    font-size: 32px; 
                    background-color: #333;
                    border-radius: 60px;
                    border: 3px solid #444;
                """)
        except Exception as e:
            self.on_large_actor_profile_failed(label)
    
    def create_actor_movie_item(self, movie_data):
        """Create a movie item widget for actor's filmography"""
        movie_widget = QWidget()
        movie_widget.setFixedSize(140, 250)
        movie_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        movie_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(movie_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Poster image
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #222;
                border-radius: 8px;
            }
            QLabel:hover {
                border: 2px solid #E50914;
            }
        """)
        
        # Show placeholder immediately
        poster_label.setText("🎬")
        poster_label.setStyleSheet("""
            color: #666; 
            font-size: 24px; 
            background-color: #333;
            border-radius: 8px;
            border: 1px solid #444;
        """)
        
        layout.addWidget(poster_label)
        
        # Movie title
        title_text = movie_data.get("title", "Unknown Movie")
        title_label = QLabel(title_text)
        title_label.setStyleSheet("""
            color: white;
            font-size: 12px;
            font-weight: 500;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            background-color: transparent;
            padding: 2px 4px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(32)
        layout.addWidget(title_label)
        
        # Store movie data and add click handler
        movie_widget.movie_data = movie_data
        movie_widget.mousePressEvent = lambda event: self.show_home_movie_details(movie_data)
        
        # Load poster image asynchronously
        poster_path = movie_data.get("poster_path")
        if poster_path:
            QTimer.singleShot(50, lambda: self.load_poster_async(poster_label, poster_path, "🎬"))
        
        return movie_widget
    
    def create_more_like_this_section(self, content_id, content_type="movie"):
        """Create a horizontal scrollable 'More Like This' section"""
        # Get similar content
        similar_content = self.get_similar_content(content_id, content_type, limit=15)
        
        if not similar_content:
            return None
        
        # Container for the section
        section_container = QWidget()
        section_layout = QVBoxLayout(section_container)
        section_layout.setContentsMargins(0, 20, 0, 0)
        section_layout.setSpacing(15)
        
        # Section title
        title_label = QLabel("More Like This")
        title_label.setStyleSheet("""
            font-size: 22px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        section_layout.addWidget(title_label)
        
        # Horizontal scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(False)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFixedHeight(290)  # Increased from 250 to accommodate titles
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        
        # Container for similar content items
        content_container = QWidget()
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)
        
        # Create items for similar content
        for item in similar_content:
            if content_type == "movie":
                item_widget = self.create_similar_movie_item(item)
            else:
                item_widget = self.create_similar_series_item(item)
            
            if item_widget:
                content_layout.addWidget(item_widget)
        
        content_layout.addStretch()
        scroll_area.setWidget(content_container)
        section_layout.addWidget(scroll_area)
        
        return section_container
    
    def create_similar_movie_item(self, movie_data):
        """Create a similar movie item widget"""
        movie_widget = QWidget()
        movie_widget.setFixedSize(140, 250)  # Increased height to accommodate title
        movie_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        movie_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(movie_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Poster image
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #222;
                border-radius: 8px;
            }
            QLabel:hover {
                border: 2px solid #E50914;
            }
        """)
        
        # Load poster image
        poster_path = movie_data.get("poster_path")
        if poster_path:
            try:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    poster_label.setPixmap(pixmap)
                else:
                    poster_label.setText("No Image")
                    poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
            except (requests.ConnectionError, requests.Timeout):
                poster_label.setText("📡\nNo Internet")
                poster_label.setStyleSheet("color: #E50914; font-size: 10px; background-color: #333;")
            except Exception as e:
                poster_label.setText("❌\nError")
                poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
        else:
            poster_label.setText("🎬\nNo Image")
            poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
        
        layout.addWidget(poster_label)
        
        # Movie title
        title_text = movie_data.get("title", "Unknown Movie")
        title_label = QLabel(title_text)
        title_label.setStyleSheet("""
            color: white;
            font-size: 12px;
            font-weight: 500;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            background-color: transparent;
            padding: 2px 4px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(32)  # Limit height to 2 lines
        layout.addWidget(title_label)
        
        # Store movie data and add click handler
        movie_widget.movie_data = movie_data
        movie_widget.mousePressEvent = lambda event: self.show_home_movie_details(movie_data)
        
        return movie_widget
    
    def create_similar_series_item(self, series_data):
        """Create a similar TV series item widget"""
        series_widget = QWidget()
        series_widget.setFixedSize(140, 250)  # Increased height to accommodate title
        series_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        series_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(series_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Poster image
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #222;
                border-radius: 8px;
            }
            QLabel:hover {
                border: 2px solid #E50914;
            }
        """)
        
        # Load poster image
        poster_path = series_data.get("poster_path")
        if poster_path:
            try:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    poster_label.setPixmap(pixmap)
                else:
                    poster_label.setText("No Image")
                    poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
            except (requests.ConnectionError, requests.Timeout):
                poster_label.setText("📡\nNo Internet")
                poster_label.setStyleSheet("color: #E50914; font-size: 10px; background-color: #333;")
            except Exception as e:
                poster_label.setText("❌\nError")
                poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
        else:
            poster_label.setText("📺\nNo Image")
            poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
        
        layout.addWidget(poster_label)
        
        # Series title
        title_text = series_data.get("name", "Unknown Series")
        title_label = QLabel(title_text)
        title_label.setStyleSheet("""
            color: white;
            font-size: 12px;
            font-weight: 500;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            background-color: transparent;
            padding: 2px 4px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(32)  # Limit height to 2 lines
        layout.addWidget(title_label)
        
        # Store series data and add click handler
        series_widget.series_data = series_data
        series_widget.mousePressEvent = lambda event: self.show_home_series_details(series_data)
        
        return series_widget

    def create_genre_row(self, genre_name, genre_id, content_type="movie"):
        """Create a horizontal scrollable row of movies or TV series for a specific genre"""
        genre_container = QWidget()
        genre_layout = QVBoxLayout(genre_container)
        genre_layout.setContentsMargins(0, 0, 0, 0)
        genre_layout.setSpacing(10)
        
        # Genre title
        genre_title = QLabel(genre_name)
        genre_title.setStyleSheet("""
            font-size: 20px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 5px;
        """)
        genre_layout.addWidget(genre_title)
        
        # Horizontal scroll area for movie/series posters
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(False)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll_area.setFixedHeight(280)  # Increased from 240 to accommodate titles
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        
        # Container for movie/series posters
        content_container = QWidget()
        content_layout = QHBoxLayout(content_container)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(15)
        
        # Add loading placeholder initially
        loading_label = QLabel("Loading...")
        loading_label.setStyleSheet("color: #666666; font-size: 14px; padding: 20px;")
        loading_label.setAlignment(Qt.AlignCenter)
        content_layout.addWidget(loading_label)
        
        # Load content asynchronously with delay to prevent blocking
        QTimer.singleShot(50, lambda: self.load_genre_content_delayed(content_layout, genre_id, content_type))
        
        content_layout.addStretch()
        scroll_area.setWidget(content_container)
        genre_layout.addWidget(scroll_area)
        
        return genre_container

    def load_genre_content_delayed(self, content_layout, genre_id, content_type):
        """Load genre content with delay to prevent UI blocking"""
        try:
            # Clear loading placeholder
            for i in reversed(range(content_layout.count())):
                item = content_layout.itemAt(i)
                if item and item.widget() and hasattr(item.widget(), 'text') and "Loading..." in item.widget().text():
                    item.widget().setParent(None)
                    break
            
            # Load content for this genre based on type - with faster loading
            if content_type == "tv":
                self.load_genre_series_fast(content_layout, genre_id)
            else:
                self.load_genre_movies_fast(content_layout, genre_id)
                
        except Exception as e:
            print(f"Error loading genre content: {e}")
            error_label = QLabel("Failed to load")
            error_label.setStyleSheet("color: #ff6b6b; font-size: 12px;")
            content_layout.addWidget(error_label)

    def load_genre_movies_fast(self, layout, genre_id):
        """Load popular movies for a specific genre using TMDB API - optimized for speed"""
        try:
            # Get current rotation page for content variety (default to 1)
            current_page = getattr(self, 'content_rotation_page', 1)
            
            all_movies = []
            
            # Fetch from 1 page initially for faster loading, then add second page
            for page in [current_page]:  # Start with just one page for speed
                if genre_id == "trending":
                    # For "Trending" section, use trending movies
                    url = f"{TMDB_API_URL}/trending/movie/week"
                    params = {"api_key": TMDB_API_KEY, "page": page}
                else:
                    # For specific genres, discover movies with better popularity filters
                    url = f"{TMDB_API_URL}/discover/movie"
                    
                    # Special handling for romance genre for better content
                    if genre_id == 10749:  # Romance genre
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_genres": genre_id,
                            "sort_by": "popularity.desc",  # Sort by popularity for romance
                            "vote_average.gte": 5.5,       # Lower threshold for romance content
                            "vote_count.gte": 50,          # Lower vote requirement
                            "with_original_language": "en", # Focus on English content
                            "primary_release_date.gte": "2010-01-01",
                            "page": page
                        }
                    # Special handling for horror genre which has fewer high-rated movies
                    elif genre_id == 27:  # Horror genre
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_genres": genre_id,
                            "sort_by": "popularity.desc",  # Use popularity instead of vote count for horror
                            "vote_average.gte": 5.0,       # Lower minimum rating for horror
                            "vote_count.gte": 20,          # Lower vote requirement
                            "primary_release_date.gte": "2010-01-01",  # Longer time range
                            "page": page
                        }
                    else:
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_genres": genre_id,
                            "sort_by": "vote_count.desc",  # Sort by most voted first
                            "vote_average.gte": 6.0,       # Minimum rating of 6.0
                            "vote_count.gte": 100,         # At least 100 votes
                            "primary_release_date.gte": "2015-01-01",  # Movies from 2015 onwards
                            "page": page
                        }
                
                response = requests.get(url, params=params, timeout=5)  # Reduced timeout from 10s to 5s
                response.raise_for_status()
                data = response.json()
                
                # Add movies from this page
                page_movies = data.get("results", [])
                all_movies.extend(page_movies)
            
            # Load up to 20 movies initially for faster display
            movies = all_movies[:20]  # Reduced from 40 to 20 for faster initial load
            for i, movie in enumerate(movies):
                movie_widget = self.create_home_movie_item_fast(movie)
                layout.addWidget(movie_widget)
                
                # Process events every 5 items to keep UI responsive
                if i % 5 == 0:
                    QApplication.processEvents()
                
        except requests.ConnectionError:
            logging.error("No internet connection for loading genre movies")
            placeholder = QLabel("No Internet")
            placeholder.setStyleSheet("""
                color: #E50914; 
                font-size: 12px; 
                font-weight: bold;
                padding: 15px;
                background-color: #333;
                border-radius: 8px;
                min-width: 140px;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            layout.addWidget(placeholder)
        except requests.Timeout:
            logging.error("Timeout loading genre movies")
            placeholder = QLabel("Timeout")
            placeholder.setStyleSheet("""
                color: #FFA500; 
                font-size: 12px; 
                font-weight: bold;
                padding: 15px;
                background-color: #333;
                border-radius: 8px;
                min-width: 140px;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            layout.addWidget(placeholder)
        except Exception as e:
            logging.error(f"Error loading genre movies: {str(e)}")
            placeholder = QLabel("Error")
            placeholder.setStyleSheet("""
                color: #666; 
                font-size: 12px;
                padding: 15px;
                background-color: #333;
                border-radius: 8px;
                min-width: 140px;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            layout.addWidget(placeholder)

    def load_genre_series_fast(self, layout, genre_id):
        """Load popular TV series for a specific genre using TMDB API - optimized for speed"""
        try:
            # Get current rotation page for content variety (default to 1)
            current_page = getattr(self, 'content_rotation_page', 1)
            
            all_series = []
            
            # Fetch from multiple pages for Romance, Horror, and Music to get more options
            pages_to_fetch = [current_page]
            if genre_id in [10749, 27, 10402]:  # Romance, Horror, Music
                pages_to_fetch = [current_page, current_page + 1] if current_page < 3 else [current_page, 1]
            
            for page in pages_to_fetch:
                try:
                    if genre_id == "trending":
                        # For "Trending" section, use trending TV shows
                        url = f"{TMDB_API_URL}/trending/tv/week"
                        params = {"api_key": TMDB_API_KEY, "page": page}
                    else:
                        # For specific genres, discover TV series with better popularity filters
                        url = f"{TMDB_API_URL}/discover/tv"
                        
                        # Special handling for romance genre for better content
                        if genre_id == 10749:  # Romance genre - enhanced for more options
                            params = {
                                "api_key": TMDB_API_KEY,
                                "with_genres": genre_id,
                                "sort_by": "popularity.desc",  # Sort by popularity to get trending romance shows
                                "vote_average.gte": 4.0,       # Lower threshold to include more shows
                                "vote_count.gte": 10,          # Lower vote count to include newer shows
                                "first_air_date.gte": "2000-01-01",  # Include shows from 2000 onwards for variety
                                "page": page,
                                  "include_adult": "false",
                                "region": "US",  # <-- Add this line
                                "with_origin_country": "US",
                                "with_original_language": "en"
                            }
                      # Special handling for horror genre for more options
                        elif genre_id == 27:  # Horror genre - enhanced for more options
                            params = {
                                "api_key": TMDB_API_KEY,
                                "with_genres": genre_id,
                                "sort_by": "popularity.desc",  # Use popularity instead of vote count for horror
                                "vote_average.gte": 4.5,       # Lower minimum rating for horror to get more shows
                                "vote_count.gte": 5,           # Very low vote requirement to include new horror shows
                                "first_air_date.gte": "1995-01-01",  # Much longer time range for horror
                                "page": page,
                                "include_adult": "false"
                            }
                        # Special handling for music genre for more options
                        elif genre_id == 10402:  # Music genre - enhanced for more options
                            params = {
                                "api_key": TMDB_API_KEY,
                                "with_genres": genre_id,
                                "sort_by": "popularity.desc",  # Use popularity for music shows
                                "vote_average.gte": 4.0,       # Lower minimum rating for music
                                "vote_count.gte": 5,           # Very low vote requirement to include music shows
                                "first_air_date.gte": "1990-01-01",  # Long time range for music shows
                                "page": page,
                                "include_adult": "false"
                            }
                        else:
                            params = {
                                "api_key": TMDB_API_KEY,
                                "with_genres": genre_id,
                                "sort_by": "vote_count.desc",  # Sort by most voted first
                                "vote_average.gte": 6.5,       # Minimum rating of 6.5 for TV shows
                                "vote_count.gte": 50,          # At least 50 votes
                                "first_air_date.gte": "2010-01-01",  # Shows from 2010 onwards
                                "page": page
                            }
                    
                    response = requests.get(url, params=params, timeout=5)  # Reduced timeout from 10s to 5s
                    response.raise_for_status()
                    data = response.json()
                    
                    # Add series from this page
                    page_series = data.get("results", [])
                    all_series.extend(page_series)
                    
                except Exception as page_error:
                    logging.warning(f"Error fetching page {page} for genre {genre_id}: {str(page_error)}")
                    continue  # Try next page if this one fails
            
            # For Romance, Horror, and Music, try additional API calls to get even more content
            if genre_id in [10749, 27, 10402] and len(all_series) < 15:
                try:
                    # Try alternative search methods for these genres
                    if genre_id == 10749:  # Romance - also search by keywords
                        alt_url = f"{TMDB_API_URL}/discover/tv"
                        alt_params = {
                            "api_key": TMDB_API_KEY,
                            "with_keywords": "9840|12916|210024",  # Romance, Love, Relationship keywords
                            "sort_by": "popularity.desc",
                            "vote_average.gte": 3.5,
                            "page": 1,  
                            "with_origin_country": "US",            # <-- Add this
                            "with_original_language": "en" 
                        }
                        alt_response = requests.get(alt_url, params=alt_params, timeout=3)
                        if alt_response.status_code == 200:
                            alt_series = alt_response.json().get("results", [])
                            all_series.extend(alt_series[:10])  # Add up to 10 more
                    
                    elif genre_id == 27:  # Horror - also search by keywords
                        alt_url = f"{TMDB_API_URL}/discover/tv"
                        alt_params = {
                            "api_key": TMDB_API_KEY,
                            "with_keywords": "12377|14819|170362",  # Horror, Supernatural, Scary keywords
                            "sort_by": "popularity.desc",
                            "vote_average.gte": 3.0,
                            "page": 1
                        }
                        alt_response = requests.get(alt_url, params=alt_params, timeout=3)
                        if alt_response.status_code == 200:
                            alt_series = alt_response.json().get("results", [])
                            all_series.extend(alt_series[:10])  # Add up to 10 more
                    
                    elif genre_id == 10402:  # Music - also search by keywords
                        alt_url = f"{TMDB_API_URL}/discover/tv"
                        alt_params = {
                            "api_key": TMDB_API_KEY,
                            "with_keywords": "6054|9715|10349",  # Music, Musical, Performance keywords
                            "sort_by": "popularity.desc",
                            "vote_average.gte": 3.0,
                            "page": 1
                        }
                        alt_response = requests.get(alt_url, params=alt_params, timeout=3)
                        if alt_response.status_code == 200:
                            alt_series = alt_response.json().get("results", [])
                            all_series.extend(alt_series[:10])  # Add up to 10 more
                except:
                    pass  # Continue if alternative search fails
            
            # Remove duplicates while preserving order
            seen_ids = set()
            unique_series = []
            for series in all_series:
                if series.get('id') not in seen_ids:
                    seen_ids.add(series.get('id'))
                    unique_series.append(series)
            
            # For Romance, Horror, and Music, show up to 30 series, otherwise 20
            max_series = 30 if genre_id in [10749, 27, 10402] else 20
            series = unique_series[:max_series]
            
            # If no series found, try a more generic search as fallback
            if not series:
                try:
                    # Fallback: try with more relaxed criteria
                    fallback_url = f"{TMDB_API_URL}/discover/tv"
                    fallback_params = {
                        "api_key": TMDB_API_KEY,
                        "sort_by": "popularity.desc",
                        "vote_average.gte": 3.0,
                        "page": 1,
                        "include_adult": "false"
                    }
                    
                    # If it's a genre search, still try to include the genre but with relaxed criteria
                    if genre_id != "trending" and str(genre_id).isdigit():
                        fallback_params["with_genres"] = genre_id
                    
                    fallback_response = requests.get(fallback_url, params=fallback_params, timeout=3)
                    if fallback_response.status_code == 200:
                        fallback_data = fallback_response.json()
                        fallback_series = fallback_data.get("results", [])[:10]  # Get at least 10 shows
                        series = fallback_series
                        logging.info(f"Used fallback content for genre {genre_id}, found {len(series)} shows")
                except Exception as fallback_error:
                    logging.warning(f"Fallback search also failed for genre {genre_id}: {str(fallback_error)}")
                    pass  # If fallback also fails, continue with empty series
            
            for i, show in enumerate(series):
                series_widget = self.create_home_series_item_fast(show)
                layout.addWidget(series_widget)
                
                # Process events every 5 items to keep UI responsive
                if i % 5 == 0:
                    QApplication.processEvents()
            
            # If still no series, show a placeholder
            if not series:
                placeholder = QLabel("No shows found")
                placeholder.setStyleSheet("""
                    color: #888; 
                    font-size: 12px;
                    padding: 15px;
                    background-color: #2a2a2a;
                    border-radius: 8px;
                    min-width: 140px;
                """)
                placeholder.setAlignment(Qt.AlignCenter)
                layout.addWidget(placeholder)
                
        except requests.ConnectionError:
            logging.error("No internet connection for loading genre series")
            placeholder = QLabel("No Internet")
            placeholder.setStyleSheet("""
                color: #E50914; 
                font-size: 12px; 
                font-weight: bold;
                padding: 15px;
                background-color: #333;
                border-radius: 8px;
                min-width: 140px;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            layout.addWidget(placeholder)
        except requests.Timeout:
            logging.error("Timeout loading genre series")
            placeholder = QLabel("Timeout")
            placeholder.setStyleSheet("""
                color: #FFA500; 
                font-size: 12px; 
                font-weight: bold;
                padding: 15px;
                background-color: #333;
                border-radius: 8px;
                min-width: 140px;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            layout.addWidget(placeholder)
        except Exception as e:
            logging.error(f"Error loading genre series: {str(e)}")
            placeholder = QLabel("Error")
            placeholder.setStyleSheet("""
                color: #666; 
                font-size: 12px;
                padding: 15px;
                background-color: #333;
                border-radius: 8px;
                min-width: 140px;
            """)
            placeholder.setAlignment(Qt.AlignCenter)
            layout.addWidget(placeholder)

    def create_home_movie_item_fast(self, movie_data):
        """Create a clickable movie poster widget with faster loading"""
        movie_widget = QWidget()
        movie_widget.setFixedSize(140, 250)  # Increased height to accommodate title
        movie_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        movie_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(movie_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Poster image with placeholder
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #222;
                border-radius: 8px;
            }
            QLabel:hover {
                border: 2px solid #E50914;
            }
        """)
        
        # Show placeholder immediately
        poster_label.setText("🎬")
        poster_label.setStyleSheet("""
            color: #666; 
            font-size: 24px; 
            background-color: #333;
            border-radius: 8px;
            border: 1px solid #444;
        """)
        
        layout.addWidget(poster_label)
        
        # Movie title
        title_text = movie_data.get("title", "Unknown Movie")
        title_label = QLabel(title_text)
        title_label.setStyleSheet("""
            color: white;
            font-size: 12px;
            font-weight: 500;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            background-color: transparent;
            padding: 2px 4px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(32)  # Limit height to 2 lines
        layout.addWidget(title_label)
        
        # Store movie data for click handling
        movie_widget.movie_data = movie_data
        movie_widget.mousePressEvent = lambda event: self.show_home_movie_details(movie_data)
        
        # Load image asynchronously after widget is created - faster loading
        poster_path = movie_data.get("poster_path")
        if poster_path:
            QTimer.singleShot(50, lambda: self.load_poster_async(poster_label, poster_path, "🎬"))  # Reduced from 100ms to 50ms
        
        return movie_widget

    def create_home_series_item_fast(self, series_data):
        """Create a clickable TV series poster widget with faster loading"""
        series_widget = QWidget()
        series_widget.setFixedSize(140, 250)  # Increased height to accommodate title
        series_widget.setStyleSheet("""
            QWidget {
                background-color: transparent;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: rgba(255, 255, 255, 0.1);
            }
        """)
        series_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(series_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Poster image with placeholder
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        poster_label.setStyleSheet("""
            QLabel {
                background-color: #222;
                border-radius: 8px;
            }
            QLabel:hover {
                border: 2px solid #E50914;
            }
        """)
        
        # Show placeholder immediately
        poster_label.setText("📺")
        poster_label.setStyleSheet("""
            color: #666; 
            font-size: 24px; 
            background-color: #333;
            border-radius: 8px;
            border: 1px solid #444;
        """)
        
        layout.addWidget(poster_label)
        
        # Series title
        title_text = series_data.get("name", "Unknown Series")
        title_label = QLabel(title_text)
        title_label.setStyleSheet("""
            color: white;
            font-size: 12px;
            font-weight: 500;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            background-color: transparent;
            padding: 2px 4px;
        """)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setMaximumHeight(32)  # Limit height to 2 lines
        layout.addWidget(title_label)
        
        # Store series data for click handling
        series_widget.series_data = series_data
        series_widget.mousePressEvent = lambda event: self.show_home_series_details(series_data)
        
        # Load image asynchronously after widget is created - faster loading
        poster_path = series_data.get("poster_path")
        if poster_path:
            QTimer.singleShot(50, lambda: self.load_poster_async(poster_label, poster_path, "📺"))  # Reduced from 100ms to 50ms
        
        return series_widget

    def on_poster_loaded(self, label, pixmap):
        """Handle successful poster loading"""
        try:
            if label and not label.isHidden():
                label.clear()  # Clear any existing text/pixmap
                label.setPixmap(pixmap)
                label.setStyleSheet("border-radius: 8px; border: 1px solid #444;")
        except Exception as e:
            pass

    def on_poster_failed(self, label, fallback_icon):
        """Handle failed poster loading"""
        try:
            if label and not label.isHidden():
                label.clear()
                label.setText(fallback_icon)
                label.setStyleSheet("""
                    color: #666; 
                    font-size: 24px; 
                    background-color: #333;
                    border-radius: 8px;
                    border: 1px solid #444;
                """)
        except Exception as e:
            pass

    def on_poster_offline(self, label, fallback_icon):
        """Handle offline poster loading with subtle offline indicator"""
        try:
            if label and not label.isHidden():
                label.clear()
                label.setText(f"📡\n{fallback_icon}")
                label.setStyleSheet("""
                    color: #555; 
                    font-size: 20px; 
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #2a2a2a, stop:1 #333333);
                    border-radius: 8px;
                    border: 2px dashed #444;
                    text-align: center;
                    line-height: 1.2;
                """)
                label.setAlignment(Qt.AlignCenter)
        except Exception as e:
            # Fallback to standard failed handling
            self.on_poster_failed(label, fallback_icon)

    def load_poster_async(self, label, poster_path, fallback_icon):
        """Load poster image asynchronously using signal-slot mechanism"""
        self.poster_loader.load_poster(label, poster_path, fallback_icon)

    def on_backdrop_loaded(self, label, pixmap):
        """Handle successful backdrop loading"""
        try:
            if label and not label.isHidden():
                label.clear()  # Clear any existing text/pixmap
                # Store original for resizing
                label.original_pixmap = pixmap
                # Add resize event handler
                label.resizeEvent = lambda event: self.resize_banner(label, event)
                # Create banner with gradient overlay
                banner = self.create_poster_banner(pixmap, width=label.width(), height=label.height())
                label.setPixmap(banner)
        except Exception as e:
            pass

    def on_backdrop_failed(self, label, fallback_icon):
        """Handle failed backdrop loading"""
        try:
            if label and not label.isHidden():
                label.clear()
                label.setText(fallback_icon)
                label.setStyleSheet("""
                    color: #666; 
                    font-size: 48px; 
                    background-color: #222;
                    border-radius: 8px;
                    text-align: center;
                """)
        except Exception as e:
            pass

    def on_backdrop_offline(self, label, title):
        """Handle offline backdrop loading with proper offline message"""
        try:
            if label and not label.isHidden():
                label.clear()
                
                # Create offline message text
                offline_text = "📡\n\nOffline Mode\n"
                if title:
                    # Truncate long titles
                    display_title = title[:30] + "..." if len(title) > 30 else title
                    offline_text += f'"{display_title}"\n\n'
                offline_text += "Backdrop not available offline\nConnect to internet to view image"
                
                label.setText(offline_text)
                label.setStyleSheet("""
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #1a1a1a, stop:1 #2a2a2a);
                    border-radius: 8px;
                    border: 2px dashed #444;
                    text-align: center;
                    color: #888;
                    font-size: 14px;
                    font-family: 'Netflix Sans', 'Arial', sans-serif;
                    padding: 20px;
                    line-height: 1.4;
                """)
                label.setAlignment(Qt.AlignCenter)
                label.setWordWrap(True)
                
        except Exception as e:
            # Fallback to simple text if styling fails
            try:
                if label and not label.isHidden():
                    label.clear()
                    label.setText("📡\nOffline Mode\nNo backdrop available")
                    label.setStyleSheet("""
                        color: #666; 
                        font-size: 16px; 
                        background-color: #1a1a1a;
                        border-radius: 8px;
                        border: 2px dashed #444;
                        text-align: center;
                        padding: 20px;
                    """)
                    label.setAlignment(Qt.AlignCenter)
            except:
                pass

    def load_backdrop_async(self, label, backdrop_path, fallback_icon, title=""):
        """Load backdrop image asynchronously using signal-slot mechanism"""
        self.poster_loader.load_backdrop(label, backdrop_path, fallback_icon, title)

    def show_home_series_details(self, series_data):
        """Show detailed view for a discovered TV series with trailer option"""
        # Track current series data for back navigation
        self.current_series_data = series_data
        self.previous_view_stack.append(("series_details", series_data))
        
        # Clear previous content
        for i in reversed(range(self.home_details_layout.count())):
            widget = self.home_details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Create scroll area for the entire content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        # Container widget for all content
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 15, 20, 20)
        container_layout.setSpacing(20)

        # Back button
        back_button = QPushButton("Back to Home")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 150px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        back_button.clicked.connect(self.navigate_back)
        container_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Banner with backdrop image (Netflix-style horizontal banner) - cached version
        backdrop_path = series_data.get("backdrop_path")
        if backdrop_path:
            # Create banner label placeholder
            banner_label = QLabel()
            banner_label.setFixedHeight(300)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            banner_label.setStyleSheet("""
                QLabel {
                    border-radius: 8px;
                    background-color: #222;
                    color: #666;
                    font-size: 48px;
                    text-align: center;
                }
            """)
            banner_label.setAlignment(Qt.AlignCenter)
            banner_label.setText("🎬")  # Placeholder while loading
            container_layout.addWidget(banner_label)
            
            # Load backdrop asynchronously with caching
            series_title = series_data.get("name", "")
            self.load_backdrop_async(banner_label, backdrop_path, "🎬", series_title)

        # Series details
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)

        # Title
        title_label = QLabel(series_data.get("name", "Unknown Series"))
        title_label.setStyleSheet("""
            font-size: 32px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        details_layout.addWidget(title_label)

        # Metadata
        meta_parts = []
        if series_data.get("first_air_date"):
            year = series_data["first_air_date"][:4]
            meta_parts.append(year)
        if series_data.get("vote_average"):
            rating = series_data["vote_average"]
            meta_parts.append(f"★ {rating:.1f}")
        
        metadata_label = QLabel(" • ".join(meta_parts))
        metadata_label.setStyleSheet("""
            font-size: 16px; 
            color: #AAAAAA; 
            margin-bottom: 20px;
            font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
        """)
        details_layout.addWidget(metadata_label)

        # Synopsis
        synopsis_label = QLabel("Synopsis")
        synopsis_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 5px;
        """)
        details_layout.addWidget(synopsis_label)

        synopsis_text = QTextEdit()
        synopsis_text.setPlainText(series_data.get("overview", "No synopsis available"))
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
        """)
        synopsis_text.setMinimumHeight(100)
        synopsis_text.setMaximumHeight(200)
        details_layout.addWidget(synopsis_text)

        # Cast section
        series_id = series_data.get("id")
        if series_id:
            cast_section = self.create_cast_section(series_id, "tv")
            if cast_section:
                details_layout.addWidget(cast_section)

        # Action buttons
        buttons_layout = QHBoxLayout()
        
        # Watch Trailer button
        trailer_button = QPushButton("Watch Trailer")
        trailer_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 16px;
                border-radius: 4px;
                font-weight: bold;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        trailer_button.clicked.connect(lambda: self.watch_series_trailer(series_data))
        buttons_layout.addWidget(trailer_button)
        
        buttons_layout.addStretch()
        details_layout.addLayout(buttons_layout)

        details_layout.addStretch()
        container_layout.addWidget(details_widget)
        
        # Add "More Like This" section
        series_id = series_data.get("id")
        if series_id:
            more_like_this_section = self.create_more_like_this_section(series_id, "tv")
            if more_like_this_section:
                container_layout.addWidget(more_like_this_section)
        
        # Set up scroll area and add to main layout
        scroll_area.setWidget(container)
        self.home_details_layout.addWidget(scroll_area)
        self.stacked_widget.setCurrentIndex(5)

    def watch_series_trailer(self, series_data):
        """Open YouTube trailer for the TV series"""
        try:
            # Check internet connection first
            if not self.check_internet_connection():
                QMessageBox.warning(self, "No Internet", "Please check your internet connection to watch trailers.")
                return
            
            series_title = series_data.get("name", "")
            year = ""
            if series_data.get("first_air_date"):
                year = series_data["first_air_date"][:4]
            
            # Create search query for YouTube
            search_query = f"{series_title} {year} trailer"
            youtube_search_url = f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
            
            # Open in default browser
            if sys.platform == "win32":
                subprocess.run(["start", youtube_search_url], shell=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", youtube_search_url])
            else:
                subprocess.run(["xdg-open", youtube_search_url])
                
            logging.info(f"Opening YouTube search for: {search_query}")
            
        except Exception as e:
            logging.error(f"Error opening series trailer: {str(e)}")
            QMessageBox.critical(self, "Error", f"Could not open trailer:\n{str(e)}")

    def create_home_movie_item(self, movie_data):
        """Create a clickable movie poster widget"""
        movie_widget = QWidget()
        movie_widget.setFixedSize(140, 210)
        movie_widget.setStyleSheet("""
            QWidget {
                background-color: #222;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: #333;
                border: 2px solid #E50914;
            }
        """)
        movie_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(movie_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Poster image
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        
        # Load poster image
        poster_path = movie_data.get("poster_path")
        if poster_path:
            try:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    poster_label.setPixmap(pixmap)
                else:
                    poster_label.setText("No Image")
                    poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
            except (requests.ConnectionError, requests.Timeout):
                poster_label.setText("📡\nNo Internet")
                poster_label.setStyleSheet("color: #E50914; font-size: 10px; background-color: #333;")
            except Exception as e:
                poster_label.setText("❌\nError")
                poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
        else:
            poster_label.setText("🎬\nNo Image")
            poster_label.setStyleSheet("color: white; font-size: 12px; background-color: #333;")
        
        layout.addWidget(poster_label)
        
        # Store movie data for click handling
        movie_widget.movie_data = movie_data
        movie_widget.mousePressEvent = lambda event: self.show_home_movie_details(movie_data)
        
        return movie_widget

    def show_home_movie_details(self, movie_data):
        """Show detailed view for a discovered movie with trailer option"""
        # Track current movie data for back navigation
        self.current_movie_data = movie_data
        self.previous_view_stack.append(("movie_details", movie_data))
        
        # Clear previous content
        for i in reversed(range(self.home_details_layout.count())):
            widget = self.home_details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Create scroll area for the entire content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        # Container widget for all content
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(20, 15, 20, 20)
        container_layout.setSpacing(20)

        # Back button
        back_button = QPushButton("Back to Home")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 150px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        back_button.clicked.connect(self.navigate_back)
        container_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Banner with backdrop image (Netflix-style horizontal banner) - cached version
        backdrop_path = movie_data.get("backdrop_path")
        if backdrop_path:
            # Create banner label placeholder
            banner_label = QLabel()
            banner_label.setFixedHeight(300)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            banner_label.setStyleSheet("""
                QLabel {
                    border-radius: 8px;
                    background-color: #222;
                    color: #666;
                    font-size: 48px;
                    text-align: center;
                }
            """)
            banner_label.setAlignment(Qt.AlignCenter)
            banner_label.setText("🎬")  # Placeholder while loading
            container_layout.addWidget(banner_label)
            
            # Load backdrop asynchronously with caching
            movie_title = movie_data.get("title", "")
            self.load_backdrop_async(banner_label, backdrop_path, "🎬", movie_title)

        # Movie details
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)

        # Title
        title_label = QLabel(movie_data.get("title", "Unknown Title"))
        title_label.setStyleSheet("""
            font-size: 32px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        details_layout.addWidget(title_label)

        # Metadata (rating, year, runtime, genres)
        meta_parts = []
        # Year
        if movie_data.get("release_date"):
            year = movie_data["release_date"][:4]
            meta_parts.append(year)
        # Rating
        if movie_data.get("vote_average"):
            rating = movie_data["vote_average"]
            meta_parts.append(f"★ {rating:.1f}")
        # Runtime (fetch if not present)
        runtime = movie_data.get("runtime")
        runtime_str = None
        if runtime is None:
            # Try to fetch runtime from TMDB
            movie_id = movie_data.get("id")
            runtime = None
            if movie_id:
                try:
                    details_url = f"{TMDB_API_URL}/movie/{movie_id}"
                    response = requests.get(details_url, params={"api_key": TMDB_API_KEY}, timeout=5)
                    if response.status_code == 200:
                        movie_details = response.json()
                        runtime = movie_details.get("runtime", 0)
                except Exception:
                    runtime = None
        if runtime:
            hours = runtime // 60
            minutes = runtime % 60
            runtime_str = f"{hours}h {minutes}m" if hours > 0 else f"{minutes}m"
        else:
            runtime_str = "N/A"
        meta_parts.append(runtime_str)
        
        metadata_label = QLabel(" • ".join(meta_parts))
        metadata_label.setStyleSheet("""
            font-size: 16px; 
            color: #AAAAAA; 
            margin-bottom: 20px;
            font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
        """)
        details_layout.addWidget(metadata_label)

        # Synopsis
        synopsis_label = QLabel("Synopsis")
        synopsis_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 5px;
        """)
        details_layout.addWidget(synopsis_label)

        synopsis_text = QTextEdit()
        synopsis_text.setPlainText(movie_data.get("overview", "No synopsis available"))
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
        """)
        synopsis_text.setMinimumHeight(100)
        synopsis_text.setMaximumHeight(200)
        details_layout.addWidget(synopsis_text)

        # Cast section
        movie_id = movie_data.get("id")
        if movie_id:
            cast_section = self.create_cast_section(movie_id, "movie")
            if cast_section:
                details_layout.addWidget(cast_section)

        # Action buttons
        buttons_layout = QHBoxLayout()
        
        # Watch Trailer button
        trailer_button = QPushButton("Watch Trailer")
        trailer_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 16px;
                border-radius: 4px;
                font-weight: bold;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        trailer_button.clicked.connect(lambda: self.watch_trailer(movie_data))
        buttons_layout.addWidget(trailer_button)
        
        buttons_layout.addStretch()
        details_layout.addLayout(buttons_layout)

        details_layout.addStretch()
        container_layout.addWidget(details_widget)
        
        # Add "More Like This" section
        movie_id = movie_data.get("id")
        if movie_id:
            more_like_this_section = self.create_more_like_this_section(movie_id, "movie")
            if more_like_this_section:
                container_layout.addWidget(more_like_this_section)
        
        # Set up scroll area and add to main layout
        scroll_area.setWidget(container)
        self.home_details_layout.addWidget(scroll_area)
        self.stacked_widget.setCurrentIndex(5)

    def watch_trailer(self, movie_data):
        """Open YouTube trailer for the movie"""
        try:
            # Check internet connection first
            if not self.check_internet_connection():
                QMessageBox.warning(self, "No Internet", "Please check your internet connection to watch trailers.")
                return
            
            movie_title = movie_data.get("title", "")
            year = ""
            if movie_data.get("release_date"):
                year = movie_data["release_date"][:4]
            
            # Create search query for YouTube
            search_query = f"{movie_title} {year} trailer"
            youtube_search_url = f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
            
            # Open in default browser
            if sys.platform == "win32":
                subprocess.run(["start", youtube_search_url], shell=True)
            elif sys.platform == "darwin":
                subprocess.run(["open", youtube_search_url])
            else:
                subprocess.run(["xdg-open", youtube_search_url])
                
            logging.info(f"Opening YouTube search for: {search_query}")
            
        except Exception as e:
            logging.error(f"Error opening trailer: {str(e)}")
            QMessageBox.critical(self, "Error", f"Could not open trailer:\n{str(e)}")

    def create_media_view(self, title):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(20)
        
        title_container = QWidget()
        title_container.setFixedHeight(60)
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        title_layout.addWidget(title_label)
        
        underline = QWidget()
        underline.setFixedHeight(3)
        underline.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #E50914, stop:0.5 #B00710, stop:1 #E50914);
        """)
        title_layout.addWidget(underline)
        
        layout.addWidget(title_container)
        
        search_filter_widget = QWidget()
        search_filter_layout = QHBoxLayout(search_filter_widget)
        search_filter_layout.setContentsMargins(0, 0, 0, 20)
        
        self.search_bar = QLineEdit()
        self.search_bar.setPlaceholderText("Search...")
        self.search_bar.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                font-size: 14px;
                min-width: 200px;
            }
        """)
        self.search_bar.textChanged.connect(self.filter_media)
        search_filter_layout.addWidget(self.search_bar)
        
        self.filter_combo = QComboBox()
        self.filter_combo.addItem("All")
        self.filter_combo.addItem("Action")
        self.filter_combo.addItem("Comedy")
        self.filter_combo.addItem("Drama")
        self.filter_combo.addItem("Sci-Fi")
        self.filter_combo.addItem("Horror")
        self.filter_combo.addItem("Documentary")
        self.filter_combo.currentTextChanged.connect(self.filter_media)
        search_filter_layout.addWidget(self.filter_combo)
        
        layout.addWidget(search_filter_widget)
        
        if title == "Movies":
            self.movies_list = QListWidget()
            self.movies_list.setViewMode(QListWidget.IconMode)
            self.movies_list.setResizeMode(QListWidget.Adjust)
            self.movies_list.setMovement(QListWidget.Static)
            self.movies_list.setSpacing(20)
            self.movies_list.setIconSize(QSize(150, 225))
            self.movies_list.setGridSize(QSize(170, 270))
            self.movies_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            self.movies_list.itemClicked.connect(self.show_movie_details)
            
            # Add context menu for movies
            self.movies_list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.movies_list.customContextMenuRequested.connect(self.show_movies_context_menu)
            
            # Wrap the list in a scroll area
            list_scroll = QScrollArea()
            list_scroll.setWidgetResizable(True)
            list_scroll.setWidget(self.movies_list)
            list_scroll.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background: transparent;
                }
            """)
            layout.addWidget(list_scroll, 1)
        else:
            self.series_list = QListWidget()
            self.series_list.setViewMode(QListWidget.IconMode)
            self.series_list.setResizeMode(QListWidget.Adjust)
            self.series_list.setMovement(QListWidget.Static)
            self.series_list.setSpacing(20)
            self.series_list.setIconSize(QSize(150, 225))
            self.series_list.setGridSize(QSize(170, 270))
            self.series_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
            self.series_list.itemClicked.connect(self.show_series_details)
            
            # Add context menu for series
            self.series_list.setContextMenuPolicy(Qt.CustomContextMenu)
            self.series_list.customContextMenuRequested.connect(self.show_series_context_menu)
            
            # Wrap the list in a scroll area
            list_scroll = QScrollArea()
            list_scroll.setWidgetResizable(True)
            list_scroll.setWidget(self.series_list)
            list_scroll.setStyleSheet("""
                QScrollArea {
                    border: none;
                    background: transparent;
                }
            """)
            layout.addWidget(list_scroll, 1)
        
        scroll_area.setWidget(container)
        return scroll_area
    
    def filter_media(self):
        search_text = self.search_bar.text().lower()
        filter_text = self.filter_combo.currentText()
        
        list_widget = self.movies_list if self.stacked_widget.currentIndex() == 0 else self.series_list
            
        for i in range(list_widget.count()):
            item = list_widget.item(i)
            matches_search = search_text in item.text().lower()
            matches_filter = (filter_text == "All" or 
                            (hasattr(item, 'genres') and filter_text in item.genres))
            item.setHidden(not (matches_search and matches_filter))
    
    def create_series_list_view(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background: transparent;
            }
        """)
        
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 20, 40, 40)
        layout.setSpacing(20)
        
        title_container = QWidget()
        title_container.setFixedHeight(60)
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("TV Series")
        title_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        title_layout.addWidget(title_label)
        
        underline = QWidget()
        underline.setFixedHeight(3)
        underline.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #E50914, stop:0.5 #B00710, stop:1 #E50914);
        """)
        title_layout.addWidget(underline)
        
        layout.addWidget(title_container)
        
        search_filter_widget = QWidget()
        search_filter_layout = QHBoxLayout(search_filter_widget)
        search_filter_layout.setContentsMargins(0, 0, 0, 20)
        
        self.series_search_bar = QLineEdit()
        self.series_search_bar.setPlaceholderText("Search series...")
        self.series_search_bar.setStyleSheet("""
            QLineEdit {
                padding: 8px;
                font-size: 14px;
                min-width: 200px;
            }
        """)
        self.series_search_bar.textChanged.connect(self.filter_series)
        search_filter_layout.addWidget(self.series_search_bar)
        
        self.series_filter_combo = QComboBox()
        self.series_filter_combo.addItem("All")
        self.series_filter_combo.addItem("Action")
        self.series_filter_combo.addItem("Comedy")
        self.series_filter_combo.addItem("Drama")
        self.series_filter_combo.addItem("Sci-Fi")
        self.series_filter_combo.addItem("Horror")
        self.series_filter_combo.addItem("Documentary")
        self.series_filter_combo.currentTextChanged.connect(self.filter_series)
        search_filter_layout.addWidget(self.series_filter_combo)
        
        layout.addWidget(search_filter_widget)
        
        self.series_list = QListWidget()
        self.series_list.setViewMode(QListWidget.IconMode)
        self.series_list.setResizeMode(QListWidget.Adjust)
        self.series_list.setMovement(QListWidget.Static)
        self.series_list.setSpacing(20)
        self.series_list.setIconSize(QSize(150, 225))
        self.series_list.setGridSize(QSize(170, 270))
        self.series_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.series_list.itemClicked.connect(self.show_series_episodes)
        
        # Add context menu for series
        self.series_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.series_list.customContextMenuRequested.connect(self.show_series_context_menu)
        
        # Wrap the list in a scroll area
        list_scroll = QScrollArea()
        list_scroll.setWidgetResizable(True)
        list_scroll.setWidget(self.series_list)
        list_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        layout.addWidget(list_scroll, 1)
        
        self.populate_series_list()
        scroll_area.setWidget(container)
        return scroll_area
    
    def filter_series(self):
        search_text = self.series_search_bar.text().lower()
        filter_text = self.series_filter_combo.currentText()
        
        for i in range(self.series_list.count()):
            item = self.series_list.item(i)
            matches_search = search_text in item.text().lower()
            matches_filter = (filter_text == "All" or 
                            (hasattr(item, 'genres') and filter_text in item.genres))
            item.setHidden(not (matches_search and matches_filter))
    
    def populate_series_list(self):
        self.series_list.clear()
        
        # Use a set to track processed series and avoid duplicates
        processed_series = set()
        
        if os.path.exists(series_folder):
            for series_name in sorted(os.listdir(series_folder)):
                series_path = os.path.join(series_folder, series_name)
                if os.path.isdir(series_path):
                    # Create a normalized identifier to detect duplicates
                    normalized_series = series_name.lower().strip()
                    
                    # Skip if already processed
                    if normalized_series in processed_series:
                        logging.warning(f"Duplicate series detected and skipped: {series_name}")
                        continue
                        
                    processed_series.add(normalized_series)
                    
                    item = QListWidgetItem(series_name)
                    poster_path = self.find_series_poster(series_path)
                    if poster_path:
                        pixmap = QPixmap(poster_path)
                        overlay = QPixmap(pixmap.size())
                        overlay.fill(Qt.transparent)
                        painter = QPainter(overlay)
                        gradient = QLinearGradient(0, 0, 0, pixmap.height())
                        gradient.setColorAt(0, QColor(0, 0, 0, 150))
                        gradient.setColorAt(1, QColor(0, 0, 0, 50))
                        painter.fillRect(overlay.rect(), gradient)
                        painter.end()
                        
                        combined = QPixmap(pixmap)
                        combined_painter = QPainter(combined)
                        combined_painter.drawPixmap(0, 0, overlay)
                        combined_painter.end()
                        
                        item.setIcon(QIcon(combined))
                    else:
                        item.setIcon(QIcon(self.create_series_placeholder(series_name)))
                    item.setData(Qt.UserRole, series_path)
                    
                    QTimer.singleShot(0, lambda s=series_path, i=item: self.load_series_metadata(s, i))
                    
                    self.series_list.addItem(item)

    def load_series_metadata(self, series_path, item):
        try:
            series_name = os.path.basename(series_path)
            year = extract_year(series_name)
            
            cache_name = f"{series_name}"
            if year:
                cache_name += f" {year}"
            meta_file = f"{quote(cache_name)}_meta.txt"
            meta_path = os.path.join(SYNOPSIS_CACHE_DIR, meta_file)
            
            if os.path.exists(meta_path):
                with open(meta_path, 'r', encoding='utf-8') as f:
                    meta = f.read().split('|')
                    if len(meta) == 3:
                        setattr(item, 'imdb_rating', float(meta[0]) if meta[0] != "None" else None)
                        setattr(item, 'genres', meta[1].split(',') if meta[1] else [])
                        setattr(item, 'release_year', meta[2] if meta[2] else year)
                return
            
            params = {"api_key": TMDB_API_KEY, "query": series_name}
            if year:
                params["first_air_date_year"] = year

            search_url = f"{TMDB_API_URL}/search/tv"
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()

            imdb_rating = None
            genres = []
            release_year = year
            
            # Find the best matching series
            best_match = None
            best_score = -1
            
            for result in data.get("results", []):
                result_name = result.get("name", "")
                result_year = result.get("first_air_date", "")[:4] if result.get("first_air_date") else None
                
                # Calculate match score
                score = 0
                
                # Name match (case insensitive)
                if result_name.lower() == series_name.lower():
                    score += 100
                elif series_name.lower() in result_name.lower():
                    score += 50
                
                # Year match
                if year and result_year and year == result_year:
                    score += 100
                
                # Update best match
                if score > best_score:
                    best_score = score
                    best_match = result
            
            if best_match:
                imdb_rating = best_match.get("vote_average", None)
                if "genre_ids" in best_match:
                    genres = [str(gid) for gid in best_match["genre_ids"]]
                release_year = best_match.get("first_air_date", "")[:4] if best_match.get("first_air_date") else year
            
            genre_map = {
                28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
                18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
                9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller",
                10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
                10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
            }
            genres_named = [genre_map.get(int(gid), "") for gid in genres if gid]
            genres_named = [g for g in genres_named if g]

            setattr(item, 'imdb_rating', imdb_rating)
            setattr(item, 'genres', genres_named)
            setattr(item, 'release_year', release_year)
            
            os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
            with open(meta_path, 'w', encoding='utf-8') as f:
                f.write(f"{imdb_rating}|{','.join(genres_named)}|{release_year}")
                
        except Exception as e:
            logging.error(f"Error loading metadata for {series_path}: {str(e)}")

    def create_series_placeholder(self, series_name):
        pixmap = QPixmap(150, 225)
        pixmap.fill(QColor(20, 20, 20))
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        gradient = QLinearGradient(0, 0, 0, pixmap.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 150))
        gradient.setColorAt(1, QColor(0, 0, 0, 50))
        painter.fillRect(pixmap.rect(), gradient)
        
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(55, 30, 40, 165)
        painter.setBrush(QColor(140, 0, 0))
        painter.drawRect(65, 30, 20, 165)
        
        painter.setPen(QColor(255, 255, 255))
        font = QFont('Netflix Sans Bold', 10, QFont.Bold)
        font.setHintingPreference(QFont.PreferFullHinting)
        font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
        painter.setFont(font)
        # Enable text antialiasing for crisp rendering
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        rect = pixmap.rect().adjusted(10, 180, -10, -10)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, series_name)
        
        painter.end()
        return pixmap

    def find_series_poster(self, folder_path):
        poster_names = ["poster.jpg", "folder.jpg", "cover.jpg"]
        for name in poster_names:
            path = os.path.join(folder_path, name)
            if os.path.exists(path):
                return path
        
        try:
            series_name = os.path.basename(folder_path)
            year = extract_year(series_name)
            
            params = {"api_key": TMDB_API_KEY, "query": series_name}
            if year:
                params["first_air_date_year"] = year
                
            search_url = f"{TMDB_API_URL}/search/tv"
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            best_match = None
            best_score = -1
            
            for result in data.get("results", []):
                result_name = result.get("name", "")
                result_year = result.get("first_air_date", "")[:4] if result.get("first_air_date") else None
                
                # Calculate match score
                score = 0
                
                # Name match (case insensitive)
                if result_name.lower() == series_name.lower():
                    score += 100
                elif series_name.lower() in result_name.lower():
                    score += 50
                
                # Year match
                if year and result_year and year == result_year:
                    score += 100
                
                # Update best match
                if score > best_score:
                    best_score = score
                    best_match = result
            
            if best_match and best_match.get("poster_path"):
                poster_path = best_match.get("poster_path")
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                image_data = requests.get(image_url).content
                poster_path = os.path.join(folder_path, "poster.jpg")
                with open(poster_path, "wb") as f:
                    f.write(image_data)
                return poster_path
        except Exception as e:
            logging.error(f"Error finding poster for {folder_path}: {str(e)}")
        return None

    def show_series_window(self):
        self.previous_view_stack.append(("series_list", None))
        self.populate_series_list()
        self.stacked_widget.setCurrentIndex(2)

    def show_series_episodes(self, item):
        self.previous_view_stack.append(("episodes", None))
        series_path = item.data(Qt.UserRole)
        if not series_path:
            return

        # Clear previous content
        for i in reversed(range(self.episodes_layout.count())):
            widget = self.episodes_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # Back button
        back_button = QPushButton("Back")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))
        self.episodes_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Banner with backdrop from TMDB or fallback to poster - cached version
        backdrop_used = False
        series_name = item.text()
        backdrop_data = self.get_tmdb_series_backdrop(series_name)
        
        if backdrop_data:
            backdrop_path = backdrop_data.get("backdrop_path")
            if backdrop_path:
                # Create banner label placeholder
                banner_label = QLabel()
                banner_label.setFixedHeight(300)
                banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                banner_label.setStyleSheet("""
                    QLabel {
                        border-radius: 8px;
                        background-color: #222;
                        color: #666;
                        font-size: 48px;
                        text-align: center;
                    }
                """)
                banner_label.setAlignment(Qt.AlignCenter)
                banner_label.setText("📺")  # Placeholder while loading
                self.episodes_layout.addWidget(banner_label)
                
                # Load backdrop asynchronously with caching
                self.load_backdrop_async(banner_label, backdrop_path, "📺", series_name)
                backdrop_used = True
        
        # Fallback to cached backdrop search or proper no-backdrop message if backdrop failed
        if not backdrop_used:
            banner_label = QLabel()
            banner_label.setFixedHeight(300)  # Same height as backdrop banner
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            
            # Try to find cached backdrop for this series
            cached_backdrop_found = False
            try:
                safe_title = "".join(c for c in series_name if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
                
                # Try different cache filename formats
                possible_cache_names = [
                    f"series_{safe_title}_Unknown.jpg".replace(' ', '_'),
                    f"tv_{safe_title}_Unknown.jpg".replace(' ', '_'),
                    f"series_{safe_title}_no_year.jpg".replace(' ', '_'),
                    f"tv_{safe_title}_no_year.jpg".replace(' ', '_'),
                ]
                
                for cache_name in possible_cache_names:
                    cache_path = os.path.join(BACKDROP_CACHE_DIR, cache_name)
                    if os.path.exists(cache_path):
                        cached_pixmap = QPixmap(cache_path)
                        if not cached_pixmap.isNull():
                            # Create proper banner with cached backdrop
                            banner = self.create_poster_banner(cached_pixmap, width=900, height=300)
                            banner_label.setPixmap(banner)
                            cached_backdrop_found = True
                            break
                
            except Exception as e:
                logging.error(f"Error loading cached backdrop for {series_name}: {str(e)}")
            
            if not cached_backdrop_found:
                # Show proper "no backdrop available" message instead of stretched poster
                banner_label.setText("📺\n\nNo Backdrop Available\nBackdrops will load when online")
                banner_label.setStyleSheet("""
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #1a1a1a, stop:1 #2a2a2a);
                    border-radius: 8px;
                    border: 2px dashed #444;
                    text-align: center;
                    color: #888;
                    font-size: 16px;
                    font-family: 'Netflix Sans', 'Arial', sans-serif;
                    padding: 20px;
                    line-height: 1.4;
                """)
                banner_label.setAlignment(Qt.AlignCenter)
                banner_label.setWordWrap(True)
            
            self.episodes_layout.addWidget(banner_label)

        # Series info
        info_widget = QWidget()
        info_layout = QVBoxLayout(info_widget)
        info_layout.setContentsMargins(10, 0, 10, 0)
        title_label = QLabel(item.text())
        title_label.setStyleSheet("""
            font-size: 22px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        info_layout.addWidget(title_label)
        
        synopsis, imdb_rating, genres, year = self.get_series_synopsis(series_path, return_meta=True)
        meta_parts = []
        if year:
            meta_parts.append(str(year))
        if genres:
            meta_parts.append(", ".join(genres))
        if imdb_rating:
            meta_parts.append(f"IMDb: ★ {imdb_rating:.1f}")
        metadata_label = QLabel(" • ".join(meta_parts))
        metadata_label.setStyleSheet("font-size: 14px; color: #AAAAAA;")
        info_layout.addWidget(metadata_label)
        synopsis_label = QLabel(synopsis if synopsis else "Synopsis not available")
        synopsis_label.setWordWrap(True)
        synopsis_label.setStyleSheet("font-size: 13px; color: #AAAAAA;")
        info_layout.addWidget(synopsis_label)
        self.episodes_layout.addWidget(info_widget)

        # Seasons navigation
        seasons = self.get_seasons_list(series_path)
        if seasons:
            seasons_widget = QWidget()
            seasons_layout = QHBoxLayout(seasons_widget)
            seasons_layout.setContentsMargins(0, 10, 0, 10)
            seasons_layout.setSpacing(10)
            
            seasons_label = QLabel("Seasons:")
            seasons_label.setStyleSheet("font-size: 16px; color: white;")
            seasons_layout.addWidget(seasons_label)
            
            # Sort seasons naturally (Season 1, Season 2, etc.)
            seasons_sorted = sorted(seasons, key=lambda x: int(re.search(r'\d+', x).group()) if re.search(r'\d+', x) else 0)
            
            for season in seasons_sorted:
                btn = QPushButton(season)
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #2D2D2D;
                        color: white;
                        border: none;
                        padding: 5px 10px;
                        border-radius: 4px;
                        min-width: 80px;
                    }
                    QPushButton:hover {
                        background-color: #3D3D3D;
                    }
                    QPushButton:pressed {
                        background-color: #E50914;
                    }
                """)
                btn.clicked.connect(lambda checked, s=season: self.show_season_episodes(series_path, s))
                seasons_layout.addWidget(btn)
            
            seasons_layout.addStretch()
            self.episodes_layout.addWidget(seasons_widget)

        # Episodes list title
        episodes_title = QLabel("Episodes")
        episodes_title.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-top: 10px;
        """)
        self.episodes_layout.addWidget(episodes_title)

        # Scrollable episodes list
        episodes_scroll = QScrollArea()
        episodes_scroll.setWidgetResizable(True)
        episodes_scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background: transparent;
            }
        """)
        episodes_container = QWidget()
        episodes_list_layout = QVBoxLayout(episodes_container)
        episodes_list_layout.setContentsMargins(0, 0, 0, 0)
        episodes_list_layout.setSpacing(10)

        # Show all episodes by default, or filter by season if selected
        displayed_episodes = set()  # Track displayed episodes to prevent duplicates
        
        for root, _, files in os.walk(series_path):
            if self.current_season and os.path.basename(root) != self.current_season:
                continue
                
            for file in sorted(files):
                if any(file.lower().endswith(ext) for ext in media_extensions):
                    file_path = os.path.join(root, file)
                    
                    # Create episode identifier to prevent duplicates
                    season_ep = self.extract_season_episode(file)
                    if season_ep:
                        season, episode = season_ep
                        episode_id = f"S{season:02d}E{episode:02d}"
                        
                        # Skip if this episode is already displayed
                        if episode_id in displayed_episodes:
                            logging.warning(f"Duplicate episode detected and skipped: {file}")
                            continue
                            
                        displayed_episodes.add(episode_id)
                    else:
                        # For episodes without clear S##E## format, use filename as identifier
                        file_id = os.path.splitext(file)[0].lower()
                        if file_id in displayed_episodes:
                            logging.warning(f"Duplicate episode detected and skipped: {file}")
                            continue
                        displayed_episodes.add(file_id)
                    
                    episode_item = ImageItem(file_path)
                    
                    episode_widget = QWidget()
                    ep_layout = QHBoxLayout(episode_widget)
                    ep_layout.setContentsMargins(8, 4, 8, 4)
                    ep_layout.setSpacing(10)
                    
                    icon_label = QLabel()
                    icon_label.setPixmap(episode_item.icon().pixmap(40, 60))
                    icon_label.setFixedSize(40, 60)
                    ep_layout.addWidget(icon_label)
                    
                    info_layout = QVBoxLayout()
                    info_layout.setSpacing(2)
                    
                    if season_ep:
                        season, episode = season_ep
                        ep_num_label = QLabel(f"S{season:02d}E{episode:02d}")
                        ep_num_label.setStyleSheet("font-size: 12px; color: #AAAAAA;")
                        info_layout.addWidget(ep_num_label)
                    
                    text_label = QLabel(episode_item.text())
                    text_label.setStyleSheet("font-size: 14px; color: white;")
                    info_layout.addWidget(text_label)
                    
                    ep_layout.addLayout(info_layout)
                    ep_layout.addStretch()
                    
                    episode_widget.setStyleSheet("""
                        background-color: #232323;
                        border-radius: 6px;
                    """)
                    episode_widget.mousePressEvent = lambda e, ep=episode_item, sp=series_path: self.show_episode_details(ep, parent_series_path=sp)
                    
                    # Add context menu for episodes
                    episode_widget.setContextMenuPolicy(Qt.CustomContextMenu)
                    episode_widget.customContextMenuRequested.connect(lambda pos, ep=episode_item: self.show_episode_context_menu(pos, ep, episode_widget))
                    
                    episodes_list_layout.addWidget(episode_widget)

        episodes_list_layout.addStretch()
        episodes_scroll.setWidget(episodes_container)
        self.episodes_layout.addWidget(episodes_scroll, 1)
        self.stacked_widget.setCurrentIndex(3)
        
    def show_season_episodes(self, series_path, season):
        self.current_season = season
        temp_item = QListWidgetItem(season)
        temp_item.setData(Qt.UserRole, series_path)
        self.show_series_episodes(temp_item)

    def get_seasons_list(self, series_path):
        seasons = []
        if os.path.exists(series_path):
            for item in os.listdir(series_path):
                item_path = os.path.join(series_path, item)
                if os.path.isdir(item_path) and item.lower().startswith("season"):
                    seasons.append(item)
        return seasons

    def get_series_synopsis(self, series_path, return_meta=False):
        try:
            series_name = os.path.basename(series_path)
            year = extract_year(series_name)
            
            cache_name = f"{series_name}"
            if year:
                cache_name += f" {year}"
            cache_file = f"{quote(cache_name)}.txt"
            cache_path = os.path.join(SYNOPSIS_CACHE_DIR, cache_file)
            meta_file = cache_file.replace('.txt', '_meta.txt')
            meta_path = os.path.join(SYNOPSIS_CACHE_DIR, meta_file)
            
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    overview = f.read()
                imdb_rating = None
                genres = []
                result_year = year
                if os.path.exists(meta_path):
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = f.read().split('|')
                        if len(meta) == 3:
                            imdb_rating = float(meta[0]) if meta[0] != "None" else None
                            genres = meta[1].split(',') if meta[1] else []
                            result_year = meta[2] if meta[2] else year
                if return_meta:
                    return overview, imdb_rating, genres, result_year
                return overview
            
            params = {"api_key": TMDB_API_KEY, "query": series_name}
            if year:
                params["first_air_date_year"] = year

            search_url = f"{TMDB_API_URL}/search/tv"
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()

            overview = ""
            imdb_rating = None
            genres = []
            result_year = year
            
            # Find the best matching series
            best_match = None
            best_score = -1
            
            for result in data.get("results", []):
                result_name = result.get("name", "")
                result_year = result.get("first_air_date", "")[:4] if result.get("first_air_date") else None
                
                # Calculate match score
                score = 0
                
                # Name match (case insensitive)
                if result_name.lower() == series_name.lower():
                    score += 100
                elif series_name.lower() in result_name.lower():
                    score += 50
                
                # Year match
                if year and result_year and year == result_year:
                    score += 100
                
                # Update best match
                if score > best_score:
                    best_score = score
                    best_match = result
            
            if best_match:
                overview = best_match.get("overview", "")
                imdb_rating = best_match.get("vote_average", None)
                if "genre_ids" in best_match:
                    genres = [str(gid) for gid in best_match["genre_ids"]]
                result_year = best_match.get("first_air_date", "")[:4] if best_match.get("first_air_date") else year
            
            genre_map = {
                28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
                18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
                9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller",
                10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
                10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
            }
            genres_named = [genre_map.get(int(gid), "") for gid in genres if gid]
            genres_named = [g for g in genres_named if g]
            
            if overview:
                os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(overview)
                with open(meta_path, 'w', encoding='utf-8') as f:
                    f.write(f"{imdb_rating}|{','.join(genres_named)}|{result_year}")
            if return_meta:
                return overview, imdb_rating, genres_named, result_year
            return overview
        except Exception as e:
            logging.error(f"Error getting synopsis for {series_path}: {str(e)}")
        if return_meta:
            return None, None, [], None
        return None

    def get_tmdb_movie_backdrop(self, movie_title):
        """Get TMDB backdrop data for a movie"""
        try:
            # Extract year from title if possible
            year_match = re.search(r'(19|20)\d{2}', movie_title)
            year = year_match.group() if year_match else None
            
            # Clean movie title
            clean_title = re.sub(r'(19|20)\d{2}', '', movie_title).strip()
            clean_title = re.sub(r'[^\w\s]', ' ', clean_title).strip()
            
            params = {"api_key": TMDB_API_KEY, "query": clean_title}
            if year:
                params["year"] = year
            
            search_url = f"{TMDB_API_URL}/search/movie"
            response = requests.get(search_url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            # Find the best matching movie
            best_match = None
            best_score = -1
            
            for result in data.get("results", []):
                result_title = result.get("title", "")
                result_year = result.get("release_date", "")[:4] if result.get("release_date") else None
                
                # Calculate match score
                score = 0
                
                # Title match (case insensitive)
                if result_title.lower() == clean_title.lower():
                    score += 100
                elif clean_title.lower() in result_title.lower() or result_title.lower() in clean_title.lower():
                    score += 50
                
                # Year match
                if year and result_year and year == result_year:
                    score += 100
                elif year and result_year and abs(int(year) - int(result_year)) <= 1:
                    score += 50  # Close year match
                
                # Prefer results with backdrop
                if result.get("backdrop_path"):
                    score += 25
                
                # Update best match
                if score > best_score:
                    best_score = score
                    best_match = result
            
            return best_match
            
        except Exception as e:
            logging.error(f"Error getting TMDB backdrop for {movie_title}: {str(e)}")
            return None

    def get_tmdb_series_backdrop(self, series_name):
        """Get TMDB backdrop data for a TV series"""
        try:
            # Extract year from series name if possible
            year_match = re.search(r'(19|20)\d{2}', series_name)
            year = year_match.group() if year_match else None
            
            # Clean series name
            clean_name = re.sub(r'(19|20)\d{2}', '', series_name).strip()
            clean_name = re.sub(r'[^\w\s]', ' ', clean_name).strip()
            
            params = {"api_key": TMDB_API_KEY, "query": clean_name}
            if year:
                params["first_air_date_year"] = year
            
            search_url = f"{TMDB_API_URL}/search/tv"
            response = requests.get(search_url, params=params, timeout=5)
            response.raise_for_status()
            data = response.json()
            
            # Find the best matching series
            best_match = None
            best_score = -1
            
            for result in data.get("results", []):
                result_name = result.get("name", "")
                result_year = result.get("first_air_date", "")[:4] if result.get("first_air_date") else None
                
                # Calculate match score
                score = 0
                
                # Name match (case insensitive)
                if result_name.lower() == clean_name.lower():
                    score += 100
                elif clean_name.lower() in result_name.lower() or result_name.lower() in clean_name.lower():
                    score += 50
                
                # Year match
                if year and result_year and year == result_year:
                    score += 100
                elif year and result_year and abs(int(year) - int(result_year)) <= 1:
                    score += 50  # Close year match
                
                # Prefer results with backdrop
                if result.get("backdrop_path"):
                    score += 25
                
                # Update best match
                if score > best_score:
                    best_score = score
                    best_match = result
            
            return best_match
            
        except Exception as e:
            logging.error(f"Error getting TMDB backdrop for {series_name}: {str(e)}")
            return None

    def create_poster_banner(self, pixmap, width=900, height=3080):
        """Create a Netflix-style banner from backdrop image - standard scaling approach"""
        if pixmap.isNull():
            banner = QPixmap(width, height)
            banner.fill(QColor(20, 20, 20))
            return banner
        
        # Create banner with exact dimensions
        banner = QPixmap(width, height)
        banner.fill(Qt.black)
        
        painter = QPainter(banner)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # Scale image to fill the entire banner (may crop edges but fills completely)
        scaled = pixmap.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        
        # Always align the top of the image with the top of the banner (touches title bar)
        x = (width - scaled.width()) // 2
        if scaled.height() > height:
            y = 0  # Top of image flush with top of banner
        else:
            y = 0  # If image is shorter, still align to top

        painter.drawPixmap(x, y, scaled)
        
        # Add subtle gradient overlay for text readability (lighter than before)
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QColor(0, 0, 0, 0))        # Transparent at top
        gradient.setColorAt(0.6, QColor(0, 0, 0, 50))     # Very light overlay
        gradient.setColorAt(0.9, QColor(20, 20, 20, 120)) # Darker at bottom for text
        gradient.setColorAt(1, QColor(20, 20, 20, 160))   # Bottom edge for text contrast
        painter.fillRect(banner.rect(), gradient)
        
        painter.end()
        return banner


    def show_movie_details(self, item):
        # Movie details view (for movies tab)
        for i in reversed(range(self.details_layout.count())):
            widget = self.details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        back_button = QPushButton("Back")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))  # Go back to movies view
        self.details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Try to get TMDB backdrop for better banner
        backdrop_used = False
        movie_title = self.extract_movie_title(item.text())
        backdrop_data = self.get_tmdb_movie_backdrop(movie_title)
        if backdrop_data:
            backdrop_path = backdrop_data.get("backdrop_path")
            if backdrop_path:
                banner_label = QLabel()
                banner_label.setFixedHeight(300)
                banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                banner_label.setStyleSheet("""
                    QLabel {
                        border-radius: 8px;
                        background-color: #222;
                        color: #666;
                        font-size: 48px;
                        text-align: center;
                    }
                """)
                banner_label.setAlignment(Qt.AlignCenter)
                banner_label.setText("🎬")
                self.details_layout.addWidget(banner_label)
                self.load_backdrop_async(banner_label, backdrop_path, "🎬", movie_title)
                backdrop_used = True

        if not backdrop_used:
            banner_label = QLabel()
            banner_label.setFixedHeight(300)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cached_backdrop_found = False
            try:
                safe_title = "".join(c for c in movie_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
                year = extract_year(item.text())
                possible_cache_names = [
                    f"movie_{safe_title}_{year}.jpg".replace(' ', '_') if year else None,
                    f"movie_{safe_title}_no_year.jpg".replace(' ', '_'),
                    f"movie_{safe_title}_Unknown.jpg".replace(' ', '_'),
                ]
                for cache_name in possible_cache_names:
                    if cache_name is None:
                        continue
                    cache_path = os.path.join(BACKDROP_CACHE_DIR, cache_name)
                    if os.path.exists(cache_path):
                        cached_pixmap = QPixmap(cache_path)
                        if not cached_pixmap.isNull():
                            banner = self.create_poster_banner(cached_pixmap, width=900, height=300)
                            banner_label.setPixmap(banner)
                            cached_backdrop_found = True
                            break
            except Exception as e:
                logging.error(f"Error loading cached backdrop for {movie_title}: {str(e)}")
            if not cached_backdrop_found:
                banner_label.setText("🎬\n\nNo Backdrop Available\nBackdrops will load when online")
                banner_label.setStyleSheet("""
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #1a1a1a, stop:1 #2a2a2a);
                    border-radius: 8px;
                    border: 2px dashed #444;
                    text-align: center;
                    color: #888;
                    font-size: 16px;
                    font-family: 'Netflix Sans', 'Arial', sans-serif;
                    padding: 20px;
                    line-height: 1.4;
                """)
                banner_label.setAlignment(Qt.AlignCenter)
                banner_label.setWordWrap(True)
            self.details_layout.addWidget(banner_label)

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        title_label = QLabel(item.text())
        title_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        details_layout.addWidget(title_label)
        meta_parts = []
        if getattr(item, "release_year", None):
            meta_parts.append(str(item.release_year))
        if getattr(item, "genres", None):
            meta_parts.append(", ".join(item.genres))
        if getattr(item, "imdb_rating", None):
            meta_parts.append(f"IMDb: ★ {item.imdb_rating:.1f}")
        metadata_label = QLabel(" • ".join(meta_parts))
        metadata_label.setStyleSheet("""
            font-size: 16px; 
            color: #AAAAAA; 
            margin-bottom: 20px;
            font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
        """)
        details_layout.addWidget(metadata_label)
        synopsis_label = QLabel("Synopsis")
        synopsis_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 5px;
        """)
        details_layout.addWidget(synopsis_label)
        synopsis_text = QTextEdit()
        synopsis_text.setPlainText(item.synopsis if hasattr(item, 'synopsis') and item.synopsis else "Synopsis not available")
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
        """)
        synopsis_text.setFixedHeight(150)
        details_layout.addWidget(synopsis_text)
        play_button = QPushButton("Play")
        play_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 18px;
                border-radius: 4px;
                margin-top: 20px;
                max-width: 150px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        play_button.clicked.connect(lambda: self.play_media(item))
        details_layout.addWidget(play_button)
        details_layout.addStretch()
        self.details_layout.addWidget(details_widget)
        self.stacked_widget.setCurrentIndex(4)

    def show_series_details(self, item, parent_series_path=None):
        # Series details view (for series tab)
        for i in reversed(range(self.details_layout.count())):
            widget = self.details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        back_button = QPushButton("Back")
        back_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                max-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        if parent_series_path:
            back_button.clicked.connect(lambda: self.show_series_episodes(self._make_series_item(parent_series_path)))
        else:
            back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(2))
        self.details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

    def _make_series_item(self, series_path):
        item = QListWidgetItem(os.path.basename(series_path))
        item.setData(Qt.UserRole, series_path)
        return item

        # Try to get TMDB backdrop for better banner (series)
        backdrop_used = False
        series_title = item.text()
        backdrop_data = self.get_tmdb_series_backdrop(series_title)
        if backdrop_data:
            backdrop_path = backdrop_data.get("backdrop_path")
            if backdrop_path:
                banner_label = QLabel()
                banner_label.setFixedHeight(300)
                banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                banner_label.setStyleSheet("""
                    QLabel {
                        border-radius: 8px;
                        background-color: #222;
                        color: #666;
                        font-size: 48px;
                        text-align: center;
                    }
                """)
                banner_label.setAlignment(Qt.AlignCenter)
                banner_label.setText("🎬")
                self.details_layout.addWidget(banner_label)
                self.load_backdrop_async(banner_label, backdrop_path, "🎬", series_title)
                backdrop_used = True

        if not backdrop_used:
            banner_label = QLabel()
            banner_label.setFixedHeight(300)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cached_backdrop_found = False
            try:
                safe_title = "".join(c for c in series_title if c.isalnum() or c in (' ', '-', '_')).rstrip()[:50]
                year = extract_year(series_title)
                possible_cache_names = [
                    f"series_{safe_title}_{year}.jpg".replace(' ', '_') if year else None,
                    f"series_{safe_title}_no_year.jpg".replace(' ', '_'),
                    f"series_{safe_title}_Unknown.jpg".replace(' ', '_'),
                ]
                for cache_name in possible_cache_names:
                    if cache_name is None:
                        continue
                    cache_path = os.path.join(BACKDROP_CACHE_DIR, cache_name)
                    if os.path.exists(cache_path):
                        cached_pixmap = QPixmap(cache_path)
                        if not cached_pixmap.isNull():
                            banner = self.create_poster_banner(cached_pixmap, width=900, height=300)
                            banner_label.setPixmap(banner)
                            cached_backdrop_found = True
                            break
            except Exception as e:
                logging.error(f"Error loading cached backdrop for {series_title}: {str(e)}")
            if not cached_backdrop_found:
                banner_label.setText("🎬\n\nNo Backdrop Available\nBackdrops will load when online")
                banner_label.setStyleSheet("""
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                        stop:0 #1a1a1a, stop:1 #2a2a2a);
                    border-radius: 8px;
                    border: 2px dashed #444;
                    text-align: center;
                    color: #888;
                    font-size: 16px;
                    font-family: 'Netflix Sans', 'Arial', sans-serif;
                    padding: 20px;
                    line-height: 1.4;
                """)
                banner_label.setAlignment(Qt.AlignCenter)
                banner_label.setWordWrap(True)
            self.details_layout.addWidget(banner_label)

        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        title_label = QLabel(series_title)
        title_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        details_layout.addWidget(title_label)
        meta_parts = []
        if getattr(item, "release_year", None):
            meta_parts.append(str(item.release_year))
        if getattr(item, "genres", None):
            meta_parts.append(", ".join(item.genres))
        if getattr(item, "imdb_rating", None):
            meta_parts.append(f"IMDb: ★ {item.imdb_rating:.1f}")
        metadata_label = QLabel(" • ".join(meta_parts))
        metadata_label.setStyleSheet("""
            font-size: 16px; 
            color: #AAAAAA; 
            margin-bottom: 20px;
            font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
        """)
        details_layout.addWidget(metadata_label)
        synopsis_label = QLabel("Synopsis")
        synopsis_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 5px;
        """)
        details_layout.addWidget(synopsis_label)
        synopsis_text = QTextEdit()
        synopsis_text.setPlainText(item.synopsis if hasattr(item, 'synopsis') and item.synopsis else "Synopsis not available")
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
        """)
        synopsis_text.setFixedHeight(150)
        details_layout.addWidget(synopsis_text)
        play_button = QPushButton("Play")
        play_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 18px;
                border-radius: 4px;
                margin-top: 20px;
                max-width: 150px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        play_button.clicked.connect(lambda: self.play_media(item))
        details_layout.addWidget(play_button)
        details_layout.addStretch()
        self.details_layout.addWidget(details_widget)
        self.stacked_widget.setCurrentIndex(4)

    def extract_season_episode(self, filename):
        match = re.search(r'[Ss](\d+)[Ee](\d+)', filename, re.IGNORECASE)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None

    def update_media_lists(self):
        """Synchronous version for immediate loading"""
        self.movies_list.clear()
        
        # Use a set to track processed files and avoid duplicates
        processed_files = set()
        
        if os.path.exists(movies_folder):
            for root, _, files in os.walk(movies_folder):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        file_path = os.path.join(root, file)
                        
                        # Create a normalized identifier to detect duplicates
                        normalized_path = os.path.normpath(file_path).lower()
                        
                        # Skip if already processed
                        if normalized_path in processed_files:
                            logging.warning(f"Duplicate movie detected and skipped: {file_path}")
                            continue
                            
                        processed_files.add(normalized_path)
                        item = ImageItem(file_path)
                        self.movies_list.addItem(item)
        
        self.media_lists_loaded = True

    def update_media_lists_async(self):
        """Asynchronous version with loading indicator"""
        if self.media_lists_loaded or self.media_loading_in_progress:
            return
            
        # Set flag to prevent duplicate calls
        self.media_loading_in_progress = True
            
        # Clear existing movies list to prevent duplicates
        self.movies_list.clear()
            
        # Show loading indicator in movies tab
        self.show_loading_in_movies_tab()
        
        # Use QTimer to process in chunks to keep UI responsive
        self.media_files = []
        self.current_file_index = 0
        
        # Use a set to track processed files and avoid duplicates
        processed_files = set()
        
        # Collect all media files first
        if os.path.exists(movies_folder):
            for root, _, files in os.walk(movies_folder):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        file_path = os.path.join(root, file)
                        
                        # Create a normalized identifier to detect duplicates
                        normalized_path = os.path.normpath(file_path).lower()
                        
                        # Skip if already processed
                        if normalized_path in processed_files:
                            logging.warning(f"Duplicate movie detected and skipped: {file_path}")
                            continue
                            
                        processed_files.add(normalized_path)
                        self.media_files.append(file_path)
        
        # Process files in batches
        self.process_media_batch()

    def process_media_batch(self):
        """Process media files in small batches to keep UI responsive"""
        batch_size = 5  # Process 5 files at a time
        end_index = min(self.current_file_index + batch_size, len(self.media_files))
        
        for i in range(self.current_file_index, end_index):
            file_path = self.media_files[i]
            item = ImageItem(file_path)
            self.movies_list.addItem(item)
        
        self.current_file_index = end_index
        
        # Update progress if we have a progress indicator
        if hasattr(self, 'loading_progress'):
            progress = int((self.current_file_index / len(self.media_files)) * 100)
            self.loading_progress.setValue(progress)
        
        # Continue processing if there are more files
        if self.current_file_index < len(self.media_files):
            QTimer.singleShot(50, self.process_media_batch)  # Small delay to keep UI responsive
        else:
            # Finished loading
            self.media_lists_loaded = True
            self.media_loading_in_progress = False  # Reset flag
            self.hide_loading_in_movies_tab()

    def show_loading_in_movies_tab(self):
        """Show loading indicator in movies tab"""
        if hasattr(self, 'movies_loading_widget'):
            return  # Already showing
            
        from PyQt5.QtWidgets import QProgressBar
        
        # Create loading widget
        self.movies_loading_widget = QWidget()
        loading_layout = QVBoxLayout(self.movies_loading_widget)
        loading_layout.setContentsMargins(50, 100, 50, 100)
        loading_layout.setSpacing(20)
        
        # Loading label
        loading_label = QLabel("Loading Your Movies...")
        loading_label.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        loading_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(loading_label)
        
        # Progress bar
        self.loading_progress = QProgressBar()
        self.loading_progress.setStyleSheet("""
            QProgressBar {
                border: 2px solid #333333;
                border-radius: 10px;
                background-color: #222222;
                height: 20px;
                text-align: center;
                color: white;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #E50914;
                border-radius: 8px;
            }
        """)
        self.loading_progress.setMaximum(100)
        self.loading_progress.setValue(0)
        loading_layout.addWidget(self.loading_progress)
        
        # Sub message
        sub_label = QLabel("Please wait while we scan your movie collection...")
        sub_label.setStyleSheet("""
            font-size: 16px; 
            color: #AAAAAA;
            font-family: 'Netflix Sans', 'Arial', sans-serif;
        """)
        sub_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(sub_label)
        
        loading_layout.addStretch()
        
        # Add to movies view temporarily
        if hasattr(self, 'movies_view') and self.movies_view.widget():
            main_layout = self.movies_view.widget().layout()
            main_layout.addWidget(self.movies_loading_widget)

    def hide_loading_in_movies_tab(self):
        """Hide loading indicator in movies tab"""
        if hasattr(self, 'movies_loading_widget'):
            self.movies_loading_widget.setParent(None)
            delattr(self, 'movies_loading_widget')
            delattr(self, 'loading_progress')

    def show_sort_confirmation(self):
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText("This will scan your downloads folders and organize media files.")
        msg.setInformativeText("Do you want to continue?")
        msg.setWindowTitle("Confirm File Sorting")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #141414;
            }
            QMessageBox QLabel {
                color: white;
            }
            QMessageBox QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                min-width: 80px;
            }
            QMessageBox QPushButton:hover {
                background-color: #F40612;
            }
        """)
        
        ret = msg.exec_()
        if ret == QMessageBox.Yes:
            self.sort_files()
    
    def find_and_remove_duplicates(self):
        """Find and optionally remove duplicate movies and series"""
        duplicates_found = []
        
        try:
            # Find movie duplicates
            movie_duplicates = self.find_movie_duplicates()
            if movie_duplicates:
                duplicates_found.extend(movie_duplicates)
            
            # Find series duplicates
            series_duplicates = self.find_series_duplicates()
            if series_duplicates:
                duplicates_found.extend(series_duplicates)
            
            if duplicates_found:
                # Show duplicates dialog
                self.show_duplicates_dialog(duplicates_found)
            else:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Information)
                msg.setText("No duplicates found in your media library!")
                msg.setWindowTitle("Duplicate Check Complete")
                msg.setStyleSheet("""
                    QMessageBox {
                        background-color: #141414;
                    }
                    QMessageBox QLabel {
                        color: white;
                    }
                    QMessageBox QPushButton {
                        background-color: #E50914;
                        color: white;
                        border: none;
                        padding: 8px 16px;
                        font-size: 14px;
                        border-radius: 4px;
                    }
                """)
                msg.exec_()
                
        except Exception as e:
            logging.error(f"Error finding duplicates: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error while checking for duplicates:\n{str(e)}")
    
    def find_movie_duplicates(self):
        """Find duplicate movies based on title similarity and file size"""
        duplicates = []
        processed_files = set()
        
        if not os.path.exists(movies_folder):
            return duplicates
        
        movie_files = []
        for root, _, files in os.walk(movies_folder):
            for file in files:
                if any(file.lower().endswith(ext) for ext in media_extensions):
                    file_path = os.path.join(root, file)
                    movie_files.append(file_path)
        
        # Compare each movie with every other movie
        for i, file1 in enumerate(movie_files):
            if file1 in processed_files:
                continue
                
            title1 = self.extract_movie_title(os.path.basename(file1)).lower()
            try:
                size1 = os.path.getsize(file1)
            except OSError:
                continue  # Skip files we can't read
            
            duplicate_group = [file1]
            
            for j, file2 in enumerate(movie_files[i+1:], i+1):
                if file2 in processed_files:
                    continue
                    
                title2 = self.extract_movie_title(os.path.basename(file2)).lower()
                try:
                    size2 = os.path.getsize(file2)
                except OSError:
                    continue
                
                # Check if titles are similar
                if self.are_titles_similar(title1, title2):
                    # Check size difference (allow up to 30% difference for quality variations)
                    size_diff = abs(size1 - size2) / max(size1, size2)
                    if size_diff < 0.3:
                        duplicate_group.append(file2)
                        processed_files.add(file2)
            
            if len(duplicate_group) > 1:
                # Sort group by size (largest first) for better removal logic
                duplicate_group_with_info = []
                for file_path in duplicate_group:
                    try:
                        size = os.path.getsize(file_path)
                        mtime = os.path.getmtime(file_path)
                        duplicate_group_with_info.append((file_path, size, mtime))
                    except OSError:
                        duplicate_group_with_info.append((file_path, 0, 0))
                
                # Sort by size (largest first), then by modification time (newest first)
                duplicate_group_with_info.sort(key=lambda x: (x[1], x[2]), reverse=True)
                sorted_files = [info[0] for info in duplicate_group_with_info]
                
                duplicates.append({
                    'type': 'movie',
                    'title': title1,
                    'files': sorted_files
                })
                processed_files.update(duplicate_group)
        
        return duplicates
    
    def find_series_duplicates(self):
        """Find duplicate series based on name similarity"""
        duplicates = []
        
        if not os.path.exists(series_folder):
            return duplicates
        
        series_dirs = []
        for item in os.listdir(series_folder):
            series_path = os.path.join(series_folder, item)
            if os.path.isdir(series_path):
                series_dirs.append((item, series_path))
        
        processed_series = set()
        
        # Compare each series with every other series
        for i, (name1, path1) in enumerate(series_dirs):
            if name1 in processed_series:
                continue
                
            clean_name1 = name1.lower().strip()
            duplicate_group = [(name1, path1)]
            
            for j, (name2, path2) in enumerate(series_dirs[i+1:], i+1):
                if name2 in processed_series:
                    continue
                    
                clean_name2 = name2.lower().strip()
                
                # Check if series names are very similar
                if self.are_titles_similar(clean_name1, clean_name2, threshold=0.9):
                    duplicate_group.append((name2, path2))
                    processed_series.add(name2)
            
            if len(duplicate_group) > 1:
                duplicates.append({
                    'type': 'series',
                    'title': clean_name1,
                    'folders': duplicate_group
                })
                processed_series.update([name for name, _ in duplicate_group])
        
        return duplicates
    
    def show_duplicates_dialog(self, duplicates):
        """Show a dialog with found duplicates and options to remove them"""
        dialog = QDialog(self)
        dialog.setWindowTitle("Duplicate Media Found")
        dialog.setFixedSize(900, 700)
        dialog.setStyleSheet("""
            QDialog {
                background-color: #141414;
                color: white;
            }
        """)
        
        layout = QVBoxLayout(dialog)
        
        # Header
        header_label = QLabel(f"Found {len(duplicates)} duplicate groups:")
        header_label.setStyleSheet("""
            font-size: 18px; 
            font-weight: bold; 
            color: white;
            margin-bottom: 10px;
        """)
        layout.addWidget(header_label)
        
        # Options for handling duplicates
        options_widget = QWidget()
        options_layout = QHBoxLayout(options_widget)
        options_layout.setSpacing(15)
        
        self.duplicate_action = "keep_largest"  # Default action
        
        # Radio buttons for different actions
        keep_largest_radio = QRadioButton("Keep largest file (recommended)")
        keep_largest_radio.setChecked(True)
        keep_largest_radio.setStyleSheet("color: white; font-size: 14px;")
        keep_largest_radio.toggled.connect(lambda: setattr(self, 'duplicate_action', 'keep_largest'))
        options_layout.addWidget(keep_largest_radio)
        
        keep_newest_radio = QRadioButton("Keep newest file")
        keep_newest_radio.setStyleSheet("color: white; font-size: 14px;")
        keep_newest_radio.toggled.connect(lambda: setattr(self, 'duplicate_action', 'keep_newest'))
        options_layout.addWidget(keep_newest_radio)
        
        manual_review_radio = QRadioButton("Manual review only")
        manual_review_radio.setStyleSheet("color: white; font-size: 14px;")
        manual_review_radio.toggled.connect(lambda: setattr(self, 'duplicate_action', 'manual'))
        options_layout.addWidget(manual_review_radio)
        
        layout.addWidget(options_widget)
        
        # Scrollable list of duplicates with checkboxes
        scroll_area = QScrollArea()
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)
        
        self.duplicate_checkboxes = []  # Store checkboxes for each duplicate group
        
        for i, duplicate in enumerate(duplicates):
            group_widget = QWidget()
            group_widget.setStyleSheet("""
                QWidget {
                    background-color: #1A1A1A;
                    border-radius: 8px;
                    margin: 5px 0px;
                    padding: 10px;
                }
            """)
            group_layout = QVBoxLayout(group_widget)
            
            # Group header with checkbox
            header_widget = QWidget()
            header_layout = QHBoxLayout(header_widget)
            
            group_checkbox = QCheckBox()
            group_checkbox.setChecked(True)  # Check all by default
            group_checkbox.setStyleSheet("QCheckBox::indicator { width: 18px; height: 18px; }")
            header_layout.addWidget(group_checkbox)
            self.duplicate_checkboxes.append((group_checkbox, duplicate))
            
            if duplicate['type'] == 'movie':
                title_label = QLabel(f"🎬 Movie: {duplicate['title']}")
                header_layout.addWidget(title_label)
                header_layout.addStretch()
                group_layout.addWidget(header_widget)
                
                # Show file details
                for j, file_path in enumerate(duplicate['files']):
                    try:
                        file_size = os.path.getsize(file_path)
                        file_size_mb = file_size / (1024 * 1024)
                        file_time = os.path.getmtime(file_path)
                        file_date = time.strftime('%Y-%m-%d %H:%M', time.localtime(file_time))
                        
                        file_info = f"   📄 {os.path.basename(file_path)} ({file_size_mb:.1f}MB, {file_date})"
                        if j == 0:  # Mark the first (typically largest/newest) as what will be kept
                            file_info += " ✓ KEEP"
                            color = "#4CAF50"
                        else:
                            file_info += " ❌ REMOVE"
                            color = "#F44336"
                            
                        file_label = QLabel(file_info)
                        file_label.setStyleSheet(f"color: {color}; margin-left: 20px; font-size: 12px;")
                        group_layout.addWidget(file_label)
                    except OSError:
                        file_label = QLabel(f"   📄 {os.path.basename(file_path)} (Error reading file)")
                        file_label.setStyleSheet("color: #AAAAAA; margin-left: 20px; font-size: 12px;")
                        group_layout.addWidget(file_label)
            else:  # series
                title_label = QLabel(f"📺 Series: {duplicate['title']}")
                header_layout.addWidget(title_label)
                header_layout.addStretch()
                group_layout.addWidget(header_widget)
                
                for j, (name, path) in enumerate(duplicate['folders']):
                    folder_info = f"   📁 {name}"
                    if j == 0:
                        folder_info += " ✓ KEEP"
                        color = "#4CAF50"
                    else:
                        folder_info += " ❌ REMOVE"
                        color = "#F44336"
                        
                    folder_label = QLabel(folder_info)
                    folder_label.setStyleSheet(f"color: {color}; margin-left: 20px; font-size: 12px;")
                    group_layout.addWidget(folder_label)
            
            title_label.setStyleSheet("font-weight: bold; color: #E50914; font-size: 14px;")
            scroll_layout.addWidget(group_widget)
        
        scroll_area.setWidget(scroll_widget)
        scroll_area.setWidgetResizable(True)
        layout.addWidget(scroll_area)
        
        # Action buttons
        button_layout = QHBoxLayout()
        
        # Select/Deselect all
        select_all_btn = QPushButton("Select All")
        select_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #555555;
                padding: 8px 16px;
                font-size: 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
        """)
        select_all_btn.clicked.connect(lambda: self.toggle_all_duplicates(True))
        button_layout.addWidget(select_all_btn)
        
        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #555555;
                padding: 8px 16px;
                font-size: 12px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
            }
        """)
        deselect_all_btn.clicked.connect(lambda: self.toggle_all_duplicates(False))
        button_layout.addWidget(deselect_all_btn)
        
        button_layout.addStretch()
        
        # Main action buttons
        remove_btn = QPushButton("🗑️ Remove Selected Duplicates")
        remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 4px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        remove_btn.clicked.connect(lambda: self.remove_selected_duplicates(dialog))
        button_layout.addWidget(remove_btn)
        
        close_btn = QPushButton("Cancel")
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #666666;
                color: white;
                border: none;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #777777;
            }
        """)
        close_btn.clicked.connect(dialog.close)
        button_layout.addWidget(close_btn)
        
        layout.addLayout(button_layout)
        
        dialog.exec_()
    
    def toggle_all_duplicates(self, checked):
        """Toggle all duplicate checkboxes"""
        for checkbox, _ in self.duplicate_checkboxes:
            checkbox.setChecked(checked)
    
    def remove_selected_duplicates(self, dialog):
        """Remove selected duplicates based on user preferences"""
        if not hasattr(self, 'duplicate_checkboxes'):
            return
            
        selected_duplicates = []
        for checkbox, duplicate in self.duplicate_checkboxes:
            if checkbox.isChecked():
                selected_duplicates.append(duplicate)
        
        if not selected_duplicates:
            QMessageBox.information(dialog, "No Selection", "No duplicates selected for removal.")
            return
        
        # Confirm removal
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText(f"Are you sure you want to remove duplicates from {len(selected_duplicates)} groups?")
        msg.setInformativeText(f"Action: {self.duplicate_action.replace('_', ' ').title()}")
        msg.setWindowTitle("Confirm Duplicate Removal")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.No)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #141414;
            }
            QMessageBox QLabel {
                color: white;
            }
            QMessageBox QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        
        if msg.exec_() != QMessageBox.Yes:
            return
        
        # Process removals
        removed_count = 0
        errors = []
        
        for duplicate in selected_duplicates:
            try:
                if duplicate['type'] == 'movie':
                    removed = self.remove_duplicate_movies(duplicate)
                    removed_count += removed
                else:
                    removed = self.remove_duplicate_series(duplicate)
                    removed_count += removed
            except Exception as e:
                errors.append(f"Error processing {duplicate['title']}: {str(e)}")
        
        # Show results
        dialog.close()
        
        if errors:
            error_msg = QMessageBox()
            error_msg.setIcon(QMessageBox.Warning)
            error_msg.setText(f"Removed {removed_count} duplicates with some errors:")
            error_msg.setDetailedText("\n".join(errors))
            error_msg.setWindowTitle("Duplicate Removal Complete")
            error_msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                }
            """)
            error_msg.exec_()
        else:
            success_msg = QMessageBox()
            success_msg.setIcon(QMessageBox.Information)
            success_msg.setText(f"Successfully removed {removed_count} duplicate files!")
            success_msg.setWindowTitle("Duplicates Removed")
            success_msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                }
            """)
            success_msg.exec_()
        
        # Refresh the media lists
        self.update_media_lists()
        self.populate_series_list()
    
    def remove_duplicate_movies(self, duplicate):
        """Remove duplicate movie files, keeping the best one"""
        files = duplicate['files']
        if len(files) <= 1:
            return 0
        
        # Determine which file to keep based on user preference
        if self.duplicate_action == 'keep_largest':
            # Sort by file size (largest first)
            files_with_info = []
            for file_path in files:
                try:
                    size = os.path.getsize(file_path)
                    files_with_info.append((file_path, size, 0))
                except OSError:
                    files_with_info.append((file_path, 0, 0))  # If can't get size, put at end
            files_with_info.sort(key=lambda x: x[1], reverse=True)
            keep_file = files_with_info[0][0]
            remove_files = [info[0] for info in files_with_info[1:]]
        
        elif self.duplicate_action == 'keep_newest':
            # Sort by modification time (newest first)
            files_with_info = []
            for file_path in files:
                try:
                    mtime = os.path.getmtime(file_path)
                    files_with_info.append((file_path, 0, mtime))
                except OSError:
                    files_with_info.append((file_path, 0, 0))
            files_with_info.sort(key=lambda x: x[2], reverse=True)
            keep_file = files_with_info[0][0]
            remove_files = [info[0] for info in files_with_info[1:]]
        
        else:  # manual review
            return 0  # Don't remove anything in manual mode
        
        # Remove the duplicate files
        removed_count = 0
        for file_path in remove_files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logging.info(f"Removed duplicate movie: {file_path}")
                    removed_count += 1
            except Exception as e:
                logging.error(f"Failed to remove {file_path}: {str(e)}")
                raise
        
        return removed_count
    
    def remove_duplicate_series(self, duplicate):
        """Remove duplicate series folders, keeping the first one"""
        folders = duplicate['folders']
        if len(folders) <= 1:
            return 0
        
        if self.duplicate_action == 'manual':
            return 0  # Don't remove anything in manual mode
        
        # Keep the first folder (usually the one with more episodes or better organized)
        keep_folder = folders[0][1]
        remove_folders = [folder[1] for folder in folders[1:]]
        
        removed_count = 0
        for folder_path in remove_folders:
            try:
                if os.path.exists(folder_path):
                    # Count files before removal for reporting
                    file_count = 0
                    for root, _, files in os.walk(folder_path):
                        file_count += len([f for f in files if any(f.lower().endswith(ext) for ext in media_extensions)])
                    
                    shutil.rmtree(folder_path)
                    logging.info(f"Removed duplicate series folder: {folder_path}")
                    removed_count += file_count
            except Exception as e:
                logging.error(f"Failed to remove {folder_path}: {str(e)}")
                raise
        
        return removed_count
    
    def auto_remove_duplicates(self, keep_largest=True):
        """Automatically remove duplicates without user interaction"""
        try:
            # Find duplicates
            duplicates_found = []
            
            # Find movie duplicates
            movie_duplicates = self.find_movie_duplicates()
            if movie_duplicates:
                duplicates_found.extend(movie_duplicates)
            
            # Find series duplicates
            series_duplicates = self.find_series_duplicates()
            if series_duplicates:
                duplicates_found.extend(series_duplicates)
            
            if not duplicates_found:
                return 0, "No duplicates found in your media library."
            
            # Set removal preference
            self.duplicate_action = 'keep_largest' if keep_largest else 'keep_newest'
            
            # Remove duplicates automatically
            removed_count = 0
            errors = []
            
            for duplicate in duplicates_found:
                try:
                    if duplicate['type'] == 'movie':
                        removed = self.remove_duplicate_movies(duplicate)
                        removed_count += removed
                    else:
                        removed = self.remove_duplicate_series(duplicate)
                        removed_count += removed
                except Exception as e:
                    errors.append(f"Error processing {duplicate['title']}: {str(e)}")
            
            # Refresh the media lists
            if removed_count > 0:
                self.update_media_lists()
                self.populate_series_list()
            
            if errors:
                return removed_count, f"Removed {removed_count} duplicates with errors: " + "; ".join(errors)
            else:
                return removed_count, f"Successfully removed {removed_count} duplicate files."
                
        except Exception as e:
            logging.error(f"Error in auto_remove_duplicates: {str(e)}")
            return 0, f"Error during automatic duplicate removal: {str(e)}"
    
    def clean_cache_duplicates(self):
        """Clean up duplicate entries in cache directories"""
        try:
            cache_dirs = [POSTER_CACHE_DIR, SYNOPSIS_CACHE_DIR, BACKDROP_CACHE_DIR]
            cleaned_count = 0
            
            for cache_dir in cache_dirs:
                if not os.path.exists(cache_dir):
                    continue
                    
                # Group cache files by similar names
                cache_files = {}
                for filename in os.listdir(cache_dir):
                    file_path = os.path.join(cache_dir, filename)
                    if os.path.isfile(file_path):
                        # Extract base name for grouping
                        base_name = filename.lower()
                        # Remove year and file extension for comparison
                        base_name = re.sub(r'_\d{4}', '', base_name)
                        base_name = re.sub(r'\.(jpg|jpeg|png|txt)$', '', base_name)
                        
                        if base_name not in cache_files:
                            cache_files[base_name] = []
                        cache_files[base_name].append((filename, file_path))
                
                # Find duplicates within each group
                for base_name, files in cache_files.items():
                    if len(files) > 1:
                        # Sort by modification time, keep the newest
                        files.sort(key=lambda x: os.path.getmtime(x[1]), reverse=True)
                        
                        # Remove older duplicates
                        for filename, file_path in files[1:]:
                            try:
                                os.remove(file_path)
                                cleaned_count += 1
                                logging.info(f"Removed duplicate cache file: {filename}")
                            except OSError as e:
                                logging.error(f"Error removing cache file {filename}: {e}")
            
            if cleaned_count > 0:
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Information)
                msg.setText(f"Cleaned {cleaned_count} duplicate cache files!")
                msg.setWindowTitle("Cache Cleanup Complete")
                msg.setStyleSheet("""
                    QMessageBox {
                        background-color: #141414;
                    }
                    QMessageBox QLabel {
                        color: white;
                    }
                    QMessageBox QPushButton {
                        background-color: #E50914;
                        color: white;
                        border: none;
                        padding: 8px 16px;
                        font-size: 14px;
                        border-radius: 4px;
                    }
                """)
                msg.exec_()
            else:
                logging.info("No duplicate cache files found.")
                
        except Exception as e:
            logging.error(f"Error cleaning cache duplicates: {str(e)}")
            QMessageBox.critical(self, "Error", f"Error while cleaning cache:\n{str(e)}")

    def play_media(self, item):
        try:
            file_path = getattr(item, "file_path", None)
            if not file_path:
                return

            if sys.platform == "win32":
                os.startfile(file_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", file_path])
            else:
                subprocess.run(["xdg-open", file_path])
            logging.info(f"Playing media file: {file_path}")
        except Exception as e:
            logging.error(f"Error playing media file: {str(e)}")
            QMessageBox.critical(self, "Error", f"Could not play media file:\n{str(e)}")

    def delete_media(self, item):
        try:
            file_path = getattr(item, "file_path", None)
            if not file_path:
                return

            # Determine if this is a movie or episode
            is_movie = movies_folder in file_path
            is_episode = series_folder in file_path

            if is_movie:
                title = f"Delete Movie: {item.text()}"
                message = f"Are you sure you want to permanently delete this movie?\n\n{item.text()}\n\nThis action cannot be undone."
            elif is_episode:
                title = f"Delete Episode: {item.text()}"
                message = f"Are you sure you want to permanently delete this episode?\n\n{item.text()}\n\nThis action cannot be undone."
            else:
                title = f"Delete File: {item.text()}"
                message = f"Are you sure you want to permanently delete this file?\n\n{item.text()}\n\nThis action cannot be undone."

            # Create confirmation dialog
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText(message)
            msg.setWindowTitle(title)
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                    min-width: 80px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #F40612;
                }
            """)

            ret = msg.exec_()
            if ret == QMessageBox.Yes:
                # Delete the file
                if os.path.exists(file_path):
                    os.remove(file_path)
                    logging.info(f"Deleted media file: {file_path}")
                    
                    # Show success message
                    success_msg = QMessageBox()
                    success_msg.setIcon(QMessageBox.Information)
                    success_msg.setText("File deleted successfully!")
                    success_msg.setWindowTitle("Success")
                    success_msg.setStyleSheet("""
                        QMessageBox {
                            background-color: #141414;
                        }
                        QMessageBox QLabel {
                            color: white;
                        }
                        QMessageBox QPushButton {
                            background-color: #E50914;
                            color: white;
                            border: none;
                            padding: 8px 16px;
                            font-size: 14px;
                            border-radius: 4px;
                        }
                    """)
                    success_msg.exec_()
                    
                    # Refresh the media lists and go back to the appropriate view
                    self.update_media_lists()
                    self.populate_series_list()
                    
                    if is_movie:
                        self.stacked_widget.setCurrentIndex(1)  # Movies view
                    elif is_episode:
                        self.stacked_widget.setCurrentIndex(3)  # Episodes view
                else:
                    QMessageBox.critical(self, "Error", "File not found or already deleted.")
        except Exception as e:
            logging.error(f"Error deleting media file: {str(e)}")
            QMessageBox.critical(self, "Error", f"Could not delete media file:\n{str(e)}")

    def delete_series(self, series_path, series_name):
        try:
            if not os.path.exists(series_path):
                QMessageBox.critical(self, "Error", "Series folder not found.")
                return

            # Count total files in the series
            total_files = 0
            for root, _, files in os.walk(series_path):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        total_files += 1

            # Create confirmation dialog
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setText(f"Are you sure you want to permanently delete the entire series?\n\n{series_name}\n\nThis will delete {total_files} episode(s) and the entire series folder.\n\nThis action cannot be undone.")
            msg.setWindowTitle(f"Delete Series: {series_name}")
            msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
            msg.setDefaultButton(QMessageBox.No)
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                    min-width: 80px;
                }
                QMessageBox QPushButton:hover {
                    background-color: #F40612;
                }
            """)

            ret = msg.exec_()
            if ret == QMessageBox.Yes:
                # Delete the entire series folder
                import shutil
                shutil.rmtree(series_path)
                logging.info(f"Deleted series folder: {series_path}")
                
                # Show success message
                success_msg = QMessageBox()
                success_msg.setIcon(QMessageBox.Information)
                success_msg.setText(f"Series '{series_name}' deleted successfully!")
                success_msg.setWindowTitle("Success")
                success_msg.setStyleSheet("""
                    QMessageBox {
                        background-color: #141414;
                    }
                    QMessageBox QLabel {
                        color: white;
                    }
                    QMessageBox QPushButton {
                        background-color: #E50914;
                        color: white;
                        border: none;
                        padding: 8px 16px;
                        font-size: 14px;
                        border-radius: 4px;
                    }
                """)
                success_msg.exec_()
                
                # Refresh the series list and go back to series view
                self.populate_series_list()
                self.stacked_widget.setCurrentIndex(2)  # Series list view
        except Exception as e:
            logging.error(f"Error deleting series: {str(e)}")
            QMessageBox.critical(self, "Error", f"Could not delete series:\n{str(e)}")

    def show_movies_context_menu(self, position):
        item = self.movies_list.itemAt(position)
        if item is None:
            return

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #444444;
            }
            QMenu::item {
                padding: 8px 16px;
            }
            QMenu::item:selected {
                background-color: #E50914;
            }
        """)

        delete_action = menu.addAction("Delete Movie")
        delete_action.triggered.connect(lambda: self.delete_media(item))

        menu.exec_(self.movies_list.mapToGlobal(position))

    def show_series_context_menu(self, position):
        item = self.series_list.itemAt(position)
        if item is None:
            return

        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #444444;
            }
            QMenu::item {
                padding: 8px 16px;
            }
            QMenu::item:selected {
                background-color: #E50914;
            }
        """)

        delete_action = menu.addAction("Delete Series")
        series_path = item.data(Qt.UserRole)
        if series_path:
            delete_action.triggered.connect(lambda: self.delete_series(series_path, item.text()))

        menu.exec_(self.series_list.mapToGlobal(position))

    def show_episode_context_menu(self, position, episode_item, widget):
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #444444;
            }
            QMenu::item {
                padding: 8px 16px;
            }
            QMenu::item:selected {
                background-color: #E50914;
            }
        """)

        delete_action = menu.addAction("Delete Episode")
        delete_action.triggered.connect(lambda: self.delete_media(episode_item))

        menu.exec_(widget.mapToGlobal(position))
    
    def sort_files(self):
        try:
            for downloads_folder in downloads_folders:
                if os.path.exists(downloads_folder):
                    self.process_downloads_folder(downloads_folder)
                else:
                    logging.error(f"Downloads folder not found: {downloads_folder}")
            
            self.update_media_lists()
            
            # Check for any new duplicates that might have been created
            duplicates_found = []
            movie_duplicates = self.find_movie_duplicates()
            series_duplicates = self.find_series_duplicates()
            
            if movie_duplicates:
                duplicates_found.extend(movie_duplicates)
            if series_duplicates:
                duplicates_found.extend(series_duplicates)
            
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            
            if duplicates_found:
                msg.setText(f"Files have been sorted successfully!\n\nFound {len(duplicates_found)} potential duplicate groups.\nYou can review and remove them in Settings → Find & Remove Duplicates.")
                msg.setWindowTitle("Sorting Complete - Duplicates Detected")
            else:
                msg.setText("Files have been sorted successfully!\n\nNo duplicates detected.")
                msg.setWindowTitle("Sorting Complete")
                
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                }
            """)
            msg.exec_()
        except Exception as e:
            logging.error(f"Error during file sorting: {str(e)}")
            QMessageBox.critical(self, "Error", f"An error occurred during file sorting:\n{str(e)}")
    
    def process_downloads_folder(self, downloads_folder):
        for file_name in os.listdir(downloads_folder):
            file_path = os.path.join(downloads_folder, file_name)
            if os.path.isdir(file_path):
                continue
            try:
                if any(file_name.lower().endswith(ext) for ext in media_extensions):
                    # Check for potential duplicates before moving
                    if self.is_potential_duplicate(file_path):
                        logging.warning(f"Potential duplicate detected: {file_name}")
                        # Still proceed but with extra logging
                    
                    file_name_with_spaces = self.replace_underscores_and_dots(file_name)
                    series_name, season, year = extract_series_info(file_name_with_spaces)
                    if series_name and season:
                        series_folder_path = os.path.join(series_folder, series_name, season)
                        self.move_file(file_path, series_folder_path, file_name)
                    else:
                        self.move_file(file_path, movies_folder, file_name)
            except Exception as e:
                logging.error(f"Failed to process {file_name}: {str(e)}")
    
    def is_potential_duplicate(self, file_path):
        """Check if a file might be a duplicate of existing content"""
        try:
            file_name = os.path.basename(file_path)
            file_size = os.path.getsize(file_path)
            
            # Extract title for comparison
            clean_title = self.extract_movie_title(file_name).lower()
            
            # Check against existing movies
            if os.path.exists(movies_folder):
                for root, _, files in os.walk(movies_folder):
                    for existing_file in files:
                        if any(existing_file.lower().endswith(ext) for ext in media_extensions):
                            existing_title = self.extract_movie_title(existing_file).lower()
                            existing_path = os.path.join(root, existing_file)
                            
                            # Check for title similarity
                            if self.are_titles_similar(clean_title, existing_title):
                                try:
                                    existing_size = os.path.getsize(existing_path)
                                    size_diff = abs(file_size - existing_size) / max(file_size, existing_size)
                                    
                                    # If titles are very similar and sizes are close, likely duplicate
                                    if size_diff < 0.1:  # Less than 10% size difference
                                        logging.warning(f"Potential duplicate found: '{file_name}' vs '{existing_file}'")
                                        return True
                                except OSError:
                                    pass
            
            # Check against existing series if it's detected as series content
            series_name, season, year = extract_series_info(file_name)
            if series_name and os.path.exists(series_folder):
                series_path = os.path.join(series_folder, series_name)
                if os.path.exists(series_path):
                    for root, _, files in os.walk(series_path):
                        for existing_file in files:
                            if any(existing_file.lower().endswith(ext) for ext in media_extensions):
                                # Check for episode duplicates (same season/episode)
                                existing_season_ep = self.extract_season_episode(existing_file)
                                new_season_ep = self.extract_season_episode(file_name)
                                
                                if (existing_season_ep and new_season_ep and 
                                    existing_season_ep == new_season_ep):
                                    logging.warning(f"Potential episode duplicate: '{file_name}' vs '{existing_file}'")
                                    return True
            
            return False
        except Exception as e:
            logging.error(f"Error checking for duplicates: {str(e)}")
            return False
    
    def are_titles_similar(self, title1, title2, threshold=0.8):
        """Check if two titles are similar using a simple similarity metric"""
        # Remove common words and clean titles
        common_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
        
        def clean_title(title):
            # Remove special characters and split into words
            import re
            words = re.findall(r'\b\w+\b', title.lower())
            # Remove common words
            return set(word for word in words if word not in common_words and len(word) > 2)
        
        words1 = clean_title(title1)
        words2 = clean_title(title2)
        
        if not words1 or not words2:
            return False
        
        # Calculate Jaccard similarity
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        similarity = intersection / union if union > 0 else 0
        return similarity >= threshold
    
    def replace_underscores_and_dots(self, file_name):
        return file_name.replace('_', ' ').replace('.', ' ')
    
    def get_unique_filename(self, dest_folder, file_name):
        base_name, extension = os.path.splitext(file_name)
        unique_name = file_name
        counter = 1
        
        # First check if exact file already exists
        dest_path = os.path.join(dest_folder, unique_name)
        if os.path.exists(dest_path):
            # Check if it's the same file (by size and name similarity)
            try:
                existing_size = os.path.getsize(dest_path)
                # If files have same name pattern and similar size, it might be a duplicate
                logging.info(f"File with similar name already exists: {dest_path} (size: {existing_size})")
            except OSError:
                pass
                
        # Generate unique name if needed
        while os.path.exists(os.path.join(dest_folder, unique_name)):
            unique_name = f"{base_name}_{counter}{extension}"
            counter += 1
            
        return unique_name
    
    def ensure_directory_exists(self, directory):
        if not os.path.exists(directory):
            os.makedirs(directory)
            logging.info(f"Created directory: {directory}")
    
    def move_file(self, src_path, dest_folder, file_name):
        retries = 3
        for attempt in range(retries):
            try:
                self.ensure_directory_exists(dest_folder)
                unique_name = self.get_unique_filename(dest_folder, file_name)
                dest_path = os.path.join(dest_folder, unique_name)
                logging.info(f"Moving file from {src_path} to {dest_path}")
                shutil.move(src_path, dest_path)
                logging.info(f"Moved {file_name} to {dest_folder}")
                break
            except PermissionError as e:
                logging.error(f"Permission error moving {file_name}: {str(e)}")
                time.sleep(5)
            except FileNotFoundError as e:
                logging.error(f"File not found: {file_name}. Error: {str(e)}")
                break
            except Exception as e:
                logging.error(f"Error moving {file_name}: {str(e)}")
                break
    
    def show_settings(self):
        settings_dialog = QDialog(self)
        settings_dialog.setWindowTitle("Mediaflix Settings")
        settings_dialog.setFixedSize(750, 700)  # Larger size for better layout
        settings_dialog.setStyleSheet("""
            QDialog {
                background-color: #141414;
                color: white;
                border: 2px solid #333333;
                border-radius: 12px;
            }
        """)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(30, 25, 30, 25)
        layout.setSpacing(25)
        
        # Header section with icon and title
        header_container = QWidget()
        header_layout = QHBoxLayout(header_container)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(15)
        
        # Settings icon
        settings_icon = QLabel("⚙️")
        settings_icon.setStyleSheet("""
            font-size: 32px;
            background-color: #222222;
            border-radius: 25px;
            padding: 10px;
            min-width: 50px;
            max-width: 50px;
            min-height: 50px;
            max-height: 50px;
        """)
        settings_icon.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(settings_icon)
        
        # Title and subtitle
        title_container = QWidget()
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        title_layout.setSpacing(2)
        
        title = QLabel("Settings")
        title.setStyleSheet("""
            font-size: 28px; 
            font-weight: bold; 
            color: #FFFFFF;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        title_layout.addWidget(title)
        
        subtitle = QLabel("Configure your Mediaflix experience")
        subtitle.setStyleSheet("""
            font-size: 14px; 
            color: #AAAAAA;
            font-family: 'Netflix Sans', 'Arial', sans-serif;
            margin-top: 2px;
        """)
        title_layout.addWidget(subtitle)
        
        header_layout.addWidget(title_container)
        header_layout.addStretch()
        
        # Close button
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(35, 35)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #AAAAAA;
                border: none;
                font-size: 18px;
                font-weight: bold;
                border-radius: 17px;
            }
            QPushButton:hover {
                background-color: #E50914;
                color: white;
            }
        """)
        close_btn.clicked.connect(settings_dialog.close)
        header_layout.addWidget(close_btn)
        
        layout.addWidget(header_container)
        
        # Divider line
        divider = QWidget()
        divider.setFixedHeight(2)
        divider.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 transparent, stop:0.1 #E50914, stop:0.9 #E50914, stop:1 transparent);
        """)
        layout.addWidget(divider)
        
        # Scroll area for settings content
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: transparent;
            }
            QScrollArea > QWidget > QWidget {
                background-color: transparent;
            }
        """)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 10, 0, 0)
        scroll_layout.setSpacing(20)
        
        # Media Folders Section
        folders_section = self.create_settings_section(
            "📁", "Media Folders", "Configure where your movies and TV series are stored"
        )
        
        folders_content = QWidget()
        folders_layout = QVBoxLayout(folders_content)
        folders_layout.setContentsMargins(0, 0, 0, 0)
        folders_layout.setSpacing(15)
        
        # Movies folder
        movies_container = self.create_folder_input("🎬", "Movies Folder", movies_folder, self.browse_movies_folder)
        self.movies_folder_edit = movies_container.findChild(QLineEdit)
        folders_layout.addWidget(movies_container)
        
        # Series folder
        series_container = self.create_folder_input("📺", "TV Series Folder", series_folder, self.browse_series_folder)
        self.series_folder_edit = series_container.findChild(QLineEdit)
        folders_layout.addWidget(series_container)
        
        folders_section.layout().addWidget(folders_content)
        scroll_layout.addWidget(folders_section)
        
        # Downloads Management Section
        downloads_section = self.create_settings_section(
            "📥", "Downloads Management", "Manage folders to monitor for new downloads"
        )
        
        downloads_content = QWidget()
        downloads_layout = QVBoxLayout(downloads_content)
        downloads_layout.setContentsMargins(0, 0, 0, 0)
        downloads_layout.setSpacing(15)
        
        # Downloads list with modern styling
        self.downloads_list = QListWidget()
        self.downloads_list.setSelectionMode(QListWidget.SingleSelection)
        self.downloads_list.setStyleSheet("""
            QListWidget {
                background-color: #222222;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 8px;
                font-size: 13px;
                min-height: 120px;
                max-height: 120px;
            }
            QListWidget::item {
                padding: 8px 12px;
                border-radius: 4px;
                margin: 2px 0px;
            }
            QListWidget::item:hover {
                background-color: #333333;
            }
            QListWidget::item:selected {
                background-color: #E50914;
                color: white;
            }
        """)
        
        for folder in downloads_folders:
            item = QListWidgetItem(f"📂 {folder}")
            self.downloads_list.addItem(item)
        
        downloads_layout.addWidget(self.downloads_list)
        
        # Action buttons for downloads
        downloads_buttons = QWidget()
        downloads_buttons_layout = QHBoxLayout(downloads_buttons)
        downloads_buttons_layout.setContentsMargins(0, 0, 0, 0)
        downloads_buttons_layout.setSpacing(10)
        
        add_btn = QPushButton("➕ Add Folder")
        add_btn.setStyleSheet(self.get_action_button_style("#28A745"))  # Green
        add_btn.clicked.connect(self.add_downloads_folder)
        downloads_buttons_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("🗑️ Remove Selected")
        remove_btn.setStyleSheet(self.get_action_button_style("#DC3545"))  # Red
        remove_btn.clicked.connect(self.remove_downloads_folder)
        downloads_buttons_layout.addWidget(remove_btn)
        
        downloads_buttons_layout.addStretch()
        downloads_layout.addWidget(downloads_buttons)
        
        downloads_section.layout().addWidget(downloads_content)
        scroll_layout.addWidget(downloads_section)
        
        # Cache & Performance Section
        cache_section = self.create_settings_section(
            "⚡", "Cache & Performance", "Optimize loading and offline experience"
        )
        
        cache_content = QWidget()
        cache_layout = QVBoxLayout(cache_content)
        cache_layout.setContentsMargins(0, 0, 0, 0)
        cache_layout.setSpacing(15)
        
        # Backdrop preloading option
        backdrop_container = QWidget()
        backdrop_layout = QHBoxLayout(backdrop_container)
        backdrop_layout.setContentsMargins(15, 10, 15, 10)
        backdrop_layout.setSpacing(15)
        backdrop_container.setStyleSheet("""
            QWidget {
                background-color: #222222;
                border-radius: 8px;
                border: 1px solid #333333;
            }
        """)
        
        backdrop_info = QWidget()
        backdrop_info_layout = QVBoxLayout(backdrop_info)
        backdrop_info_layout.setContentsMargins(0, 0, 0, 0)
        backdrop_info_layout.setSpacing(3)
        
        backdrop_title = QLabel("🖼️ Preload Backdrops")
        backdrop_title.setStyleSheet("""
            font-size: 14px;
            font-weight: bold;
            color: white;
        """)
        backdrop_info_layout.addWidget(backdrop_title)
        
        backdrop_desc = QLabel("Download all movie and TV show backdrops for offline viewing")
        backdrop_desc.setStyleSheet("""
            font-size: 12px;
            color: #AAAAAA;
            margin: 0px;
        """)
        backdrop_desc.setWordWrap(True)
        backdrop_info_layout.addWidget(backdrop_desc)
        
        backdrop_layout.addWidget(backdrop_info, 1)
        
        # Preload button
        preload_btn = QPushButton("🚀 Start Cache")
        preload_btn.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 10px 18px;
                font-size: 13px;
                border-radius: 6px;
                font-weight: 600;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)
        preload_btn.clicked.connect(lambda: self.manual_backdrop_preload(preload_btn))
        backdrop_layout.addWidget(preload_btn)
        
        cache_layout.addWidget(backdrop_container)
        
        # Cache status display
        status_container = QWidget()
        status_layout = QHBoxLayout(status_container)
        status_layout.setContentsMargins(15, 10, 15, 10)
        status_layout.setSpacing(15)
        status_container.setStyleSheet("""
            QWidget {
                background-color: #1A1A1A;
                border-radius: 8px;
                border: 1px solid #333333;
            }
        """)
        
        # Cache info
        cached_count = self.get_cached_backdrop_count()
        cache_info = QLabel(f"💾 {cached_count} backdrops cached • Ready for offline viewing")
        cache_info.setStyleSheet("""
            font-size: 13px;
            color: #AAAAAA;
            font-weight: 500;
        """)
        status_layout.addWidget(cache_info, 1)
        
        # View cache button
        view_cache_btn = QPushButton("📊 Status")
        view_cache_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #555555;
                padding: 8px 14px;
                font-size: 12px;
                border-radius: 6px;
                font-weight: 500;
                min-width: 70px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #777777;
            }
        """)
        view_cache_btn.clicked.connect(self.show_cache_status)
        status_layout.addWidget(view_cache_btn)
        
        cache_layout.addWidget(status_container)
        cache_section.layout().addWidget(cache_content)
        scroll_layout.addWidget(cache_section)
        
        # Refresh & Maintenance Section
        refresh_section = self.create_settings_section(
            "🔄", "Refresh & Maintenance", "Keep your content fresh and up-to-date"
        )
        
        refresh_content = QWidget()
        refresh_layout = QVBoxLayout(refresh_content)
        refresh_layout.setContentsMargins(0, 0, 0, 0)
        refresh_layout.setSpacing(12)
        
        # Refresh buttons with enhanced styling
        refresh_home_btn = QPushButton("⟳ Refresh Home Content")
        refresh_home_btn.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 14px 20px;
                font-size: 14px;
                border-radius: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)
        refresh_home_btn.clicked.connect(lambda: self.close_settings_and_refresh(settings_dialog, "home"))
        refresh_layout.addWidget(refresh_home_btn)
        
        refresh_all_btn = QPushButton("🔄 Refresh All Content & Clear Cache")
        refresh_all_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #444444;
                padding: 14px 20px;
                font-size: 14px;
                border-radius: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #555555;
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
            }
        """)
        refresh_all_btn.clicked.connect(lambda: self.close_settings_and_refresh(settings_dialog, "all"))
        refresh_layout.addWidget(refresh_all_btn)
        
        # Add duplicate checker button
        duplicate_check_btn = QPushButton("🔍 Find & Remove Duplicates")
        duplicate_check_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF8C00;
                color: white;
                border: none;
                padding: 14px 20px;
                font-size: 14px;
                border-radius: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #FF9500;
            }
            QPushButton:pressed {
                background-color: #E67E00;
            }
        """)
        duplicate_check_btn.clicked.connect(lambda: self.close_settings_and_find_duplicates(settings_dialog))
        refresh_layout.addWidget(duplicate_check_btn)
        
        # Add automatic duplicate removal button
        auto_remove_btn = QPushButton("🚀 Auto-Remove Duplicates (Keep Largest)")
        auto_remove_btn.setStyleSheet("""
            QPushButton {
                background-color: #9C27B0;
                color: white;
                border: none;
                padding: 14px 20px;
                font-size: 14px;
                border-radius: 8px;
                font-weight: 600;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #AB47BC;
            }
            QPushButton:pressed {
                background-color: #8E24AA;
            }
        """)
        auto_remove_btn.clicked.connect(lambda: self.close_settings_and_auto_remove(settings_dialog))
        refresh_layout.addWidget(auto_remove_btn)
        
        # Enhanced description with tips
        refresh_description = QLabel("""
<div style='line-height: 1.4;'>
<b style='color: #FFFFFF;'>💡 Tips:</b><br/>
• <b>Refresh Home:</b> Updates movie/TV recommendations with fresh content<br/>
• <b>Refresh All:</b> Clears cache and reloads all media libraries<br/>
• <b>Find Duplicates:</b> Manually review and remove duplicate movies and series<br/>
• <b>Auto-Remove:</b> Automatically removes duplicates (keeps largest files)<br/>
• <b>Auto-refresh:</b> Home content refreshes automatically every 10 minutes
</div>
        """)
        refresh_description.setStyleSheet("""
            color: #CCCCCC;
            font-size: 12px;
            padding: 15px;
            background-color: #1A1A1A;
            border-radius: 8px;
            border-left: 4px solid #E50914;
        """)
        refresh_description.setWordWrap(True)
        refresh_layout.addWidget(refresh_description)
        
        refresh_section.layout().addWidget(refresh_content)
        scroll_layout.addWidget(refresh_section)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        # Bottom action bar
        bottom_bar = QWidget()
        bottom_bar.setStyleSheet("""
            background-color: #1A1A1A;
            border-radius: 8px;
            padding: 5px;
        """)
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(15, 10, 15, 10)
        bottom_layout.setSpacing(15)
        
        # Version info
        version_label = QLabel("Mediaflix v1.0")
        version_label.setStyleSheet("""
            color: #666666;
            font-size: 12px;
            font-style: italic;
        """)
        bottom_layout.addWidget(version_label)
        
        bottom_layout.addStretch()
        
        # Action buttons
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #AAAAAA;
                border: 1px solid #555555;
                padding: 10px 20px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: 500;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #333333;
                color: white;
                border-color: #777777;
            }
        """)
        cancel_btn.clicked.connect(settings_dialog.close)
        bottom_layout.addWidget(cancel_btn)
        
        save_button = QPushButton("💾 Save Settings")
        save_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 12px 24px;
                font-size: 14px;
                border-radius: 6px;
                font-weight: bold;
                min-width: 120px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)
        save_button.clicked.connect(lambda: self.save_settings_and_close(settings_dialog))
        bottom_layout.addWidget(save_button)
        
        layout.addWidget(bottom_bar)
        settings_dialog.setLayout(layout)
        
        # Center the dialog on screen
        settings_dialog.move(
            self.geometry().center() - settings_dialog.rect().center()
        )
        
        settings_dialog.exec_()

    def create_settings_section(self, icon, title, description):
        """Create a modern settings section with icon, title, and description"""
        section_widget = QWidget()
        section_widget.setStyleSheet("""
            QWidget {
                background-color: #1A1A1A;
                border-radius: 12px;
                border: 1px solid #333333;
            }
        """)
        
        layout = QVBoxLayout(section_widget)
        layout.setContentsMargins(20, 15, 20, 20)
        layout.setSpacing(15)
        
        # Header with icon and title
        header_widget = QWidget()
        header_layout = QHBoxLayout(header_widget)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(12)
        
        # Icon
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("""
            font-size: 20px;
            background-color: #2D2D2D;
            border-radius: 6px;
            padding: 8px;
            min-width: 20px;
            max-width: 20px;
        """)
        icon_label.setAlignment(Qt.AlignCenter)
        header_layout.addWidget(icon_label)
        
        # Title and description
        text_widget = QWidget()
        text_layout = QVBoxLayout(text_widget)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        
        title_label = QLabel(title)
        title_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #FFFFFF;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        text_layout.addWidget(title_label)
        
        desc_label = QLabel(description)
        desc_label.setStyleSheet("""
            font-size: 12px;
            color: #AAAAAA;
            font-family: 'Netflix Sans', 'Arial', sans-serif;
        """)
        text_layout.addWidget(desc_label)
        
        header_layout.addWidget(text_widget)
        header_layout.addStretch()
        
        layout.addWidget(header_widget)
        return section_widget

    def create_folder_input(self, icon, label_text, current_path, browse_callback):
        """Create a modern folder input with icon, label, and browse button"""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        
        # Label with icon
        label_container = QWidget()
        label_layout = QHBoxLayout(label_container)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(8)
        
        icon_label = QLabel(icon)
        icon_label.setStyleSheet("""
            font-size: 14px;
            color: #E50914;
        """)
        label_layout.addWidget(icon_label)
        
        text_label = QLabel(label_text)
        text_label.setStyleSheet("""
            font-size: 13px;
            color: #FFFFFF;
            font-weight: 500;
        """)
        label_layout.addWidget(text_label)
        label_layout.addStretch()
        
        layout.addWidget(label_container)
        
        # Input container
        input_container = QWidget()
        input_layout = QHBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(10)
        
        # Path input
        path_input = QLineEdit(current_path)
        path_input.setStyleSheet("""
            QLineEdit {
                background-color: #222222;
                border: 1px solid #444444;
                border-radius: 6px;
                padding: 10px 12px;
                font-size: 13px;
                color: white;
            }
            QLineEdit:focus {
                border-color: #E50914;
                outline: none;
            }
        """)
        input_layout.addWidget(path_input)
        
        # Browse button
        browse_btn = QPushButton("📁 Browse")
        browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #555555;
                padding: 10px 16px;
                font-size: 12px;
                border-radius: 6px;
                font-weight: 500;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #3D3D3D;
                border-color: #777777;
            }
        """)
        browse_btn.clicked.connect(browse_callback)
        input_layout.addWidget(browse_btn)
        
        layout.addWidget(input_container)
        return container

    def get_action_button_style(self, color):
        """Get consistent styling for action buttons"""
        return f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                padding: 10px 16px;
                font-size: 12px;
                border-radius: 6px;
                font-weight: 600;
                min-width: 100px;
            }}
            QPushButton:hover {{
                background-color: {color}CC;
            }}
            QPushButton:pressed {{
                background-color: {color}AA;
            }}
        """

    def close_settings_and_refresh(self, dialog, refresh_type):
        """Close settings dialog and perform refresh"""
        dialog.close()
        if refresh_type == "home":
            self.reload_home_content()
        elif refresh_type == "all":
            self.refresh_all()

    def close_settings_and_find_duplicates(self, dialog):
        """Close settings dialog and find duplicates"""
        dialog.close()
        QTimer.singleShot(100, self.comprehensive_duplicate_check)  # Run comprehensive check

    def close_settings_and_auto_remove(self, dialog):
        """Close settings dialog and automatically remove duplicates"""
        dialog.close()
        QTimer.singleShot(100, self.auto_remove_duplicates_with_confirmation)

    def auto_remove_duplicates_with_confirmation(self):
        """Auto-remove duplicates with user confirmation"""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText("This will automatically remove duplicate files, keeping the largest copy of each.")
        msg.setInformativeText("This action cannot be undone. Continue?")
        msg.setWindowTitle("Auto-Remove Duplicates")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #141414;
            }
            QMessageBox QLabel {
                color: white;
            }
            QMessageBox QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        
        if msg.exec_() == QMessageBox.Yes:
            removed_count, message = self.auto_remove_duplicates(keep_largest=True)
            
            # Show results
            result_msg = QMessageBox()
            if removed_count > 0:
                result_msg.setIcon(QMessageBox.Information)
                result_msg.setText(f"Auto-removal complete!")
                result_msg.setInformativeText(message)
            else:
                result_msg.setIcon(QMessageBox.Information)
                result_msg.setText("No duplicates found")
                result_msg.setInformativeText(message)
            
            result_msg.setWindowTitle("Duplicate Removal Results")
            result_msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                }
            """)
            result_msg.exec_()

    def comprehensive_duplicate_check(self):
        """Run a comprehensive duplicate check including files and cache"""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Question)
        msg.setText("This will scan your entire media library for duplicates and clean cache files.")
        msg.setInformativeText("This process may take a few minutes. Continue?")
        msg.setWindowTitle("Comprehensive Duplicate Check")
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setStyleSheet("""
            QMessageBox {
                background-color: #141414;
            }
            QMessageBox QLabel {
                color: white;
            }
            QMessageBox QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        
        ret = msg.exec_()
        if ret == QMessageBox.Yes:
            # First clean cache duplicates
            self.clean_cache_duplicates()
            # Then check for media duplicates
            QTimer.singleShot(500, self.find_and_remove_duplicates)

    def save_settings_and_close(self, dialog):
        """Save settings and close dialog"""
        self.save_settings()
        dialog.close()
    
    def add_downloads_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Downloads Folder", home_directory)
        if folder:
            # Check if folder already exists
            for i in range(self.downloads_list.count()):
                item_text = self.downloads_list.item(i).text()
                # Remove the folder icon when comparing
                existing_folder = item_text.replace("📂 ", "") if item_text.startswith("📂 ") else item_text
                if existing_folder == folder:
                    return
            # Add new folder with icon
            self.downloads_list.addItem(QListWidgetItem(f"📂 {folder}"))
    
    def remove_downloads_folder(self):
        current_item = self.downloads_list.currentItem()
        if current_item:
            self.downloads_list.takeItem(self.downloads_list.row(current_item))
    
    def browse_movies_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Movies Folder", movies_folder)
        if folder:
            self.movies_folder_edit.setText(folder)
    
    def browse_series_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select TV Series Folder", series_folder)
        if folder:
            self.series_folder_edit.setText(folder)
    
    def save_settings(self):
        global movies_folder, series_folder, downloads_folders
        
        new_movies_folder = self.movies_folder_edit.text()
        new_series_folder = self.series_folder_edit.text()
        
        new_downloads_folders = []
        for i in range(self.downloads_list.count()):
            new_downloads_folders.append(self.downloads_list.item(i).text())
        
        settings_changed = (
            new_movies_folder != movies_folder or
            new_series_folder != series_folder or
            new_downloads_folders != downloads_folders
        )
        
        if settings_changed:
            movies_folder = new_movies_folder
            series_folder = new_series_folder
            downloads_folders = new_downloads_folders
            
            self.update_media_lists()
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setText("Settings have been saved successfully!")
            msg.setWindowTitle("Settings Saved")
            msg.setStyleSheet("""
                QMessageBox {
                    background-color: #141414;
                }
                QMessageBox QLabel {
                    color: white;
                }
                QMessageBox QPushButton {
                    background-color: #E50914;
                    color: white;
                    border: none;
                    padding: 8px 16px;
                    font-size: 14px;
                    border-radius: 4px;
                }
            """)
            msg.exec_()
        else:
            QMessageBox.information(self, "Settings", "No changes were made to settings.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    try:
        check_tmdb_api_key()
        if not os.path.exists(movies_folder):
            os.makedirs(movies_folder)
        if not os.path.exists(series_folder):
            os.makedirs(series_folder)
        os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
        os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
        
        # Log startup info including duplicate prevention
        logging.info("Starting Mediaflix with enhanced duplicate prevention...")
        logging.info("Duplicate detection enabled for movies, series, and episodes")
        
        window = MediaOrganizerApp()
        window.show()
        sys.exit(app.exec_())
    except Exception as e:
        tb_str = traceback.format_exc()
        show_critical_error(f"A fatal error occurred: {e}", tb_str)
        sys.exit(1)
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
                            QSizePolicy, QSpacerItem, QTextEdit)
from PyQt5.QtCore import Qt, QSize, QTimer, QPoint, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QPalette, QPainter, QFontDatabase, QLinearGradient
import subprocess
from concurrent.futures import ThreadPoolExecutor

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
POSTER_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "posters")
SYNOPSIS_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "synopsis")

# Set up logging
log_file = os.path.join(home_directory, "media_organizer.log")
logging.basicConfig(filename=log_file, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def extract_year(name):
    match = re.search(r'(19|20)\d{2}', name)
    return match.group(0) if match else None

# --- Fast cache clearing thread ---
class CacheClearThread(QThread):
    finished = pyqtSignal()
    def run(self):
        def delete_file(file_path):
            try:
                os.remove(file_path)
            except Exception as e:
                logging.error(f"Error deleting file {file_path}: {str(e)}")
        for cache_dir in [POSTER_CACHE_DIR, SYNOPSIS_CACHE_DIR]:
            if os.path.exists(cache_dir):
                files = [os.path.join(cache_dir, f) for f in os.listdir(cache_dir) if os.path.isfile(os.path.join(cache_dir, f))]
                # Use up to 8 threads for parallel deletion (tweak as needed)
                with ThreadPoolExecutor(max_workers=8) as executor:
                    executor.map(delete_file, files)
        self.finished.emit()
# --- End cache clearing thread ---

class ImageItem(QListWidgetItem):
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.display_name = os.path.splitext(self.file_name)[0]
        self.search_title = self.extract_movie_title(self.display_name)
        self.search_year = extract_year(self.display_name)
        self.setText(self.display_name)
        self.setSizeHint(QSize(200, 300))  # Larger size for images
        self.setToolTip(self.display_name)

        # New: metadata fields
        self.imdb_rating = None
        self.genres = []
        self.release_year = self.search_year

        # Start with a Netflix-style placeholder icon
        self.setIcon(QIcon(self.create_placeholder_image()))

        # Load the actual image in the background
        self.load_image_async()
        
        # Load synopsis and metadata in the background
        self.synopsis = ""
        self.load_synopsis_async()

    def extract_movie_title(self, name):
        # Replace dots and underscores with spaces
        clean = name.replace('.', ' ').replace('_', ' ')
        # Extract everything before a valid year (1900-2099)
        match = re.search(r'(19|20)\d{2}', clean)
        if match:
            return clean[:match.start()].strip()
        return clean.strip()

    def create_placeholder_image(self):
        pixmap = QPixmap(150, 225)
        pixmap.fill(QColor(20, 20, 20))  # Netflix dark background
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw a gradient overlay
        gradient = QLinearGradient(0, 0, 0, pixmap.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 150))
        gradient.setColorAt(1, QColor(0, 0, 0, 50))
        painter.fillRect(pixmap.rect(), gradient)
        
        # Draw a red "N" like Netflix logo
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(55, 30, 40, 165)
        painter.setBrush(QColor(140, 0, 0))
        painter.drawRect(65, 30, 20, 165)
        
        # Draw the title in white, bold, centered
        painter.setPen(QColor(255, 255, 255))
        font = QFont('Netflix Sans', 10, QFont.Bold)
        painter.setFont(font)
        rect = pixmap.rect().adjusted(10, 180, -10, -10)
        painter.drawText(rect, Qt.AlignCenter | Qt.TextWordWrap, self.search_title)
        
        painter.end()
        return pixmap

    def load_image_async(self):
        QTimer.singleShot(0, self._fetch_and_set_image)

    def _fetch_and_set_image(self):
        try:
            # 1. Try exact match: title + year
            cache_name = f"{self.search_title}"
            if self.search_year:
                cache_name += f" {self.search_year}"
            cache_file = f"{quote(cache_name)}.jpg"
            cache_path = os.path.join(POSTER_CACHE_DIR, cache_file)

            # Always ensure cache directory exists
            os.makedirs(POSTER_CACHE_DIR, exist_ok=True)

            # Try to load from cache first
            if os.path.exists(cache_path):
                pixmap = QPixmap(cache_path)
                if not pixmap.isNull():
                    self.setIcon(QIcon(self._apply_poster_overlay(pixmap)))
                    return

            # 2. Try closest year match for same title
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

            # 3. Fetch from TMDB: always fallback to first result with a poster
            params = {
                "api_key": TMDB_API_KEY,
                "query": self.search_title
            }
            if self.search_year:
                params["year"] = self.search_year

            search_url = f"{TMDB_API_URL}/search/multi"
            response = requests.get(search_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            poster_path = None
            for result in data.get("results", []):
                # Only accept results with a matching year if possible
                result_year = result.get("release_date", "")[:4] or result.get("first_air_date", "")[:4]
                if self.search_year and result_year == self.search_year:
                    poster_path = result.get("poster_path") or result.get("backdrop_path")
                    if poster_path:
                        break
            # Fallback: pick the first result with a poster
            if not poster_path:
                for result in data.get("results", []):
                    poster_path = result.get("poster_path") or result.get("backdrop_path")
                    if poster_path:
                        break

            if poster_path:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                image_data = requests.get(image_url, timeout=10).content
                # Save the poster locally for offline use
                with open(cache_path, "wb") as f:
                    f.write(image_data)
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                if not pixmap.isNull():
                    self.setIcon(QIcon(self._apply_poster_overlay(pixmap)))
            return

        # If all else fails, keep the placeholder
        except Exception as e:
            logging.error(f"Error loading image for {self.display_name}: {str(e)}")

    def _apply_poster_overlay(self, pixmap):
        """Apply gradient overlay to poster image"""
        overlay = QPixmap(pixmap.size())
        overlay.fill(Qt.transparent)
        painter = QPainter(overlay)
        gradient = QLinearGradient(0, 0, 0, overlay.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 150))
        gradient.setColorAt(1, QColor(0, 0, 0, 50))
        painter.fillRect(overlay.rect(), gradient)
        painter.end()
        
        combined = QPixmap(pixmap)
        combined_painter = QPainter(combined)
        combined_painter.drawPixmap(0, 0, overlay)
        combined_painter.end()
        
        return combined

    def load_synopsis_async(self):
        QTimer.singleShot(0, self._fetch_synopsis)

    def _fetch_synopsis(self):
        try:
            # Check cache first
            cache_name = f"{self.search_title}"
            if self.search_year:
                cache_name += f" {self.search_year}"
            cache_file = f"{quote(cache_name)}.txt"
            cache_path = os.path.join(SYNOPSIS_CACHE_DIR, cache_file)
            
            if os.path.exists(cache_path):
                with open(cache_path, 'r', encoding='utf-8') as f:
                    self.synopsis = f.read()
                # Try to load metadata cache
                meta_file = cache_file.replace('.txt', '_meta.txt')
                meta_path = os.path.join(SYNOPSIS_CACHE_DIR, meta_file)
                if os.path.exists(meta_path):
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = f.read().split('|')
                        if len(meta) == 3:
                            self.imdb_rating = float(meta[0]) if meta[0] != "None" else None
                            self.genres = meta[1].split(',') if meta[1] else []
                            self.release_year = meta[2] if meta[2] else self.search_year
                return

            # Fetch from TMDB
            params = {
                "api_key": TMDB_API_KEY,
                "query": self.search_title
            }
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
                # Try to match year first
                result_year = result.get("release_date", "")[:4] or result.get("first_air_date", "")[:4]
                if self.search_year and result_year == self.search_year:
                    overview = result.get("overview", "")
                    imdb_rating = result.get("vote_average", None)
                    genres = []
                    if "genre_ids" in result:
                        genres = [str(gid) for gid in result["genre_ids"]]
                    release_year = result_year
                    if overview:
                        break
            # Fallback: pick the first result with an overview
            if not overview:
                for result in data.get("results", []):
                    overview = result.get("overview", "")
                    imdb_rating = result.get("vote_average", None)
                    genres = []
                    if "genre_ids" in result:
                        genres = [str(gid) for gid in result["genre_ids"]]
                    release_year = result.get("release_date", "")[:4] or result.get("first_air_date", "")[:4]
                    if overview:
                        break

            # Try to resolve genre names (optional, simple mapping for demo)
            genre_map = {
                28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
                18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
                9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller",
                10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
                10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
            }
            genres_named = []
            for gid in genres:
                try:
                    genres_named.append(genre_map.get(int(gid), ""))
                except Exception:
                    pass
            genres_named = [g for g in genres_named if g]

            self.imdb_rating = imdb_rating
            self.genres = genres_named
            self.release_year = release_year

            if overview:
                os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    f.write(overview)
                # Save metadata cache
                meta_file = cache_file.replace('.txt', '_meta.txt')
                meta_path = os.path.join(SYNOPSIS_CACHE_DIR, meta_file)
                with open(meta_path, 'w', encoding='utf-8') as f:
                    f.write(f"{imdb_rating}|{','.join(genres_named)}|{release_year}")
                self.synopsis = overview
        except Exception as e:
            logging.error(f"Error loading synopsis for {self.display_name}: {str(e)}")
            self.synopsis = "Synopsis not available"

    def get_file_info(self, file_path):
        """Return file size, and try to get duration and resolution if possible."""
        info = []
        # File size
        try:
            size_bytes = os.path.getsize(file_path)
            size_mb = size_bytes / (1024 * 1024)
            info.append(f"Size: {size_mb:.1f} MB")
        except Exception:
            pass
        # Try to get duration and resolution using ffprobe (if available)
        try:
            import subprocess, json
            cmd = [
                "ffprobe", "-v", "error", "-select_streams", "v:0",
                "-show_entries", "stream=width,height,duration",
                "-of", "json", file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            data = json.loads(result.stdout)
            if "streams" in data and data["streams"]:
                stream = data["streams"][0]
                if "width" in stream and "height" in stream:
                    info.append(f"Resolution: {stream['width']}x{stream['height']}")
                if "duration" in stream:
                    try:
                        seconds = float(stream["duration"])
                        mins = int(seconds // 60)
                        secs = int(seconds % 60)
                        info.append(f"Duration: {mins}:{secs:02d} min")
                    except Exception:
                        pass
        except Exception:
            pass
        return " | ".join(info)

class MediaOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Netflix-Style Media Organizer")
        self.setGeometry(100, 100, 1200, 800)
        
        # Load custom Netflix fonts
        self.load_custom_fonts()
        # Set dark theme (after fonts are loaded)
        self.set_dark_theme()
        
        # Create main widget and layout
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QHBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        # Create sidebar
        self.create_sidebar()
        
        # Create main content area
        self.create_main_content()
        
        # Initialize media lists
        self.update_media_lists()
        
        # Set window icon
        self.setWindowIcon(QIcon(self.create_netflix_icon()))
    
    def load_custom_fonts(self):
        font_dir = os.path.join(os.path.dirname(__file__), "assets", "fonts")
        if os.path.exists(font_dir):
            QFontDatabase.addApplicationFont(os.path.join(font_dir, "NetflixSans-Bold.otf"))
            QFontDatabase.addApplicationFont(os.path.join(font_dir, "NetflixSans-Medium.otf"))
            QFontDatabase.addApplicationFont(os.path.join(font_dir, "NetflixSans-Regular.otf"))
        else:
            # Fallback to system fonts if custom fonts not found
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
        dark_palette.setColor(QPalette.Highlight, QColor(229, 9, 20))  # Netflix red
        dark_palette.setColor(QPalette.HighlightedText, Qt.white)
        self.setPalette(dark_palette)
        
        self.setStyleSheet("""
            QMainWindow {
                background-color: #141414;
            }
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 8px 16px;
                font-size: 14px;
                border-radius: 4px;
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
                min-width: 100px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
            QListWidget {
                background-color: #141414;
                border: none;
                outline: none;
                font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Arial', sans-serif;
                color: white;
            }
            QListWidget::item {
                border-radius: 4px;
                width: 150px;
                height: 225px;
                margin: 10px;
                background-color: #2D2D2D;
            }
            QListWidget::item:hover {
                background-color: #3D3D3D;
                transform: scale(1.05);
            }
            QListWidget::item:selected {
                background-color: #E50914;
                border: 2px solid #FFFFFF;
            }
            QLabel {
                color: white;
                font-size: 16px;
                font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Arial', sans-serif;
            }
            QScrollArea {
                background-color: #141414;
                border: none;
            }
            QScrollBar:vertical {
                background: #2D2D2D;
                width: 10px;
                margin: 0px;
            }
            QScrollBar::handle:vertical {
                background: #5D5D5D;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                background: none;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
            QFrame {
                background-color: #141414;
                border: none;
            }
            QDialog {
                background-color: #141414;
            }
            QLineEdit {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #5D5D5D;
                border-radius: 4px;
                padding: 5px;
                font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Arial', sans-serif;
            }
            QTextEdit {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #5D5D5D;
                border-radius: 4px;
                padding: 5px;
                font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Arial', sans-serif;
            }
        """)
    
    def create_netflix_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))  # Transparent background
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor(229, 9, 20))  # Netflix red
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
        painter.end()
        return pixmap

    def create_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(220)
        self.sidebar.setStyleSheet("background-color: #000000;")
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(20, 30, 20, 30)
        self.sidebar_layout.setSpacing(30)
        
        # Netflix-style logo
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
        
        # Navigation buttons
        nav_buttons = [
            ("Movies", lambda: self.stacked_widget.setCurrentIndex(0)),
            ("TV Series", self.show_series_window),
            ("Sort Files", self.show_sort_confirmation),
        ]
        
        for text, callback in nav_buttons:
            btn = QPushButton(text)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(callback)
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
            self.sidebar_layout.addWidget(btn)

        # --- Refresh Button ---
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setCursor(Qt.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh_all)
        refresh_btn.setStyleSheet("""
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
        self.sidebar_layout.addWidget(refresh_btn)
        # --- End Refresh Button ---

        self.sidebar_layout.addStretch()
        
        # Settings button
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
            }
            QPushButton:hover {
                background-color: #2D2D2D;
            }
        """)
        self.sidebar_layout.addWidget(self.settings_button)
        
        self.main_layout.addWidget(self.sidebar)

    # --- Fast Refresh logic using QThread ---
    def refresh_all(self):
        """Clear cache and refresh media lists asynchronously."""
        self.setEnabled(False)
        self.cache_thread = CacheClearThread()
        self.cache_thread.finished.connect(self._on_refresh_done)
        self.cache_thread.start()

    def _on_refresh_done(self):
        self.update_media_lists()
        self.populate_series_list()
        self.setEnabled(True)
        QMessageBox.information(self, "Refreshed", "Cache cleared and media lists refreshed!")
    # --- End refresh logic ---

    def create_main_content(self):
        self.content_area = QFrame()
        self.content_area.setStyleSheet("background-color: #141414;")
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(0, 0, 0, 0)
        self.content_layout.setSpacing(0)
        
        # Create a stacked widget for different views
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet("border: none;")
        
        # Movies view
        self.movies_view = self.create_media_view("Movies")
        self.stacked_widget.addWidget(self.movies_view)
        
        # Series list view
        self.series_list_view = self.create_series_list_view()
        self.stacked_widget.addWidget(self.series_list_view)
        
        # Episodes view
        self.episodes_view = QWidget()
        self.episodes_layout = QVBoxLayout(self.episodes_view)
        self.episodes_layout.setContentsMargins(40, 20, 40, 20)
        self.episodes_layout.setSpacing(20)
        self.stacked_widget.addWidget(self.episodes_view)
        
        # Details view
        self.details_view = QWidget()
        self.details_layout = QVBoxLayout(self.details_view)
        self.details_layout.setContentsMargins(40, 20, 40, 20)
        self.details_layout.setSpacing(20)
        self.stacked_widget.addWidget(self.details_view)
        
        self.content_layout.addWidget(self.stacked_widget)
        self.main_layout.addWidget(self.content_area, 1)

    def create_media_view(self, title):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none;")
        
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 20, 40, 40)
        layout.setSpacing(20)
        
        # Title with Netflix-style gradient underline
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
        
        # Gradient underline
        underline = QWidget()
        underline.setFixedHeight(3)
        underline.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #E50914, stop:0.5 #B00710, stop:1 #E50914);
        """)
        title_layout.addWidget(underline)
        
        layout.addWidget(title_container)
        
        # Media list
        media_list = QListWidget()
        media_list.setViewMode(QListWidget.IconMode)
        media_list.setResizeMode(QListWidget.Adjust)
        media_list.setMovement(QListWidget.Static)
        media_list.setSpacing(20)
        media_list.setIconSize(QSize(150, 225))
        media_list.setGridSize(QSize(170, 270))
        media_list.setStyleSheet("""
            QListWidget {
                border: none;
                outline: none;
            }
            QListWidget::item {
                border-radius: 8px;
                transition: all 0.2s ease;
            }
            QListWidget::item:hover {
                transform: scale(1.05);
            }
        """)
        
        if title == "Movies":
            self.movies_list = media_list
            media_list.itemClicked.connect(self.show_media_details)
        else:
            self.series_list = media_list
            media_list.itemClicked.connect(self.show_series_episodes)
        
        layout.addWidget(media_list)
        scroll_area.setWidget(container)
        return scroll_area
    
    def create_series_list_view(self):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("border: none;")
        
        container = QWidget()
        container.setStyleSheet("background-color: #141414;")
        layout = QVBoxLayout(container)
        layout.setContentsMargins(40, 20, 40, 40)
        layout.setSpacing(20)
        
        # Title with Netflix-style gradient underline
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
        
        # Gradient underline
        underline = QWidget()
        underline.setFixedHeight(3)
        underline.setStyleSheet("""
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #E50914, stop:0.5 #B00710, stop:1 #E50914);
        """)
        title_layout.addWidget(underline)
        
        layout.addWidget(title_container)
        
        # Series list
        self.series_list = QListWidget()
        self.series_list.setViewMode(QListWidget.IconMode)
        self.series_list.setResizeMode(QListWidget.Adjust)
        self.series_list.setMovement(QListWidget.Static)
        self.series_list.setSpacing(20)
        self.series_list.setIconSize(QSize(150, 225))
        self.series_list.setGridSize(QSize(170, 270))
        self.series_list.setStyleSheet("""
            QListWidget {
                border: none;
                outline: none;
            }
            QListWidget::item {
                border-radius: 8px;
                transition: all 0.2s ease;
            }
            QListWidget::item:hover {
                transform: scale(1.05);
            }
        """)
        self.series_list.itemClicked.connect(self.show_series_episodes)
        
        layout.addWidget(self.series_list)
        self.populate_series_list()
        
        scroll_area.setWidget(container)
        return scroll_area

    def populate_series_list(self):
        self.series_list.clear()
        if os.path.exists(series_folder):
            for series_name in sorted(os.listdir(series_folder)):
                series_path = os.path.join(series_folder, series_name)
                if os.path.isdir(series_path):
                    item = QListWidgetItem(series_name)
                    poster_path = self.find_series_poster(series_path)
                    if poster_path:
                        # Create a pixmap with gradient overlay
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
                        # Use Netflix-style placeholder for series without posters
                        item.setIcon(QIcon(self.create_series_placeholder(series_name)))
                    item.setData(Qt.UserRole, series_path)
                    self.series_list.addItem(item)

    def create_series_placeholder(self, series_name):
        """Create a Netflix-style placeholder for series"""
        pixmap = QPixmap(150, 225)
        pixmap.fill(QColor(20, 20, 20))  # Netflix dark background
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Draw a gradient overlay
        gradient = QLinearGradient(0, 0, 0, pixmap.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 150))
        gradient.setColorAt(1, QColor(0, 0, 0, 50))
        painter.fillRect(pixmap.rect(), gradient)
        
        # Draw a red "N" like Netflix logo
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(55, 30, 40, 165)
        painter.setBrush(QColor(140, 0, 0))
        painter.drawRect(65, 30, 20, 165)
        
        # Draw the title in white, bold, centered
        painter.setPen(QColor(255, 255, 255))
        font = QFont('Netflix Sans', 10, QFont.Bold)
        painter.setFont(font)
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
            params = {
                "api_key": TMDB_API_KEY,
                "query": series_name
            }
            if year:
                params["first_air_date_year"] = year
            search_url = f"{TMDB_API_URL}/search/tv"
            response = requests.get(search_url, params=params)
            response.raise_for_status()
            data = response.json()
            poster_path = None
            # Try to match year first
            for result in data.get("results", []):
                result_year = result.get("first_air_date", "")[:4]
                if year and result_year == year:
                    poster_path = result.get("poster_path")
                    if poster_path:
                        break
            # Fallback: pick the first result with a poster
            if not poster_path:
                for result in data.get("results", []):
                    poster_path = result.get("poster_path")
                    if poster_path:
                        break
            if poster_path:
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
        self.populate_series_list()
        self.stacked_widget.setCurrentIndex(1)

    def show_series_episodes(self, item):
        series_path = item.data(Qt.UserRole)
        if not series_path:
            return

        # Clear previous content
        for i in reversed(range(self.episodes_layout.count())):
            widget = self.episodes_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

        # --- Back button ---
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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        self.episodes_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # --- Banner with poster or placeholder ---
        banner_height = 120
        banner_label = QLabel()
        poster_path = self.find_series_poster(series_path)
        if poster_path and os.path.exists(poster_path):
            pixmap = QPixmap(poster_path)
        else:
            pixmap = self.create_series_placeholder(item.text())
        banner = self.create_poster_banner(pixmap, width=900, height=banner_height)
        banner_label.setPixmap(banner)
        banner_label.setFixedHeight(banner_height)
        banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.episodes_layout.addWidget(banner_label)

        # Series info (title, metadata, synopsis)
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
        # --- Fetch synopsis and metadata ---
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

        # --- Scrollable, compact episodes list ---
        episodes_scroll = QScrollArea()
        episodes_scroll.setWidgetResizable(True)
        episodes_scroll.setStyleSheet("border: none; background: transparent;")
        episodes_container = QWidget()
        episodes_list_layout = QVBoxLayout(episodes_container)
        episodes_list_layout.setContentsMargins(0, 0, 0, 0)
        episodes_list_layout.setSpacing(10)

        for root, _, files in os.walk(series_path):
            for file in sorted(files):
                if any(file.lower().endswith(ext) for ext in media_extensions):
                    file_path = os.path.join(root, file)
                    episode_item = ImageItem(file_path)
                    # --- Compact episode widget ---
                    episode_widget = QWidget()
                    ep_layout = QHBoxLayout(episode_widget)
                    ep_layout.setContentsMargins(8, 4, 8, 4)
                    ep_layout.setSpacing(10)
                    icon_label = QLabel()
                    icon_label.setPixmap(episode_item.icon().pixmap(40, 60))
                    icon_label.setFixedSize(40, 60)
                    ep_layout.addWidget(icon_label)
                    text_label = QLabel(episode_item.text())
                    text_label.setStyleSheet("color: white; font-size: 14px;")
                    ep_layout.addWidget(text_label)
                    ep_layout.addStretch()
                    episode_widget.setStyleSheet("""
                        background-color: #232323;
                        border-radius: 6px;
                    """)
                    # Click event
                    episode_widget.mousePressEvent = lambda e, ep=episode_item: self.show_media_details(ep)
                    episodes_list_layout.addWidget(episode_widget)

        episodes_list_layout.addStretch()
        episodes_scroll.setWidget(episodes_container)
        self.episodes_layout.addWidget(episodes_scroll, 1)
        self.stacked_widget.setCurrentIndex(2)

    def get_series_synopsis(self, series_path, return_meta=False):
        """Get synopsis and metadata for a TV series"""
        try:
            series_name = os.path.basename(series_path)
            year = extract_year(series_name)
            # Check cache first
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
            # Fetch from TMDB
            params = {
                "api_key": TMDB_API_KEY,
                "query": series_name
            }
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
            for result in data.get("results", []):
                result_year = result.get("first_air_date", "")[:4]
                if year and result_year == year:
                    overview = result.get("overview", "")
                    imdb_rating = result.get("vote_average", None)
                    genres = []
                    if "genre_ids" in result:
                        genres = [str(gid) for gid in result["genre_ids"]]
                    if overview:
                        break
            if not overview:
                for result in data.get("results", []):
                    overview = result.get("overview", "")
                    imdb_rating = result.get("vote_average", None)
                    genres = []
                    if "genre_ids" in result:
                        genres = [str(gid) for gid in result["genre_ids"]]
                    result_year = result.get("first_air_date", "")[:4]
                    if overview:
                        break
            # Try to resolve genre names (same as above)
            genre_map = {
                28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy", 80: "Crime", 99: "Documentary",
                18: "Drama", 10751: "Family", 14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
                9648: "Mystery", 10749: "Romance", 878: "Sci-Fi", 10770: "TV Movie", 53: "Thriller",
                10752: "War", 37: "Western", 10759: "Action & Adventure", 10762: "Kids", 10763: "News",
                10764: "Reality", 10765: "Sci-Fi & Fantasy", 10766: "Soap", 10767: "Talk", 10768: "War & Politics"
            }
            genres_named = []
            for gid in genres:
                try:
                    genres_named.append(genre_map.get(int(gid), ""))
                except Exception:
                    pass
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

    # --- Banner helper for details view ---
    def create_poster_banner(self, pixmap, width=900, height=180):
        """Create a banner with the poster blended as a top background gradient."""
        if pixmap.isNull():
            banner = QPixmap(width, height)
            banner.fill(QColor(20, 20, 20))
            return banner
        # Scale poster to fit banner height
        scaled = pixmap.scaledToHeight(height, Qt.SmoothTransformation)
        banner = QPixmap(width, height)
        banner.fill(Qt.transparent)
        painter = QPainter(banner)
        # Draw the poster, centered horizontally
        x = (width - scaled.width()) // 2
        painter.drawPixmap(x, 0, scaled)
        # Overlay a vertical gradient (fade to dark)
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.7, QColor(20, 20, 20, 220))
        gradient.setColorAt(1, QColor(20, 20, 20, 255))
        painter.fillRect(banner.rect(), gradient)
        painter.end()
        return banner

    def show_media_details(self, item):
        """Show detailed view for a movie or episode"""
        # Clear previous content
        for i in reversed(range(self.details_layout.count())):
            widget = self.details_layout.itemAt(i).widget()
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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # --- Poster banner at the top ---
        icon = item.icon()
        if not icon.isNull():
            banner_label = QLabel()
            pixmap = icon.pixmap(600, 900)
            banner = self.create_poster_banner(pixmap)
            banner_label.setPixmap(banner)
            banner_label.setFixedHeight(180)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.details_layout.addWidget(banner_label)

        # Details content
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)

        # Title
        title_label = QLabel(item.text())
        title_label.setStyleSheet("""
            font-size: 28px; 
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            margin-bottom: 10px;
        """)
        details_layout.addWidget(title_label)

        # --- Metadata line (year, genres, IMDb) ---
        meta_parts = []
        if getattr(item, "release_year", None):
            meta_parts.append(str(item.release_year))
        if getattr(item, "genres", None):
            meta_parts.append(", ".join(item.genres))
        if getattr(item, "imdb_rating", None):
            meta_parts.append(f"IMDb: ★ {item.imdb_rating:.1f}")
        metadata_label = QLabel(" • ".join(meta_parts))
        metadata_label.setStyleSheet("font-size: 16px; color: #AAAAAA; margin-bottom: 20px;")
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
        synopsis_text.setPlainText(item.synopsis if hasattr(item, 'synopsis') and item.synopsis else "Synopsis not available")
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #5D5D5D;
                border-radius: 4px;
                padding: 10px;
                font-size: 14px;
            }
        """)
        synopsis_text.setFixedHeight(150)
        details_layout.addWidget(synopsis_text)

        # Play button
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
        self.stacked_widget.setCurrentIndex(3)

    def extract_season_episode(self, filename):
        """Extract season and episode numbers from filename"""
        match = re.search(r'[Ss](\d+)[Ee](\d+)', filename, re.IGNORECASE)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return None

    def update_media_lists(self):
        self.movies_list.clear()
        if os.path.exists(movies_folder):
            for root, _, files in os.walk(movies_folder):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        file_path = os.path.join(root, file)
                        item = ImageItem(file_path)
                        self.movies_list.addItem(item)

    def show_sort_confirmation(self):
        """Show confirmation dialog before sorting files"""
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

    def play_media(self, item):
        try:
            file_path = getattr(item, "file_path", None)
            if not file_path:
                return

            print(f"Trying to play: {file_path}")  # Add this line for debugging

            # Remove or comment out the animation line below
            # self.animate_click(item)
            
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
    
    def animate_click(self, item):
        animation = QPropertyAnimation(item, b"iconSize")
        animation.setDuration(200)
        animation.setEasingCurve(QEasingCurve.OutQuad)
        animation.setStartValue(QSize(150, 225))
        animation.setEndValue(QSize(160, 240))
        animation.start()
        
        animation2 = QPropertyAnimation(item, b"iconSize")
        animation2.setDuration(200)
        animation2.setEasingCurve(QEasingCurve.InQuad)
        animation2.setStartValue(QSize(160, 240))
        animation2.setEndValue(QSize(150, 225))
        animation.finished.connect(animation2.start)
    
    def sort_files(self):
        try:
            for downloads_folder in downloads_folders:
                if os.path.exists(downloads_folder):
                    self.process_downloads_folder(downloads_folder)
                else:
                    logging.error(f"Downloads folder not found: {downloads_folder}")
            self.update_media_lists()
            
            # Show success notification
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setText("Files have been sorted successfully!")
            msg.setWindowTitle("Success")
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
                    file_name_with_spaces = self.replace_underscores_and_dots(file_name)
                    if self.is_series(file_name_with_spaces):
                        series_name, season = self.get_series_info(file_name_with_spaces)
                        if series_name:
                            series_folder_path = os.path.join(series_folder, series_name, season)
                            self.move_file(file_path, series_folder_path, file_name)
                        else:
                            self.move_file(file_path, movies_folder, file_name)
                    else:
                        self.move_file(file_path, movies_folder, file_name)
            except Exception as e:
                logging.error(f"Failed to process {file_name}: {str(e)}")
    
    def replace_underscores_and_dots(self, file_name):
        return file_name.replace('_', ' ').replace('.', ' ')
    
    def is_series(self, file_name):
        series_pattern = re.compile(r'.*[Ss](\d{1,2})[Ee](\d{1,2})', re.IGNORECASE)
        return series_pattern.search(file_name)
    
    def get_series_info(self, file_name):
        match = re.search(r'(.+?)[Ss](\d{1,2})[Ee](\d{1,2})', file_name, re.IGNORECASE)
        if match:
            series_name = match.group(1).strip()
            season = f"Season {int(match.group(2))}"
            return series_name, season
        return None, None
    
    def get_unique_filename(self, dest_folder, file_name):
        base_name, extension = os.path.splitext(file_name)
        unique_name = file_name
        counter = 1
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
        settings_dialog.setWindowTitle("Settings")
        settings_dialog.setFixedSize(500, 350)
        settings_dialog.setStyleSheet("""
            QDialog {
                background-color: #141414;
            }
            QLabel {
                color: white;
            }
            QLineEdit {
                background-color: #2D2D2D;
                color: white;
                border: 1px solid #5D5D5D;
                border-radius: 4px;
                padding: 5px;
            }
        """)
        
        layout = QVBoxLayout()
        
        # Title
        title = QLabel("Settings")
        title.setStyleSheet("""
            font-size: 24px; 
            font-weight: bold; 
            color: #E50914;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
            padding-bottom: 10px;
            border-bottom: 2px solid #E50914;
        """)
        layout.addWidget(title)
        
        # Movies folder settings
        movies_group = QWidget()
        movies_layout = QVBoxLayout(movies_group)
        movies_layout.setContentsMargins(0, 10, 0, 10)
        
        movies_label = QLabel("Movies Folder:")
        movies_label.setStyleSheet("font-size: 16px;")
        movies_layout.addWidget(movies_label)
        
        movies_edit_layout = QHBoxLayout()
        self.movies_folder_edit = QLineEdit(movies_folder)
        movies_edit_layout.addWidget(self.movies_folder_edit)
        
        movies_browse = QPushButton("Browse")
        movies_browse.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        movies_browse.clicked.connect(self.browse_movies_folder)
        movies_edit_layout.addWidget(movies_browse)
        
        movies_layout.addLayout(movies_edit_layout)
        layout.addWidget(movies_group)
        
        # Series folder settings
        series_group = QWidget()
        series_layout = QVBoxLayout(series_group)
        series_layout.setContentsMargins(0, 10, 0, 10)
        
        series_label = QLabel("TV Series Folder:")
        series_label.setStyleSheet("font-size: 16px;")
        series_layout.addWidget(series_label)
        
        series_edit_layout = QHBoxLayout()
        self.series_folder_edit = QLineEdit(series_folder)
        series_edit_layout.addWidget(self.series_folder_edit)
        
        series_browse = QPushButton("Browse")
        series_browse.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 5px 10px;
                border-radius: 4px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        series_browse.clicked.connect(self.browse_series_folder)
        series_edit_layout.addWidget(series_browse)
        
        series_layout.addLayout(series_edit_layout)
        layout.addWidget(series_group)
        
        # Save button
        save_button = QPushButton("Save Settings")
        save_button.setStyleSheet("""
            QPushButton {
                background-color: #E50914;
                color: white;
                border: none;
                padding: 10px;
                font-size: 16px;
                border-radius: 4px;
                margin-top: 20px;
            }
            QPushButton:hover {
                background-color: #F40612;
            }
        """)
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button)
        
        settings_dialog.setLayout(layout)
        settings_dialog.exec_()
    
    def browse_movies_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Movies Folder", movies_folder)
        if folder:
            self.movies_folder_edit.setText(folder)
    
    def browse_series_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select TV Series Folder", series_folder)
        if folder:
            self.series_folder_edit.setText(folder)
    
    def save_settings(self):
        global movies_folder, series_folder
        new_movies_folder = self.movies_folder_edit.text()
        new_series_folder = self.series_folder_edit.text()
        if new_movies_folder != movies_folder or new_series_folder != series_folder:
            movies_folder = new_movies_folder
            series_folder = new_series_folder
            self.update_media_lists()
            
            # Show a stylish notification
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Information)
            msg.setText("Folder settings have been updated.")
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
            QMessageBox.information(self, "Settings", "No changes were made to folder settings.")

    # --- Add this helper to blend poster with dark background ---
    def blend_poster_pixmap(self, pixmap):
        """Return a pixmap with a dark gradient overlay for blending."""
        if pixmap.isNull():
            return pixmap
        overlay = QPixmap(pixmap.size())
        overlay.fill(Qt.transparent)
        painter = QPainter(overlay)
        gradient = QLinearGradient(0, 0, 0, overlay.height())
        gradient.setColorAt(0, QColor(0, 0, 0, 180))
        gradient.setColorAt(1, QColor(0, 0, 0, 60))
        painter.fillRect(overlay.rect(), gradient)
        painter.end()
        blended = QPixmap(pixmap)
        painter = QPainter(blended)
        painter.drawPixmap(0, 0, overlay)
        painter.end()
        return blended

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not os.path.exists(movies_folder):
        os.makedirs(movies_folder)
    if not os.path.exists(series_folder):
        os.makedirs(series_folder)
    os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
    os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
    window = MediaOrganizerApp()
    window.show()
    sys.exit(app.exec_())
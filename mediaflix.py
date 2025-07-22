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
                            QSizePolicy, QSpacerItem, QTextEdit, QComboBox, QGroupBox, QGridLayout, QMenu)
from PyQt5.QtCore import Qt, QSize, QTimer, QPoint, QPropertyAnimation, QEasingCurve, QThread, pyqtSignal, QObject
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QPalette, QPainter, QFontDatabase, QLinearGradient
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
POSTER_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "posters")
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
        for cache_dir in [POSTER_CACHE_DIR, SYNOPSIS_CACHE_DIR]:
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
        font = QFont('Netflix Sans', 10, QFont.Bold)
        painter.setFont(font)
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
    """Thread-safe poster loader with signals"""
    poster_loaded = pyqtSignal(object, QPixmap)  # label, pixmap
    poster_failed = pyqtSignal(object, str)      # label, fallback_icon
    
    def load_poster(self, label, poster_path, fallback_icon):
        """Load poster in background thread and emit signal when done"""
        def load_image():
            try:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                
                response = requests.get(image_url, timeout=10)
                if response.status_code == 200:
                    
                    pixmap = QPixmap()
                    success = pixmap.loadFromData(response.content)
                    
                    if success and not pixmap.isNull():
                        self.poster_loaded.emit(label, pixmap)
                        return
                
                self.poster_failed.emit(label, fallback_icon)
                
            except Exception as e:
                self.poster_failed.emit(label, fallback_icon)
        
        threading.Thread(target=load_image, daemon=True).start()

class MediaOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mediiaflix")
        
        # Set minimum size and initial size, but allow full resizing
        self.setMinimumSize(800, 600)  # Minimum usable size
        self.resize(1200, 800)  # Initial size
        
        self.current_season = None
        self.active_tab = None  # Track the active tab
        self.current_content_filter = "movie"  # Default content filter for home tab (Movies)
        
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
        
        self.load_custom_fonts()
        self.set_dark_theme()
        
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
        
        # Setup automatic content rotation timer (refresh every 10 minutes)
        self.auto_refresh_timer = QTimer()
        self.auto_refresh_timer.timeout.connect(self.auto_refresh_home_content)
        self.auto_refresh_timer.start(600000)  # 10 minutes = 600,000 milliseconds
        
        self.setWindowIcon(QIcon(self.create_netflix_icon()))

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
        font_dir = os.path.join(os.path.dirname(__file__), "assets", "fonts")
        if os.path.exists(font_dir):
            QFontDatabase.addApplicationFont(os.path.join(font_dir, "NetflixSans-Bold.otf"))
            QFontDatabase.addApplicationFont(os.path.join(font_dir, "NetflixSans-Medium.otf"))
            QFontDatabase.addApplicationFont(os.path.join(font_dir, "NetflixSans-Regular.otf"))

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
    font-family: Segoe UI, Arial, sans-serif;
}
QLineEdit, QListWidget, QTextEdit {
    background-color: #222222;
    color: #ffffff;
    border: 1px solid #444444;
}
QPushButton {
    background-color: #e50914;
    color: #ffffff;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #b00610;
}
QGroupBox, QLabel {
    color: #ffffff;
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
        """Extract movie title by removing file extensions and year"""
        clean = name.replace('.', ' ').replace('_', ' ')
        match = re.search(r'(19|20)\d{2}', clean)
        if match:
            return clean[:match.start()].strip()
        return clean.strip()

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
            (self.home_button, lambda: self.stacked_widget.setCurrentIndex(0)),
            (self.movies_button, lambda: self.stacked_widget.setCurrentIndex(1)),
            (self.series_button, self.show_series_window),
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
                }
                QPushButton:hover {
                    background-color: #2D2D2D;
                }
                QPushButton:checked {
                    background-color: #E50914;
                    font-weight: bold;
                }
            """)
            btn.setCheckable(True)
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
            }
            QPushButton:hover {
                background-color: #2D2D2D;
            }
        """)
        self.sort_button.setCheckable(False)  # Don't allow persistent checking
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
            }
            QPushButton:hover {
                background-color: #2D2D2D;
            }
        """)
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
        """Create the Netflix-style home discovery view with movies by genre"""
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
        
        # Title
        title_container = QWidget()
        title_container.setFixedHeight(60)
        title_layout = QVBoxLayout(title_container)
        title_layout.setContentsMargins(0, 0, 0, 0)
        
        title_label = QLabel("Discover Movies & Shows")
        title_label.setStyleSheet("""
            font-size: 28px; 
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
                font-family: 'Netflix Sans Medium', 'Netflix Sans', 'Arial', sans-serif;
            }
            QPushButton:hover {
                color: white;
                background-color: rgba(255, 255, 255, 0.1);
            }
            QPushButton:checked {
                background-color: #E50914;
                color: white;
                font-weight: bold;
            }
        """
        
        self.movies_filter_btn.setStyleSheet(toggle_button_style)
        self.series_filter_btn.setStyleSheet(toggle_button_style)
        
        toggle_layout.addWidget(self.movies_filter_btn)
        toggle_layout.addWidget(self.series_filter_btn)
        
        # Set Movies as default
        self.movies_filter_btn.setChecked(True)
        self.current_content_filter = "movie"
        
        filter_layout.addWidget(toggle_container)
        
        # Add stretch to push refresh button to far right
        filter_layout.addStretch()
        
        # Add reload button on the far right
        self.reload_home_btn = QPushButton("⟳")  # Standard refresh symbol
        self.reload_home_btn.setFixedHeight(45)
        self.reload_home_btn.setFixedWidth(45)  # Square button for icon
        self.reload_home_btn.clicked.connect(self.reload_home_content)
        self.reload_home_btn.setToolTip("Refresh content")  # Tooltip for clarity
        self.reload_home_btn.setStyleSheet("""
            QPushButton {
                background-color: #2D2D2D;
                color: #FFFFFF;
                border: none;
                padding: 0px;
                font-size: 18px;
                font-weight: bold;
                border-radius: 22px;
                font-family: Arial, sans-serif;
            }
            QPushButton:hover {
                background-color: #E50914;
                color: white;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
        """)
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
        
        # Load content asynchronously immediately - faster initial load
        QTimer.singleShot(10, self.load_home_content_async)  # Reduced from 50ms to 10ms
        
        return scroll_area

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
            font-weight: bold; 
            color: white;
            font-family: 'Netflix Sans Bold', 'Netflix Sans', 'Arial', sans-serif;
        """)
        text_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(text_label)
        
        # Sub text
        sub_label = QLabel("Discovering the best movies and shows for you")
        sub_label.setStyleSheet("""
            font-size: 14px; 
            color: #AAAAAA;
            font-family: 'Netflix Sans', 'Arial', sans-serif;
        """)
        sub_label.setAlignment(Qt.AlignCenter)
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
            font-family: 'Netflix Sans', 'Arial', sans-serif;
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
                font-family: Arial, sans-serif;
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
            ("⚡ Action & Adventure", 10759),  # Action & Adventure
            ("🎭 Animation", 16),  # Animation
            ("😄 Comedy", 35),  # Comedy
            ("🚔 Crime", 80),  # Crime
            ("� Documentary", 99),  # Documentary
            ("🎬 Drama", 18),  # Drama
            ("👨‍👩‍👧‍👦 Family", 10751),  # Family
            ("👶 Kids", 10762),  # Kids
            ("🔍 Mystery", 9648),  # Mystery
            ("� News", 10763),  # News
            ("📺 Reality", 10764),  # Reality
            ("🌌 Sci-Fi & Fantasy", 10765),  # Sci-Fi & Fantasy
            ("🧼 Soap", 10766),  # Soap
            ("💬 Talk", 10767),  # Talk
            ("⚔️ War & Politics", 10768),  # War & Politics
            ("🤠 Western", 37),  # Western
            ("💖 Romance", 10749),  # Romance (using movie genre ID as TV doesn't have dedicated romance)
            ("😱 Horror", 27),  # Horror (using movie genre ID)
            ("� Music", 10402),  # Music (using movie genre ID)
            ("🎪 Variety Show", 10767),  # Using Talk genre for variety shows
            ("🏥 Medical Drama", 18),  # Using Drama genre for medical shows
            ("🎓 Educational", 99),  # Using Documentary for educational content
            ("🎮 Game Show", 10764),  # Using Reality for game shows
            ("� Travel", 99),  # Using Documentary for travel shows
            ("🍳 Cooking", 10764),  # Using Reality for cooking shows
            ("� Home & Garden", 10764),  # Using Reality for home improvement
            ("� Business", 10763),  # Using News for business content
            ("⚽ Sports", 10763),  # Using News for sports content
            ("🧠 Psychological Thriller", 9648)  # Using Mystery for psychological content
        ]
        
        # Load more genres initially to show variety, then load remaining - optimized for speed
        if current_filter == "movie":
            self.load_priority_genres(parent_layout, movie_genres[:4], "movie")  # Reduced from 6 to 4 for faster initial load
            # Load remaining genres after a delay
            QTimer.singleShot(500, lambda: self.load_remaining_genres(parent_layout, movie_genres[4:], "movie"))
        elif current_filter == "tv":
            self.load_priority_genres(parent_layout, tv_genres[:5], "tv")  # Reduced from 8 to 5 for faster initial load
            # Load remaining genres after a delay
            QTimer.singleShot(500, lambda: self.load_remaining_genres(parent_layout, tv_genres[5:], "tv"))

    def load_priority_genres(self, parent_layout, genres, content_type):
        """Load priority genres immediately for faster initial display - optimized"""
        # Load fewer initial genres for faster startup
        priority_count = 4 if content_type == "movie" else 5  # Reduced counts for faster loading
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
        scroll_area.setFixedHeight(240)
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
        scroll_area.setFixedHeight(240)
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
            
            # Fetch from 1 page initially for faster loading
            for page in [current_page]:  # Start with just one page for speed
                if genre_id == "trending":
                    # For "Trending" section, use trending TV shows
                    url = f"{TMDB_API_URL}/trending/tv/week"
                    params = {"api_key": TMDB_API_KEY, "page": page}
                else:
                    # For specific genres, discover TV series with better popularity filters
                    url = f"{TMDB_API_URL}/discover/tv"
                    
                    # Special handling for romance genre for better content
                    if genre_id == 10749:  # Romance genre - special handling for shows like "Never Have I Ever"
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_genres": genre_id,
                            "sort_by": "popularity.desc",  # Sort by popularity to get trending romance shows
                            "vote_average.gte": 5.5,       # Lower threshold for romance shows
                            "vote_count.gte": 20,          # Lower vote count to include newer shows
                            "first_air_date.gte": "2005-01-01",  # Include shows from 2005 onwards for variety
                            "page": page,
                            "with_original_language": "en"  # Focus on English shows for better variety
                        }
                    # Special handling for genres that need different criteria
                    elif genre_id == 27:  # Horror genre
                        params = {
                            "api_key": TMDB_API_KEY,
                            "with_genres": genre_id,
                            "sort_by": "popularity.desc",  # Use popularity instead of vote count for horror
                            "vote_average.gte": 5.0,       # Lower minimum rating for horror
                            "vote_count.gte": 10,          # Lower vote requirement
                            "first_air_date.gte": "2000-01-01",  # Longer time range
                            "page": page
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
            
            # Load up to 20 series initially for faster display
            series = all_series[:20]  # Reduced from 40 to 20 for faster initial load
            for i, show in enumerate(series):
                series_widget = self.create_home_series_item_fast(show)
                layout.addWidget(series_widget)
                
                # Process events every 5 items to keep UI responsive
                if i % 5 == 0:
                    QApplication.processEvents()
                
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
        
        # Poster image with placeholder
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        
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
        series_widget.setFixedSize(140, 210)
        series_widget.setStyleSheet("""
            QWidget {
                background-color: #222;
                border-radius: 8px;
            }
            QWidget:hover {
                background-color: #333;
                border: 2px solid #E50914;
            }
        """)
        series_widget.setCursor(Qt.PointingHandCursor)
        
        layout = QVBoxLayout(series_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # Poster image with placeholder
        poster_label = QLabel()
        poster_label.setFixedSize(140, 210)
        poster_label.setScaledContents(True)
        poster_label.setAlignment(Qt.AlignCenter)
        
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

    def load_poster_async(self, label, poster_path, fallback_icon):
        """Load poster image asynchronously using signal-slot mechanism"""
        self.poster_loader.load_poster(label, poster_path, fallback_icon)

    def show_home_series_details(self, series_data):
        """Show detailed view for a discovered TV series with trailer option"""
        # Clear previous content
        for i in reversed(range(self.home_details_layout.count())):
            widget = self.home_details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.home_details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Banner with backdrop image (Netflix-style horizontal banner)
        backdrop_path = series_data.get("backdrop_path")
        if backdrop_path:
            try:
                # Use w1280 backdrop for high quality Netflix-style banner
                image_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}"
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    if not pixmap.isNull():
                        # Create responsive Netflix-style banner that adapts to window size
                        banner_label = QLabel()
                        banner_label.setPixmap(pixmap)  # Store original pixmap
                        banner_label.setScaledContents(True)  # Enable automatic scaling
                        banner_label.setFixedHeight(300)
                        banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                        banner_label.setStyleSheet("""
                            QLabel {
                                border-radius: 8px;
                                background-color: #222;
                            }
                        """)
                        # Store pixmap for dynamic resizing
                        banner_label.original_pixmap = pixmap
                        banner_label.resizeEvent = lambda event: self.resize_banner(banner_label, event)
                        self.home_details_layout.addWidget(banner_label)
            except (requests.ConnectionError, requests.Timeout):
                logging.error("No internet connection for backdrop image")
                # Add placeholder banner for no internet with Netflix styling
                no_image_label = QLabel("📺 No Internet Connection")
                no_image_label.setStyleSheet("""
                    background-color: #333;
                    color: #E50914;
                    font-size: 24px;
                    font-weight: bold;
                    padding: 100px;
                    border-radius: 12px;
                    border: 2px solid #555;
                """)
                no_image_label.setAlignment(Qt.AlignCenter)
                no_image_label.setFixedHeight(300)
                self.home_details_layout.addWidget(no_image_label)
            except Exception as e:
                logging.error(f"Error loading backdrop: {str(e)}")
                # Add error placeholder with better styling
                error_label = QLabel("🎬 Error Loading Banner")
                error_label.setStyleSheet("""
                    background-color: #333;
                    color: #FFA500;
                    font-size: 24px;
                    font-weight: bold;
                    padding: 100px;
                    border-radius: 12px;
                    border: 2px solid #555;
                """)
                error_label.setAlignment(Qt.AlignCenter)
                error_label.setFixedHeight(300)
                self.home_details_layout.addWidget(error_label)

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
        synopsis_text.setPlainText(series_data.get("overview", "No synopsis available"))
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
            }
        """)
        synopsis_text.setFixedHeight(150)
        details_layout.addWidget(synopsis_text)

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
        self.home_details_layout.addWidget(details_widget)
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
        # Clear previous content
        for i in reversed(range(self.home_details_layout.count())):
            widget = self.home_details_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)

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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.home_details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Banner with backdrop image (Netflix-style horizontal banner)
        backdrop_path = movie_data.get("backdrop_path")
        if backdrop_path:
            try:
                # Use w1280 backdrop for high quality Netflix-style banner
                image_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}"
                response = requests.get(image_url, timeout=5)
                if response.status_code == 200:
                    pixmap = QPixmap()
                    pixmap.loadFromData(response.content)
                    if not pixmap.isNull():
                        # Create responsive Netflix-style banner that adapts to window size
                        banner_label = QLabel()
                        banner_label.setPixmap(pixmap)  # Store original pixmap
                        banner_label.setScaledContents(True)  # Enable automatic scaling
                        banner_label.setFixedHeight(300)
                        banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                        banner_label.setStyleSheet("""
                            QLabel {
                                border-radius: 8px;
                                background-color: #222;
                            }
                        """)
                        # Store pixmap for dynamic resizing
                        banner_label.original_pixmap = pixmap
                        banner_label.resizeEvent = lambda event: self.resize_banner(banner_label, event)
                        self.home_details_layout.addWidget(banner_label)
            except (requests.ConnectionError, requests.Timeout):
                logging.error("No internet connection for backdrop image")
                # Add placeholder banner for no internet with Netflix styling
                no_image_label = QLabel("🎬 No Internet Connection")
                no_image_label.setStyleSheet("""
                    background-color: #333;
                    color: #E50914;
                    font-size: 24px;
                    font-weight: bold;
                    padding: 100px;
                    border-radius: 12px;
                    border: 2px solid #555;
                """)
                no_image_label.setAlignment(Qt.AlignCenter)
                no_image_label.setFixedHeight(300)
                self.home_details_layout.addWidget(no_image_label)
            except Exception as e:
                logging.error(f"Error loading backdrop: {str(e)}")
                # Add error placeholder with better styling
                error_label = QLabel("🎬 Error Loading Banner")
                error_label.setStyleSheet("""
                    background-color: #333;
                    color: #FFA500;
                    font-size: 24px;
                    font-weight: bold;
                    padding: 100px;
                    border-radius: 12px;
                    border: 2px solid #555;
                """)
                error_label.setAlignment(Qt.AlignCenter)
                error_label.setFixedHeight(300)
                self.home_details_layout.addWidget(error_label)
            except Exception as e:
                logging.error(f"Error loading backdrop: {str(e)}")

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

        # Metadata
        meta_parts = []
        if movie_data.get("release_date"):
            year = movie_data["release_date"][:4]
            meta_parts.append(year)
        if movie_data.get("vote_average"):
            rating = movie_data["vote_average"]
            meta_parts.append(f"★ {rating:.1f}")
        if movie_data.get("runtime"):
            runtime = movie_data["runtime"]
            hours = runtime // 60
            minutes = runtime % 60
            meta_parts.append(f"{hours}h {minutes}m")
        
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
        synopsis_text.setPlainText(movie_data.get("overview", "No synopsis available"))
        synopsis_text.setReadOnly(True)
        synopsis_text.setStyleSheet("""
            QTextEdit {
                background-color: transparent;
                color: white;
                border: none;
                padding: 10px;
                font-size: 14px;
            }
        """)
        synopsis_text.setFixedHeight(150)
        details_layout.addWidget(synopsis_text)

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
        self.home_details_layout.addWidget(details_widget)
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
            self.movies_list.itemClicked.connect(self.show_media_details)
            
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
        if os.path.exists(series_folder):
            for series_name in sorted(os.listdir(series_folder)):
                series_path = os.path.join(series_folder, series_name)
                if os.path.isdir(series_path):
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
        self.populate_series_list()
        self.stacked_widget.setCurrentIndex(2)

    def show_series_episodes(self, item):
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

        # Banner with backdrop from TMDB or fallback to poster
        backdrop_used = False
        series_name = item.text()
        backdrop_data = self.get_tmdb_series_backdrop(series_name)
        
        if backdrop_data:
            backdrop_path = backdrop_data.get("backdrop_path")
            if backdrop_path:
                try:
                    # Use w1280 backdrop for high quality Netflix-style banner
                    image_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}"
                    response = requests.get(image_url, timeout=5)
                    if response.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(response.content)
                        if not pixmap.isNull():
                            # Create responsive Netflix-style banner that adapts to window size
                            banner_label = QLabel()
                            banner_label.setPixmap(pixmap)  # Store original pixmap
                            banner_label.setScaledContents(True)  # Enable automatic scaling
                            banner_label.setFixedHeight(300)
                            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                            banner_label.setStyleSheet("""
                                QLabel {
                                    border-radius: 8px;
                                    background-color: #222;
                                }
                            """)
                            # Store pixmap for dynamic resizing
                            banner_label.original_pixmap = pixmap
                            banner_label.resizeEvent = lambda event: self.resize_banner(banner_label, event)
                            self.episodes_layout.addWidget(banner_label)
                            backdrop_used = True
                except (requests.ConnectionError, requests.Timeout, Exception):
                    pass  # Fall back to poster banner
        
        # Fallback to poster banner if backdrop failed
        if not backdrop_used:
            banner_height = 120
            banner_label = QLabel()
            poster_path = self.find_series_poster(series_path)
            if poster_path and os.path.exists(poster_path):
                pixmap = QPixmap(poster_path)
            else:
                pixmap = self.create_series_placeholder(item.text())
            banner_label.setPixmap(pixmap)
            banner_label.setScaledContents(True)  # Enable automatic scaling
            banner_label.setFixedHeight(banner_height)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            banner_label.setStyleSheet("""
                QLabel {
                    border-radius: 8px;
                    background-color: #222;
                }
            """)
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
        for root, _, files in os.walk(series_path):
            if self.current_season and os.path.basename(root) != self.current_season:
                continue
                
            for file in sorted(files):
                if any(file.lower().endswith(ext) for ext in media_extensions):
                    file_path = os.path.join(root, file)
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
                    
                    season_ep = self.extract_season_episode(file)
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
                    episode_widget.mousePressEvent = lambda e, ep=episode_item: self.show_media_details(ep)
                    
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

    def create_poster_banner(self, pixmap, width=900, height=300):
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
        
        # Center the scaled image in the banner
        x = (width - scaled.width()) // 2
        y = (height - scaled.height()) // 2
        
        # Draw the image to fill the banner completely
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

    def show_media_details(self, item):
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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))  # Always go back to movies view
        self.details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Try to get TMDB backdrop for better banner
        backdrop_used = False
        movie_title = self.extract_movie_title(item.text())
        backdrop_data = self.get_tmdb_movie_backdrop(movie_title)
        
        if backdrop_data:
            backdrop_path = backdrop_data.get("backdrop_path")
            if backdrop_path:
                try:
                    # Use w1280 backdrop for high quality Netflix-style banner
                    image_url = f"https://image.tmdb.org/t/p/w1280{backdrop_path}"
                    response = requests.get(image_url, timeout=5)
                    if response.status_code == 200:
                        pixmap = QPixmap()
                        pixmap.loadFromData(response.content)
                        if not pixmap.isNull():
                            # Create responsive Netflix-style banner that adapts to window size
                            banner_label = QLabel()
                            banner_label.setPixmap(pixmap)  # Store original pixmap
                            banner_label.setScaledContents(True)  # Enable automatic scaling
                            banner_label.setFixedHeight(300)
                            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                            banner_label.setStyleSheet("""
                                QLabel {
                                    border-radius: 8px;
                                    background-color: #222;
                                }
                            """)
                            # Store pixmap for dynamic resizing
                            banner_label.original_pixmap = pixmap
                            banner_label.resizeEvent = lambda event: self.resize_banner(banner_label, event)
                            self.details_layout.addWidget(banner_label)
                            backdrop_used = True
                except (requests.ConnectionError, requests.Timeout, Exception):
                    pass  # Fall back to poster banner
        
        # Fallback to poster banner if backdrop failed
        if not backdrop_used and not item.icon().isNull():
            banner_label = QLabel()
            pixmap = item.icon().pixmap(600, 900)
            banner_label.setPixmap(pixmap)
            banner_label.setScaledContents(True)  # Enable automatic scaling
            banner_label.setFixedHeight(180)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            banner_label.setStyleSheet("""
                QLabel {
                    border-radius: 8px;
                    background-color: #222;
                }
            """)
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
        metadata_label.setStyleSheet("font-size: 16px; color: #AAAAAA; margin-bottom: 20px;")
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
        if os.path.exists(movies_folder):
            for root, _, files in os.walk(movies_folder):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        file_path = os.path.join(root, file)
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
        
        # Collect all media files first
        if os.path.exists(movies_folder):
            for root, _, files in os.walk(movies_folder):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        file_path = os.path.join(root, file)
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
                    series_name, season, year = extract_series_info(file_name_with_spaces)
                    if series_name and season:
                        series_folder_path = os.path.join(series_folder, series_name, season)
                        self.move_file(file_path, series_folder_path, file_name)
                    else:
                        self.move_file(file_path, movies_folder, file_name)
            except Exception as e:
                logging.error(f"Failed to process {file_name}: {str(e)}")
    
    def replace_underscores_and_dots(self, file_name):
        return file_name.replace('_', ' ').replace('.', ' ')
    
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
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #B00710;
                transform: translateY(0px);
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
                transform: translateY(-1px);
            }
            QPushButton:pressed {
                background-color: #1D1D1D;
                transform: translateY(0px);
            }
        """)
        refresh_all_btn.clicked.connect(lambda: self.close_settings_and_refresh(settings_dialog, "all"))
        refresh_layout.addWidget(refresh_all_btn)
        
        # Enhanced description with tips
        refresh_description = QLabel("""
<div style='line-height: 1.4;'>
<b style='color: #FFFFFF;'>💡 Tips:</b><br/>
• <b>Refresh Home:</b> Updates movie/TV recommendations with fresh content<br/>
• <b>Refresh All:</b> Clears cache and reloads all media libraries<br/>
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
                transform: translateY(-1px);
            }}
            QPushButton:pressed {{
                background-color: {color}AA;
                transform: translateY(0px);
            }}
        """

    def close_settings_and_refresh(self, dialog, refresh_type):
        """Close settings dialog and perform refresh"""
        dialog.close()
        if refresh_type == "home":
            self.reload_home_content()
        elif refresh_type == "all":
            self.refresh_all()

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
    if not os.path.exists(movies_folder):
        os.makedirs(movies_folder)
    if not os.path.exists(series_folder):
        os.makedirs(series_folder)
    os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
    os.makedirs(SYNOPSIS_CACHE_DIR, exist_ok=True)
    window = MediaOrganizerApp()
    window.show()
    sys.exit(app.exec_())   
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
                            QSizePolicy, QSpacerItem, QTextEdit, QComboBox, QGroupBox, QGridLayout)
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

class MediaOrganizerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mediiaflix")
        self.setGeometry(100, 100, 1200, 800)
        self.current_season = None
        self.active_tab = None  # Track the active tab
        
        self.load_custom_fonts()
        self.set_dark_theme()
        
        self.main_widget = QWidget()
        self.setCentralWidget(self.main_widget)
        self.main_layout = QHBoxLayout(self.main_widget)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)
        
        self.create_sidebar()
        self.create_main_content()
        self.update_media_lists()
        self.setWindowIcon(QIcon(self.create_netflix_icon()))
    
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

    def create_sidebar(self):
        self.sidebar = QFrame()
        self.sidebar.setFixedWidth(220)
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
        self.movies_button = QPushButton("Movies")
        self.series_button = QPushButton("TV Series")
        self.sort_button = QPushButton("Sort Files")
        
        nav_buttons = [
            (self.movies_button, lambda: self.stacked_widget.setCurrentIndex(0)),
            (self.series_button, self.show_series_window),
            (self.sort_button, self.show_sort_confirmation),
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
        
        # Set movies as default active tab
        self.set_active_tab(self.movies_button)
    
    def create_tab_handler(self, button, callback):
        def handler():
            self.set_active_tab(button)
            callback()
        return handler
    
    def set_active_tab(self, button):
        # Reset all buttons to inactive state
        for btn in [self.movies_button, self.series_button, self.sort_button]:
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
        self.update_media_lists()
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
                min-width: 300px;
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
                min-width: 300px;
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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(1))
        self.episodes_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        # Banner with poster or placeholder
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
                    episodes_list_layout.addWidget(episode_widget)

        episodes_list_layout.addStretch()
        episodes_scroll.setWidget(episodes_container)
        self.episodes_layout.addWidget(episodes_scroll, 1)
        self.stacked_widget.setCurrentIndex(2)
        
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

    def create_poster_banner(self, pixmap, width=900, height=180):
        if pixmap.isNull():
            banner = QPixmap(width, height)
            banner.fill(QColor(20, 20, 20))
            return banner
        
        scaled = pixmap.scaledToHeight(height, Qt.SmoothTransformation)
        banner = QPixmap(width, height)
        banner.fill(Qt.transparent)
        painter = QPainter(banner)
        x = (width - scaled.width()) // 2
        painter.drawPixmap(x, 0, scaled)
        
        gradient = QLinearGradient(0, 0, 0, height)
        gradient.setColorAt(0, QColor(0, 0, 0, 0))
        gradient.setColorAt(0.7, QColor(20, 20, 20, 220))
        gradient.setColorAt(1, QColor(20, 20, 20, 255))
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
        back_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0 if hasattr(self, 'movies_list') and item in [self.movies_list.item(i) for i in range(self.movies_list.count())] else 2))
        self.details_layout.addWidget(back_button, alignment=Qt.AlignLeft)

        if not item.icon().isNull():
            banner_label = QLabel()
            pixmap = item.icon().pixmap(600, 900)
            banner = self.create_poster_banner(pixmap)
            banner_label.setPixmap(banner)
            banner_label.setFixedHeight(180)
            banner_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
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
        settings_dialog.setWindowTitle("Settings")
        settings_dialog.setFixedSize(600, 500)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(20)
        
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
        
        # Scroll area for settings
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(15)
        
        # Folders group
        folders_group = QGroupBox("Folders")
        folders_layout = QGridLayout(folders_group)
        folders_layout.setContentsMargins(15, 15, 15, 15)
        folders_layout.setSpacing(15)
        
        # Movies folder
        movies_label = QLabel("Movies Folder:")
        folders_layout.addWidget(movies_label, 0, 0)
        
        self.movies_folder_edit = QLineEdit(movies_folder)
        folders_layout.addWidget(self.movies_folder_edit, 0, 1)
        
        movies_browse = QPushButton("Browse")
        movies_browse.clicked.connect(self.browse_movies_folder)
        folders_layout.addWidget(movies_browse, 0, 2)
        
        # Series folder
        series_label = QLabel("TV Series Folder:")
        folders_layout.addWidget(series_label, 1, 0)
        
        self.series_folder_edit = QLineEdit(series_folder)
        folders_layout.addWidget(self.series_folder_edit, 1, 1)
        
        series_browse = QPushButton("Browse")
        series_browse.clicked.connect(self.browse_series_folder)
        folders_layout.addWidget(series_browse, 1, 2)
        
        scroll_layout.addWidget(folders_group)
        
        # Downloads folders group
        downloads_group = QGroupBox("Downloads Folders (for sorting)")
        downloads_layout = QVBoxLayout(downloads_group)
        downloads_layout.setContentsMargins(15, 15, 15, 15)
        downloads_layout.setSpacing(10)
        
        self.downloads_list = QListWidget()
        self.downloads_list.setSelectionMode(QListWidget.SingleSelection)
        
        for folder in downloads_folders:
            item = QListWidgetItem(folder)
            self.downloads_list.addItem(item)
        
        downloads_layout.addWidget(self.downloads_list)
        
        # Buttons for managing download folders
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(10)
        
        add_btn = QPushButton("Add Folder")
        add_btn.clicked.connect(self.add_downloads_folder)
        buttons_layout.addWidget(add_btn)
        
        remove_btn = QPushButton("Remove Selected")
        remove_btn.clicked.connect(self.remove_downloads_folder)
        buttons_layout.addWidget(remove_btn)
        
        downloads_layout.addLayout(buttons_layout)
        scroll_layout.addWidget(downloads_group)
        
        scroll_layout.addStretch()
        scroll_area.setWidget(scroll_content)
        layout.addWidget(scroll_area)
        
        # Save button
        save_button = QPushButton("Save Settings")
        save_button.setStyleSheet("""
            QPushButton {
                padding: 10px;
                font-size: 16px;
            }
        """)
        save_button.clicked.connect(self.save_settings)
        layout.addWidget(save_button, alignment=Qt.AlignRight)
        
        settings_dialog.setLayout(layout)
        settings_dialog.exec_()
    
    def add_downloads_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Downloads Folder", home_directory)
        if folder:
            for i in range(self.downloads_list.count()):
                if self.downloads_list.item(i).text() == folder:
                    return
            self.downloads_list.addItem(QListWidgetItem(folder))
    
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
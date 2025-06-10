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
                            QMessageBox, QStackedWidget, QScrollArea, QFrame, QDialog, QLineEdit, QSizePolicy)
from PyQt5.QtCore import Qt, QSize, QTimer, QPoint
from PyQt5.QtGui import QIcon, QPixmap, QFont, QColor, QPalette, QPainter, QFontDatabase
import subprocess

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

# Set up logging
log_file = os.path.join(home_directory, "media_organizer.log")
logging.basicConfig(filename=log_file, level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def extract_year(name):
    match = re.search(r'(19|20)\d{2}', name)
    return match.group(0) if match else None

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

        # Start with a Netflix-style placeholder icon
        self.setIcon(QIcon(self.create_placeholder_image()))

        # Load the actual image in the background
        self.load_image_async()

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
        # Draw a red "N" like Netflix logo
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(229, 9, 20))
        painter.drawRect(55, 30, 40, 165)
        painter.setBrush(QColor(140, 0, 0))
        painter.drawRect(65, 30, 20, 165)
        # Draw the title in white, bold, centered
        painter.setPen(QColor(255, 255, 255))
        font = QFont('Arial', 12, QFont.Bold)
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
            if os.path.exists(cache_path):
                pixmap = QPixmap(cache_path)
                if not pixmap.isNull():
                    self.setIcon(QIcon(pixmap))
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
                    self.setIcon(QIcon(pixmap))
                    return

            # 3. Fetch from TMDB: always fallback to first result with a poster
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
                image_data = requests.get(image_url).content
                os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
                with open(cache_path, "wb") as f:
                    f.write(image_data)
                pixmap = QPixmap()
                pixmap.loadFromData(image_data)
                if not pixmap.isNull():
                    self.setIcon(QIcon(pixmap))
            # If no poster found, keep the Netflix-style placeholder
        except Exception as e:
            logging.error(f"Error loading image for {self.display_name}: {str(e)}")

def find_series_poster(self, folder_path):
    poster_names = ["poster.jpg", "folder.jpg", "cover.jpg"]
    # Special case for FOREVER
    if os.path.basename(folder_path).lower() == "forever":
        forever_cover = os.path.join(os.path.dirname(__file__), "assets", "forever_cover.jpg")
        if os.path.exists(forever_cover):
            return forever_cover
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

        # If the folder name is ALL CAPS, look for an exact match in TMDB results (case-sensitive)
        is_all_caps = series_name.isupper()
        for result in data.get("results", []):
            tmdb_name = result.get("name", "")
            result_year = result.get("first_air_date", "")[:4]
            if is_all_caps and tmdb_name.isupper() and tmdb_name == series_name:
                if (not year or result_year == year) and result.get("poster_path"):
                    poster_path = result.get("poster_path")
                    break
            elif not is_all_caps and year and result_year == year and tmdb_name.lower() == series_name.lower():
                if result.get("poster_path"):
                    poster_path = result.get("poster_path")
                    break

        # If no exact match, fallback to first result with a poster
        if not poster_path:
            for result in data.get("results", []):
                if result.get("poster_path"):
                    poster_path = result.get("poster_path")
                    break
        if poster_path:
            image_url = f"{TMDB_IMAGE_URL}{poster_path}"
            image_data = requests.get(image_url).content
            poster_path = os.path.join(folder_path, "poster.jpg")
            with open(poster_path, "wb") as f:
                f.write(image_data)
            return poster_path
        # If no poster found, return None (the UI will use the Netflix-style placeholder)
    except Exception as e:
        logging.error(f"Error finding poster for {folder_path}: {str(e)}")
    return None

class PosterListItem(QWidget):
    def __init__(self, icon_path, title, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(8)
        # Poster image
        label_icon = QLabel()
        if isinstance(icon_path, str) and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path)
        elif isinstance(icon_path, QIcon):
            pixmap = icon_path.pixmap(150, 225)
        elif isinstance(icon_path, QPixmap):
            pixmap = icon_path
        else:
            pixmap = QPixmap(150, 225)
            pixmap.fill(QColor(20, 20, 20))
        label_icon.setPixmap(pixmap.scaled(150, 225, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        label_icon.setAlignment(Qt.AlignCenter)
        label_icon.setMaximumSize(150, 225)
        label_icon.setMinimumSize(1, 1)
        label_icon.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(label_icon)
        # Title text
        label_text = QLabel(title)
        label_text.setAlignment(Qt.AlignCenter)
        label_text.setWordWrap(True)
        label_text.setStyleSheet("""
            color: white;
            font-size: 15px;
            font-weight: bold;
            font-family: 'Netflix Sans Medium', 'Arial', sans-serif;
        """)
        label_text.setMaximumHeight(40)
        layout.addWidget(label_text)

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
            }
            QPushButton:hover {
                background-color: #F40612;
            }
            QPushButton:pressed {
                background-color: #B00710;
            }
            QListWidget {
                background-color: #141414;
                border: 1px solid #303030;
                border-radius: 4px;
                font-family: 'Netflix Sans Regular', 'Netflix Sans', 'Arial', sans-serif;
                color: white;
            }
            QListWidget::item {
                border-bottom: 1px solid #303030;
                padding: 10px;
                width: 150px;
                height: 225px;
                margin: 10px;
            }
            QListWidget::item:hover {
                background-color: #303030;
            }
            QListWidget::item:selected {
                background-color: #E50914;
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
            QFrame {
                background-color: #141414;
                border: none;
            }
        """)
    
    def create_netflix_icon(self):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(0, 0, 0, 0))  # Transparent background
        painter = QPainter(pixmap)
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
        self.sidebar.setFixedWidth(200)
        self.sidebar_layout = QVBoxLayout(self.sidebar)
        self.sidebar_layout.setContentsMargins(10, 20, 10, 20)
        self.sidebar_layout.setSpacing(20)
        logo = QLabel("Media Organizer")
        logo.setStyleSheet("font-size: 20px; color: #E50914; font-weight: bold;")
        logo.setAlignment(Qt.AlignCenter)
        self.sidebar_layout.addWidget(logo)
        self.movies_button = QPushButton("Movies")
        self.movies_button.clicked.connect(lambda: self.stacked_widget.setCurrentIndex(0))
        self.sidebar_layout.addWidget(self.movies_button)
        self.series_button = QPushButton("TV Series")
        self.series_button.clicked.connect(self.show_series_window)
        self.sidebar_layout.addWidget(self.series_button)
        self.sort_button = QPushButton("Sort Files")
        self.sort_button.clicked.connect(self.sort_files)
        self.sidebar_layout.addWidget(self.sort_button)
        self.sidebar_layout.addStretch()
        self.settings_button = QPushButton("Settings")
        self.settings_button.clicked.connect(self.show_settings)
        self.sidebar_layout.addWidget(self.settings_button)
        self.main_layout.addWidget(self.sidebar)
    
    def create_main_content(self):
        self.content_area = QFrame()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(20, 20, 20, 20)
        self.content_layout.setSpacing(20)
        self.stacked_widget = QStackedWidget()
        self.movies_view = self.create_media_view("Movies")
        self.stacked_widget.addWidget(self.movies_view)
        self.series_list_view = self.create_series_list_view()
        self.stacked_widget.addWidget(self.series_list_view)
        self.episodes_view = QWidget()
        self.episodes_layout = QVBoxLayout(self.episodes_view)
        self.stacked_widget.addWidget(self.episodes_view)
        self.content_layout.addWidget(self.stacked_widget)
        self.main_layout.addWidget(self.content_area, 1)

    def create_media_view(self, title):
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        title_label = QLabel(title)
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #E50914;")
        layout.addWidget(title_label)
        media_list = QListWidget()
        media_list.setViewMode(QListWidget.IconMode)
        media_list.setResizeMode(QListWidget.Adjust)
        media_list.setMovement(QListWidget.Static)
        media_list.setSpacing(20)
        media_list.setIconSize(QSize(150, 225))
        media_list.setGridSize(QSize(170, 250))
        if title == "Movies":
            self.movies_list = media_list
            media_list.itemDoubleClicked.connect(self.play_media)
        else:
            self.series_list = media_list
            media_list.itemDoubleClicked.connect(self.show_series_episodes)
        layout.addWidget(media_list)
        scroll_area.setWidget(container)
        return scroll_area
    
    def create_series_list_view(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        title_label = QLabel("TV Series")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #E50914;")
        layout.addWidget(title_label)
        self.series_list = QListWidget()
        self.series_list.setViewMode(QListWidget.IconMode)
        self.series_list.setResizeMode(QListWidget.Adjust)
        self.series_list.setMovement(QListWidget.Static)
        self.series_list.setSpacing(20)
        self.series_list.setIconSize(QSize(150, 225))
        self.series_list.setGridSize(QSize(170, 250))
        self.series_list.setStyleSheet("color: white;")
        layout.addWidget(self.series_list)
        self.series_list.itemDoubleClicked.connect(self.show_series_episodes)
        self.populate_series_list()
        return container

    def populate_series_list(self):
        self.series_list.clear()
        if os.path.exists(series_folder):
            for series_name in sorted(os.listdir(series_folder)):
                series_path = os.path.join(series_folder, series_name)
                if os.path.isdir(series_path):
                    poster_path = self.find_series_poster(series_path)
                    # Use custom widget for better text appearance
                    item_widget = PosterListItem(poster_path if poster_path else self.get_folder_icon(), series_name)
                    item = QListWidgetItem()
                    item.setSizeHint(item_widget.sizeHint())
                    self.series_list.addItem(item)
                    self.series_list.setItemWidget(item, item_widget)
                    item.setData(Qt.UserRole, series_path)

    def find_series_poster(self, folder_path):
        poster_names = ["poster.jpg", "folder.jpg", "cover.jpg"]
        # Special case for FOREVER
        if os.path.basename(folder_path).lower() == "forever":
            forever_cover = os.path.join(os.path.dirname(__file__), "assets", "forever_cover.jpg")
            if os.path.exists(forever_cover):
                return forever_cover
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

            # If the folder name is ALL CAPS, look for an exact match in TMDB results (case-sensitive)
            is_all_caps = series_name.isupper()
            for result in data.get("results", []):
                tmdb_name = result.get("name", "")
                result_year = result.get("first_air_date", "")[:4]
                if is_all_caps and tmdb_name.isupper() and tmdb_name == series_name:
                    if (not year or result_year == year) and result.get("poster_path"):
                        poster_path = result.get("poster_path")
                        break
                elif not is_all_caps and year and result_year == year and tmdb_name.lower() == series_name.lower():
                    if result.get("poster_path"):
                        poster_path = result.get("poster_path")
                        break

            # If no exact match, fallback to first result with a poster
            if not poster_path:
                for result in data.get("results", []):
                    if result.get("poster_path"):
                        poster_path = result.get("poster_path")
                        break
            if poster_path:
                image_url = f"{TMDB_IMAGE_URL}{poster_path}"
                image_data = requests.get(image_url).content
                poster_path = os.path.join(folder_path, "poster.jpg")
                with open(poster_path, "wb") as f:
                    f.write(image_data)
                return poster_path
            # If no poster found, return None (the UI will use the Netflix-style placeholder)
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
        for i in reversed(range(self.episodes_layout.count())):
            widget = self.episodes_layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
        title_label = QLabel(f"Episodes - {item.text()}")
        title_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #E50914;")
        self.episodes_layout.addWidget(title_label)
        episodes_list = QListWidget()
        episodes_list.setViewMode(QListWidget.IconMode)
        episodes_list.setResizeMode(QListWidget.Adjust)
        episodes_list.setMovement(QListWidget.Static)
        episodes_list.setSpacing(10)
        episodes_list.setIconSize(QSize(150, 50))
        for root, _, files in os.walk(series_path):
            for file in sorted(files):
                if any(file.lower().endswith(ext) for ext in media_extensions):
                    file_path = os.path.join(root, file)
                    episode_item = ImageItem(file_path)
                    episodes_list.addItem(episode_item)
        episodes_list.itemDoubleClicked.connect(self.play_media)
        self.episodes_layout.addWidget(episodes_list)
        self.stacked_widget.setCurrentIndex(2)

    def update_media_lists(self):
        self.movies_list.clear()
        if os.path.exists(movies_folder):
            for root, _, files in os.walk(movies_folder):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in media_extensions):
                        file_path = os.path.join(root, file)
                        item = ImageItem(file_path)
                        self.movies_list.addItem(item)

    def get_folder_icon(self):
        return self.style().standardIcon(QApplication.style().SP_DirIcon)
    
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
            QMessageBox.information(self, "Success", "Files have been sorted successfully!")
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
        settings_dialog.setFixedSize(400, 300)
        layout = QVBoxLayout()
        label = QLabel("Media Folders Settings")
        label.setStyleSheet("font-size: 18px; font-weight: bold; color: #E50914;")
        layout.addWidget(label)
        movies_layout = QHBoxLayout()
        movies_label = QLabel("Movies Folder:")
        movies_layout.addWidget(movies_label)
        self.movies_folder_edit = QLineEdit(movies_folder)
        movies_layout.addWidget(self.movies_folder_edit)
        movies_browse = QPushButton("Browse")
        movies_browse.clicked.connect(self.browse_movies_folder)
        movies_layout.addWidget(movies_browse)
        layout.addLayout(movies_layout)
        series_layout = QHBoxLayout()
        series_label = QLabel("TV Series Folder:")
        series_layout.addWidget(series_label)
        self.series_folder_edit = QLineEdit(series_folder)
        series_layout.addWidget(self.series_folder_edit)
        series_browse = QPushButton("Browse")
        series_browse.clicked.connect(self.browse_series_folder)
        series_layout.addWidget(series_browse)
        layout.addLayout(series_layout)
        save_button = QPushButton("Save Settings")
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
            QMessageBox.information(self, "Settings Saved", "Folder settings have been updated.")
        else:
            QMessageBox.information(self, "Settings", "No changes were made to folder settings.")
    
    def organize_existing_series_files(self):
        for file_name in os.listdir(series_folder):
            file_path = os.path.join(series_folder, file_name)
            if os.path.isfile(file_path) and any(file_name.lower().endswith(ext) for ext in media_extensions):
                file_name_with_spaces = self.replace_underscores_and_dots(file_name)
                if self.is_series(file_name_with_spaces):
                    series_name, season = self.get_series_info(file_name_with_spaces)
                    if series_name:
                        series_folder_path = os.path.join(series_folder, series_name, season)
                        self.move_file(file_path, series_folder_path, file_name)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    if not os.path.exists(movies_folder):
        os.makedirs(movies_folder)
    if not os.path.exists(series_folder):
        os.makedirs(series_folder)
    os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
    window = MediaOrganizerApp()
    window.show()
    sys.exit(app.exec_())
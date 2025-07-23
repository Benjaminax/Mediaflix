#!/usr/bin/env python3
"""
Manual Backdrop Downloader for Mediaflix
Downloads all backdrops for your movies and series immediately
"""

import os
import sys
import requests
import logging
import time
from urllib.parse import quote

# Add current directory to path
sys.path.append(os.path.dirname(__file__))

# Import from your main app
home_directory = os.path.expanduser("~")
movies_folder = os.path.join(home_directory, "Videos", "Movies")
series_folder = os.path.join(home_directory, "Videos", "Series")
media_extensions = ['.mp4', '.mkv', '.avi', '.mov']

# TMDB API Configuration
TMDB_API_KEY = "875bd4ff3b965afae93faa3d789f6d7e"
TMDB_API_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w1280"  # High quality backdrops
BACKDROP_CACHE_DIR = os.path.join(home_directory, ".media_organizer_cache", "backdrops")

# Set up logging
log_file = os.path.join(home_directory, "backdrop_downloader.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)  # Also print to console
    ]
)

def extract_year(name):
    """Extract year from filename"""
    import re
    match = re.search(r'(19|20)\d{2}', name)
    return match.group() if match else None

def clean_movie_title(file_name):
    """Extract clean movie title from filename"""
    import re
    # Remove file extension
    name = os.path.splitext(file_name)[0]
    # Replace dots, underscores with spaces
    name = name.replace('.', ' ').replace('_', ' ')
    # Remove common tags
    name = re.sub(r'\b(720p|1080p|480p|YouthTrendx|WEB-DL|WEBRip|x264|x265|AAC|YTS\.MX|10bit)\b', '', name, flags=re.IGNORECASE)
    # Remove year and everything after
    year_match = re.search(r'(19|20)\d{2}', name)
    if year_match:
        name = name[:year_match.start()].strip()
    return name.strip()

def search_movie_backdrop(movie_title, year=None):
    """Search for movie backdrop on TMDB"""
    try:
        params = {"api_key": TMDB_API_KEY, "query": movie_title}
        if year:
            params["year"] = year
        
        response = requests.get(f"{TMDB_API_URL}/search/movie", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("results"):
            # Get the first result with a backdrop
            for result in data["results"]:
                if result.get("backdrop_path"):
                    return result["backdrop_path"]
        return None
        
    except Exception as e:
        logging.error(f"Error searching for movie {movie_title}: {e}")
        return None

def search_series_backdrop(series_name, year=None):
    """Search for TV series backdrop on TMDB"""
    try:
        params = {"api_key": TMDB_API_KEY, "query": series_name}
        if year:
            params["first_air_date_year"] = year
            
        response = requests.get(f"{TMDB_API_URL}/search/tv", params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("results"):
            # Get the first result with a backdrop
            for result in data["results"]:
                if result.get("backdrop_path"):
                    return result["backdrop_path"]
        return None
        
    except Exception as e:
        logging.error(f"Error searching for series {series_name}: {e}")
        return None

def download_backdrop(backdrop_path, cache_filename):
    """Download and save backdrop image"""
    try:
        if not backdrop_path:
            return False
            
        # Create cache directory if it doesn't exist
        os.makedirs(BACKDROP_CACHE_DIR, exist_ok=True)
        
        cache_filepath = os.path.join(BACKDROP_CACHE_DIR, cache_filename)
        
        # Skip if already cached
        if os.path.exists(cache_filepath):
            logging.info(f"Backdrop already cached: {cache_filename}")
            return True
            
        # Download backdrop
        image_url = f"{TMDB_IMAGE_URL}{backdrop_path}"
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        
        # Save to cache
        with open(cache_filepath, 'wb') as f:
            f.write(response.content)
            
        logging.info(f"Downloaded backdrop: {cache_filename}")
        return True
        
    except Exception as e:
        logging.error(f"Error downloading backdrop {cache_filename}: {e}")
        return False

def download_all_movie_backdrops():
    """Download backdrops for all movies"""
    logging.info("Starting movie backdrop downloads...")
    
    if not os.path.exists(movies_folder):
        logging.warning(f"Movies folder not found: {movies_folder}")
        return
        
    movie_count = 0
    success_count = 0
    
    for file_name in os.listdir(movies_folder):
        if any(file_name.lower().endswith(ext) for ext in media_extensions):
            movie_count += 1
            
            # Extract movie info
            clean_title = clean_movie_title(file_name)
            year = extract_year(file_name)
            
            logging.info(f"Processing movie: {clean_title} ({year if year else 'Unknown year'})")
            
            # Search for backdrop
            backdrop_path = search_movie_backdrop(clean_title, year)
            
            if backdrop_path:
                # Create cache filename
                cache_filename = f"movie_{clean_title.replace(' ', '_')}_{year if year else 'Unknown'}.jpg"
                
                # Download backdrop
                if download_backdrop(backdrop_path, cache_filename):
                    success_count += 1
            else:
                logging.warning(f"No backdrop found for movie: {clean_title}")
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
    
    logging.info(f"Movie backdrops complete: {success_count}/{movie_count} successful")

def download_all_series_backdrops():
    """Download backdrops for all TV series"""
    logging.info("Starting TV series backdrop downloads...")
    
    if not os.path.exists(series_folder):
        logging.warning(f"Series folder not found: {series_folder}")
        return
        
    series_count = 0
    success_count = 0
    
    for series_name in os.listdir(series_folder):
        series_path = os.path.join(series_folder, series_name)
        if os.path.isdir(series_path):
            series_count += 1
            
            # Extract series info
            year = extract_year(series_name)
            clean_name = series_name
            if year:
                clean_name = series_name.replace(year, '').strip()
                
            logging.info(f"Processing series: {clean_name} ({year if year else 'Unknown year'})")
            
            # Search for backdrop
            backdrop_path = search_series_backdrop(clean_name, year)
            
            if backdrop_path:
                # Create cache filename
                cache_filename = f"series_{clean_name.replace(' ', '_')}_{year if year else 'Unknown'}.jpg"
                
                # Download backdrop
                if download_backdrop(backdrop_path, cache_filename):
                    success_count += 1
            else:
                logging.warning(f"No backdrop found for series: {clean_name}")
            
            # Small delay to avoid rate limiting
            time.sleep(0.5)
    
    logging.info(f"Series backdrops complete: {success_count}/{series_count} successful")

def main():
    """Main function to download all backdrops"""
    logging.info("=== Starting Manual Backdrop Download ===")
    logging.info(f"Movies folder: {movies_folder}")
    logging.info(f"Series folder: {series_folder}")
    logging.info(f"Cache directory: {BACKDROP_CACHE_DIR}")
    
    start_time = time.time()
    
    # Test internet connection
    try:
        response = requests.get(f"{TMDB_API_URL}/configuration", params={"api_key": TMDB_API_KEY}, timeout=5)
        response.raise_for_status()
        logging.info("Internet connection and TMDB API confirmed working")
    except Exception as e:
        logging.error(f"Internet/API connection failed: {e}")
        return
    
    # Download movie backdrops
    download_all_movie_backdrops()
    
    # Download series backdrops  
    download_all_series_backdrops()
    
    end_time = time.time()
    duration = end_time - start_time
    
    # Show final summary
    cached_files = []
    if os.path.exists(BACKDROP_CACHE_DIR):
        cached_files = [f for f in os.listdir(BACKDROP_CACHE_DIR) if f.endswith('.jpg')]
    
    logging.info("=== Backdrop Download Complete ===")
    logging.info(f"Total time: {duration:.1f} seconds")
    logging.info(f"Total cached backdrops: {len(cached_files)}")
    logging.info(f"Cache directory: {BACKDROP_CACHE_DIR}")
    
    print(f"\n✅ Backdrop download completed!")
    print(f"📁 Cache location: {BACKDROP_CACHE_DIR}")
    print(f"🖼️  Total backdrops: {len(cached_files)}")
    print(f"⏱️  Time taken: {duration:.1f} seconds")

if __name__ == "__main__":
    main()

import os
import requests
from urllib.parse import quote

TMDB_API_KEY = "875bd4ff3b965afae93faa3d789f6d7e"
TMDB_API_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_URL = "https://image.tmdb.org/t/p/w500"

series_search = "Forever"
search_year = "2025"

home = os.path.expanduser("~")
POSTER_CACHE_DIR = os.path.join(home, ".media_organizer_cache", "posters")
BACKDROP_CACHE_DIR = os.path.join(home, ".media_organizer_cache", "backdrops")
os.makedirs(POSTER_CACHE_DIR, exist_ok=True)
os.makedirs(BACKDROP_CACHE_DIR, exist_ok=True)

params = {"api_key": TMDB_API_KEY, "query": series_search}
resp = requests.get(f"{TMDB_API_URL}/search/tv", params=params, timeout=10)
resp.raise_for_status()
data = resp.json()
results = data.get('results', [])

best = None
# prefer year matches
year_matches = [r for r in results if (r.get('first_air_date','')[:4]) == search_year]
if year_matches:
    for r in year_matches:
        if r.get('name','').lower() == series_search.lower():
            best = r
            break
    if not best:
        best = year_matches[0]
        TMD = {JOD=S66 }
        
        
        
        SHEHIHE = 'SHEHIHE'

# fallback to case-insensitive name match
if not best:
    for r in results:
        if r.get('name','').lower() == series_search.lower():
            best = r
            break

# final fallback
if not best and results:
    best = results[0]

if not best:
    print('No TMDB results found for', series_search)
    raise SystemExit(1)

print('Selected TMDB result:', best.get('name'), best.get('first_air_date'))
poster_path = best.get('poster_path')
backdrop_path = best.get('backdrop_path')

if poster_path:
    url = f"{TMDB_IMAGE_URL}{poster_path}"
    r = requests.get(url, timeout=15)
    if r.status_code == 200:
        safe = quote(f"{series_search} {search_year}")
        fname = os.path.join(POSTER_CACHE_DIR, f"{safe}.jpg")
        with open(fname, 'wb') as f:
            f.write(r.content)
        print('Wrote poster to', fname)

if backdrop_path:
    url = f"https://image.tmdb.org/t/p/original{backdrop_path}"
    r = requests.get(url, timeout=20)
    if r.status_code == 200:
        safe = quote(f"{series_search} {search_year}")
        fname = os.path.join(BACKDROP_CACHE_DIR, f"{safe}.jpg")
        with open(fname, 'wb') as f:
            f.write(r.content)
        print('Wrote backdrop to', fname)

print('Done')

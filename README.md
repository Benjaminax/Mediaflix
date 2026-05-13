# Mediaflix

Mediaflix is a modern streaming application that combines a Python-powered backend with a sleek React/TypeScript frontend. It allows you to organize, browse, and stream your local media collection with a beautiful, Netflix-inspired interface.

## Features

- **Modern UI:** Clean, responsive interface built with React, TypeScript, and Tailwind CSS.
- **Media Organization:** Automatically organizes movies and series from your local folders.
- **TMDB Integration:** Fetches metadata, posters, and backdrops from The Movie Database (TMDB).
- **Streaming & Playback:** Stream videos directly from your collection.
- **Cross-platform:** Works on Windows and other platforms with Python and Node.js.

## Getting started

### 1. Clone the repository

```bash
git clone https://github.com/Benjaminax/Mediaflix.git
cd Mediaflix
```

### 2. Install dependencies

#### Backend (Python)

```bash
pip install -r requirements.txt
```

#### Frontend (React)

```bash
cd frontend
npm install
```

### 3. Configure environment variables (if applicable)

If you use a `.env` file for the frontend or backend, copy and fill in the values:

```bash
cp .env.example .env
```

If you are on Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

Required variables in `.env` (example):

```env
TMDB_API_KEY=your-tmdb-api-key
```

### 4. Run the application

#### Backend

```bash
python mediaflix.py
```

#### Frontend

```bash
cd frontend
npm run dev
```

### 5. Build for production

```bash
cd frontend
npm run build
```

## API endpoints (if applicable)

- `GET /api/media` -> List all available media items
- `GET /api/media/:id` -> Get details for a specific media item
- `POST /api/refresh` -> Refresh the media library

**Request body example:**

```json
{
	"action": "refresh"
}
```

## Dependencies

- **PyQt5:** Python GUI framework for the desktop app.
- **Pillow:** Image processing for posters and backdrops.
- **requests:** HTTP requests for TMDB API.
- **React:** Frontend UI library.
- **TypeScript:** Type-safe JavaScript for frontend.
- **Tailwind CSS:** Utility-first CSS framework for styling.

## Project structure

```
Mediaflix/
├── backend/
│   ├── app.py
│   ├── requirements.txt
│   └── ...
├── frontend/
│   ├── package.json
│   ├── src/
│   │   ├── components/
│   │   ├── data/
│   │   ├── pages/
│   │   ├── screenshots/
│   │   └── ...
│   └── ...
├── mediaflix.py
├── requirements.txt
├── README.md
└── ...
```

## Screenshots

![Screenshot 1](frontend/src/screenshots/Screenshot%202026-05-13%20003000.png)
![Screenshot 2](frontend/src/screenshots/Screenshot%202026-05-13%20003023.png)
![Screenshot 3](frontend/src/screenshots/Screenshot%202026-05-13%20003034.png)
![Screenshot 4](frontend/src/screenshots/Screenshot%202026-05-13%20003048.png)

## Socials

If you have any questions, you can reach me here:

- **Instagram:** [@_.benjamin.a._](https://www.instagram.com/_.benjamin.a._/)
- **GitHub:** [Benjaminax](https://github.com/Benjaminax/)
- **Email:** kojoben29@gmail.com

In God we trust


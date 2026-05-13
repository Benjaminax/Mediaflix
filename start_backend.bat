@echo off
echo 🚀 Starting Mediaflix Backend API...
cd backend
call mediaflix_env\Scripts\activate.bat
python app.py
pause

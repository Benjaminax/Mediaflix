@echo off
echo 🎬 Starting Mediaflix Application...
echo ====================================

echo 🚀 Starting backend server...
start cmd /k "call start_backend.bat"

timeout /t 3 /nobreak > nul

echo 🌐 Starting frontend server...
start cmd /k "call start_frontend.bat"

timeout /t 3 /nobreak > nul

echo.
echo ✅ Mediaflix is running
echo 📱 Frontend: http://localhost:3000
echo 🔧 Backend API: http://localhost:5000
echo 🔍 API Health: http://localhost:5000/api/health
echo.
echo Close this window or press Ctrl+C in the server windows to stop
pause

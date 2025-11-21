@echo off
rem Build Mediaflix into a Windows executable using PyInstaller
rem Usage: run this from the project root in PowerShell or cmd.exe

echo Checking Python and pip...
python -V || (echo Python not found on PATH && exit /b 1)

echo Ensuring pip is up-to-date and PyInstaller is installed...
python -m pip install --upgrade pip
python -m pip install pyinstaller --quiet

echo Locating PyQt5 plugin directories...
for /f "usebackq delims=" %%P in (`python - <<^PY
import PyQt5, os
plugin_dir = os.path.join(os.path.dirname(PyQt5.__file__), 'Qt', 'plugins')
print(plugin_dir)
PY
`) do set PYQT_PLUGINS=%%P

if not defined PYQT_PLUGINS (
	echo Could not locate PyQt5 plugins automatically. Proceeding without explicit plugin inclusion.
)

echo Starting PyInstaller build (one-folder, windowed)...
set ADD_DATA_ARGS=--add-data "assets;assets" --add-data "backend;backend" --add-data "assets/fonts;assets/fonts"

rem If we found PyQt plugins, add platforms and styles to the bundle so Qt can find them at runtime
if defined PYQT_PLUGINS (
	echo Found PyQt plugins at %PYQT_PLUGINS%
	rem Normalize slashes for passing to PyInstaller on Windows
	set PLUGINS_DIR=%PYQT_PLUGINS%
	set ADD_DATA_ARGS=%ADD_DATA_ARGS% --add-data "%PLUGINS_DIR%\platforms;platforms" --add-data "%PLUGINS_DIR%\styles;styles"
)

pyinstaller --noconfirm --clean --onedir --windowed --icon="assets\app.ico" %ADD_DATA_ARGS% mediaflix.py

if %ERRORLEVEL% NEQ 0 (
	echo.
	echo Build failed with errorlevel %ERRORLEVEL%.
	exit /b %ERRORLEVEL%
)

echo.
echo Build complete. See the generated folder: dist\mediaflix
echo To run the app, open: dist\mediaflix\mediaflix.exe
pause

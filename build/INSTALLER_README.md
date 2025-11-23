Mediaflix Installer — build instructions

This README explains how to produce a Windows installer (with an uninstaller) for Mediaflix using Inno Setup.

Prerequisites
- You already built the single-file EXE with PyInstaller. The installer script expects `dist\mediaflix.exe` to exist.
- Install Inno Setup (https://jrsoftware.org/isinfo.php). The compiler `ISCC.exe` is typically installed to `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`.

Build steps (PowerShell)
1. Ensure the PyInstaller build is present. Include common Qt plugin folders so the bundled app runs on other PCs:
```powershell
# Example PyInstaller command (adjust the PyQt5 plugins path for your environment):
pyinstaller --noconfirm --onefile --windowed --icon="assets\app.ico" \
	--add-data "assets;assets" \
	--add-data "backend;backend" \
	--add-data "C:\Users\kojob\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyQt5\Qt5\plugins\platforms;platforms" \
	--add-data "C:\Users\kojob\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyQt5\Qt5\plugins\styles;styles" \
	--add-data "C:\Users\kojob\AppData\Local\Programs\Python\Python313\Lib\site-packages\PyQt5\Qt5\plugins\imageformats;imageformats" \
	mediaflix.py
```
2. Run the Inno Setup compiler to produce an installer. Adjust the ISCC path if you installed Inno Setup elsewhere:
```powershell
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "build\MediaflixInstaller.iss"
```
3. After compilation you'll find `Mediaflix_Installer.exe` in the Inno Setup output directory (by default the same folder as the .iss file). Run that installer to install Mediaflix.

What the installer does
- Installs `mediaflix.exe` and included files to `C:\Program Files\Mediaflix` (default).
- Creates a Start Menu shortcut and (optionally) a Desktop icon.
- Registers an uninstaller entry in Add/Remove Programs.
- Removes the install folder on uninstall.

Customizations you may want
- Add `imageformats`, `styles`, or other Qt plugin subfolders if the built exe requires them at runtime. Add extra `Source` lines in the `[Files]` section, or embed them into the exe with PyInstaller.
- Add a License file via `[LicenseFile]` and show license during install.
- Digitally sign the installer using `signtool.exe` for trust.

Troubleshooting
- If the installed app fails to run due to missing Qt plugins (errors mentioning "could not find the Qt platform plugin" or similar), include the needed subfolders from your Python environment's PyQt5 plugin path (for example `platforms`, `styles`, `imageformats`) or embed them with PyInstaller as shown above.
- On Windows you may also need the Microsoft Visual C++ Redistributable for Visual Studio to be present on target machines; if users see missing DLL errors, ask them to install the x64 VC++ redistributable (2015-2022) from Microsoft.
- If you want the installer to include other runtime files (e.g., config, user templates), add them under `[Files]`.

If you want, I can:
- Patch `mediaflix.py` to use `sys._MEIPASS` so bundled resources are found more reliably when the exe is executed, and then re-run the PyInstaller build.
- Add extra `[Files]` lines or folder copy logic for additional Qt plugin folders.

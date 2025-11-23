; Mediaflix Inno Setup installer script
; Place this file in the repository and build with Inno Setup (ISCC.exe)

[Setup]
AppName=Mediaflix
AppVersion=1.0
DefaultDirName={autopf}\Mediaflix
DefaultGroupName=Mediaflix
OutputBaseFilename=Mediaflix_Installer
Compression=lzma
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
DisableDirPage=no
DisableProgramGroupPage=no
Uninstallable=yes
PrivilegesRequired=admin

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
; The built single-file exe should be in dist\mediaflix.exe
Source: "..\dist\mediaflix.exe"; DestDir: "{app}"; Flags: ignoreversion
; Include the app icon so installer can reference it (optional)
Source: "..\assets\app.ico"; DestDir: "{app}"; Flags: ignoreversion
; If you want to install other small files (readme, license), add them here
; Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Mediaflix"; Filename: "{app}\mediaflix.exe"; IconFilename: "{app}\app.ico"
Name: "{commondesktop}\Mediaflix"; Filename: "{app}\mediaflix.exe"; Tasks: desktopicon; IconFilename: "{app}\app.ico"

[Run]
; Offer to run the app after install
Filename: "{app}\mediaflix.exe"; Description: "Launch Mediaflix"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Ensure the install folder is removed on uninstall
Type: filesandordirs; Name: "{app}"

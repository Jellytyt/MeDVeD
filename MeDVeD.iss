; Inno Setup script for MeDVeD. Wraps the PyInstaller *onedir* build
; (dist\MeDVeD\) into a single Setup.exe.
;
; Per-user install (PrivilegesRequired=lowest) into %LOCALAPPDATA%\Programs\MeDVeD
; so installs AND silent auto-updates never raise a UAC prompt. Because the app
; runs from a real folder (no temp self-extraction), the onefile "Failed to load
; Python DLL" first-run error cannot occur.
;
; Build locally:  iscc /DMyAppVersion=0.9.7 MeDVeD.iss
; CI passes the tag (without the leading v) as MyAppVersion.
; Output:         installer_output\MeDVeD-Setup-<version>.exe

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "MeDVeD"
#define MyAppExeName "MeDVeD.exe"
#define MyAppPublisher "Jellytyt"
#define MyAppURL "https://github.com/Jellytyt/MeDVeD"

[Setup]
; AppId ties every release together so upgrades replace in place and there is one
; uninstall entry. NEVER change this GUID once published.
AppId={{8A6F2C1E-6E2B-4E0A-9C3D-7F2B9E5A1D44}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=installer_output
OutputBaseFilename=MeDVeD-Setup-{#MyAppVersion}
SetupIconFile=assets\medved.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Close a running MeDVeD (via Restart Manager) before replacing its files. The
; auto-updater already waits for the old process to exit first, so this mainly
; covers a manual re-install over a running copy.
CloseApplications=yes
RestartApplications=no
ShowLanguageDialog=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\MeDVeD\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Launch after install. No "skipifsilent" flag on purpose: this MUST also run
; during a silent auto-update so the new version relaunches itself.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall runascurrentuser

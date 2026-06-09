; Inno Setup script for the YouTube -> Smash Ultimate converter.
;
; This wraps the PyInstaller ONE-FOLDER build (dist\YouTubeToSmash\) into a
; standard Windows setup.exe: installs into Program Files, creates Start Menu
; and (optional) desktop shortcuts, and registers an uninstaller.
;
; Build order:
;   1. From the project root:  pyinstaller yt2smash.spec
;      -> produces  dist\YouTubeToSmash\YouTubeToSmash.exe (+ yt2smash-cli.exe)
;   2. Open this file in Inno Setup Compiler (or run:  iscc installer\yt2smash.iss)
;      -> produces  installer\Output\YouTubeToSmash-Setup.exe
;
; Get Inno Setup (free): https://jrsoftware.org/isdl.php

#define MyAppName "YouTube to Smash Ultimate"
#define MyAppShortName "YouTubeToSmash"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "YouTube to Smash Ultimate"
#define MyAppExeName "YouTubeToSmash.exe"
; Path to the PyInstaller onedir output, relative to this .iss file.
#define DistDir "..\dist\YouTubeToSmash"

[Setup]
; A stable, unique AppId so upgrades and uninstall work across versions.
; Generate your own with the Inno Setup IDE (Tools > Generate GUID) if forking.
AppId={{8E5C0E2A-3B7D-4C6E-9F21-2A7B1D4E9C30}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-USER install: lands under %LocalAppData%\Programs, no admin / UAC prompt.
DefaultDirName={autopf}\{#MyAppShortName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; PrivilegesRequired=lowest installs for the current user only and needs no
; admin rights; with it, {autopf} resolves to %LocalAppData%\Programs and every
; shortcut/uninstaller is registered per-user. To switch back to a per-machine
; install for all users, set this to "admin" (which makes {autopf} = Program
; Files and prompts for elevation).
PrivilegesRequired=lowest
OutputDir=Output
OutputBaseFilename=YouTubeToSmash-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Uncomment if you provide an icon:
; SetupIconFile=..\assets\app.ico
; Uncomment to require accepting a licence during install:
; LicenseFile=..\LICENSE.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Recursively bundle the entire PyInstaller onedir output.
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Offer to launch the app at the end of setup.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

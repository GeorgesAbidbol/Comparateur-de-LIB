; Installeur Windows de Banane Pot (Inno Setup). Fabriqué par .github/workflows/windows.yml :
;   iscc /DAppVersion=0.5.2 packaging\banane-pot.iss
; Installation pour l'utilisateur seul (pas de droits administrateur), raccourci sur le bureau.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F0C1E5A-7B6E-4B7C-9D2B-BA7A7E907001}
AppName=Banane Pot
AppVersion={#AppVersion}
AppPublisher=Jo
DefaultDirName={autopf}\Banane Pot
DefaultGroupName=Banane Pot
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=Banane-Pot-Setup-v{#AppVersion}
SetupIconFile=..\src\ma3lib\data\banane-pot.ico
UninstallDisplayIcon={app}\Banane Pot.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Files]
Source: "..\dist\Banane Pot\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autodesktop}\Banane Pot"; Filename: "{app}\Banane Pot.exe"
Name: "{group}\Banane Pot"; Filename: "{app}\Banane Pot.exe"

[Run]
Filename: "{app}\Banane Pot.exe"; Description: "Lancer Banane Pot"; Flags: nowait postinstall skipifsilent

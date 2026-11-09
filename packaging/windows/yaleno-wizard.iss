; Inno-Setup-Skript für den Windows-Installer des Yaleno Wizard.
;
;   pyinstaller --noconfirm yaleno_wizard.spec
;   iscc /DAppVersion=0.1.0 packaging\windows\yaleno-wizard.iss
;   → dist\yaleno-wizard-setup-0.1.0.exe
;
; Installiert ohne Admin-Rechte für den aktuellen Benutzer (auf Wunsch für alle Benutzer),
; legt einen Eintrag mit Logo im Startmenü an (optional auf dem Desktop) und bringt eine
; Deinstallation mit (Einstellungen und gespeicherte Passwörter bleiben erhalten).

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppName "Yaleno Wizard"
#define AppExe "yaleno-wizard.exe"

[Setup]
; Feste Kennung – nie ändern, sonst gelten Updates als neues Programm.
AppId={{B702FD4F-CA05-42E9-A05B-BD3F14DF7220}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Nillan Hendrix
AppPublisherURL=https://github.com/NillanHendrix/Yaleno-Wizard
AppSupportURL=https://github.com/NillanHendrix/Yaleno-Wizard/issues
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist
OutputBaseFilename=yaleno-wizard-setup-{#AppVersion}
SetupIconFile=..\..\src\yaleno_wizard\assets\yaleno.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; laufende Instanzen (z. B. Hintergrund-Abgleich) vor dem Ersetzen schließen
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; Comment: "Dateien und Einstellungen zwischen Geräten abgleichen"
Name: "{group}\{#AppName} – Hintergrund-Abgleich"; Filename: "{app}\{#AppExe}"; Parameters: "--background"; Comment: "Abgleich im Hintergrund starten (Symbol im Infobereich)"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Autostart des Hintergrund-Abgleichs wird vom Programm gesetzt – bei der Deinstallation entfernen.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "yaleno-wizard"; Flags: uninsdeletevalue dontcreatekey

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
; Hintergrund-Abgleich beenden, damit die Datei gelöscht werden kann
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExe}"; Flags: runhidden; RunOnceId: "StopYalenoWizard"

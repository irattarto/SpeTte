; Inno Setup script: wraps the PyInstaller onedir build into a per-user installer.
; Build:  iscc /DAppVersion=0.1.0 packaging\windows\installer.iss   (run from the repository root)

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "SpeTte"
#define AppExe "SpeTte.exe"

[Setup]
AppId={{D7C1A2E4-5B3F-4A68-9E21-3F6B8C0D5A17}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=SpeTte
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Installs for the current user only: no administrator prompt
PrivilegesRequired=lowest
OutputDir=..\..\installer-output
OutputBaseFilename=SpeTte-Setup-x64
SetupIconFile=..\..\data\icons\app_icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/normal
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "..\..\dist\SpeTte\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
// Settings and downloaded models live in %LOCALAPPDATA%\SpeTte; ask before deleting them
// (never in a silent uninstall: the files are large and expensive to download again).
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\SpeTte');
    if DirExists(DataDir) and not UninstallSilent then
      if MsgBox('Also delete your SpeTte settings, downloaded speech models (' + DataDir + ')?',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;

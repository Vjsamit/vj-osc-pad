[Setup]
AppName=VJ Chaser
AppVersion=2.0
AppPublisher=VJ Samir
DefaultDirName={autopf}\VJ Chaser
DefaultGroupName=VJ Chaser
OutputDir=..\dist
OutputBaseFilename=VJChaser_Setup
SetupIconFile=editor\icon.ico
UninstallDisplayIcon={app}\VJChaserEditor.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern

[Files]
Source: "..\dist\VJChaserEditor.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\VJChaser.dll"; DestDir: "{userdocs}\Resolume Arena\Extra Effects"; Flags: ignoreversion
Source: "..\dist\VJChaser.dll"; DestDir: "{userdocs}\Resolume Avenue\Extra Effects"; Flags: ignoreversion; Check: AvenueExists
Source: "..\dist\VJChaser.dll"; DestDir: "{app}\plugin"; Flags: ignoreversion

[Icons]
Name: "{group}\VJ Chaser Editor"; Filename: "{app}\VJChaserEditor.exe"
Name: "{autodesktop}\VJ Chaser Editor"; Filename: "{app}\VJChaserEditor.exe"
Name: "{group}\Plugin folder"; Filename: "{app}\plugin"
Name: "{group}\Uninstall VJ Chaser"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\VJChaserEditor.exe"; Description: "VJ Chaser Editor abhi kholo"; Flags: nowait postinstall skipifsilent

[Code]
function AvenueExists: Boolean;
begin
  Result := DirExists(ExpandConstant('{userdocs}\Resolume Avenue'));
end;

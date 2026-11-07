[Setup]
AppName=VJ Pad Bridge
AppVersion=2.0
AppPublisher=VJ Samir
DefaultDirName={autopf}\VJ Pad Bridge
DefaultGroupName=VJ Pad Bridge
OutputDir=..\dist
OutputBaseFilename=VJPadBridge_Setup
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\VJPadBridge.exe
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=admin
WizardStyle=modern

[Files]
Source: "..\dist\VJPadBridge.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\VJ Pad Bridge"; Filename: "{app}\VJPadBridge.exe"
Name: "{autodesktop}\VJ Pad Bridge"; Filename: "{app}\VJPadBridge.exe"
Name: "{group}\Uninstall VJ Pad Bridge"; Filename: "{uninstallexe}"

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""VJ Pad Bridge"" dir=in action=allow program=""{app}\VJPadBridge.exe"" enable=yes profile=any"; Flags: runhidden
Filename: "{app}\VJPadBridge.exe"; Description: "VJ Pad Bridge abhi chalu karo"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""VJ Pad Bridge"""; Flags: runhidden; RunOnceId: "fw"

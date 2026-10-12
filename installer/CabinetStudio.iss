; Cabinet Studio per-user installer (Inno Setup 6). Build: ISCC.exe installer\CabinetStudio.iss
#define AppName "Cabinet Studio"
#define AppVersion "0.3.35"
#define AppPublisher "Warren Williams"
#define AppExe "CabinetStudio.exe"
#define Root "..\"
#define SrcDir Root + "builds\_new0335\CabinetStudio"
#define Manual "Cabinet-Studio-User-Manual"

[Setup]
AppId={{6C1F5D2A-8B3E-4F7A-9C21-CAB1E7570D10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
VersionInfoVersion={#AppVersion}.0
VersionInfoCompany={#AppPublisher}
VersionInfoProductName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=LICENSE.txt
InfoAfterFile=README-FIRST.txt
SetupIconFile={#Root}assets\cabinet_studio.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName} {#AppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Root}dist_share
OutputBaseFilename=CabinetStudio-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README-FIRST.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}docs\{#Manual}.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}docs\{#Manual}.pdf"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"
Name: "{group}\Cabinet Studio User Manual"; Filename: "{app}\{#Manual}.html"
Name: "{group}\Read me first"; Filename: "{app}\README-FIRST.txt"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

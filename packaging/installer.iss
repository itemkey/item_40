#ifndef AppVersion
  #define AppVersion "0.2.0"
#endif
[Setup]
#ifdef TestAppId
AppId={#TestAppId}
#else
AppId={{066C3D60-D933-4FBC-8C9E-D95B978C10AC}
#endif
AppName=item-40
AppVersion={#AppVersion}
AppPublisher=itemkey
AppPublisherURL=https://github.com/itemkey/item_40
#ifdef TestDefaultDir
DefaultDirName={#TestDefaultDir}
#else
DefaultDirName={localappdata}\Programs\item-40
#endif
DefaultGroupName=item-40
UsePreviousAppDir=yes
UsePreviousGroup=no
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=item-40-{#AppVersion}-windows-x64-setup
SetupIconFile=app.ico
UninstallDisplayIcon={app}\item-40.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\item-40\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: files; Name: "{app}\Masterskaya.exe"
#ifndef TestAppId
Type: files; Name: "{userprograms}\Мастерская\Мастерская.lnk"
Type: dirifempty; Name: "{userprograms}\Мастерская"
Type: files; Name: "{userdesktop}\Мастерская.lnk"
#endif

[Icons]
Name: "{group}\item-40"; Filename: "{app}\item-40.exe"
Name: "{autodesktop}\item-40"; Filename: "{app}\item-40.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; Flags: unchecked

[Run]
Filename: "{app}\item-40.exe"; Description: "Запустить item-40"; Flags: nowait postinstall skipifsilent

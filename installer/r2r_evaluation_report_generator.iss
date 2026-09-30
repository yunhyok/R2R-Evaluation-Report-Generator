#ifndef AppVersion
  #define AppVersion "0.5.0"
#endif
#define AppPublisher "Yunhyok"
#define AppExeName "R2REvaluationReportGenerator.exe"

#ifdef DisposableValidation
  #define AppId "{{2E42973D-7A33-4CF3-91FD-7A4C62ACCC4F}"
  #define AppName "R2R Evaluation Report Generator Disposable Validation"
  #define AppDirName "{localappdata}\Programs\R2R Evaluation Report Generator Disposable Validation"
  #define InstallerOutputDir "..\dist\installer\disposable"
  #define InstallerOutputName "R2R-Evaluation-Report-Generator-" + AppVersion + "-disposable-setup"
#else
  #define AppId "{{BFA7031A-FBC3-4878-8893-9B83A28587DA}"
  #define AppName "R2R Evaluation Report Generator"
  #define AppDirName "{localappdata}\Programs\R2R Evaluation Report Generator"
  #define InstallerOutputDir "..\dist\installer"
  #define InstallerOutputName "R2R-Evaluation-Report-Generator-" + AppVersion + "-setup"
#endif

[Setup]
AppId={#AppId}
AppName={#AppName}
AppVersion={#AppVersion}
VersionInfoVersion={#AppVersion}.0
AppPublisher={#AppPublisher}
PrivilegesRequired=lowest
DefaultDirName={#AppDirName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir={#InstallerOutputDir}
OutputBaseFilename={#InstallerOutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
CloseApplicationsFilter={#AppExeName}
RestartApplications=no
UninstallDisplayIcon={app}\{#AppExeName}
LicenseFile=..\LICENSE

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Files]
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "바탕 화면 바로 가기 만들기"; GroupDescription: "추가 아이콘:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{#AppName} 실행"; Flags: nowait postinstall skipifsilent

; Instalador de Corte con Inno Setup 6 (04 §A.13 y §D.4, texto literal). Inno Setup NO está autorizado hoy (BUILD_SPEC §12 #2):
; el entregable es el zip con Instalar.ps1. Si el usuario lo autoriza: build_windows.ps1 -InnoSetup (pasa /DVersion, /DOrigen, /DIcono).
; Guardado en UTF-8 con BOM para que ISCC lea bien los acentos. No compilado (ISCC no está instalado).
#ifndef Version
  #define Version "0.0.0"
#endif
[Setup]
AppId={{E7689AC7-E192-4F4D-BCC3-5669F4B4112B}
AppName=Corte
AppVersion={#Version}
AppVerName=Corte {#Version}
AppPublisher=Corte
DefaultDirName={localappdata}\Programs\CreatorHub
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputBaseFilename=CreatorHub-Setup-{#Version}
SetupIconFile={#Icono}
UninstallDisplayIcon={app}\CreatorHub.exe
UninstallDisplayName=Corte
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
CloseApplicationsFilter=CreatorHub.exe
RestartApplications=no
ShowLanguageDialog=no
VersionInfoVersion={#Version}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el Escritorio"

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#Origen}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Corte"; Filename: "{app}\CreatorHub.exe"; AppUserModelID: "CreatorHub.App"; Comment: "Tus muestras, ventas y plan de videos"
Name: "{userdesktop}\Corte"; Filename: "{app}\CreatorHub.exe"; AppUserModelID: "CreatorHub.App"; Tasks: escritorio

[Run]
Filename: "{app}\CreatorHub.exe"; Description: "Abrir Corte"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\CreatorHub.exe"; Parameters: "--desinstalar"; Flags: runhidden waituntilterminated; RunOnceId: "LimpiarInicio"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var Codigo: Integer;
begin
  { --salir espera (hasta 15 s) a que la app suelte su mutex; Restart Manager queda de respaldo }
  if FileExists(ExpandConstant('{app}\CreatorHub.exe')) then
    Exec(ExpandConstant('{app}\CreatorHub.exe'), '--salir', '', SW_HIDE, ewWaitUntilTerminated, Codigo);
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and
     (MsgBox('¿Borrar también tus datos de Corte (copia de TikTok, plan, notas y celulares emparejados)? No se puede deshacer.',
             mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
    DelTree(ExpandConstant('{localappdata}\CreatorHub'), True, True, True);
end;

; Instalador de KernelGrove para Windows (Inno Setup 6.1 o posterior).
;
; Envuelve el `dist\kernelgrove\` que deja `build.ps1` — no compila nada, igual
; que `build_deb.sh` en Linux: menú Inicio, desinstalador y, si el usuario lo
; pide, las dos herramientas con las que se compilan overlays.
;
; Inno Setup y no MSI/WiX: el resultado es el mismo y el script es esto.
;
; Instalación **por usuario** (`PrivilegesRequired=lowest`): no pide
; administrador, que es un aviso menos delante de alguien que solo quiere
; probar el programa, y deja todo en `%LOCALAPPDATA%\Programs\KernelGrove`.
;
; ---------------------------------------------------------------------------
; `dtc` y `cpp`
; ---------------------------------------------------------------------------
; En Linux son paquetes de la distribución y el `.deb` solo los recomienda.
; En Windows no hay de dónde: no existe una distribución oficial de `dtc`, y
; el preprocesador solo llega dentro de instaladores de varios cientos de
; megas. Así que aquí sí se descargan, y las descarga el instalador porque es
; el único momento en que ya hay una barra de progreso y un usuario mirando.
;
; De **hosting estático**, con `sha256`, exactamente igual que la base de
; datos (`kernelgrove/db_download.py`): dos ficheros que no hacen nada al otro
; lado, sin API, y por eso las URL son ajustes de compilación y no un
; servicio. Van vacías en el repositorio: mientras lo estén, el componente no
; existe y el instalador se compila y funciona igual. Se rellenan aquí o se
; inyectan al compilar:
;
;   ISCC.exe /DToolsDtcUrl="https://…/dtc-1.7.0-win64.zip" ^
;            /DToolsDtcSha256=abc… /DToolsCppUrl=… /DToolsCppSha256=… …
;
; Qué tiene que haber dentro de cada `.zip`: los ejecutables **en la raíz**,
; sin carpeta intermedia — se extraen tal cual a `{app}\tools`, que es donde
; `api/toolchain._bundled_tools_dir` los busca. Para el preprocesador, el
; `clang.exe` de LLVM: es un único fichero que se basta solo, mientras que el
; `cpp.exe` de MinGW necesita su `cc1.exe` al lado (y `toolchain.py` ya
; acepta `clang` como preprocesador, con su `-E`).
;
; Y en cada `.zip`, junto al ejecutable, su fichero de licencia (`COPYING`
; el de dtc, `LICENSE.txt` el de LLVM): se extraen a `{app}\tools` con él, que
; es lo que exige conservar los avisos. La fuente de `dtc` —GPL-2.0, y la
; servimos nosotros— se publica al lado del `.zip`. Ver
; `packaging/windows/README.md` y la cláusula 6 del acuerdo.

#define AppName "KernelGrove"
#define AppPublisher "KernelGrove"

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#ifndef ToolsDtcUrl
  #define ToolsDtcUrl ""
#endif
#ifndef ToolsDtcSha256
  #define ToolsDtcSha256 ""
#endif
#ifndef ToolsCppUrl
  #define ToolsCppUrl ""
#endif
#ifndef ToolsCppSha256
  #define ToolsCppSha256 ""
#endif

#define ToolsAvailable (ToolsDtcUrl != "") && (ToolsCppUrl != "")

[Setup]
AppId={{C7B117EB-C669-4906-96CA-A001719A7773}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
; Por usuario: sin UAC, sin administrador, sin escribir en Archivos de programa.
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
; Sin `LicenseFile`: Apache-2.0 no pide aceptar nada para instalar ni usar el
; programa. La licencia y el `NOTICE` se copian a `{app}` (ver `[Files]`).
OutputDir=..\..\dist
OutputBaseFilename=kernelgrove-{#AppVersion}-win64-setup
SetupIconFile=kernelgrove.ico
UninstallDisplayIcon={app}\kernelgrove.exe
UninstallDisplayName={#AppName} {#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
; El programa se llamaba DTstudio y el `AppId` no ha cambiado, para que
; esto sea una actualización y no un segundo producto. Inno reutiliza
; entonces la carpeta y el grupo de la instalación anterior: la carpeta
; se deja estar —forzar otra dejaría la vieja entera de huérfana, que
; son cientos de megas— pero el grupo del menú de inicio no, porque es
; lo que el usuario lee. El grupo viejo se borra en `[InstallDelete]`.
UsePreviousGroup=no
; Preguntar el idioma siempre. Por omisión (`auto`) Inno lo deduce del que
; tenga Windows y no enseña el diálogo cuando acierta a deducirlo, así que en
; un Windows en castellano el asistente salía en castellano entero sin ofrecer
; en ningún momento cambiarlo. Son dos idiomas y una pantalla: se pregunta.
ShowLanguageDialog=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[CustomMessages]
; Lo que no sale de los `.isl` de Inno porque es nuestro. Escrito aquí y no
; en línea en `[Components]`/`[Code]`: ahí sería una sola cadena en un solo
; idioma, que es lo que hacía que partes del asistente no siguieran al idioma
; elegido.
english.ToolsComponent=Compilation tools (dtc + preprocessor, downloaded)
spanish.ToolsComponent=Herramientas de compilación (dtc + preprocesador, se descargan)
english.UnpackFailed=Could not unpack %1. Install dtc and a preprocessor by hand; KernelGrove works without them, only compiling is unavailable.
spanish.UnpackFailed=No se ha podido descomprimir %1. Instale dtc y un preprocesador a mano; KernelGrove funciona sin ellos, solo deja de poder compilar.
english.NoTar=This Windows has no tar.exe (needs Windows 10 1803 or later), so the compilation tools cannot be unpacked. Everything else was installed.
spanish.NoTar=Este Windows no tiene tar.exe (hace falta Windows 10 1803 o posterior), así que no se pueden descomprimir las herramientas de compilación. Todo lo demás se ha instalado.

[Components]
Name: "app"; Description: "{#AppName}"; Types: full compact custom; Flags: fixed
#if ToolsAvailable
Name: "tools"; Description: "{cm:ToolsComponent}"; Types: full
#endif

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; El bundle entero de PyInstaller, tal cual. La base de datos no va dentro
; (ver `packaging/linux/README.md`): el programa la descarga solo la primera
; vez que arranca sin ella, a `%USERPROFILE%\.kernelgrove\bindings.db`.
Source: "..\..\dist\kernelgrove\*"; DestDir: "{app}"; Components: app; \
    Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Components: app
Source: "..\..\NOTICE"; DestDir: "{app}"; DestName: "NOTICE.txt"; Components: app

[InstallDelete]
; Lo que cambió de nombre no lo sobreescribe nadie: al instalar encima de
; DTstudio, su ejecutable y su copia del paquete se quedarían al lado de los
; nuevos, arrancables desde el acceso directo viejo. Dos versiones instaladas
; es peor que ninguna, y son ~300 MB de la anterior. `{app}` es aquí la
; carpeta de la instalación anterior, que es justo la que hay que limpiar.
Type: files; Name: "{app}\dtstudio.exe"
Type: filesandordirs; Name: "{app}\_internal\dtstudio"
; El grupo del menú de inicio de la versión anterior, con sus dos accesos
; directos dentro. El del escritorio solo existe si se marcó la casilla.
Type: filesandordirs; Name: "{userprograms}\DTstudio"
Type: files; Name: "{autodesktop}\DTstudio.lnk"

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\kernelgrove.exe"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\kernelgrove.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\kernelgrove.exe"; Description: "{cm:LaunchProgram,{#AppName}}"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Lo descargado no lo instaló `[Files]`, así que el desinstalador no lo
; conoce y hay que decírselo. `%USERPROFILE%\.kernelgrove` (base de datos,
; acuerdo aceptado) se queda: son datos del usuario, no del programa.
Type: filesandordirs; Name: "{app}\tools"

#if ToolsAvailable
[Code]
var
  DownloadPage: TDownloadWizardPage;

function OnDownloadProgress(const Url, FileName: String;
  const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage(
    SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc),
    @OnDownloadProgress);
end;

{ Se descarga antes de instalar nada: si la red falla, no queda medio
  programa puesto. El `sha256` lo comprueba el propio Inno — media descarga
  pesa lo mismo que una entera y un `dtc.exe` truncado falla mucho más tarde
  y de forma mucho más confusa que aquí. }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpReady) and IsComponentSelected('tools') then
  begin
    DownloadPage.Clear;
    DownloadPage.Add('{#ToolsDtcUrl}', 'dtc.zip', '{#ToolsDtcSha256}');
    DownloadPage.Add('{#ToolsCppUrl}', 'cpp.zip', '{#ToolsCppSha256}');
    DownloadPage.Show;
    try
      try
        DownloadPage.Download;
      except
        if not DownloadPage.AbortedByUser then
          SuppressibleMsgBox(AddPeriod(GetExceptionMessage), mbCriticalError,
            MB_OK, IDOK);
        Result := False;
      end;
    finally
      DownloadPage.Hide;
    end;
  end;
end;

{ Se extrae con el `tar.exe` que Windows trae desde la 1803 (es bsdtar, y
  abre `.zip`). Traer una librería de descompresión al instalador para esto
  sería añadir una dependencia por dos ficheros. }
procedure ExtraerHerramienta(const Archivo: String);
var
  Codigo: Integer;
begin
  if not Exec(ExpandConstant('{sys}\tar.exe'),
       '-x -f "' + ExpandConstant('{tmp}\') + Archivo + '" -C "' +
       ExpandConstant('{app}\tools') + '"',
       '', SW_HIDE, ewWaitUntilTerminated, Codigo) or (Codigo <> 0) then
    SuppressibleMsgBox(ExpandConstant('{cm:UnpackFailed,' + Archivo + '}'),
      mbError, MB_OK, IDOK);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and IsComponentSelected('tools') then
  begin
    if not FileExists(ExpandConstant('{sys}\tar.exe')) then
    begin
      SuppressibleMsgBox(ExpandConstant('{cm:NoTar}'), mbInformation, MB_OK,
        IDOK);
      Exit;
    end;
    ForceDirectories(ExpandConstant('{app}\tools'));
    ExtraerHerramienta('dtc.zip');
    ExtraerHerramienta('cpp.zip');
  end;
end;
#endif

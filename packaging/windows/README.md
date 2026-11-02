# Empaquetado en Windows

## Construir

```powershell
pip install -e '.[packaging]'      # PyInstaller
.\packaging\windows\build.ps1
```

Resultado en `dist\kernelgrove\` — el ejecutable `kernelgrove.exe` con sus DLL al
lado (`--onedir`, no `--onefile`, mismo motivo LGPL que en Linux). Probarlo:

```powershell
$env:KERNELGROVE_DB_PATH='C:\ruta\a\bindings.db'; .\dist\kernelgrove\kernelgrove.exe
```

**En una máquina Windows.** PyInstaller no hace cross-compiling: esto no se
construye desde Linux. `windows-latest` de GitHub Actions vale.

## Instalador

```powershell
.\packaging\windows\build_installer.ps1
```

Deja `dist\kernelgrove-<versión>-win64-setup.exe`. Necesita Inno Setup 6.1 o
posterior (`winget install --id JRSoftware.InnoSetup`) — 6.1 es la que trae
la página de descarga que se usa abajo.

Inno Setup y no MSI/WiX: mismo resultado (menú Inicio, desinstalador,
entrada en «Aplicaciones instaladas») con un script declarativo en vez de un
proyecto.

Instala **por usuario**, sin pedir administrador, en
`%LOCALAPPDATA%\Programs\KernelGrove`. Es un aviso menos delante de alguien que
solo quiere probar el programa, y evita el problema que en Linux obligó a
buscar la base también en `~`: instalado en Archivos de programa, todo lo que
el programa escribe junto a sí mismo necesitaría privilegios.

El instalador no pide aceptar ninguna licencia: Apache-2.0 no lo exige. Copia
`LICENSE.txt` y `NOTICE.txt` junto al ejecutable, que es lo que sí exige.

### Actualizar desde DTstudio

El programa se llamaba DTstudio hasta la 1.0b2. El `AppId` **no ha
cambiado**, y eso es deliberado: es lo que hace que el instalador nuevo sea
una actualización del anterior y no un segundo producto — una sola entrada
en «Aplicaciones instaladas», que pasa a llamarse KernelGrove, y un solo
desinstalador.

De ahí salen tres cosas que hay que atender a mano, porque Inno solo
sobreescribe ficheros que se llaman igual:

- **La carpeta se queda como estaba** (`%LOCALAPPDATA%\Programs\DTstudio`).
  `UsePreviousAppDir` se deja en su valor por omisión a propósito: forzar
  `...\KernelGrove` dejaría la carpeta anterior entera de huérfana, unos
  300 MB que nadie va a ir a borrar. El nombre de la carpeta no lo lee casi
  nadie; el de la entrada de desinstalación sí, y ese sí cambia.
- **El grupo del menú de inicio no se queda**: `UsePreviousGroup=no` fuerza
  uno nuevo llamado KernelGrove, y `[InstallDelete]` borra el viejo con sus
  dos accesos directos dentro. Eso es lo que el usuario mira.
- **El ejecutable viejo se borra** (`[InstallDelete]`: `dtstudio.exe` y
  `_internal\dtstudio`). Sin esa línea se quedaba al lado del nuevo,
  arrancable desde su acceso directo, con su propia copia del paquete: dos
  versiones instaladas a la vez, y la vieja buscando un `~/.dtstudio` que la
  nueva ya se ha llevado.

Lo del usuario no lo toca el instalador y no hace falta que lo toque:
`%USERPROFILE%\.dtstudio` y los ajustes de Qt
bajo `HKCU\Software\DTstudio` los recoge el propio programa al arrancar
(`kernelgrove/legacy.py`). Las herramientas descargadas viven en
`{app}\tools`, que es la misma carpeta de siempre, así que siguen donde
estaban y el ejecutable nuevo las encuentra sin hacer nada.

## `dtc` y `cpp`: por qué aquí sí se descargan

En Linux son paquetes de la distribución y el `.deb` se limita a
recomendarlos (`Recommends`), porque `apt` los instala y los actualiza. En
Windows no hay equivalente:

- **`dtc`** no tiene distribución oficial para Windows. Lo más parecido es el
  paquete de MSYS2 (`mingw-w64-x86_64-dtc`), que llega en un
  `.pkg.tar.zst` y presupone tener MSYS2 instalado.
- **El preprocesador** solo viene dentro de instaladores grandes (LLVM ronda
  el giga instalado) o de un MinGW completo.

Pedirle eso a alguien que acaba de instalar un editor de device trees es
perderlo. Así que el instalador ofrece un componente opcional,
**«Compilation tools»**, que las descarga y las deja en `{app}\tools`.

Cómo está montado, y por qué así:

- **Hosting estático, no una API** — igual que la base de datos
  (`kernelgrove/db_download.py`): un `.zip` colgado en una *release* de GitHub
  (o en un bucket) y su `sha256`. Nada que mantener corriendo.
- **Se comprueba el `sha256`**, que es lo que hace el propio Inno al
  descargar. Media descarga pesa lo mismo que una entera y un `dtc.exe`
  truncado falla mucho más tarde y de forma mucho más confusa que ahí.
- **Se descarga antes de instalar nada** (en `wpReady`), para que un fallo de
  red no deje medio programa puesto.
- **Se descomprime con el `tar.exe` de Windows** (bsdtar, presente desde la
  1803, y abre `.zip`). Meter una librería de descompresión en el instalador
  por dos ficheros sería una dependencia por nada. Si no está, lo dice y
  sigue: el resto queda instalado.
- **No se toca el `PATH`.** Es un cambio global del sistema por un programa
  concreto, y encima no alcanzaría a un proceso ya lanzado. En su lugar
  `api/toolchain._bundled_tools_dir` mira el `tools\` que hay junto al
  ejecutable cuando está empaquetado — dos líneas, y funciona igual si
  alguien copia ahí sus propios binarios a mano.
- **El desinstalador se lleva `{app}\tools`** (`[UninstallDelete]`): no lo
  puso `[Files]`, así que no lo conoce por sí solo. `%USERPROFILE%\.kernelgrove`
  (base de datos, acuerdo aceptado) se queda: son datos del usuario.

Sin el componente, o si falla la descarga, no pasa nada más que no poder
compilar: la aplicación entera —editar, validar, generar overlays— es Python
sobre la base de datos, y `toolchain.install_hint()` explica qué falta.

### Qué hay que publicar, y qué tiene que haber dentro

Las URL van **vacías en el repositorio**. Mientras lo estén, el componente no
se compila siquiera y el instalador sale sin él. Se inyectan al construir:

Van a una *release* de GitHub, que es el mismo hosting estático que ya usa
la base de datos (`kernelgrove/db_download.py`) y no hay que mantener nada
corriendo:

```powershell
$base = 'https://github.com/serg4life/kernelgrove/releases/download/tools-v1'
$env:KERNELGROVE_TOOLS_DTC_URL    = "$base/dtc-1.7.0-win64.zip"
$env:KERNELGROVE_TOOLS_DTC_SHA256 = '<sha256 del zip>'
$env:KERNELGROVE_TOOLS_CPP_URL    = "$base/clang-win64.zip"
$env:KERNELGROVE_TOOLS_CPP_SHA256 = '<sha256 del zip>'
.\packaging\windows\build_installer.ps1
```

**Con la etiqueta fija, no con `/releases/latest/download/`.** La base sí usa
`latest`, y puede porque va detrás de un manifiesto que dice el `sha256` del
día; aquí el `sha256` está cocido dentro del instalador, así que un `latest`
que se mueva rompería a la vez todos los instaladores ya publicados. Una
*release* aparte para las herramientas (`tools-v1`) evita además tener que
resubir los `.zip` cada vez que sale una versión del programa.

Cada `.zip` tiene que llevar, **en la raíz** y sin carpeta intermedia:

- el ejecutable (`dtc.exe`, `clang.exe`), porque se extrae tal cual a
  `{app}\tools`, y
- **su fichero de licencia** al lado (`COPYING` el de dtc, `LICENSE.txt` el
  de LLVM). Conservar los avisos es una obligación de las dos licencias, y
  así viaja con el binario y se va con él al desinstalar.

Para el preprocesador, el **`clang.exe`** de LLVM: es un único fichero que se
basta solo, mientras que el `cpp.exe` de MinGW necesita su `cc1.exe` al lado.
`toolchain.py` ya lo acepta como preprocesador (`CPP_CANDIDATES`) y
`compile_overlay._cpp_command` ya le añade el `-E` que necesita.

**Licencias.** Lo que cambia respecto a Linux no es que se descargue —eso ya
pasa con `apt`— sino **de qué servidor salen los bits**: allí los sirve
Debian y el distribuidor es Debian; aquí los servimos nosotros, así que la
obligación es nuestra. Es una casilla, no un problema:

- `dtc` es **GPL-2.0-or-later**. Publica junto al `.zip` el tarball de la
  fuente exacta de ese build y enlázalo desde la página de descargas, y mete
  su `COPYING` dentro del `.zip`.
- `clang`/LLVM es **Apache-2.0 con excepción LLVM**: basta con acompañar el
  aviso (`LICENSE.txt` dentro del `.zip`).

**La aplicación no se contamina**: KernelGrove los lanza como procesos aparte
(`subprocess`), no enlaza nada de ellos, y distribuirlos juntos es mera
agregación. Es menos compromiso del que ya se asume con Qt, que es LGPLv3 y
sí va dentro del bundle. Ambos están declarados en «Ayuda → Licencias»
(`src/kernelgrove/gui/LICENSES.md`), en su propio apartado, dejando dicho que
no forman parte del programa.

## Firma de código

Sin firmar, tanto el `.exe` como el instalador disparan SmartScreen
(«Windows protegió su PC»). Un certificado estándar (~100–400 USD/año)
quita el aviso solo después de acumular reputación; uno EV lo quita desde el
primer día. Es aplazable hasta que haya distribución real a terceros
(proyectos open source pueden pedir firma gratuita, p. ej. SignPath). Si se compra, se firma el `.exe` interno **y**
el instalador, con `signtool sign /fd sha256 /tr <timestamp> …` como paso
posterior a cada script.

## Qué NO lleva dentro

Lo mismo que en Linux, y por lo mismo (ver `packaging/linux/README.md`):
`bindings.db` (la aplicación la descarga sola la primera vez que arranca sin
ella, a `%USERPROFILE%\.kernelgrove\bindings.db`), `kernelgrove.db_manager`,
y `dtschema`/`pyyaml`. Antes de publicar hay que comprobar la URL del
manifiesto de la base (`kernelgrove/db_download.py`).

## El icono

`kernelgrove.ico` se generó del símbolo de la marca
(`src/kernelgrove/gui/brand/logo-icon.svg`) con siete tamaños dentro
(16…256), que es lo que Windows pide para que se vea bien en la barra de
tareas y en Explorer:

```
python scripts/build_icon.py            # rasteriza los siete y llama a convert
```

Cada tamaño se rasteriza **por separado** desde el SVG con el mismo Qt que
dibuja el logotipo en la aplicación, en vez de reducir un PNG de 256: a 16 px
un brote reescalado se emborrona, y así el trazo cae donde debe. El morado que
sale es el del fichero (`#8b5cf6`), no el de la piel activa — la barra de
tareas no dice de qué color es su fondo, y ese aguanta los dos (4,2:1 sobre
blanco, 4,4:1 sobre negro).

A diferencia de Linux, aquí el icono de la ventana **sí** sale del `.exe`
(no hay `.desktop` de por medio), así que basta con el `icon=` del `.spec`.

## Pendiente

- **CI**: `windows-latest` en un `release.yml` con matrix por SO, en vez de
  builds manuales — mismo pendiente que en Linux.
- **ARM64**: PyInstaller construye para la máquina donde corre; haría falta
  un runner Windows ARM64 y un instalador aparte.

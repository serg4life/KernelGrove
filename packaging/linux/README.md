# Empaquetado en Linux

## Construir

```
pip install -e '.[packaging]'      # PyInstaller
bash packaging/linux/build.sh
```

Resultado en `dist/kernelgrove/` — un directorio con el ejecutable `kernelgrove` y sus
librerías al lado (`--onedir`, no `--onefile`, ver el porqué en
`kernelgrove.spec`). Probarlo:

```
KERNELGROVE_DB_PATH=/ruta/a/bindings.db dist/kernelgrove/kernelgrove
```

## Instalar (`.deb`)

```
bash packaging/linux/build_deb.sh
sudo apt install ./dist/kernelgrove_<version>_<arch>.deb
```

Empaqueta el `dist/kernelgrove/` que acaba de construirse — sin compilar nada,
solo metadatos, el `.desktop` y el icono, que es lo que lo convierte en algo
que aparece en el menú de aplicaciones y que `apt remove` se lleva limpio.
Con `dpkg-deb` y no con `fpm` (que es lo que apuntaba `docs/ROADMAP.md`):
`fpm` es una gema de Ruby que habría que instalar, y `dpkg-deb` viene en
cualquier Debian/Ubuntu, que es exactamente donde se construye un `.deb`.

Qué instala:

| Ruta | Qué |
|---|---|
| `/opt/kernelgrove/` | el bundle entero de PyInstaller |
| `/usr/bin/kernelgrove` | enlace al ejecutable |
| `/usr/share/applications/kernelgrove.desktop` | lanzador del menú |
| `/usr/share/icons/hicolor/scalable/apps/kernelgrove.svg` | el símbolo de la marca |

**El icono de la ventana lo pone esta entrada, no la aplicación.** GNOME no
usa el icono que la ventana lleva dentro (`_NET_WM_ICON`, que Qt sí rellena
desde `app.setWindowIcon`): asocia la ventana a un `.desktop` por el
identificador que declara (`QApplication.setDesktopFileName`, «kernelgrove») y
de ahí saca el icono. Sin la entrada instalada lo que se ve es el
`application-x-executable` del tema — en Yaru, un engranaje. De ahí que el
nombre del fichero (`kernelgrove.desktop`), el `Icon=` (`kernelgrove`, que resuelve
contra `hicolor`) y el identificador de la aplicación tengan que coincidir:
si se cambia uno hay que cambiar los tres. Para ejecutar desde el
repositorio, `scripts/install_desktop_entry.sh` instala el equivalente en
`~/.local` sin sudo.

Declara `Depends: libxcb-cursor0` — es la librería de sistema que Qt ≥6.5
necesita para el plugin `xcb` y que la aplicación comprueba a mano al
arrancar (`main._missing_xcb_runtime_deps`); como dependencia del paquete,
esa comprobación no llega a hacer falta.

Y `Recommends: device-tree-compiler, cpp`, que son las dos herramientas con
las que se compilan y descompilan overlays (`api/toolchain.py`). En
`Recommends` y no en `Depends` a propósito: `apt` las instala por defecto,
así que compilar funciona nada más instalar, pero todo lo demás funciona sin
ellas y el programa ya detecta cuáles hay y explica la que falte. No se
empaquetan ni se descargan nunca — son paquetes de la distribución, con sus
propias actualizaciones de seguridad, y traerlas dentro sería hacerse cargo
de parchearlas.

Un `.deb` por arquitectura: empaqueta un `dist/` que PyInstaller construyó
para la máquina donde se lanzó.

**La base de datos no va dentro** (ver más abajo). Instalada en `/opt`, que
es de root, dejarla junto al ejecutable exigiría `sudo` para un fichero que
es del usuario, así que `main._default_db_path` la busca también en
`~/.kernelgrove/bindings.db`. Si no está en ninguno de los dos, la aplicación lo
dice **en un cuadro de diálogo**: lanzada desde el menú no hay terminal donde
leer un mensaje de consola, y pulsar el icono parecía no hacer nada.

Antes de publicar conviene revisar el correo del mantenedor
(`KERNELGROVE_DEB_MAINTAINER`). El `copyright` del paquete es el `NOTICE` y la
`LICENSE` del repositorio, que Apache-2.0 obliga a llevar en cualquier
redistribución.

## Qué NO lleva dentro, y por qué

- **`bindings.db`**: la base de datos es un artefacto independiente del
  software (y eso condiciona además cómo
  se trata el contenido derivado del kernel Linux que contiene, GPL-2.0 y
  BSD-2-Clause mezclados según fichero). El ejecutable la busca junto a sí
  mismo por defecto, o donde diga `KERNELGROVE_DB_PATH` — nunca la genera ni la
  incluye el propio build.
- **`kernelgrove.db_manager`** (la herramienta de ingesta) **ni `dtschema`/`pyyaml`**:
  excluidos explícitamente en `kernelgrove.spec` (`excludes=[...]`), y ya
  verificado que ningún import real los alcanza desde `gui`/`api`/
  `dts_engine` — la exclusión es cinturón y tirantes, no la única barrera.

## Cumplimiento LGPL de Qt

PySide6/Qt se distribuye bajo LGPLv3 entre otras opciones. `--onedir` deja
sus librerías como ficheros `.so` sueltos en `dist/kernelgrove/_internal/`, no
comprimidas dentro de un binario único — así un usuario puede sustituirlas,
que es la condición de LGPL para uso en software propietario. No cambiar a
`--onefile` sin revisar esa condición de nuevo.

## Otras plataformas

Este directorio es Linux x86_64 únicamente — PyInstaller no hace
cross-compiling. Para ARM64, Windows y sus instaladores, ver el plan en
`docs/ROADMAP.md`.

## Pendiente (no implementado en este pase)

- **AppImage**: envolver `dist/kernelgrove/` con `linuxdeploy` +
  `linuxdeploy-plugin-qt` para un único fichero ejecutable sin instalación.
  No incluido aquí porque requiere descargar esas herramientas y no se pudo
  validar en este entorno — el `--onedir` de arriba ya es un Linux
  funcional, el AppImage es solo un envoltorio de distribución encima.
- **Firma/notarización**: no aplica en Linux como en Windows, pero conviene
  publicar sumas SHA256 de cada release.
- **CI**: automatizar este script en GitHub Actions (`ubuntu-latest`) por
  cada tag, para no depender de una máquina concreta.

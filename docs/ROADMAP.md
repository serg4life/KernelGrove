# Roadmap de empaquetado multiplataforma

Qué construir y en qué orden, para no tener que re-derivarlo la próxima
vez que se retome. Los pasos 2, 3 y 4 ya están hechos; lo que sí existe hoy
está en `packaging/linux/README.md` y `packaging/windows/README.md`.

## Estado actual

El único artefacto que se genera es `dist/kernelgrove/` vía
`packaging/linux/build.sh` + `kernelgrove.spec` — un directorio `--onedir` de
PyInstaller, **solo Linux x86_64**, sin instalador (se ejecuta el binario
directamente). PyInstaller no hace cross-compiling: empaqueta lo que hay
instalado en la máquina donde se lanza, así que este resultado no sirve ni
para Linux ARM64 ni para Windows — hace falta construir en/para cada
combinación de SO y arquitectura por separado.

## Plan, en el orden en que conviene abordarlo

1. **Linux ARM64** — coste bajo. Mismo `kernelgrove.spec`/`build.sh` sin tocar,
   lanzado en un runner ARM64 (GitHub Actions ya ofrece `ubuntu-24.04-arm64`
   hosted, sin infraestructura propia que mantener). PySide6/jsonschema
   tienen wheels arm64; `dtc`/`cpp` los sigue aportando el
   usuario igual que en x86_64. Solo hace falta añadir una entrada al matrix
   de CI.

2. **`.deb`** — **hecho**, `packaging/linux/build_deb.sh` (ver
   `packaging/linux/README.md`). Con `dpkg-deb` en vez de `fpm`: `fpm` es una
   gema de Ruby que habría que instalar y `dpkg-deb` ya está en cualquier
   Debian/Ubuntu. El `.desktop` y el icono, que faltaban, existen ya
   (`packaging/linux/kernelgrove.desktop` y el símbolo de la marca,
   `src/kernelgrove/gui/brand/logo-icon.svg`). Sigue siendo un `.deb` por
   arquitectura, porque empaqueta el `dist/` arch-específico.

3. **Windows, build `--onedir`** — **hecho**, `packaging/windows/build.ps1`
   + `kernelgrove.spec` (ver `packaging/windows/README.md`). Calcado del de
   Linux más las tres cosas que Windows añade: el icono `.ico` (generado del
   símbolo de la marca, ya está en el repo), los metadatos de versión del
   `.exe` —leídos de `pyproject.toml`, no escritos a mano— y `console=False`.
   Eso último obligó a un cambio de código que el plan no preveía: sin
   consola, **cada `subprocess.run` abre la suya**, y `api/toolchain.py`
   sondea `dtc`/`cpp` al arrancar y al abrir «Acerca de». Ahora los tres
   `run` de `toolchain.py` y los dos de `compile_overlay.py` llevan
   `creationflags=NO_WINDOW`, como `git_repo.py` ya hacía. Sigue haciendo
   falta construirlo en una máquina Windows (no hay cross-compiling) y sigue
   sin firmar.

4. **Instalador `.exe` (Windows)** — **hecho**, `packaging/windows/kernelgrove.iss`
   + `build_installer.ps1`. Inno Setup como estaba previsto, per-user
   (`PrivilegesRequired=lowest`, sin UAC). Lo que el plan no había resuelto
   es **`dtc` y `cpp`**: en Linux son paquetes de la distribución y el `.deb`
   se limita a recomendarlos, pero en Windows `dtc` no tiene distribución
   oficial y el preprocesador solo llega dentro de instaladores de cientos
   de megas. Se resuelve con un componente opcional que los descarga de
   hosting estático con `sha256` —el mismo patrón que la base de datos, sin
   API detrás—, los descomprime con el `tar.exe` que Windows trae desde la
   1803 y los deja en `{app}\tools`, que `toolchain._bundled_tools_dir` mira
   sin tocar el `PATH`. Las URL van vacías en el repositorio y se inyectan al
   compilar; mientras lo estén, el componente no existe y el instalador sale
   igual. Detalle legal a no olvidar: `dtc` es GPL-2.0 y redistribuir el
   binario obliga a ofrecer la fuente.

## Pendiente / decisiones abiertas

- Certificado de firma de código Windows: sí/no, y si EV o estándar —
  aplazado hasta que haya un canal de distribución real. Sin él, tanto el
  `.exe` como el instalador disparan SmartScreen.
- Dónde se publican los `.zip` de `dtc` y del preprocesador para Windows, y
  con ellos la fuente de `dtc` que la GPL-2.0 obliga a ofrecer.
- Icono de la app: en SVG (`src/kernelgrove/gui/brand/`) para Linux y ya
  convertido a `.ico` para Windows (`packaging/windows/kernelgrove.ico`, siete
  tamaños; el comando que lo genera está en su README).
- AppImage y notarización siguen fuera de alcance, ver
  `packaging/linux/README.md` § "Pendiente".
- Automatizar todo esto en CI (`release.yml` con matrix por SO/arch) en vez
  de builds manuales — mismo razonamiento que ya apunta
  `packaging/linux/README.md` para el caso Linux-only.

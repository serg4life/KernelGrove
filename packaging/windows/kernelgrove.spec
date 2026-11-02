# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para empaquetar KernelGrove en Windows.

Es el de Linux (`packaging/linux/kernelgrove.spec`) con las tres cosas que
Windows añade y que allí no existen: el icono `.ico`, los metadatos de
versión que Explorer enseña en «Detalles», y `console=False` de verdad —en
Linux daba igual, aquí sin él cada arranque abre una consola negra detrás de
la ventana.

Sigue siendo `--onedir` y no `--onefile`, por lo mismo: Qt es LGPLv3 y hay
que poder sustituir sus DLL, que dentro de un único `.exe` autoextraíble no
se puede sin rehacer el binario. Y arranca antes.

Deliberadamente NO incluye `db_manager`/`dtschema`/`pyyaml` ni la base de
datos, exactamente igual que en Linux — el porqué está allí.

`dtc` y `cpp` tampoco van dentro: los trae el instalador si el usuario lo
pide (`kernelgrove.iss`), a un `tools\\` junto al ejecutable que
`api/toolchain._bundled_tools_dir` sabe mirar.

Construir con `packaging\\windows\\build.ps1` desde la raíz del repo.
"""

import re
import tomllib
from pathlib import Path

repo_root = Path(SPECPATH).resolve().parents[1]  # noqa: F821 (SPECPATH lo inyecta PyInstaller)
packaging_dir = Path(SPECPATH).resolve()  # noqa: F821

# La versión sale de `pyproject.toml`, no de una constante aquí: dos sitios
# donde escribirla es un sitio de más para que se queden distintos, y el que
# manda es el del paquete.
version = tomllib.loads(
    (repo_root / "pyproject.toml").read_text(encoding="utf-8")
)["project"]["version"]
# Windows quiere cuatro enteros; PEP 440 permite `1.0b1`, que no lo es. Se
# toma la parte numérica del principio y se rellena con ceros — la cadena
# completa sí viaja tal cual en `FileVersion`/`ProductVersion`, que es donde
# la prerelease importa.
numeros = [int(n) for n in re.findall(r"\d+", version.split("b")[0].split("a")[0])]
filevers = tuple((numeros + [0, 0, 0, 0])[:4])

# El fichero de metadatos se genera aquí y se deja en el directorio de
# trabajo del build, no en el repo: es un derivado de `pyproject.toml`.
build_dir = Path(globals().get("workpath", SPECPATH))  # noqa: F821
build_dir.mkdir(parents=True, exist_ok=True)
version_file = build_dir / "version_info.txt"
version_file.write_text(
    f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={filevers},
    prodvers={filevers},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'KernelGrove'),
        StringStruct('FileDescription', 'KernelGrove — Device Tree Studio'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'kernelgrove'),
        StringStruct('OriginalFilename', 'kernelgrove.exe'),
        StringStruct('ProductName', 'KernelGrove'),
        StringStruct('ProductVersion', '{version}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
    encoding="utf-8",
)

block_cipher = None

a = Analysis(  # noqa: F821
    [str(repo_root / "src" / "kernelgrove" / "main.py")],
    pathex=[str(repo_root / "src")],
    binaries=[],
    # Misma lista que el spec de Linux y que `package-data` en
    # `pyproject.toml`: si se añade algo allí, se añade aquí.
    datas=[
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "translations" / "*.qm"),
            "kernelgrove/gui/translations",
        ),
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "brand" / "*.svg"),
            "kernelgrove/gui/brand",
        ),
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "fonts" / "*.ttf"),
            "kernelgrove/gui/fonts",
        ),
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "fonts" / "OFL.txt"),
            "kernelgrove/gui/fonts",
        ),
        # Lo que enseña «Ayuda → Licencias» (`widgets/legal_dialog`).
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "LICENSES.md"),
            "kernelgrove/gui",
        ),
        # La licencia y el `NOTICE`: Apache-2.0 obliga a que viajen con
        # cualquier redistribución.
        (str(repo_root / "LICENSE"), "."),
        (str(repo_root / "NOTICE"), "."),
    ],
    hiddenimports=[],
    excludes=[
        "kernelgrove.db_manager",
        "dtschema",
        "yaml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="kernelgrove",
    debug=False,
    strip=False,
    upx=False,
    # Sin consola: es una aplicación de ventana. Lo que esto obliga a cuidar
    # es que ningún `subprocess` abra la suya — ver `toolchain.NO_WINDOW`.
    console=False,
    icon=str(packaging_dir / "kernelgrove.ico"),
    version=str(version_file),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="kernelgrove",
)

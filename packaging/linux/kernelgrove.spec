# -*- mode: python ; coding: utf-8 -*-
"""Spec de PyInstaller para empaquetar KernelGrove en Linux.

Construye en modo `--onedir` (un directorio con el ejecutable y las
librerías al lado), no `--onefile`: PySide6/Qt se distribuye bajo LGPLv3, que
exige poder sustituir esas librerías — comprimirlas dentro de un único
binario lo dificulta innecesariamente. `--onedir` también arranca más
rápido, al no tener que autoextraerse en cada ejecución.

Deliberadamente NO incluye:
- `kernelgrove.db_manager` (la herramienta de ingesta) ni `dtschema`/`pyyaml`: no
  forman parte del software que se distribuye, son build-time-only para
  construir `bindings.db` (ver CLAUDE.md, sección "Commands").
- `database/bindings.db`: la base de datos es un artefacto aparte del
  software (ver `main._default_db_path` y `packaging/linux/README.md`), no
  se empaqueta con el ejecutable.

Construir con: `pyinstaller packaging/linux/kernelgrove.spec --distpath dist
--workpath build` desde la raíz del repo (ver `packaging/linux/build.sh`).
"""

from pathlib import Path

repo_root = Path(SPECPATH).resolve().parents[1]  # noqa: F821 (SPECPATH la inyecta PyInstaller)

block_cipher = None

a = Analysis(  # noqa: F821
    [str(repo_root / "src" / "kernelgrove" / "main.py")],
    pathex=[str(repo_root / "src")],
    binaries=[],
    # Todo lo que la aplicación lee de su propio paquete en tiempo de
    # ejecución y no es código: PyInstaller solo sigue los `import`, así que
    # esto hay que declararlo. Van a la misma ruta relativa desde la que se
    # busca cada cosa. Es la misma lista que `package-data` en
    # `pyproject.toml`; si se añade algo allí, se añade aquí.
    datas=[
        # Sin los `.qm`, la aplicación empaquetada solo hablaría el idioma
        # fuente (inglés): `gui/translations.py` no encontraría ninguno.
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "translations" / "*.qm"),
            "kernelgrove/gui/translations",
        ),
        # El logotipo (`gui/brand.py`) lo lee del disco para rasterizarlo en
        # la tinta del tema; sin él la aplicación no arranca.
        (
            str(repo_root / "src" / "kernelgrove" / "gui" / "brand" / "*.svg"),
            "kernelgrove/gui/brand",
        ),
        # La Inter, que el QSS nombra por familia. Sin ella no falla nada,
        # pero la aplicación se ve con la tipografía del sistema.
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
    console=False,
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

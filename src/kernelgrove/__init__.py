from kernelgrove import legacy

# Antes de importar nada más: varios módulos leen `KERNELGROVE_*` al
# importarse, así que los alias del nombre anterior tienen que estar puestos
# ya (ver `legacy.alias_env`).
legacy.alias_env()

from kernelgrove.main import main  # noqa: E402

__version__ = "1.0b3"

__all__ = ["__version__", main]

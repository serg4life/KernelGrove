"""Capa 1 del motor semántico: la especificación Device Tree.

Antes de mirar ningún binding se comprueba lo que el *lenguaje* exige, que
es lo único que vale para cualquier device tree sin excepción. La fuente es
la especificación oficial (Devicetree Specification v0.4,
https://github.com/devicetree-org/devicetree-specification): cada regla
implementada cita el apartado del que sale, y no se inventa ninguna.

Los módulos siguen la estructura del documento:

- `naming`      -> §2.2 nombres de nodo, de propiedad y etiquetas (§6.2, §6.3).
- `properties`  -> §2.3 propiedades estándar y §2.4 interrupciones.
- `addressing`  -> §2.2.1, §2.3.5 y §2.3.6: reg, unit-address y anchos.
- `structure`   -> §3 nodos obligatorios y §6.4 formato del fichero.

Traducción de la especificación a gravedad:

- «shall»/«must»          -> ERROR: el documento incumple el lenguaje.
- «should»/«recommended»  -> WARNING: es válido, pero se aparta de la norma.
- obsoleto                -> WARNING, con la sustituta en la pista.

Si algo *falta* se mira sobre el árbol con los includes fusionados; cuando no
se puede ser concluyente (un `.dtsi`, un include sin resolver, un nodo que
solo se reabre aquí) el aviso se rebaja en lugar de callarse. Ver
`SpecContext.missing_is_conclusive`.
"""

from __future__ import annotations

from typing import List, Optional

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks.spec.addressing import check_addressing
from kernelgrove.dts_engine.checks.context import SpecContext, build_context
from kernelgrove.dts_engine.checks.spec.naming import check_names
from kernelgrove.dts_engine.checks.spec.properties import check_properties
from kernelgrove.dts_engine.checks.spec.structure import check_structure
from kernelgrove.dts_engine.diagnostics import Diagnostic
from kernelgrove.dts_engine.parser import ParseResult

__all__ = ["check_spec", "SpecContext"]


def check_spec(
    result: ParseResult,
    *,
    text: Optional[str] = None,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: bool = True,
    dts_version_seen: Optional[bool] = None,
) -> List[Diagnostic]:
    """Comprueba un documento contra las reglas de la especificación.

    `result` es lo que devuelve el parser (árbol, líneas de cada propiedad e
    includes encontrados). `text` es el fuente, necesario solo para las
    reglas de fichero (`/dts-v1/;`). `fragment` marca un `.dtsi`, donde lo
    que falta puede aportarlo quien lo incluya. `merged_root` es el árbol con
    los includes fusionados, e `includes_resolved` dice si se fusionaron
    todos.
    """
    ctx = build_context(
        result,
        text=text,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
        dts_version_seen=dts_version_seen,
    )

    check_names(ctx)
    check_properties(ctx)
    check_addressing(ctx)
    check_structure(ctx)

    return ctx.diagnostics

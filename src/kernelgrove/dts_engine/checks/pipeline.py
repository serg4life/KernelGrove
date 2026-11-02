"""Orquestador por capas de las comprobaciones semánticas.

El orden está fijado y documentado en `docs/SEMANTIC-ENGINE-FLOW.md`; va de
lo que vale para todo device tree a lo que solo vale para un dispositivo
concreto, de forma que ninguna capa invente reglas que la anterior ya define:

1. Especificación Device Tree — sintaxis y reglas del lenguaje.  [implementada]
2. Bindings genéricos — clases de dispositivo y buses comunes.   [implementada]
3. Cabeceras `dt-bindings/*.h` — constantes de los valores.      [parcial: existencia]
4. Drivers del kernel — lo que el código exige de verdad.        [pendiente]
5. Bindings específicos — el binding del `compatible` concreto.  [parcial]

Las capas 2 y 5 solo funcionan si quien llama inyecta un `SchemaLookup` (lo
hace `api/service.py` con los schemas que dt-schema dejó en la base de datos).
Sin él, o con una base construida sin ellos, no se ejecutan: el motor prefiere
callar a inventarse reglas. La capa 3 es simétrica con un `MacroLookup`.

La capa 3 hoy solo comprueba **existencia** (`checks/macros.py`): si
`GPIO_HIGH` no está definida en ninguna cabecera conocida, o no en las que
este documento incluye, se avisa — pero no resuelve su *valor* numérico
(haría falta `cpp` y no aporta lo suficiente todavía). Es una pasada barata
—diccionario, no schema— así que corre en `run_checks`, no en la diferida.

**Lo caro va en una segunda pasada**, `run_schema_checks`: todo lo que
consiste en darle un nodo entero a un schema para que lo valide. Son dos
cosas —los valores de la capa 5 (≈2,6 ms por nodo) y la capa 2 completa
(≈10 ms por nodo)— y ninguna cabe en el camino que se recorre en cada
pulsación de tecla. La GUI las lanza juntas en un hilo de fondo y añade sus
avisos cuando llegan; `run_checks` se queda con lo que se responde
consultando un diccionario.

Las capas pendientes se irán añadiendo aquí, cada una en su módulo.

`merged_root` es el árbol del documento con sus includes ya fusionados. El
motor no sabe resolverlos (eso lo hace `api/includes.py` contra la base de
datos), pero sí los aprovecha: sin ellos, comprobar si a un nodo le falta una
propiedad obligatoria da falsos positivos en cuanto el fichero incluye a otro,
que es el caso normal.
"""

from __future__ import annotations

from typing import List, Mapping, Optional, Sequence

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks.bindings import (
    check_binding_layer,
    check_binding_values,
)
from kernelgrove.dts_engine.checks.bindings.lookup import SchemaLookup
from kernelgrove.dts_engine.checks.context import build_context
from kernelgrove.dts_engine.checks.generic.rules import check_generic
from kernelgrove.dts_engine.checks.macros import MacroLookup, check_macro_layer
from kernelgrove.dts_engine.checks.overlay import check_overlay_layer
from kernelgrove.dts_engine.checks.spec import check_spec
from kernelgrove.dts_engine.diagnostics import Diagnostic
from kernelgrove.dts_engine.parser import ParseResult


def run_checks(
    result: ParseResult,
    *,
    text: Optional[str] = None,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: Optional[bool] = None,
    dts_version_seen: Optional[bool] = None,
    schema_lookup: Optional[SchemaLookup] = None,
    macro_lookup: Optional[MacroLookup] = None,
    local_macros: Sequence[str] = (),
    overlay_base: Optional[DeviceTreeNode] = None,
    kernel_version: Optional[str] = None,
) -> List[Diagnostic]:
    """Ejecuta las capas implementadas sobre un documento ya parseado.

    - `text`: el fuente, para las reglas de fichero (`/dts-v1/;`).
    - `fragment`: el documento es un `.dtsi`, un trozo del árbol de otro.
    - `merged_root`: el mismo árbol con el contenido de sus includes ya
      fusionado, si quien llama ha podido construirlo.
    - `includes_resolved`: si se fusionaron *todos* los includes de device
      tree. Si no se indica, se deduce de si el documento declara alguno.
    - `dts_version_seen`: si `/dts-v1/;` aparece en el documento o en alguno
      de sus includes. Solo quien resuelve los includes puede saberlo; si no
      se indica, la comprobación se limita a lo que haya en `text`.
    - `schema_lookup`: acceso a los bindings procesados. Sin él la capa 5 no
      se ejecuta.
    - `macro_lookup`/`local_macros`: acceso al índice de macros y qué nombres
      ve este documento por sus propios includes (ver `checks/macros.py`).
      Sin `macro_lookup` la capa 3 no se ejecuta.
    - `kernel_version`: la release del kernel contra la que se trabaja
      ('6.6'), si el usuario la ha declarado. Con ella la capa 5 avisa de un
      compatible cuyo binding es posterior; sin ella no dice nada.
    - `overlay_base`: el árbol de la base sobre la que se aplicará este
      overlay, ya fusionado. Sin él la capa 6 no se ejecuta: no se puede
      afirmar que un objetivo no exista sin haber podido mirar dónde
      tendría que estar.

    No incluye los diagnósticos de sintaxis del propio parser
    (`result.diagnostics`): quien llama decide si los junta.
    """
    if includes_resolved is None:
        declared = any(not include.is_header for include in result.includes)
        includes_resolved = merged_root is not None or not declared

    diagnostics = check_spec(
        result,
        text=text,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
        dts_version_seen=dts_version_seen,
    )

    if macro_lookup is not None:
        diagnostics.extend(
            check_macro_layer(
                result,
                macro_lookup,
                local_macros,
                fragment=fragment,
                merged_root=merged_root,
                includes_resolved=includes_resolved,
            )
        )

    if schema_lookup is not None:
        diagnostics.extend(
            check_binding_layer(
                result,
                schema_lookup,
                fragment=fragment,
                merged_root=merged_root,
                includes_resolved=includes_resolved,
                kernel_version=kernel_version,
            )
        )

    if overlay_base is not None:
        diagnostics.extend(check_overlay_layer(result, overlay_base))

    return diagnostics


def run_schema_checks(
    result: ParseResult,
    schema_lookup: SchemaLookup,
    *,
    fragment: bool = False,
    merged_root: Optional[DeviceTreeNode] = None,
    includes_resolved: Optional[bool] = None,
    local_macro_values: Optional[Mapping[str, int]] = None,
) -> List[Diagnostic]:
    """Ejecuta las comprobaciones que hace el propio schema.

    Son los valores de la capa 5 y la capa 2 entera: las dos consisten en
    darle el nodo a un validador de JSON Schema, y las dos son caras (ver el
    encabezado del módulo). Comparten contexto porque codifican la misma
    instancia de cada nodo.

    Recibe lo mismo que `run_checks` salvo `text`, que solo hace falta para
    reglas de fichero. `local_macro_values` es el valor ya resuelto (capa 3,
    con `cpp`) de las macros que este documento ve por sus includes: sin él,
    una celda con `GIC_SPI`/`IRQ_TYPE_LEVEL_HIGH` sigue sin poder codificarse
    y estas dos capas se callan sobre su valor, como hasta ahora.
    """
    if includes_resolved is None:
        declared = any(not include.is_header for include in result.includes)
        includes_resolved = merged_root is not None or not declared

    ctx = build_context(
        result,
        fragment=fragment,
        merged_root=merged_root,
        includes_resolved=includes_resolved,
        schema_lookup=schema_lookup,
        local_macro_values=local_macro_values,
    )
    check_binding_values(ctx, schema_lookup)
    check_generic(ctx, schema_lookup)

    # Un mismo problema puede llegar por varias vías: el binding concreto y la
    # clase a la que pertenece (400 kHz del controlador de Cadence y 5 MHz del
    # I2C genérico), o dos bindings genéricos que dicen lo mismo (`snps,dwmac`
    # y `mediatek-dwmac` exigiendo los dos `phy-mode`). Se conserva el primero,
    # y el orden pone delante al binding concreto, que es el más preciso.
    seen: set = set()
    unique: List[Diagnostic] = []
    for item in ctx.diagnostics:
        key = (item.line, item.property_name, item.family)
        if item.property_name is not None:
            if key in seen:
                continue
            seen.add(key)
        unique.append(item)
    return unique

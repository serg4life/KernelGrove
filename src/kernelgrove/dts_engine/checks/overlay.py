"""Capa 6: reglas que solo existen porque el documento es un overlay.

Las cinco capas anteriores ya valen tal cual sobre un overlay —es un
fragmento de device tree como cualquier otro, y así se comprueba: los 361
`.dtso` del kernel pasan el parser sin una sola queja—. Lo que ninguna de
ellas puede mirar es lo que hace a un overlay un overlay: **que se aplica
sobre otro árbol**.

De ahí la regla central de esta capa, que es la misma que gobierna a las
demás: *una capa solo habla de lo que su fuente afirma*. Sin base inyectada
no se dice nada. Que un `&i2c0` no exista es un error solo si se ha podido
mirar dónde tendría que existir; sin esa comprobación, callar es lo correcto
—exactamente igual que las capas 1 y 5 se callan cuando no pueden fusionar
los includes—.

La base llega como árbol ya fusionado, no como fichero: quién la resuelve y
cómo es cosa de `api`, aquí solo se compara.
"""

from __future__ import annotations

from typing import List, Optional

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity
from kernelgrove.dts_engine.parser import ParseResult

# Cuántos símbolos parecidos se ofrecen al no encontrar uno. Más de tres
# dejan de ser una pista y pasan a ser una lista que hay que leer.
_MAX_SUGERENCIAS = 3


def check_overlay_layer(
    result: ParseResult,
    base: Optional[DeviceTreeNode],
    *,
    is_overlay: bool = True,
) -> List[Diagnostic]:
    """Comprueba un overlay contra el árbol base sobre el que se aplicará.

    `base` es el árbol de la base ya fusionado; `None` significa que no se
    ha podido resolver, y entonces esta capa no dice nada.
    """
    if not is_overlay or base is None:
        return []

    etiquetas = {
        node.label: node.path
        for node in base.iter_tree()
        if node.label and node.path
    }
    rutas = {(node.path or "/").strip("/") for node in base.iter_tree()}

    diagnostics: List[Diagnostic] = []
    for pseudo in result.root.children:
        if not pseudo.name.startswith("&"):
            continue
        diagnostic = _check_target(pseudo, etiquetas, rutas)
        if diagnostic is not None:
            diagnostics.append(diagnostic)
    return diagnostics


def _check_target(
    pseudo: DeviceTreeNode, etiquetas: dict, rutas: set
) -> Optional[Diagnostic]:
    """Un objetivo del overlay: existe en la base, o no."""
    referencia = pseudo.name
    linea = pseudo.line or 1

    if referencia.startswith("&{") and referencia.endswith("}"):
        ruta = referencia[2:-1].strip("/")
        if ruta in rutas:
            return None
        return Diagnostic(
            code=DiagnosticCode.OVERLAY_TARGET_NOT_FOUND,
            severity=Severity.ERROR,
            message=(
                f"«{referencia}» points at a path that does not exist in the base"
            ),
            line=linea,
            hint=(
                "Check the whole path against the base tree; a path is "
                "written in full, from «/»"
            ),
        )

    etiqueta = referencia[1:]
    if etiqueta in etiquetas:
        return None

    parecidas = _parecidas(etiqueta, etiquetas)
    pista = (
        f"The base does not export that label. Did you mean {parecidas}?"
        if parecidas
        else (
            "The base does not export that label. If the node exists but has "
            "no label, target it by path with «&{/path/to/node}»"
        )
    )
    return Diagnostic(
        code=DiagnosticCode.OVERLAY_TARGET_NOT_FOUND,
        severity=Severity.ERROR,
        message=f"«{referencia}» matches no node in the base",
        line=linea,
        hint=pista,
    )


def _parecidas(etiqueta: str, etiquetas: dict) -> str:
    """Etiquetas de la base parecidas a la buscada, como texto para la pista.

    Un fallo típico es el número: `&i2c1` cuando la base solo tiene `&i2c0`.
    Se comparan por prefijo en vez de por distancia de edición porque ese es
    el error real y no hace falta más maquinaria para acertarlo.
    """
    if len(etiqueta) < 3:
        return ""
    raiz = etiqueta.rstrip("0123456789") or etiqueta[:3]
    candidatas = sorted(
        nombre for nombre in etiquetas if nombre.startswith(raiz)
    )[:_MAX_SUGERENCIAS]
    return ", ".join(f"«&{nombre}»" for nombre in candidatas)

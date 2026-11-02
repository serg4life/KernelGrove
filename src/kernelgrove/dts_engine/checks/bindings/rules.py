"""Capa 5: lo que dice el binding del `compatible` concreto del nodo.

Es la última capa del flujo (`docs/SEMANTIC-ENGINE-FLOW.md`) y la única que
puede hablar de un dispositivo en particular: qué propiedades exige un
`nxp,pcf8563` y cuáles admite. La fuente son los schemas de binding del
kernel ya procesados por dt-schema durante la ingesta, resueltos por quien
implemente `SchemaLookup`; el motor no sabe de dónde salen.

`check_bindings` reúne lo barato —lo que se responde consultando el schema ya
resuelto— y `check_binding_values` lo caro: darle el nodo entero al schema
para que juzgue los valores. Se ejecutan en pasadas distintas.

Lo que esta capa **no** hace, a propósito:

- No interpreta el schema por su cuenta: los valores los juzga el propio
  schema (`SchemaLookup.validate_node`), y de su respuesta solo se cuentan
  los problemas de *valor* —`enum`, `const`, `type`, `maxItems`, rangos—, uno
  por propiedad. Lo que falta o lo que sobra lo dicen las reglas de aquí, que
  saben mirar el árbol fusionado y rebajar el aviso cuando no es concluyente.
- No habla de un valor que no haya podido codificar con certeza
  (`instance.encode_node`): quedan fuera los que llevan macros de
  `dt-bindings/*.h` (capa 3), las referencias `&label` —sus celdas las decide
  el nodo apuntado— y las matrices cuyo tamaño de fila depende de otro nodo,
  como `interrupts` y su `#interrupt-cells`.
- No repite los *valores* que ya comprueba la capa 1 (`status`, `model`,
  `#address-cells`...): una misma cosa avisada dos veces es ruido. Que el
  binding los exija sí se comprueba, porque eso la capa 1 no lo sabe.
- No exige nada que el schema declare dentro de un bloque condicional: el
  resolutor recorre los `if/then`, `oneOf` y `anyOf` solo en sentido
  permisivo, así que de ahí salen propiedades admitidas pero nunca
  obligatorias. (Al validar valores no hace falta esa cautela: la instancia
  lleva el `compatible`, así que el propio schema resuelve sus condiciones.)
"""

from __future__ import annotations

import re
from typing import List, Optional

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks import values
from kernelgrove.dts_engine.checks.bindings.instance import encode_instance
from kernelgrove.dts_engine.checks.bindings.lookup import (
    VALUE_KEYWORDS,
    NodeSchema,
    SchemaLookup,
    property_hint,
    schema_file,
)
from kernelgrove.dts_engine.checks.context import SPEC_OWNED_PROPERTIES, SpecContext
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity

# Propiedades cuya *ausencia* no juzga esta capa. `compatible` es la clave con
# la que se ha resuelto el binding, `name`/`phandle` los genera dtc, y
# `device_type` lo declara obsoleto la capa 1 fuera de `cpu` y `memory`:
# exigirlo aquí sería contradecir a una capa anterior.
_RESOLUTION_OWNED = {
    "compatible",
    "name",
    "phandle",
    "linux,phandle",
    "device_type",
}

# Propiedades que puede llevar cualquier nodo aunque su binding no las
# enumere: las mete dtc al compilar o las define la propia especificación.
_ALWAYS_ALLOWED = {
    "phandle",
    "linux,phandle",
    "name",
    "status",
    "secure-status",
}


def check_bindings(
    ctx: SpecContext, lookup: SchemaLookup, kernel_version: Optional[str] = None
) -> None:
    """Contrasta cada nodo con el binding de su `compatible`."""
    for node in ctx.walk():
        compatibles = _compatibles(ctx, node)
        if not compatibles:
            continue

        schema = _resolve(lookup, compatibles)
        if schema is None:
            _check_documented(ctx, node, compatibles, lookup)
            continue

        if _is_rejected(schema):
            _report_rejected(ctx, node, schema)
            continue

        _check_kernel_version(ctx, node, schema, lookup, kernel_version)
        _check_required(ctx, node, schema)
        _check_unknown_properties(ctx, node, schema, lookup)


def version_key(version: str) -> tuple:
    """Ordena una versión de kernel ('6.3', 'v5.10.1') por sus números."""
    return tuple(int(numero) for numero in re.findall(r"\d+", version))


def _check_kernel_version(
    ctx: SpecContext,
    node: DeviceTreeNode,
    schema: NodeSchema,
    lookup: SchemaLookup,
    kernel_version: Optional[str],
) -> None:
    """Avisa de un compatible que el kernel objetivo todavía no conoce.

    El dato es `schemas.since`, la primera release del kernel que trae ese
    fichero de binding, y es lo único que el inspector enseña que no está
    escrito en el propio binding: vive en la historia del repositorio
    (`db_manager/kernel_versions.py`). Con un objetivo declarado se puede
    contestar la pregunta que nadie más contesta —«¿esto arrancará en el
    kernel que voy a usar?»— antes de compilar.

    Solo se dice cuando se sabe: sin objetivo elegido, o sin `since` en la
    base, esta regla se calla, como todas.

    Y dice lo que el dato dice, ni una palabra más: la fecha es la del
    **fichero del binding**, no la del driver. Un compatible puede haber
    existido antes en un binding `.txt` con otro nombre —la conversión
    masiva a YAML de 2018-2021— y entonces esto adelanta la fecha. Por eso
    el mensaje habla de cuándo se documentó y la pista lo advierte, en vez
    de afirmar que el kernel objetivo no lo soporta.
    """
    if not kernel_version:
        return
    since = lookup.since(schema.schema_id)
    if not since or version_key(since) <= version_key(kernel_version):
        return

    ctx.report(
        DiagnosticCode.BINDING_NEWER_THAN_KERNEL,
        Severity.WARNING,
        f"«{schema.compatible}» is documented in Linux {since}, "
        f"newer than the target kernel ({kernel_version})",
        node,
        property_name="compatible",
        hint=(
            f"{schema_file(schema.schema_id)} lands in {since}; "
            "the driver may be older if it came from a .txt binding"
        ),
    )


def check_binding_values(ctx: SpecContext, lookup: SchemaLookup) -> None:
    """Valida los valores de cada nodo contra el schema de su binding.

    Va aparte de `check_bindings` porque es la parte cara: unos 2,6 ms por
    nodo, frente a los pocos microsegundos de las comprobaciones de arriba,
    que son consultas a un diccionario. Quien llama decide cuándo puede
    permitírsela; la GUI la ejecuta en el mismo hilo de fondo que la capa 2.
    """
    for node in ctx.walk():
        compatibles = _compatibles(ctx, node)
        if not compatibles:
            continue
        schema = _resolve(lookup, compatibles)
        if schema is None or _is_rejected(schema):
            continue
        _check_schema_values(ctx, node, schema, lookup)


def _compatibles(ctx: SpecContext, node: DeviceTreeNode) -> List[str]:
    """Lista de compatibles efectivos del nodo, en el orden declarado.

    Se leen del árbol fusionado: un `&uart0 { … }` de una placa reabre un
    nodo cuyo `compatible` está en el `.dtsi` del SoC, y sin los includes
    ese nodo parecería no tener ninguno.
    """
    raw = ctx.effective_properties(node).get("compatible")
    if raw is not None:
        strings = values.string_list(values.raw_text(raw))
        if strings:
            return strings
    return list(node.compatible)


def _resolve(lookup: SchemaLookup, compatibles: List[str]) -> Optional[NodeSchema]:
    """Devuelve el schema del primer compatible documentado.

    Es el mismo criterio que aplica `dt-validate`: el compatible más
    específico va primero y es el que manda; los siguientes son familias más
    genéricas a las que el nodo también responde.
    """
    for compatible in compatibles:
        schema = lookup.schema_for(compatible)
        if schema is not None:
            return schema
    return None


def _check_documented(
    ctx: SpecContext,
    node: DeviceTreeNode,
    compatibles: List[str],
    lookup: SchemaLookup,
) -> None:
    """Avisa de un nodo cuyo `compatible` no describe ningún binding.

    Se queda en INFO porque no siempre es un error: un device tree puede
    describir hardware cuyo binding aún no está en el kernel, o de fuera del
    árbol. Que no esté documentado significa que no se puede validar, y eso
    es exactamente lo que dice el mensaje.
    """
    if any(lookup.is_documented(compatible) for compatible in compatibles):
        return

    shown = compatibles[0]
    ctx.report(
        DiagnosticCode.BINDING_UNKNOWN_COMPATIBLE,
        Severity.INFO,
        f"«{shown}» is not documented in any binding",
        node,
        property_name="compatible",
        hint="with no binding its properties cannot be checked",
    )


def _declared_in(schema: NodeSchema) -> Optional[str]:
    """Respaldo cuando el schema no dice nada de la propiedad: dónde mirarlo."""
    fichero = schema_file(schema.schema_id)
    return f"required by {fichero}" if fichero else None


def _is_rejected(schema: NodeSchema) -> bool:
    """Indica si el compatible está documentado como no válido.

    El kernel reúne en `incomplete-devices.yaml` los compatibles heredados,
    rechazados o mal formados, y les exige una propiedad inventada
    (`broken-usage-of-incorrect-compatible`) para que la validación siempre
    falle. Detectarlo permite decir lo que pasa en vez de repetir ese
    requisito artificial.
    """
    return schema.schema_id.endswith("incomplete-devices.yaml")


def _report_rejected(
    ctx: SpecContext, node: DeviceTreeNode, schema: NodeSchema
) -> None:
    """Avisa de un compatible que el kernel documenta como rechazado."""
    ctx.report(
        DiagnosticCode.BINDING_REJECTED_COMPATIBLE,
        Severity.WARNING,
        f"«{schema.compatible}» is a rejected or incomplete compatible",
        node,
        property_name="compatible",
        hint=(
            "the kernel lists it in incomplete-devices.yaml; "
            "use the real binding's one"
        ),
    )


def _check_required(ctx: SpecContext, node: DeviceTreeNode, schema: NodeSchema) -> None:
    """Comprueba las propiedades y subnodos que el binding exige."""
    properties = ctx.effective_properties(node)
    if _is_disabled(properties):
        # Un nodo deshabilitado es una plantilla que la placa completará:
        # `dt-validate` también se salta sus requisitos por lo mismo.
        return
    if ctx.is_partial_view(node):
        # Reapertura de la que solo se ve un trozo: lo que el nodo tenga puede
        # estar en el fichero que lo define.
        return

    children = {child.name for child in ctx.effective_children(node)}
    base_children = {name.split("@", 1)[0] for name in children}

    for name in schema.required:
        if name in _RESOLUTION_OWNED:
            continue

        if name in properties or name in children or name in base_children:
            continue

        # Que la entrada sea un nodo o una propiedad se decide por cómo la
        # define el schema, pero la presencia se busca en los dos sitios: hay
        # subnodos definidos solo con un `$ref` (`port` apunta a
        # `graph.yaml`), que no se distinguen de una propiedad por su forma.
        definition = schema.properties.get(name)
        if definition is not None and definition.is_node:
            ctx.report(
                DiagnosticCode.BINDING_MISSING_NODE,
                Severity.ERROR,
                f"binding «{schema.compatible}» requires the node «{name}»",
                node,
                hint=property_hint(definition) or _declared_in(schema),
                missing=True,
            )
            continue

        ctx.report(
            DiagnosticCode.BINDING_MISSING_PROPERTY,
            Severity.ERROR,
            f"binding «{schema.compatible}» requires the property «{name}»",
            node,
            # Qué escribir, no cómo se llama el binding: el tipo de la
            # propiedad y qué dice el schema de ella (ver `property_hint`).
            hint=property_hint(definition) or _declared_in(schema),
            missing=True,
        )


def _check_unknown_properties(
    ctx: SpecContext,
    node: DeviceTreeNode,
    schema: NodeSchema,
    lookup: SchemaLookup,
) -> None:
    """Avisa de propiedades que el binding no admite.

    Solo tiene sentido cuando el schema está **cerrado**
    (`additionalProperties`/`unevaluatedProperties` a false): entonces
    enumera todo lo admisible y lo que no está, sobra. Con un schema abierto
    no se puede afirmar nada, así que no se dice nada.

    Se miran las propiedades escritas en este documento, no las del árbol
    fusionado: de las que vienen de un include ya avisará el fichero donde
    están escritas.
    """
    if not schema.closed:
        return

    for name in node.properties:
        if name in _ALWAYS_ALLOWED or name in SPEC_OWNED_PROPERTIES:
            continue
        if schema.allows(name):
            continue

        verdict = _parent_verdict(ctx, node, name, lookup)
        if verdict is True:
            continue

        # Si no se sabe qué binding tiene el nodo padre, tampoco se sabe si
        # es él quien admite la propiedad: se deja el aviso en INFO diciendo
        # justo eso, en vez de afirmar que sobra.
        severity = Severity.WARNING if verdict is False else Severity.INFO
        hint = (
            f"{schema_file(schema.schema_id)} enumerates the ones it admits"
            if verdict is False
            else "the parent node's binding is unknown, and it might admit it"
        )
        ctx.report(
            DiagnosticCode.BINDING_UNKNOWN_PROPERTY,
            severity,
            f"binding «{schema.compatible}» does not admit the property «{name}»",
            node,
            property_name=name,
            hint=hint,
        )


def _check_schema_values(
    ctx: SpecContext,
    node: DeviceTreeNode,
    schema: NodeSchema,
    lookup: SchemaLookup,
) -> None:
    """Valida los valores del nodo dándole el nodo entero a su schema.

    Es lo que hace `dt-validate`, pero sobre lo que se está editando: el nodo
    se codifica como la instancia que espera el schema y de la respuesta se
    cuentan solo los problemas de valor. Las propiedades que no se han podido
    codificar no aparecen en la instancia, así que no se dice nada de ellas.
    """
    encoded = encode_instance(ctx, node)
    reported: set = set()
    for issue in lookup.validate_node(schema, encoded.instance):
        if issue.keyword not in VALUE_KEYWORDS:
            continue
        name = issue.property_name
        if name in (None, "$nodename") or name in SPEC_OWNED_PROPERTIES:
            continue
        if not encoded.covers(name) or name in reported:
            # Un mismo valor puede incumplir a la vez lo que dice el binding y
            # lo que hereda de su clase (400 kHz del controlador de Cadence y
            # 5 MHz del I2C genérico): con decirlo una vez basta.
            continue
        reported.add(name)
        # El fichero que pone la pega solo se dice cuando **no** es el del
        # compatible: la mitad de las reglas se heredan de la clase
        # (`i2c-controller.yaml` y compañía) y ahí saberlo ahorra buscarlo;
        # cuando coincide, repetiría lo que el mensaje ya dice.
        culpable = schema_file(issue.schema_id) if issue.schema_id else ""
        ctx.report(
            DiagnosticCode.BINDING_PROPERTY_VALUE,
            Severity.WARNING,
            f"«{name}»: {issue.message} according to «{schema.compatible}»",
            node,
            property_name=name,
            hint=culpable if culpable != schema_file(schema.schema_id) else None,
        )


def _parent_verdict(
    ctx: SpecContext,
    node: DeviceTreeNode,
    name: str,
    lookup: SchemaLookup,
) -> Optional[bool]:
    """Qué dice el binding del nodo padre sobre una propiedad del hijo.

    True si la admite, False si se conoce su binding y no la admite, y None
    si no se sabe cuál es su binding y por tanto no se puede concluir nada.

    Un bus describe en su propio binding lo que pueden llevar los
    dispositivos que cuelgan de él: el controlador de memoria externa de
    STM32 declara ahí los `st,fmc2-ebi-cs-*` de sus chip-selects, y el
    binding del chip que se conecta —una ethernet Micrel, por ejemplo— no
    tiene por qué conocerlos.
    """
    parent = node.parent
    if parent is None or parent is ctx.root or parent.parent is None:
        # Colgar de la raíz no es colgar de un bus: ahí no hay ningún binding
        # padre que pueda aportar propiedades al hijo.
        return False

    compatibles = _compatibles(ctx, parent)
    if not compatibles:
        # Un contenedor sin compatible (`soc { … }`) no aporta propiedades;
        # pero si es un nodo que solo se reabre aquí, puede que sí las tenga
        # en el fichero donde está definido.
        return None if ctx.missing_is_conclusive(parent) is not None else False

    known = False
    for compatible in compatibles:
        child_schema = lookup.child_schema_for(compatible, node.name)
        if child_schema is not None and child_schema.allows(name):
            return True
        if lookup.schema_for(compatible) is not None:
            known = True
    return False if known else None


def _is_disabled(properties) -> bool:
    """Indica si el nodo está marcado como deshabilitado."""
    raw = properties.get("status")
    if raw is None:
        return False
    strings = values.string_list(values.raw_text(raw))
    return bool(strings) and strings[0] in {"disabled", "reserved"}

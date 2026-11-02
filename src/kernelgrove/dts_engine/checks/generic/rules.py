"""Capa 2: los bindings genéricos, los que valen para una clase de dispositivo.

No son el binding de un `compatible` concreto (esa es la capa 5) sino los que
describen *clases*: un controlador GPIO, un bus I2C, un regulador, las
propiedades comunes de un puerto de vídeo. dt-schema los distingue porque
llevan `select`: en vez de buscarse por compatible, se prueban contra todos
los nodos y cada uno decide si le toca. En el kernel son 228 de 5 663.

Se ejecuta **aparte de las demás capas**, porque cuesta unos 15 ms por nodo
—hay que evaluar los 228 `select`— y eso son segundos en un SoC entero. Quien
la llama (la GUI, en un hilo de fondo) decide cuándo.

Las mismas cautelas que la capa 5, y una más propia: la instancia del nodo no
lleva las propiedades que no se han podido codificar, así que un «falta esta
propiedad» solo se cuenta después de comprobar que de verdad no está escrita.
"""

from __future__ import annotations

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.checks.bindings.instance import encode_instance
from kernelgrove.dts_engine.checks.bindings.lookup import (
    VALUE_KEYWORDS,
    SchemaLookup,
)
from kernelgrove.dts_engine.checks.context import SPEC_OWNED_PROPERTIES, SpecContext
from kernelgrove.dts_engine.diagnostics import DiagnosticCode, Severity


def check_generic(ctx: SpecContext, lookup: SchemaLookup) -> None:
    """Contrasta cada nodo con los bindings genéricos que le apliquen."""
    for node in ctx.walk():
        _check_vendor_prefixes(ctx, node, lookup)
        encoded = encode_instance(ctx, node)
        issues = lookup.validate_generic(encoded.instance)
        if not issues:
            continue

        properties = ctx.effective_properties(node)
        children = {child.name for child in ctx.effective_children(node)}
        for issue in issues:
            name = issue.property_name
            if name is None or name == "$nodename" or name in SPEC_OWNED_PROPERTIES:
                continue

            if issue.keyword in ("required", "dependentRequired", "dependencies"):
                # La instancia solo lleva lo codificable: antes de decir que
                # falta hay que mirar el árbol, que es la única fuente de
                # presencia.
                if name in properties or name in children:
                    continue
                if ctx.is_partial_view(node):
                    # `&gpio1 { … }` en un `.dtsi`: lo que el nodo tenga está
                    # en el fichero que lo define, no aquí.
                    continue
                ctx.report(
                    DiagnosticCode.GENERIC_MISSING_PROPERTY,
                    Severity.ERROR,
                    f"«{name}» is required by «{_class_of(issue)}»",
                    node,
                    # El tipo, que es lo que hace falta para escribirla. El
                    # título del binding genérico ya lo dice el mensaje, y
                    # repetirlo aquí gastaba la columna en nada.
                    hint=lookup.property_type(name),
                    missing=True,
                )
                continue

            if issue.keyword not in VALUE_KEYWORDS:
                continue
            if not encoded.covers(name):
                continue

            ctx.report(
                DiagnosticCode.GENERIC_PROPERTY_VALUE,
                Severity.WARNING,
                f"«{name}»: {issue.message} "
                f"according to «{_class_of(issue)}»",
                node,
                property_name=name,
                # Sin pista: el mensaje ya dice qué falla y quién lo dice.
            )


def _check_vendor_prefixes(
    ctx: SpecContext, node: DeviceTreeNode, lookup: SchemaLookup
) -> None:
    """Comprueba que las propiedades con prefijo usen un fabricante registrado.

    Se miran solo las escritas en este documento y solo las que llevan coma:
    un `xlnx,foo` es una propiedad de fabricante y el prefijo tiene que estar
    en `vendor-prefixes.yaml`, el registro del kernel. Sin coma no hay prefijo
    que comprobar.
    """
    for name in node.properties:
        if "," not in name or lookup.is_known_property_name(name):
            continue
        if "(" in name:
            # Nombre generado por una macro de C (`EFUSE(10, 27)`): lo que hay
            # en el árbol es la macro sin expandir, no el nombre real. Es
            # trabajo de la capa 3, igual que en la capa 1.
            continue
        vendor = name.split(",", 1)[0]
        ctx.report(
            DiagnosticCode.GENERIC_VENDOR_PREFIX,
            Severity.WARNING,
            f"«{vendor}» is not a registered vendor prefix",
            node,
            property_name=name,
            hint="listed in vendor-prefixes.yaml; usually a typo",
        )


def _class_of(issue) -> str:
    """Nombre corto del binding genérico que emitió el problema."""
    return issue.schema_id.rsplit("/", 1)[-1].removesuffix(".yaml")

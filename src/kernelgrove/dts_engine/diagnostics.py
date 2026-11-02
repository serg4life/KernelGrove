"""Diagnósticos emitidos por el motor semántico.

Un diagnóstico es un problema localizado en el fuente: puede venir del
analizador sintáctico (llaves sin cerrar, propiedad sin `;`) o del análisis
semántico contra la base de bindings (compatible desconocido, nodo colgado de
un bus que no le corresponde, propiedad obligatoria ausente).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Severity(str, Enum):
    """Gravedad de un diagnóstico."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class DiagnosticCode(str, Enum):
    """Identificador estable de cada tipo de problema detectado.

    Tenerlos tipados permite filtrar o silenciar categorías concretas sin
    depender del texto del mensaje, que está pensado para leerse.
    """

    # Sintaxis
    UNBALANCED_BRACE = "unbalanced-brace"
    UNEXPECTED_CLOSE = "unexpected-close"
    MISSING_SEMICOLON = "missing-semicolon"
    MALFORMED_NODE = "malformed-node"

    # Capa 1: especificación Device Tree (ver docs/SEMANTIC-ENGINE-FLOW.md).
    # Son reglas del propio lenguaje, no de ningún binding.
    SPEC_NODE_NAME = "spec-node-name"
    SPEC_UNIT_ADDRESS = "spec-unit-address"
    SPEC_PROPERTY_NAME = "spec-property-name"
    SPEC_LABEL = "spec-label"
    SPEC_NAME_CLASH = "spec-name-clash"
    SPEC_PROPERTY_ORDER = "spec-property-order"
    SPEC_PROPERTY_VALUE = "spec-property-value"
    SPEC_CONFLICTING_PROPERTIES = "spec-conflicting-properties"
    SPEC_DEPRECATED = "spec-deprecated"
    SPEC_REG_MISMATCH = "spec-reg-mismatch"
    SPEC_MISSING_PROPERTY = "spec-missing-property"
    SPEC_MISSING_NODE = "spec-missing-node"
    SPEC_DTS_VERSION = "spec-dts-version"

    # Capa 2: bindings genéricos (clases de dispositivo, buses, propiedades
    # comunes). Son los schemas que dt-schema aplica por la forma del nodo.
    GENERIC_MISSING_PROPERTY = "generic-missing-property"
    GENERIC_PROPERTY_VALUE = "generic-property-value"
    GENERIC_VENDOR_PREFIX = "generic-vendor-prefix"

    # Capa 3: existencia de macros de `dt-bindings/*.h` (no su valor: eso
    # exigiría expandirlas de verdad, ver checks/macros.py).
    MACRO_MISSING_INCLUDE = "macro-missing-include"
    MACRO_UNKNOWN = "macro-unknown"

    # Capa 5: el binding del `compatible` concreto, tal y como lo procesa
    # dt-schema. Son reglas de un dispositivo, no del lenguaje.
    BINDING_UNKNOWN_COMPATIBLE = "binding-unknown-compatible"
    BINDING_REJECTED_COMPATIBLE = "binding-rejected-compatible"
    BINDING_MISSING_PROPERTY = "binding-missing-property"
    BINDING_MISSING_NODE = "binding-missing-node"
    BINDING_UNKNOWN_PROPERTY = "binding-unknown-property"
    BINDING_PROPERTY_VALUE = "binding-property-value"
    BINDING_NEWER_THAN_KERNEL = "binding-newer-than-kernel"

    # Capa 6: reglas propias de un overlay, que solo tienen sentido contra
    # el árbol base sobre el que se aplicará (ver checks/overlay.py).
    OVERLAY_TARGET_NOT_FOUND = "overlay-target-not-found"


@dataclass(frozen=True)
class Diagnostic:
    """Un problema detectado, localizado en el fuente."""

    code: DiagnosticCode
    severity: Severity
    message: str
    line: int = 1
    node_path: Optional[str] = None
    hint: Optional[str] = None
    # Propiedad a la que se refiere, si el problema es de una en concreto.
    # Permite señalarla en la interfaz y descartar duplicados cuando dos capas
    # avisan de lo mismo desde fuentes distintas.
    property_name: Optional[str] = None

    @property
    def family(self) -> str:
        """Tipo de problema, sin la capa que lo detectó.

        `binding-property-value` y `generic-property-value` son el mismo tipo
        de aviso visto por dos capas; comparar por la familia permite no
        repetirlo cuando las dos hablan de la misma propiedad.
        """
        value = self.code.value
        return value.split("-", 1)[1] if "-" in value else value

    @property
    def label(self) -> str:
        """Resumen de una línea para listarlo en la interfaz."""
        return f"L{self.line}  {self.message}"

    def __str__(self) -> str:
        """Representación textual del diagnóstico, con pista si la hay."""
        text = f"[{self.severity.value}] line {self.line}: {self.message}"
        if self.hint:
            text = f"{text} ({self.hint})"
        return text

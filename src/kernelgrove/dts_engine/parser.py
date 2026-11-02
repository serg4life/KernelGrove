"""Analizador de fuentes Device Tree (`.dts` / `.dtsi`).

Convierte el texto en un árbol de `DeviceTreeNode` y, de paso, informa de los
problemas estructurales que encuentra (llaves descompensadas, propiedades sin
`;`, cabeceras de nodo malformadas).

No consulta la base de datos: aquí solo se analiza la *forma* del fuente. Las
reglas del lenguaje y el contraste contra los bindings los aplican las capas
de `dts_engine.checks`, lo que permite usar este módulo tanto en la ingesta
como en el editor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from kernelgrove.dt_model.model import DeviceTreeNode
from kernelgrove.dts_engine.diagnostics import Diagnostic, DiagnosticCode, Severity

# Cabecera de nodo: "label: nombre@dirección {" (label y dirección opcionales).
# También se aceptan referencias por label ("&i2c0 {") y la raíz ("/ {").
# Caracteres admisibles en la cabecera de un nodo. Incluye «{}» porque la
# referencia por ruta se escribe `&{/ruta/al/nodo}`.
_NODE_HEADER_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_,.+-@/&#{}"
)

# Directiva de dtc que puede preceder a la cabecera de un nodo: descarta el
# nodo si nadie lo referencia. No es parte del nombre ni de la etiqueta.
_OMIT_IF_NO_REF = "/omit-if-no-ref/"

# Directivas de borrado de dtc. Son sentencias (acaban en «;») y no abren nodo,
# así que caen en `_apply_statement`, que es donde se reconocen.
_DELETE_NODE = "/delete-node/"
_DELETE_PROPERTY = "/delete-property/"

# Directivas del preprocesador: ocupan la línea entera y no llevan «;», así que
# hay que consumirlas enteras o contaminarían la siguiente sentencia. No se
# puede descartar todo lo que empiece por «#»: `#address-cells` es una
# propiedad legítima.
_PREPROCESSOR_DIRECTIVES = (
    "include",
    "define",
    "undef",
    "ifdef",
    "ifndef",
    "endif",
    "else",
    "elif",
    "if ",
    "pragma",
    "error",
    "warning",
)


@dataclass(frozen=True)
class IncludeDirective:
    """Una inclusión de otro fuente encontrada en el fichero.

    Device tree admite dos formas: la del preprocesador de C
    (`#include <x.h>` o `#include "x.dtsi"`) y la propia de dtc
    (`/include/ "x.dtsi"`).
    """

    target: str
    line: int
    # Ruta del nodo dentro del cual se escribió la directiva; vacía si está a
    # nivel de fichero, que es lo normal. Un `#include` dentro de un nodo
    # aporta su contenido *ahí*, no en la raíz, y quien lo fusione tiene que
    # saberlo (la Raspberry Pi 5 mete así los subnodos de su RP1).
    node_path: str = ""

    @property
    def is_header(self) -> bool:
        """Indica si incluye una cabecera C (`.h`) y no un device tree."""
        return self.target.endswith(".h")


@dataclass(frozen=True)
class DeleteDirective:
    """Un `/delete-node/` o `/delete-property/` encontrado en el fichero.

    dtc los procesa quitando del árbol lo que se nombra, así que sin ellos el
    árbol fusionado conserva nodos y propiedades que el binario compilado no
    tiene y las capas de comprobación juzgan un árbol que no existe. El parser
    solo los anota: aplicarlos exige el árbol ya fusionado (lo normal es que
    una placa borre algo que trae el `.dtsi` del SoC), y de eso se encarga
    `dt_model.model.apply_deletions`.
    """

    # "node" o "property".
    kind: str
    # Nombre del nodo o de la propiedad. Para un nodo puede ser también una
    # referencia (`&i2c0`, `&{/soc/i2c@0}`), que se resuelve al aplicarla.
    target: str
    # Ruta del nodo donde está escrita la directiva; vacía a nivel de fichero.
    node_path: str
    line: int


@dataclass
class ParseResult:
    """Resultado del análisis: árbol, diagnósticos, includes y líneas."""

    root: DeviceTreeNode
    diagnostics: List[Diagnostic] = field(default_factory=list)
    # (ruta del nodo, nombre de propiedad) -> línea, para localizar avisos.
    property_lines: Dict[Tuple[str, str], int] = field(default_factory=dict)
    includes: List[IncludeDirective] = field(default_factory=list)
    # Lo que el fichero manda quitar del árbol, en orden de aparición.
    deletions: List[DeleteDirective] = field(default_factory=list)

def strip_comments(text: str) -> str:
    """Elimina comentarios `//` y `/* */` conservando los saltos de línea.

    Los saltos se preservan (los comentarios de bloque se sustituyen por sus
    propios `\\n`) para que los números de línea sigan siendo correctos al
    señalar diagnósticos en el editor. Las comillas se respetan: un `//`
    dentro de una cadena no abre comentario.
    """
    out: List[str] = []
    index = 0
    length = len(text)
    in_string = False

    while index < length:
        char = text[index]

        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length:
            following = text[index + 1]
            if following == "/":
                while index < length and text[index] != "\n":
                    index += 1
                continue
            if following == "*":
                end = text.find("*/", index + 2)
                block = text[index : end + 2] if end != -1 else text[index:]
                out.append("\n" * block.count("\n"))
                index = (end + 2) if end != -1 else length
                continue

        out.append(char)
        index += 1

    return "".join(out)


def parse_compatible_value(raw_value: str) -> List[str]:
    """Extrae los strings entre comillas del valor de un `compatible`."""
    values: List[str] = []
    inside = False
    current: List[str] = []

    for char in raw_value:
        if char == '"':
            if inside:
                values.append("".join(current))
                current = []
            inside = not inside
        elif inside:
            current.append(char)

    return values


_INCLUDE_RE = re.compile(
    r"""^\s*(?:
            \#\s*include\s*(?:"(?P<quoted>[^"]+)"|<(?P<angled>[^>]+)>)
          | /include/\s*"(?P<dtc>[^"]+)"
        )""",
    re.VERBOSE,
)


def collect_includes(
    text: str, node_paths: Optional[Mapping[int, str]] = None
) -> List[IncludeDirective]:
    """Recoge las inclusiones declaradas en el fuente, con su línea.

    El análisis del árbol se salta estas líneas (no aportan nodos), pero la
    vista de grafo las representa como paquetes de contenido, así que hay que
    conservarlas en lugar de descartarlas.

    `node_paths` asocia número de línea con la ruta del nodo que estaba
    abierto ahí; lo produce el recorrido principal, que es el único que
    conoce la jerarquía. Sin él todas las inclusiones quedan a nivel de
    fichero, que es lo que se supone en la mayoría de los casos.
    """
    includes: List[IncludeDirective] = []

    for number, raw_line in enumerate(strip_comments(text).splitlines(), start=1):
        match = _INCLUDE_RE.match(raw_line)
        if not match:
            continue

        quoted = match.group("quoted")
        angled = match.group("angled")
        dtc = match.group("dtc")

        target = quoted or angled or dtc or ""
        if not target:
            continue

        includes.append(
            IncludeDirective(
                target=target,
                line=number,
                node_path=(node_paths or {}).get(number, ""),
            )
        )

    return includes


def find_matching_brace(text: str, position: int) -> Optional[int]:
    """Devuelve la posición de la llave que empareja con la de `position`.

    Recorre el texto contando profundidad y saltándose las llaves que
    aparecen dentro de cadenas. Devuelve None si la llave está huérfana.

    Función de texto puro (sin `QTextCursor`) para que la reutilicen tanto el
    resaltado del editor (`DtsEditor`) como la escritura de overrides
    (`api.overrides`), que necesita localizar el cierre de un bloque
    `&label { … }` ya existente para insertar o sustituir una propiedad.
    """
    if position < 0 or position >= len(text):
        return None

    char = text[position]
    if char == "{":
        step, opening, closing = 1, "{", "}"
    elif char == "}":
        step, opening, closing = -1, "}", "{"
    else:
        return None

    depth = 0
    index = position
    while 0 <= index < len(text):
        current = text[index]
        if current == '"':
            # Saltar la cadena entera en el sentido de la marcha.
            index += step
            while 0 <= index < len(text) and text[index] != '"':
                index += step
        elif current == opening:
            depth += 1
        elif current == closing:
            depth -= 1
            if depth == 0:
                return index
        index += step

    return None


def _parse_node_header(header: str) -> Optional[Tuple[Optional[str], str]]:
    """Descompone la cabecera de un nodo en (label, nombre).

    Devuelve None si el texto no tiene forma de cabecera de nodo, lo que el
    llamante traduce en un diagnóstico de nodo malformado.
    """
    header = header.strip()
    if not header:
        return None

    # `/omit-if-no-ref/ label: nodo {` marca el nodo para que dtc lo descarte
    # si nadie lo referencia. No forma parte del nombre ni de la etiqueta.
    if header.startswith(_OMIT_IF_NO_REF):
        header = header[len(_OMIT_IF_NO_REF) :].strip()
        if not header:
            return None

    label: Optional[str] = None
    if ":" in header:
        # Un nodo admite varias etiquetas encadenadas
        # (`vdd_gpu_s0: vdd_gpu_mem_s0: dcdc-reg1 {`). El nombre es lo que hay
        # tras el último «:»; se conserva la primera etiqueta, que es la que
        # se usa por convención para referenciarlo.
        label_part, _, rest = header.rpartition(":")
        label = label_part.split(":")[0].strip() or None
        header = rest.strip()

    if not header:
        return None

    # `/dts-v1/;` y directivas similares no son nodos.
    if header.startswith("/") and header != "/":
        return None

    if not set(header) <= _NODE_HEADER_CHARS:
        return None

    return (label, header)


def parse_dts_source(text: str) -> ParseResult:
    """Analiza un fuente Device Tree completo y devuelve árbol y diagnósticos.

    Recorre el texto carácter a carácter llevando la cuenta de la línea y una
    pila de nodos abiertos. Se apoya en tres delimitadores: `{` cierra la
    cabecera de un nodo, `}` lo cierra, y `;` termina una propiedad. Trabajar
    sobre el texto (y no línea a línea) permite aceptar propiedades repartidas
    en varias líneas, habituales en los `.dts` reales.
    """
    source = strip_comments(text)
    root = DeviceTreeNode(name="/", label="root")
    root.path = ""
    root.line = 1

    stack: List[DeviceTreeNode] = [root]
    # Línea -> ruta del nodo abierto en ella, para las directivas `#include`
    # escritas dentro de un nodo (ver `collect_includes`).
    include_nodes: Dict[int, str] = {}
    # La falta de «;» se comprueba por líneas: es la regla del lenguaje
    # («toda sentencia acaba en ;») y cubre casos que el recorrido por
    # caracteres no distingue.
    diagnostics: List[Diagnostic] = check_statement_terminators(text)
    property_lines: Dict[Tuple[str, str], int] = {}
    deletions: List[DeleteDirective] = []

    buffer: List[str] = []
    buffer_line = 1
    line = 1
    in_string = False
    index = 0
    length = len(source)

    def buffer_text() -> str:
        """Texto acumulado desde el último delimitador, ya normalizado."""
        return " ".join("".join(buffer).split())

    def buffer_is_blank() -> bool:
        """Si en el buffer no hay todavía nada que no sea espacio.

        Equivale a `not buffer_text()`, pero sin construir la cadena: esa
        pregunta se hace una vez por carácter del fichero —111 000 veces en
        un SoC mediano— y normalizar el buffer entero para responderla era la
        mitad del coste del parser. Aquí el recorrido se corta en el primer
        trozo con contenido, que en cuanto el buffer no está vacío es el
        primero o casi.
        """
        return all(not part or part.isspace() for part in buffer)

    while index < length:
        char = source[index]

        if char == "\n":
            line += 1
            buffer.append(" ")
            index += 1
            if buffer_is_blank():
                buffer_line = line
            continue

        if buffer_is_blank() and not char.isspace():
            # Primer carácter con contenido tras el último delimitador: aquí
            # empieza la sentencia o la cabecera de nodo.
            buffer_line = line

        if in_string:
            buffer.append(char)
            if char == "\\" and index + 1 < length:
                buffer.append(source[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            buffer.append(char)
            index += 1
            continue

        if char == "#" and buffer_is_blank():
            rest = source[index + 1 : index + 12].lstrip().lower()
            if rest.startswith(_PREPROCESSOR_DIRECTIVES):
                if rest.startswith("include") and stack[-1].path:
                    include_nodes[line] = stack[-1].path
                # Una macro puede continuar en la línea siguiente terminando
                # en «\»; hay que consumirla entera o su cuerpo se tomaría por
                # código del device tree.
                while index < length:
                    if source[index] == "\n":
                        line += 1
                        previous = "".join(
                            source[max(0, index - 3) : index]
                        ).rstrip()
                        if not previous.endswith("\\"):
                            index += 1
                            break
                    index += 1
                buffer = []
                buffer_line = line
                continue

        # `/include/ "fichero.dtsi"` es la inclusión propia de dtc y, a
        # diferencia del resto de directivas, no termina en «;». Si no se
        # consume entera, se fusiona con la cabecera del nodo siguiente y la
        # invalida.
        if char == "/" and buffer_is_blank() and source.startswith("/include/", index):
            if stack[-1].path:
                include_nodes[line] = stack[-1].path
            while index < length and source[index] != "\n":
                index += 1
            buffer = []
            continue

        # `&{/ruta/al/nodo}` referencia un nodo por su ruta completa. Sus llaves
        # forman parte del nombre, no abren un nodo, así que se absorben enteras.
        if char == "{" and "".join(buffer).rstrip().endswith("&"):
            end = source.find("}", index)
            if end != -1:
                buffer.append(source[index : end + 1])
                index = end + 1
                continue

        if char == "{":
            header = buffer_text()

            # «/ {» no abre un nodo nuevo: es el propio nodo raíz. Un fuente
            # puede reabrirlo varias veces y todo debe acumularse en la misma
            # raíz, así que se reutiliza en lugar de anidar otro «/».
            # El nivel raíz es tener solo el nodo raíz sintético en la pila; al
            # abrir «/ {» se reapila para que su cierre lo desapile.
            at_top_level = len(stack) == 1

            if header == "/" and at_top_level:
                stack.append(root)
                buffer = []
                buffer_line = line
                index += 1
                continue

            # `/ {` y `&label {` solo son válidos en el nivel raíz: el nodo raíz
            # no se anida y los bloques de sobrescritura por etiqueta tampoco.
            # Encontrarlos dentro de otro nodo demuestra que falta una «}», y a
            # diferencia del final del fichero aquí sí se sabe qué nodos siguen
            # abiertos. Es una regla del lenguaje, no una convención de estilo.
            if (header == "/" or header.startswith("&")) and not at_top_level:
                pending_nodes = [node for node in stack[1:] if node is not root]
                open_nodes = ", ".join(
                    f"«{node.name}» (line {node.line})" for node in pending_nodes
                ) or "the root block «/»"
                diagnostics.append(
                    Diagnostic(
                        code=DiagnosticCode.UNBALANCED_BRACE,
                        severity=Severity.ERROR,
                        message=(
                            f"«{header}» can only appear at the root level, but this "
                            f"is still open: {open_nodes}"
                        ),
                        line=(pending_nodes[-1].line if pending_nodes else buffer_line),
                        node_path=stack[-1].path,
                        hint="A «};» is missing before this line",
                    )
                )

            parsed = _parse_node_header(header)
            if parsed is None:
                diagnostics.append(
                    Diagnostic(
                        code=DiagnosticCode.MALFORMED_NODE,
                        severity=Severity.ERROR,
                        message=f"Unrecognised node header: {header!r}",
                        line=buffer_line,
                        hint="Expected «label: name@address {»",
                    )
                )
                node = _open_node(
                    stack[-1], header or "<unnamed>", None, buffer_line
                )
            else:
                label, name = parsed
                node = _open_node(stack[-1], name, label, buffer_line)

            stack.append(node)
            buffer = []
            buffer_line = line
            index += 1
            continue

        if char == "}":
            pending = buffer_text()
            if pending:
                # La falta del «;» ya la reporta `check_statement_terminators`;
                # aquí solo se registra la propiedad para que el árbol refleje
                # lo que el usuario escribió.
                _apply_statement(
                    stack[-1], pending, buffer_line, property_lines, deletions
                )

            if len(stack) > 1:
                stack.pop()
            else:
                diagnostics.append(
                    Diagnostic(
                        code=DiagnosticCode.UNEXPECTED_CLOSE,
                        severity=Severity.ERROR,
                        message="«}» with no open node to close",
                        line=line,
                    )
                )

            buffer = []
            buffer_line = line
            index += 1
            continue

        if char == ";":
            statement = buffer_text()
            if statement:
                _apply_statement(
                    stack[-1], statement, buffer_line, property_lines, deletions
                )
            buffer = []
            buffer_line = line
            index += 1
            continue

        buffer.append(char)
        index += 1

    # Al llegar al final quedan abiertos tantos nodos como «}» falten. Cuál es
    # el que se quedó sin cerrar no se puede saber: si a un nodo intermedio le
    # falta su llave, las de los siguientes la suplen y el desajuste aflora
    # aquí. Se listan todos los que siguen abiertos, del más interno al más
    # externo, porque el más interno es el candidato más probable.
    unclosed_nodes = [node for node in stack[1:] if node is not root]
    for position, unclosed in enumerate(reversed(unclosed_nodes)):
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.UNBALANCED_BRACE,
                severity=Severity.ERROR,
                message=f"Node «{unclosed.name}» is opened and never closed",
                line=unclosed.line or 1,
                node_path=unclosed.path,
                hint=(
                    "A «};» is missing. This is the innermost open node, the "
                    "likeliest candidate"
                    if position == 0
                    else "A «};» is missing"
                ),
            )
        )

    if stack[-1] is root and len(stack) > 1:
        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.UNBALANCED_BRACE,
                severity=Severity.ERROR,
                message="A «};» is missing: there are more «{» than «}» in the file",
                line=line,
                hint=(
                    "Put the cursor on a «{» in the editor: with no partner it "
                    "is highlighted in red"
                ),
            )
        )

    return ParseResult(
        root=root,
        diagnostics=diagnostics,
        property_lines=property_lines,
        includes=collect_includes(text, include_nodes),
        deletions=deletions,
    )


_IDENTIFIER_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_,.+-#"
)


def _find_second_assignment(value: str) -> int:
    """Posición del «=» de una segunda asignación dentro de un valor, o -1.

    Un valor de device tree nunca contiene «=» en su nivel superior: si
    aparece, es que a la propiedad anterior le falta el «;» y se ha fundido
    con la siguiente. Se ignoran los «=» dentro de cadenas, `<...>` o `[...]`.
    """
    depth = 0
    in_string = False
    index = 0

    while index < len(value):
        char = value[index]

        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "<[":
            depth += 1
        elif char in ">]":
            depth -= 1
        elif char == "=" and depth <= 0:
            return index

        index += 1

    return -1


def _split_before_identifier(value: str, assignment: int) -> Tuple[str, str]:
    """Parte `value` justo antes del nombre de propiedad que precede a `assignment`."""
    cursor = assignment
    while cursor > 0 and value[cursor - 1].isspace():
        cursor -= 1
    while cursor > 0 and value[cursor - 1] in _IDENTIFIER_CHARS:
        cursor -= 1
    return (value[:cursor], value[cursor:])


# Finales de línea que significan «esto sigue en la línea siguiente»:
#   =  asignación cuyo valor se escribe debajo
#   ,  lista de valores repartida en varias líneas
#   \  continuación de macro del preprocesador
#   :  etiqueta cuyo nodo se declara debajo
_CONTINUATION_ENDINGS = ("=", ",", "\\", ":")

# Líneas que no son sentencias y por tanto no llevan «;»: la inclusión propia
# de dtc y `/omit-if-no-ref/`, que modifica al nodo que viene a continuación.
# Las directivas del preprocesador («#include», «#define»...) se reconocen
# aparte, con `_is_preprocessor_directive`: no basta con el prefijo «#», que
# también empieza una propiedad legítima como `#address-cells` o
# `#cooling-cells` (ver `_PREPROCESSOR_DIRECTIVES` arriba).
_LINE_DIRECTIVE_PREFIXES = ("/include/", "/omit-if-no-ref/")


def _is_preprocessor_directive(line: str) -> bool:
    """Distingue `#include`/`#define`/... de una propiedad `#algo-cells`."""
    if not line.startswith("#"):
        return False
    return line[1:].lstrip().lower().startswith(_PREPROCESSOR_DIRECTIVES)


def check_statement_terminators(text: str) -> List[Diagnostic]:
    """Comprueba que toda sentencia termine en «;».

    Es la regla del lenguaje, y por eso resulta más fiable que deducir el
    fallo del contenido: una sentencia solo puede no acabar en «;» cuando
    abre o cierra un nodo (`{`, `};`) o cuando el valor continúa en la línea
    siguiente. Detecta casos que el análisis del contenido no ve, como una
    propiedad booleana detrás de otra sin «;» (no hay un segundo «=» que
    delate la fusión).

    La continuación se determina contando delimitadores (`<>`, `[]`, comillas)
    en lugar de mirar la sangría, que en device tree no significa nada.
    """
    diagnostics: List[Diagnostic] = []
    lines = strip_comments(text).splitlines()

    depth = 0
    in_string = False
    continuing = False

    for position, raw_line in enumerate(lines):
        line = raw_line.strip()

        starts_statement = not continuing
        depth, in_string = _scan_delimiters(raw_line, depth, in_string)

        # ¿Sigue abierta la sentencia al acabar la línea?
        continuing = (
            depth > 0
            or in_string
            or line.endswith(_CONTINUATION_ENDINGS)
            or line.endswith("/bits/")
            or _ends_with_bits_width(line)
            or not line
        )

        if not line or not starts_statement or continuing:
            continue

        if line.startswith(_LINE_DIRECTIVE_PREFIXES) or _is_preprocessor_directive(
            line
        ):
            continue

        # Abrir un nodo («foo {», «/ {», «&label {») o cerrarlo («};») son las
        # dos formas legítimas de terminar sin «;».
        if line.endswith(("{", ";")):
            continue

        # El «;» puede estar solo en la línea siguiente.
        if _next_meaningful_line(lines, position + 1).startswith(";"):
            continue

        diagnostics.append(
            Diagnostic(
                code=DiagnosticCode.MISSING_SEMICOLON,
                severity=Severity.ERROR,
                message=f"The statement does not end in «;»: {line!r}",
                line=position + 1,
                hint="Every device tree statement ends in «;»",
            )
        )

    return diagnostics


def _ends_with_bits_width(line: str) -> bool:
    """Detecta `… = /bits/ 64`, cuyo valor se escribe en la línea siguiente."""
    parts = line.split()
    return len(parts) >= 2 and parts[-2] == "/bits/" and parts[-1].isdigit()


def _next_meaningful_line(lines: List[str], start: int) -> str:
    """Primera línea con contenido a partir de `start`, ya sin espacios."""
    for candidate in lines[start:]:
        stripped = candidate.strip()
        if stripped:
            return stripped
    return ""


def _scan_delimiters(line: str, depth: int, in_string: bool) -> Tuple[int, bool]:
    """Actualiza la profundidad de `<>`/`[]` y el estado de cadena tras una línea."""
    index = 0
    while index < len(line):
        char = line[index]
        if in_string:
            if char == "\\":
                index += 2
                continue
            if char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in "<[":
            depth += 1
        elif char in ">]":
            depth = max(0, depth - 1)
        index += 1
    return (depth, in_string)


def _open_node(
    parent: DeviceTreeNode,
    name: str,
    label: Optional[str],
    line: int,
) -> DeviceTreeNode:
    """Abre un nodo bajo `parent`, reabriendo el que ya exista con ese nombre.

    En device tree, volver a escribir un nodo con el mismo nombre en el mismo
    nivel no crea otro: amplía el que ya hay, que es justo lo que hacen los
    ficheros de placa al ajustar un periférico del SoC. Si se creara un
    segundo nodo, el árbol tendría dos hermanos idénticos y cualquier
    comprobación sobre uno de ellos vería solo la mitad de sus propiedades.

    La línea y la etiqueta se conservan de la primera aparición, que es donde
    el nodo se declara; una etiqueta escrita más tarde se recoge si la
    primera no la traía.
    """
    existing = None
    for child in parent.children:
        if child.name == name:
            existing = child
            break

    if existing is not None:
        if existing.label is None:
            existing.label = label
        return existing

    node = DeviceTreeNode(name=name, label=label)
    node.line = line
    parent.add_child(node)
    return node


def _store_property(
    node: DeviceTreeNode,
    name: str,
    value: object,
    line: int,
    property_lines: Dict[Tuple[str, str], int],
) -> None:
    """Guarda una propiedad en el nodo y recuerda en qué línea aparece."""
    node.properties[name] = value
    property_lines[(node.path or node.name, name)] = line


def _parse_delete(statement: str) -> Optional[Tuple[str, str]]:
    """Descompone `/delete-node/ x` o `/delete-property/ y` en (clase, objetivo).

    Devuelve None si la sentencia no es una de las dos directivas de borrado.
    """
    for directive, kind in ((_DELETE_NODE, "node"), (_DELETE_PROPERTY, "property")):
        if statement.startswith(directive):
            target = statement[len(directive) :].strip()
            if target:
                return (kind, target)
            return None
    return None


def _apply_statement(
    node: DeviceTreeNode,
    statement: str,
    line: int,
    property_lines: Dict[Tuple[str, str], int],
    deletions: Optional[List[DeleteDirective]] = None,
) -> None:
    """Registra una sentencia terminada en `;` como propiedad del nodo actual.

    Acepta tanto `nombre = valor` como propiedades booleanas (`nombre` solo).
    Las directivas del preprocesador (`/dts-v1/`, `#include`) se ignoran, y las
    de borrado se anotan en `deletions` para aplicarlas más tarde sobre el
    árbol fusionado (ver `DeleteDirective`).

    Si faltó un «;», la sentencia contendrá en realidad dos propiedades
    pegadas: aquí se separan para que el árbol siga siendo correcto. El aviso
    lo emite `check_statement_terminators`, que aplica la regla del lenguaje.
    """
    if statement.startswith("/"):
        borrado = _parse_delete(statement)
        if borrado is not None and deletions is not None:
            kind, target = borrado
            deletions.append(
                DeleteDirective(
                    kind=kind,
                    target=target,
                    node_path=node.path or "",
                    line=line,
                )
            )
        return

    if statement.startswith("#include"):
        return

    name, separator, raw_value = statement.partition("=")
    name = name.strip()
    if not name:
        return

    # Caso 1: el valor contiene otra asignación -> «nombre = valor otra = ...»
    if separator:
        second = _find_second_assignment(raw_value)
        if second != -1:
            head, tail = _split_before_identifier(raw_value, second)
            _store_property(node, name, head.strip(), line, property_lines)
            if name == "compatible":
                node.compatible.extend(parse_compatible_value(head))
            _apply_statement(node, tail.strip(), line, property_lines, deletions)
            return

    # Caso 2: nombre con espacios -> una propiedad booleana quedó pegada a la
    # siguiente («algo-booleano otra = <1>»).
    if separator and " " in name:
        boolean_part, _, real_name = name.rpartition(" ")
        boolean_part = boolean_part.strip()
        if boolean_part:
            _store_property(node, boolean_part, True, line, property_lines)
        name = real_name.strip()
        if not name:
            return

    value: object = True if not separator else raw_value.strip()
    _store_property(node, name, value, line, property_lines)

    if name == "compatible" and separator:
        node.compatible.extend(parse_compatible_value(raw_value))


def parse_dts_file(path: Path) -> ParseResult:
    """Analiza un fichero `.dts`/`.dtsi` del disco."""
    return parse_dts_source(path.read_text(encoding="utf-8", errors="replace"))


def parse_dtsi_file(path: Path) -> DeviceTreeNode:
    """Devuelve solo el árbol de un `.dts`/`.dtsi`, descartando los diagnósticos.

    Conveniencia para llamadores a los que no les interesan los avisos del
    editor, solo el árbol.
    """
    return parse_dts_file(path).root

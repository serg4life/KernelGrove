"""Fachada de la API: el único punto de entrada que la GUI debe usar.

Envuelve el acceso a la base de datos, el parseo de `.dtsi` y la construcción
del modelo interno, de forma que la interfaz no importe `db_manager`,
`dt_model` ni las clases de base de datos directamente.
"""

from __future__ import annotations

import re
import tempfile
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from kernelgrove.api.binding_schemas import BindingSchemaLookup
from kernelgrove.api.completion import CompletionContext, context_at
from kernelgrove.api.database import BindingsDatabase
from kernelgrove.api.dto import (
    BindingEntry,
    BindingInfo,
    BindingOption,
    BuildOutcome,
    BuildStep,
    IntegratedController,
    PropertySuggestion,
    SocPackage,
    SoCSummary,
)
from kernelgrove.api.dts_writer import generate_fragment
from kernelgrove.api.includes import IncludeResolver, ResolvedInclude
from kernelgrove.api.compile_overlay import (
    compile_source_file,
)
from kernelgrove.api.macros_database import MacrosDatabase
from kernelgrove.api.overlays import (
    OverlayChange,
    OverlayFragment,
    OverlayTarget,
    build_overlay_source,
    overlay_targets,
    preview_overlay,
)
from kernelgrove.api.selection import (
    PeripheralSlot,
    build_internal_model,
    count_connected_devices,
    make_connected_slot,
)
from kernelgrove.api.soc_loader import (
    extract_connectable_nodes,
)
from kernelgrove.api.socs_database import SocsDatabase
from kernelgrove.api.sources_database import SourcesDatabase, StoredSource
from kernelgrove.api.toolchain import Toolchain, detect_toolchain
from kernelgrove.db_schema import DB_SCHEMA_VERSION
from kernelgrove.dt_model.model import (
    DeviceTreeNode,
    InternalDeviceTreeModel,
    SoCProfile,
    apply_deletions,
    resolve_label_overrides,
)
from kernelgrove.dts_engine import (
    Diagnostic,
    IncludeDirective,
    ParseResult,
    Severity,
    parse_dts_source,
    run_checks,
    run_schema_checks,
)

# Orden en que se presentan los diagnósticos: lo grave primero.
_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}

# Árboles fusionados que se recuerdan a la vez (ver `_merged_tree`): el del
# documento activo, el del hilo del análisis diferido y un poco de holgura.
_MERGED_CACHE_SIZE = 4

# Compatibles resueltos por etiqueta que se recuerdan (`_compatible_for_label`,
# lo pregunta el autocompletado en cada tecla). Acotado porque una sesión
# larga con muchos ficheros abiertos lo hacía crecer sin límite.
_LABEL_CACHE_SIZE = 512

# Entrada del memo de árboles fusionados. Guarda también el `ParseResult`
# original: mientras esté aquí, su `id()` no puede reutilizarse para otro.
_MergedEntry = Tuple[ParseResult, DeviceTreeNode, List[ResolvedInclude]]


class KernelGroveService:
    """Servicio de alto nivel sobre la base de datos y el modelo interno."""

    def __init__(self, db_path: Path):
        """Crea el servicio sobre la base de datos indicada.

        Todo (bindings, SoCs y fuentes) sale de esa base: el checkout del
        kernel solo interviene al construirla, nunca en tiempo de ejecución.
        """
        self.db_path = db_path
        self._bindings = BindingsDatabase(db_path)
        self._socs = SocsDatabase(db_path, table_name="socs")
        self._boards = SocsDatabase(db_path, table_name="boards")
        self._sources = SourcesDatabase(db_path)
        # Índice de macros de `dt-bindings/*.h` (capa 3, solo existencia).
        # Puede no estar en bases antiguas o construidas sin `--table macros`;
        # `IncludeResolver`/`analyze_source` se apagan solos sin ella.
        self._macros = MacrosDatabase(db_path)
        self._includes = IncludeResolver(self._sources, self._macros)
        # Schemas de binding procesados por dt-schema: la capa 5 del motor y
        # el autocompletado. Puede no estar en bases antiguas, así que todo
        # lo que dependa de ellos comprueba antes `binding_schemas_available`.
        self._schemas = BindingSchemaLookup(db_path)
        # (fichero, etiqueta) -> compatible del nodo que reabre `&etiqueta`.
        # Resolverlo obliga a fusionar los includes, así que se recuerda: el
        # autocompletado lo pregunta en cada tecla.
        self._label_compatibles: "OrderedDict[Tuple[Optional[str], str], Optional[str]]"
        self._label_compatibles = OrderedDict()
        # Árbol fusionado del último análisis, para no repetirlo (`_merged_tree`).
        self._merged_cache: "OrderedDict[Tuple[int, Optional[str]], _MergedEntry]"
        self._merged_cache = OrderedDict()
        # Dispositivos conectables por bus. El Generador y el Visualizador
        # precargan los mismos buses a la vez, cada uno en su hilo: sin esto
        # las mismas consultas se hacían dos veces por cada perfil cargado.
        self._options_by_bus: Dict[str, List[BindingOption]] = {}
        # Release del kernel contra la que se trabaja, si el usuario la ha
        # declarado (`kernel_target`). Es un ajuste de sesión y no un
        # argumento de cada análisis: vale para todo lo que se abra, y así no
        # hay que pasarlo por las cuatro llamadas que analizan.
        self.kernel_target: Optional[str] = None

    # ------------------------------------------------------------------
    # SoCs
    # ------------------------------------------------------------------
    def list_socs(self) -> List[SoCSummary]:
        """Lista todos los SoCs disponibles en la base de datos."""
        return self._socs.list_socs()

    def read_soc_source(self, soc: SoCSummary) -> Optional[StoredSource]:
        """Devuelve el fuente `.dtsi` de un SoC guardado en la base de datos."""
        if not soc.file_path:
            return None
        return self._sources.get(soc.file_path)

    # ------------------------------------------------------------------
    # Boards
    # ------------------------------------------------------------------
    def list_boards(self) -> List[SoCSummary]:
        """Lista todas las boards disponibles en la base de datos."""
        return self._boards.list_socs()

    def read_board_source(self, board: SoCSummary) -> Optional[StoredSource]:
        """Devuelve el fuente `.dts` de una board guardada en la base de datos."""
        if not board.file_path:
            return None
        return self._sources.get(board.file_path)

    # ------------------------------------------------------------------
    # Fuentes e inclusiones
    # ------------------------------------------------------------------
    def read_source(self, key: str) -> Optional[str]:
        """Texto de un fuente del catálogo por su clave, o `None` si no está.

        La clave es la misma que guardan `socs.file_path` y `boards.file_path`
        (`xilinx/zynqmp.dtsi`). Lo usa el asistente de overlays para resolver
        la base que un overlay declara: puede ser un fichero que ya no está
        abierto ni en el disco del usuario, pero sí en la base de datos.
        """
        stored = self._sources.get(key)
        return stored.text if stored is not None else None

    def resolve_include(
        self,
        directive: IncludeDirective,
        base_path: Optional[str] = None,
    ) -> ResolvedInclude:
        """Localiza en la base de datos el contenido de un único include.

        A diferencia de `build_visual_tree`, no distingue tipo: lo usa el
        editor para abrir cualquier include con el que se haga doble clic,
        sea un `.dtsi` o una cabecera `.h`.
        """
        return self._includes.resolve(directive, base_path)

    def find_node_source(
        self,
        result: ParseResult,
        base_path: Optional[str],
        node_path: str,
    ) -> Optional[Tuple[ResolvedInclude, int]]:
        """Qué inclusión declara `node_path`, y en qué línea suya.

        Lo pide "ver en el editor DTS" del grafo cuando el nodo no está
        escrito en el documento abierto: en una placa, sus controladores los
        declara el `.dtsi` del SoC, y la línea que arrastra el nodo cuenta
        sobre ese fichero (ver `IncludeResolver.find_declaring_include`).
        """
        return self._includes.find_declaring_include(
            result.includes, base_path, node_path
        )

    def build_visual_tree(
        self,
        result: ParseResult,
        base_path: Optional[str] = None,
    ) -> Tuple[DeviceTreeNode, List[ResolvedInclude]]:
        """Construye el árbol completo para el visualizador, fusionando includes.

        `result.root` es el árbol "tal cual" del documento, el que usan el
        editor y el generador; aquí se fusiona una **copia** con el contenido
        de cada include de device tree encontrado en la base de datos, de
        forma recursiva, para que el grafo represente la jerarquía real en
        lugar de dejar los includes como nodos aparte. Devuelve además los que
        no se han podido fusionar (no encontrados, o cabeceras C), para que la
        GUI los siga señalando.

        Es el mismo árbol que ya construyó `analyze_source` para este
        `ParseResult` (ver `_merged_tree`): se reaprovecha en lugar de
        rehacerlo. Nadie lo modifica después de construirlo —el grafo y el
        panel del SoC solo lo recorren—, así que compartirlo es seguro.
        """
        return self._merged_tree(result, base_path)

    def resolve_inspected_node(
        self,
        node: Optional[DeviceTreeNode],
        result: ParseResult,
        base_path: Optional[str] = None,
    ) -> Optional[DeviceTreeNode]:
        """Nodo a mostrar en el Inspector, resuelto si `node` es -o cuelga
        de- una reapertura `&label { … }` / `&{/ruta} { … }`.

        El árbol crudo del documento no sabe a qué nodo apunta una
        reapertura: el parser la cuelga de la raíz con un nombre literal
        (`&i2c0`) y sin su `compatible`, que vive en el nodo real del
        `.dtsi` incluido (ver `parser.py`). Sin esto el Inspector nunca
        encontraba binding para ella -exactamente lo que
        `resolve_label_overrides` ya resuelve para el árbol fusionado que usa
        el visualizador, pero que el cursor del editor nunca consultaba.

        Un nodo que no cuelga de ninguna reapertura se devuelve tal cual, sin
        tocar el árbol fusionado: es el caso normal y ya trae su propio
        `compatible`.
        """
        if node is None:
            return None

        path: List[str] = []
        reference = node
        while reference is not None and not reference.name.startswith("&"):
            path.append(reference.name)
            reference = reference.parent
        if reference is None:
            return node

        merged, _ = self._merged_tree(result, base_path)
        body = reference.name[1:]
        if body.startswith("{") and body.endswith("}"):
            target: Optional[DeviceTreeNode] = merged
            for segment in body[1:-1].split("/"):
                if not segment:
                    continue
                target = target.find_child(segment) if target is not None else None
        else:
            target = _find_labelled(merged, body)

        for step in reversed(path):
            target = target.find_child(step) if target is not None else None
        return target if target is not None else node

    def soc_profile_from_tree(self, root: DeviceTreeNode, name: str) -> SoCProfile:
        """Construye un `SoCProfile` a partir de un árbol ya analizado."""
        return SoCProfile(
            soc_name=name,
            compatible=list(root.compatible) or [name],
            peripherals=extract_connectable_nodes(root, self._bindings),
        )

    def build_soc_package(
        self, root: DeviceTreeNode, soc_compatible: Optional[str] = None
    ) -> SocPackage:
        """Recoge lo que va empaquetado dentro del SoC para su panel de propiedades.

        Es cualquier nodo del árbol fusionado (bus o no) con un `status`
        propio: el visualizador solo dibuja los que además tienen algo
        conectado (ver `tree_graph.build_graph`), pero todos deben poder
        consultarse y encenderse/apagarse desde aquí, estén o no dibujados.

        `soc_compatible` es el compatible del propio SoC, no el de la placa
        (típicamente `MainWindow._soc_name_for`, que ya resuelve cuál de los
        `compatible` de la raíz identifica al SoC en la tabla `socs`, en vez
        de asumir una posición fija en la lista): de ahí salen el nombre y
        el vendor -"xlnx,zynq-7000" da vendor "xlnx" y nombre "zynq-7000"-.
        Sin ese dato se cae al último compatible de la raíz, que en DTS es
        por convención el más genérico y el que suele señalar la familia del
        SoC.
        """
        controllers: List[IntegratedController] = []
        for node in root.iter_tree():
            if node.name != "/" and "status" in node.properties:
                controllers.append(
                    IntegratedController(
                        path=node.path or node.name,
                        label=node.label,
                        # El **primero**, no la lista entera unida por comas:
                        # es el que identifica al dispositivo, y los demás
                        # son la familia genérica a la que también responde.
                        # Unidos no caben en el bloque que los enseña y se
                        # elidían justo por la mitad, dejando "xlnx,zynq-…,
                        # cdns,gem", que no identifica nada.
                        compatible=(
                            node.compatible[0] if node.compatible else node.name
                        ),
                        status=str(node.properties.get("status")),
                    )
                )
        controllers.sort(key=lambda item: item.path)

        reference = soc_compatible or (root.compatible[-1] if root.compatible else None)
        vendor, _, name = (reference or "").partition(",")
        if not name:
            name, vendor = vendor or None, None

        return SocPackage(
            name=name,
            vendor=vendor,
            controllers=controllers,
        )

    # ------------------------------------------------------------------
    # Schemas de binding (dt-schema)
    # ------------------------------------------------------------------
    def binding_schemas_available(self) -> bool:
        """Indica si la base incluye los schemas procesados por dt-schema."""
        return self._schemas.is_available()

    def dtschema_version(self) -> Optional[str]:
        """Versión de dtschema con la que se construyó la base, si consta."""
        return self._schemas.dtschema_version()

    def database_warning(self) -> Optional[str]:
        """Qué le pasa a la base de datos abierta, o `None` si está al día.

        La base no viaja con el software —el usuario apunta a la suya, a la
        de KernelGrove o a la de un tercero—, así que puede ser de otra versión o
        estar construida a medias. Antes eso se descubría a trozos y en
        silencio: sin schemas, la capa 5 sencillamente no decía nada, que
        desde la pantalla es idéntico a "tu device tree está perfecto".

        Devuelve un texto ya redactado para enseñar tal cual; el llamante
        decide si va a un diálogo o a la barra de estado.
        """
        version = self._schemas.app_schema_version()
        if version is None:
            return (
                "The database does not record which version built it: it predates "
                "this check. It may work, but if something does not add up, "
                "rebuild it with scripts/build_database.sh."
            )
        if version != DB_SCHEMA_VERSION:
            return (
                f"The database is version {version} and this application "
                f"expects {DB_SCHEMA_VERSION}. Rebuild it with "
                "scripts/build_database.sh, or point at another one with "
                "KERNELGROVE_DB_PATH."
            )

        missing = []
        if not self._schemas.is_available():
            missing.append("the binding schemas (nothing is validated against them)")
        if not self._macros.is_available():
            missing.append("the macro index (dt-bindings macros are not checked)")
        if self._sources.count() == 0:
            missing.append("the sources (includes cannot be resolved)")
        if missing:
            return "The database is missing " + ", and ".join(missing) + "."
        return None

    def list_subdevices(self, compatible: str) -> List[BindingOption]:
        """Funciones que el binding de un dispositivo declara dentro de él.

        Un MFD (`ti,twl4030`) describe en su propio binding el PWM, el GPIO o
        el códec que lleva dentro. No cuelgan de ningún bus, así que la única
        forma de llegar a ellos es desde el dispositivo que los contiene.
        """
        options = []
        for compat in self._schemas.subdevices_of(compatible):
            info = self._bindings.get_binding_info(compat)
            title = info[1] if info and info[1] != "Unknown" else None
            options.append(BindingOption(compatible=compat, title=title))
        return options

    def list_child_options(self, compatible: Optional[str]) -> List[BindingOption]:
        """Qué puede colgar de un nodo, por las dos vías que existen.

        Un nodo admite hijos por dos razones distintas y no excluyentes:
        porque **ofrece un bus** (un controlador I2C admite los dispositivos
        que declaran ese bus como `parent_bus`) y porque **su propio binding
        describe sub-nodos** (un MFD como `ti,twl4030` lleva dentro su PWM y
        su GPIO, que no cuelgan de ningún bus). Preguntar solo por una deja
        fuera la mitad del catálogo según el nodo que sea.

        Sin compatible conocido se devuelve vacío: no se inventan
        dispositivos para un nodo del que no se sabe qué es.
        """
        if not compatible:
            return []

        info = self.get_binding_info(compatible)
        options = self.list_connectable_bindings(info.child_bus)
        vistos = {option.compatible for option in options}
        options.extend(
            option
            for option in self.list_subdevices(compatible)
            if option.compatible not in vistos
        )
        return options

    def search_bindings(
        self,
        text: str = "",
        limit: int = 300,
        vendor: str = "",
        subsystems: Optional[Sequence[str]] = None,
    ) -> List[BindingEntry]:
        """Compatibles documentados que casan con lo escrito y con los filtros.

        La misma idea que el catálogo de device trees: se busca por lo que
        se sabe —un compatible a medias, el nombre del dispositivo— y lo que
        vuelve es una lista corta. Ver `BindingsDatabase.search_bindings`,
        que es donde se explica por qué los dos filtros se resuelven en SQL
        y no sobre lo que vuelve.
        """
        return [
            BindingEntry(compatible, title, subsystem, binding, _one_line(description))
            for compatible, title, subsystem, binding, description in (
                self._bindings.search_bindings(text, limit, vendor, subsystems)
            )
        ]

    def binding_count(
        self,
        text: str = "",
        vendor: str = "",
        subsystems: Optional[Sequence[str]] = None,
    ) -> int:
        """Cuántos compatibles casan con lo buscado y sus filtros.

        Los mismos argumentos que `search_bindings` a propósito: la lista
        viene recortada y el número es el de cuántos hay detrás del recorte
        (ver `BindingsDatabase.count_bindings`).
        """
        return self._bindings.count_bindings(text, vendor, subsystems)

    def binding_vendors(self) -> List[str]:
        """Fabricantes con algún compatible documentado, para su filtro."""
        return self._bindings.binding_vendors()

    def binding_subsystems(self) -> List[str]:
        """Subsistemas presentes en la base, para el filtro de tipo.

        Crudos: quien los agrupa por tipo de dispositivo es la paleta, y esa
        clasificación vive en la GUI (`widgets/binding_groups.py`) porque es
        la misma con la que luego se conecta el dispositivo al árbol.
        """
        return self._bindings.binding_subsystems()

    def suggest_properties(
        self, compatible: str, prefix: str = "", limit: int = 200
    ) -> List[PropertySuggestion]:
        """Propiedades que admite el binding de un compatible.

        Con la herencia resuelta: incluye lo que el binding hereda de su
        clase de dispositivo y de su bus, que suele ser la mayor parte. Las
        obligatorias van primero, y dentro de cada grupo por orden
        alfabético, que es como se leen en una lista de sugerencias.
        """
        schema = self._schemas.schema_for(compatible)
        if schema is None:
            return []

        suggestions = [
            PropertySuggestion(
                name=prop.name,
                required=prop.required,
                dt_type=prop.dt_type,
                description=prop.description,
                origin=prop.origin.rsplit("/", 1)[-1] if prop.origin else None,
                # La versión es la del schema que *aporta* la propiedad, no
                # la del binding del dispositivo: una propiedad heredada de
                # una clase de dispositivo existe desde que existe esa
                # clase, y es lo que hay que saber para poder escribirla.
                since=self._schemas.since(prop.origin) if prop.origin else None,
                allowed_values=_allowed_values(prop.schema),
                constraints=_constraints(prop.schema),
                is_node=prop.is_node,
            )
            for name, prop in schema.properties.items()
            if name.startswith(prefix)
        ]
        suggestions.sort(key=lambda item: (not item.required, item.name))
        return suggestions[:limit]

    def property_details(
        self, name: str, compatible: Optional[str] = None
    ) -> PropertySuggestion:
        """Lo que se sabe de una propiedad concreta, con o sin binding.

        Si el binding del compatible la declara, se devuelve tal cual la
        declara —con su tipo, su prosa, de qué schema viene y qué valores
        admite—. Si no, queda el tipo que dt-schema deduce del conjunto de
        los bindings, que es lo único que se puede afirmar de una propiedad
        que este dispositivo no documenta. Nunca `None`: preguntar por una
        propiedad que está escrita en el fuente tiene respuesta siempre,
        aunque la respuesta sea «solo sé cómo se llama».
        """
        if compatible:
            for suggestion in self.suggest_properties(compatible):
                if suggestion.name == name:
                    return replace(
                        suggestion,
                        dt_type=self.property_type_label(name, suggestion.dt_type),
                    )
        return PropertySuggestion(name=name, dt_type=self.property_type_label(name))

    def binding_since(self, compatible: str) -> Optional[str]:
        """Versión del kernel desde la que su binding está en el árbol.

        Sale de la historia del repositorio del kernel, calculada en la
        ingesta: la primera release cuyo árbol trae el fichero del binding
        (ver `db_manager/kernel_versions.py`). `None` cuando no consta, que
        es lo que hay que enseñar en vez de una versión inventada.
        """
        return self._schemas.binding_since(compatible)

    def kernel_releases(self) -> List[str]:
        """Releases del kernel que la base conoce, de la más nueva a la más vieja.

        Salen de los propios bindings (`schemas.since`), no de una lista
        escrita a mano: una base construida contra otro checkout llega hasta
        donde llegue ese checkout, y ofrecer versiones que no están sería
        prometer una comprobación que no se puede hacer.
        """
        return self._schemas.kernel_releases()

    def property_type_label(
        self, name: str, declared: Optional[str] = None
    ) -> Optional[str]:
        """Cómo se escribe una propiedad: su tipo y, si no lo hay, su forma.

        El tipo puede no existir: `clock-frequency` es `uint32` en unos
        bindings y `uint64` en otros, y dt-schema no afirma ninguno. La
        forma sí (`scalar`), y es la que decide lo que hay que teclear —si
        va entre `<>` o entre comillas—, que es justo la duda que esta
        columna resuelve. Un guion solo se enseña cuando no se sabe ni eso.
        """
        return (
            declared
            or self._schemas.property_type(name)
            or self._schemas.property_shape(name)
        )

    def analyze_source(
        self,
        text: str,
        fragment: bool = False,
        base_path: Optional[str] = None,
        overlay_base: Optional[DeviceTreeNode] = None,
        overlay_checks: bool = False,
    ) -> Tuple[ParseResult, List[Diagnostic]]:
        """Analiza un fuente y devuelve el árbol junto a todos los diagnósticos.

        Junta la sintaxis del parser con las capas de comprobación semántica
        (`dts_engine.checks`, ver `docs/SEMANTIC-ENGINE-FLOW.md`): la capa 1,
        la de la especificación Device Tree, y la 5, la del binding del
        `compatible` concreto, que solo se ejecuta si la base incluye los
        schemas procesados por dt-schema.

        Antes de comprobar nada se fusiona una copia del árbol con el
        contenido de sus includes, igual que hace el visualizador: sin eso, un
        fichero de placa —que hereda `/cpus`, `/memory` y media docena de
        propiedades obligatorias de su `.dtsi`— aparentaría estar incompleto.
        `base_path` es la ruta del documento en la base de datos, necesaria
        para resolver los includes relativos.

        `overlay_base` es el árbol sobre el que se aplicará este documento,
        si es un overlay. Un overlay **no incluye su base** —no puede,
        duplicaría el árbol entero—, así que la única forma de que las capas
        sepan contra qué se comprueba es recibirla: con ella, el árbol
        fusionado es la base con el overlay aplicado y todo lo que pregunta
        "¿qué hay de verdad en este nodo?" puede responder.

        `overlay_checks` es aparte, y por defecto **no**: la capa 6 —«¿existe
        el objetivo?»— es una comprobación que se pide, no algo que ocurra de
        fondo mientras se escribe. Vive en el asistente de overlays, que sabe
        contra qué base se está comprobando y lo dice; en el editor, donde esa
        base es un dato invisible que el usuario no ha elegido, un error de
        capa 6 no se puede ni interpretar ni arreglar con conocimiento de
        causa. Que la base siga llegando aquí sí sirve, y para lo de siempre:
        el autocompletado dentro del overlay y la vista fusionada.
        """
        result = parse_dts_source(text)
        merged, includes_resolved = self._merge_for_analysis(result, base_path)
        if overlay_base is not None:
            # La vista fusionada de un overlay no es la base a secas: es la
            # base **con el overlay ya aplicado**. Con ella, un nodo que el
            # overlay añade (`&i2c0 { rtc@68 { … } }`) aparece en su sitio
            # real del árbol, y las capas que preguntan "¿qué hay de verdad
            # en este nodo?" pueden responder — sin esto, la capa 5 no
            # encontraba el nodo por ninguna ruta y se callaba, que es su
            # regla cuando no puede afirmar nada.
            merged, _ = preview_overlay(overlay_base, result)

        macro_lookup = self._macros if self._macros.is_available() else None
        local_macros = (
            self._includes.macro_names(result.includes, base_path)
            if macro_lookup is not None
            else ()
        )

        diagnostics: List[Diagnostic] = list(result.diagnostics)
        diagnostics.extend(
            run_checks(
                result,
                text=text,
                fragment=fragment,
                merged_root=merged,
                includes_resolved=includes_resolved,
                dts_version_seen=self._dts_version_seen(text, result, base_path),
                schema_lookup=self._schemas if self._schemas.is_available() else None,
                macro_lookup=macro_lookup,
                local_macros=local_macros,
                overlay_base=overlay_base if overlay_checks else None,
                kernel_version=self.kernel_target,
            )
        )

        # Primero los errores y luego los avisos: en un fichero con decenas de
        # avisos, un error ordenado solo por línea queda sepultado y el usuario
        # no lo ve.
        diagnostics.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], item.line))

        return (result, diagnostics)

    def completion_context(
        self,
        text: str,
        position: int,
        base_path: Optional[str] = None,
        overlay_base: Optional[DeviceTreeNode] = None,
    ) -> CompletionContext:
        """Contexto del cursor para el autocompletado, con el compatible resuelto.

        Si el nodo es una reapertura (`&uart0 { … }`) no declara compatible
        aquí: el suyo está en el fichero donde se definió, así que se busca por
        la etiqueta en el árbol fusionado.
        """
        context = context_at(text, position)
        if context.compatible or not context.reference:
            return context

        # En un overlay, el nodo que se reabre vive en la base: su
        # `compatible` no está en este fichero ni en ningún include suyo.
        if overlay_base is not None:
            node = _find_labelled(overlay_base, context.reference)
            if node is not None and node.compatible:
                return replace(context, compatible=node.compatible[0])

        compatible = self._compatible_for_label(text, context.reference, base_path)
        if compatible is None:
            return context
        return replace(context, compatible=compatible)

    def _compatible_for_label(
        self, text: str, label: str, base_path: Optional[str]
    ) -> Optional[str]:
        """Compatible del nodo etiquetado, buscándolo en el árbol fusionado."""
        key = (base_path, label)
        if key in self._label_compatibles:
            return self._label_compatibles[key]

        result = parse_dts_source(text)
        merged, _ = self._merge_for_analysis(result, base_path)
        compatible = None
        if merged is not None:
            node = _find_labelled(merged, label)
            if node is not None and node.compatible:
                compatible = node.compatible[0]

        self._label_compatibles[key] = compatible
        while len(self._label_compatibles) > _LABEL_CACHE_SIZE:
            self._label_compatibles.popitem(last=False)
        return compatible

    def analyze_schema_checks(
        self,
        text: str,
        fragment: bool = False,
        base_path: Optional[str] = None,
    ) -> List[Diagnostic]:
        """Ejecuta las comprobaciones que hace el propio schema.

        Los valores de la capa 5 y la capa 2 entera. Van aparte de
        `analyze_source` porque cuestan milisegundos por nodo —hay que validar
        cada nodo contra su schema y contra los 227 genéricos—, o sea segundos
        en un SoC entero. La GUI las llama en un hilo de fondo y añade los
        avisos que devuelven a los que ya tenía el documento.

        Devuelve lista vacía si la base no trae los schemas procesados.
        """
        if not self._schemas.is_available():
            return []

        result = parse_dts_source(text)
        merged, includes_resolved = self._merge_for_analysis(result, base_path)
        local_macro_values = (
            self._includes.macro_values(result.includes, base_path)
            if self._macros.is_available()
            else {}
        )
        diagnostics = run_schema_checks(
            result,
            self._schemas,
            fragment=fragment,
            merged_root=merged,
            includes_resolved=includes_resolved,
            local_macro_values=local_macro_values,
        )
        diagnostics.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], item.line))
        return diagnostics

    @staticmethod
    def merge_deferred(
        base: List[Diagnostic], extra: List[Diagnostic]
    ) -> List[Diagnostic]:
        """Añade los avisos de la pasada diferida a los que ya tenía el documento.

        Las capas 2 y 5 pueden decir lo mismo desde fuentes distintas: el
        binding de Cadence limita `clock-frequency` a 400 kHz y la clase I2C a
        5 MHz, así que un valor de 9 MHz incumple los dos. Se conserva el
        primero que llegue —dentro de la pasada, la capa 5 va antes— y se
        descarta el otro cuando hablan de la misma propiedad en la misma
        línea.
        """
        seen = {
            (item.line, item.property_name, item.family)
            for item in base
            if item.property_name is not None
        }
        merged = list(base)
        merged.extend(
            item
            for item in extra
            if (item.line, item.property_name, item.family) not in seen
        )
        merged.sort(key=lambda item: (_SEVERITY_ORDER[item.severity], item.line))
        return merged

    def generic_schema_count(self) -> int:
        """Número de bindings genéricos que evalúa la capa 2."""
        return self._schemas.generic_schema_count()

    def _dts_version_seen(
        self, text: str, result: ParseResult, base_path: Optional[str]
    ) -> bool:
        """Indica si `/dts-v1/;` está en el documento o en alguno de sus includes.

        `dtc` ve el texto de todos los ficheros pegados, así que la marca vale
        esté donde esté: hay `.dts` de placa que la heredan del `.dtsi` que
        incluyen. Solo se busca fuera cuando el documento no la trae.
        """
        if "/dts-v1/" in text:
            return True
        return self._includes.text_in_includes(result.includes, base_path, "/dts-v1/")

    def _merge_for_analysis(
        self, result: ParseResult, base_path: Optional[str]
    ) -> Tuple[Optional[DeviceTreeNode], bool]:
        """Fusiona los includes del documento sobre una copia de su árbol.

        Devuelve el árbol fusionado (None si el documento no incluye ningún
        device tree) y si se pudieron fusionar todos: lo que no se encuentra
        en la base puede contener justo lo que las comprobaciones echan en
        falta, y entonces no se puede afirmar que falte.
        """
        if not any(not include.is_header for include in result.includes):
            return (None, True)

        merged, unresolved = self._merged_tree(result, base_path)
        pending = any(item.is_device_tree for item in unresolved)
        return (merged, not pending)

    def _merged_tree(
        self, result: ParseResult, base_path: Optional[str]
    ) -> Tuple[DeviceTreeNode, List[ResolvedInclude]]:
        """Árbol del documento con sus includes fusionados, memoizado.

        Un mismo análisis lo pedía dos veces: `analyze_source` lo construye
        para las comprobaciones y lo descarta, y acto seguido la ventana
        llamaba a `build_visual_tree`, que repetía el clonado, la fusión
        recursiva y la resolución de `&label` sobre el mismo texto — 46 ms
        duplicados en cada pulsación de tecla sobre un SoC grande.

        El memo va por identidad del `ParseResult`, que es lo que distingue
        "el mismo análisis otra vez" de "un texto nuevo": el objeto se guarda
        en el propio valor para que su `id()` no pueda reutilizarse mientras
        esté cacheado. Cuatro entradas porque el hilo del análisis diferido
        parsea el suyo aparte y no debe expulsar al del hilo de la interfaz.
        """
        key = (id(result), base_path)
        cached = self._merged_cache.get(key)
        if cached is not None:
            self._merged_cache.move_to_end(key)
            return cached[1], cached[2]

        merged = result.root.clone()
        unresolved = self._includes.resolve_tree(merged, result.includes, base_path)
        # Igual que en el visualizador: un `&uart0 { … }` no es un nodo nuevo
        # sino la reapertura del que trae el `.dtsi` del SoC. Sin plegarlo,
        # todo lo que el nodo real ya tiene parece ausente y las capas que
        # miran qué falta avisan de propiedades que sí están.
        resolve_label_overrides(merged)
        # Lo último: un `/delete-node/` quita del árbol algo que casi siempre
        # trae un include, y plegado ya el `&label` que lo reabre. Sin esto el
        # árbol conserva nodos que dtc no compila y las capas avisan de un
        # árbol que no existe.
        apply_deletions(merged, result.deletions)

        self._merged_cache[key] = (result, merged, unresolved)
        while len(self._merged_cache) > _MERGED_CACHE_SIZE:
            self._merged_cache.popitem(last=False)
        return merged, unresolved

    # ------------------------------------------------------------------
    # Overlays
    # ------------------------------------------------------------------
    def overlay_targets(
        self, result: ParseResult, base: Optional[DeviceTreeNode]
    ) -> List[OverlayTarget]:
        """Objetivos que declara un overlay, resueltos contra su base."""
        return overlay_targets(result, base)

    def preview_overlay(
        self, base: DeviceTreeNode, overlay: ParseResult
    ) -> Tuple[DeviceTreeNode, List[OverlayChange]]:
        """Árbol resultante de aplicar el overlay, y qué ha cambiado."""
        return preview_overlay(base, overlay)

    def build_overlay_source(
        self,
        fragments: Sequence[OverlayFragment],
        includes: Sequence[str] = (),
        description: Optional[str] = None,
    ) -> str:
        """Escribe el fuente `.dtso` de los cambios elegidos."""
        return build_overlay_source(fragments, includes, description)

    def documented_compatibles(self, prefix: str, limit: int = 50) -> List[str]:
        """Compatibles documentados que empiezan por `prefix`.

        Lo usa el asistente de overlays al escribir el `compatible` de un
        nodo nuevo: ofrecer solo lo que la base conoce evita inventarse un
        dispositivo que después no valida contra ningún binding.
        """
        if not self._schemas.is_available():
            return []
        return self._schemas.documented_compatibles(prefix, limit)

    def includes_for_properties(self, values: Sequence[str]) -> List[str]:
        """Cabeceras `dt-bindings` que hacen falta para los valores dados.

        Un valor como `<GPIO_ACTIVE_HIGH>` no compila sin el `#include` que
        define esa macro, y acordarse de cuál es no es trabajo de una
        persona: el índice de macros ya sabe qué cabecera declara cada
        nombre. Se devuelve la ruta tal como se escribe en el `#include`,
        empezando por `dt-bindings/`.

        Sin índice de macros (base construida sin `--table macros`) se
        devuelve vacío: mejor un overlay sin includes, que el usuario
        completa, que un `#include` inventado.
        """
        if not self._macros.is_available():
            return []

        includes: List[str] = []
        for value in values:
            for token in _macro_tokens(value):
                for header in self._macros.headers_defining(token):
                    ruta = _include_path(header)
                    if ruta and ruta not in includes:
                        includes.append(ruta)
                    break
        return sorted(includes)

    def toolchain(self) -> Toolchain:
        """Qué herramientas de compilación hay instaladas ahora mismo.

        Se consulta cada vez y no se recuerda: el usuario puede instalar
        `dtc` con la aplicación abierta —que es justo lo que le pide el
        mensaje de ayuda— y tener que reiniciar para que se entere sería
        una tontería.
        """
        return detect_toolchain()

    def materialize_source(self, key: str, directory: Path) -> Optional[Path]:
        """Escribe en `directory` un fuente del catálogo y sus inclusiones.

        Compilar un árbol de la base de datos obliga a deshacer lo que la
        base hace: los fuentes viven dentro de `bindings.db` y `cpp` solo
        sabe leer un sistema de ficheros. Se escribe cada uno **en la ruta
        relativa con la que está guardado** (`xilinx/zynqmp.dtsi`), no todos
        juntos en una carpeta plana, porque un `#include "vecino.dtsi"` se
        resuelve junto al fichero que incluye: aplanarlos rompería justo lo
        que se está intentando reproducir.

        Recursivo y a prueba de ciclos, como `IncludeResolver.resolve_tree`.
        Las cabeceras `dt-bindings/*.h` no entran aquí: van por `-I` desde
        `materialize_headers`, que las vuelca todas de una vez.

        Devuelve la ruta del fichero principal ya escrito, o `None` si la
        clave no está en la base.
        """
        escritos: set = set()

        def escribir(source_key: str) -> Optional[Path]:
            if source_key in escritos:
                return directory / source_key
            texto = self.read_source(source_key)
            if texto is None:
                return None
            escritos.add(source_key)
            destino = directory / source_key
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(texto, encoding="utf-8")
            result = parse_dts_source(texto)
            for include in self._includes.resolve_all(
                result.includes, base_path=source_key
            ):
                # Cualquier inclusión que la base tenga, no solo los device
                # trees: un `.dtsi` incluye a veces una cabecera vecina
                # (`#include "xlnx-zynqmp-clk.h"`) que no está en
                # `dt-bindings` y que sin escribir deja a `cpp` sin ella.
                # Se baja solo por los device trees; una cabecera no
                # contiene nodos ni `#include` de device tree.
                if not include.found:
                    continue
                if include.is_device_tree:
                    escribir(include.source.path)
                else:
                    destino_h = directory / include.source.path
                    destino_h.parent.mkdir(parents=True, exist_ok=True)
                    destino_h.write_text(include.source.text, encoding="utf-8")
            return destino

        return escribir(key)

    def materialize_includes(
        self,
        text: str,
        base_key: str,
        directory: Path,
        source_dir: Path,
    ) -> int:
        """Escribe en `directory` las inclusiones que `cpp` no encontraría solo.

        El motor resuelve un `#include "zynqmp.dtsi"` contra la base de
        datos —por eso el análisis ve el árbol entero y el editor completa
        dentro de él—, pero `cpp` solo sabe leer un sistema de ficheros: sin
        esto, un `.dts` que el programa analiza sin una queja falla al
        compilar con «No such file or directory» justo en la inclusión que
        acaba de resolver. Compilar obliga a deshacer lo que la base hace,
        igual que ya se hacía con las cabeceras `dt-bindings`.

        Cada fichero se escribe **con la ruta que dice su `#include`**, no
        con la clave con la que la base lo guarda (`xilinx/zynqmp.dtsi`):
        `cpp -I` busca lo que está escrito en la directiva, así que es esa
        la ruta que tiene que existir bajo `directory`. De ahí para abajo,
        recursivo: lo que traiga a su vez ese fichero se resuelve junto a
        él, que es donde se acaba de escribir.

        `source_dir` es la carpeta contra la que `cpp` va a resolver los
        `#include "…"` del fuente principal, que es la del propio fichero:
        se compila en su sitio (`compile_source_file`) justo para que sus
        vecinos del disco se resuelvan solos. Lo que ya está ahí no se
        copia: el fichero del proyecto que el usuario edita es el que manda.

        Devuelve cuántos ficheros escribió.
        """
        escritas = 0
        recorridos: set = set()

        def bajar(texto: str, clave: str, vecindad: Path) -> None:
            nonlocal escritas
            if clave in recorridos:
                return
            recorridos.add(clave)
            result = parse_dts_source(texto)
            for include in self._includes.resolve_all(
                result.includes, base_path=clave
            ):
                objetivo = include.directive.target
                vecino = vecindad / objetivo
                if vecino.is_file():
                    # `cpp` lo encuentra donde está, pero él sí puede
                    # necesitar algo que solo esté en la base.
                    if include.is_device_tree:
                        contenido = self.read_text_file(vecino)
                        if contenido is not None:
                            bajar(contenido, str(vecino), vecino.parent)
                    continue
                if not include.found:
                    continue
                destino = directory / objetivo
                if destino.exists():
                    # Ya lo puso `materialize_headers`, o esta misma pasada.
                    continue
                destino.parent.mkdir(parents=True, exist_ok=True)
                destino.write_text(include.source.text, encoding="utf-8")
                escritas += 1
                if include.is_device_tree:
                    bajar(include.source.text, include.source.path, destino.parent)

        bajar(text, base_key, source_dir)
        return escritas

    def build_device_tree(
        self,
        dts: Path,
        overlays: Sequence[Path],
        base: Optional[DeviceTreeNode],
        on_step: Optional[Callable[["BuildStep"], None]] = None,
    ) -> "BuildOutcome":
        """Comprueba los overlays contra su base y compila todo el conjunto.

        El orden no es negociable y es la razón de que esto exista como una
        sola operación: **primero se comprueba y después se compila**. `dtc`
        no sabe nada de bindings —compila igual un overlay que apunta a un
        nodo que no existe en la base—, así que compilar antes de pasar la
        capa 6 produce un `.dtbo` que solo falla al aplicarlo en la placa,
        que es el peor sitio donde enterarse. Un ERROR en cualquier overlay
        para la compilación entera; un aviso no, porque un aviso no impide
        que el binario sea correcto.

        La base de los overlays es **el `.dts` que se va a compilar**: es lo
        que hace interpretable el veredicto de la capa 6 (ver
        `checks/overlay.py`), y es la respuesta a «¿este overlay vale para
        esta placa?», que es la pregunta que se hace al construir.

        Cada paso se avisa por `on_step` según ocurre: compilar un árbol
        completo tarda lo suyo y el registro tiene que ir contándolo, no
        aparecer entero al final.
        """
        pasos: List[BuildStep] = []

        def anotar(step: "BuildStep") -> "BuildStep":
            pasos.append(step)
            if on_step is not None:
                on_step(step)
            return step

        fallo = False
        for overlay in overlays:
            texto = self.read_text_file(overlay)
            if texto is None:
                fallo = True
                anotar(BuildStep("check", overlay, False, errors=1))
                continue
            _, diagnostics = self.analyze_source(
                texto, fragment=True, overlay_base=base, overlay_checks=True
            )
            errores = [d for d in diagnostics if d.severity is Severity.ERROR]
            avisos = [d for d in diagnostics if d.severity is Severity.WARNING]
            fallo = fallo or bool(errores)
            anotar(
                BuildStep(
                    "check",
                    overlay,
                    not errores,
                    errors=len(errores),
                    warnings=len(avisos),
                    diagnostics=errores + avisos,
                )
            )
        if fallo:
            return BuildOutcome(False, pasos)

        tools = self.toolchain()
        if not tools.can_compile:
            resultado = compile_source_file(dts, dts, toolchain=tools)
            anotar(
                BuildStep(
                    "compile", dts, False, messages=[resultado.unavailable or ""]
                )
            )
            return BuildOutcome(False, pasos)

        # Las cabeceras `dt-bindings` viven dentro de la base de datos y
        # `cpp` solo sabe leer ficheros: se vuelcan para esta compilación y
        # se borran al salir del bloque.
        with tempfile.TemporaryDirectory(prefix="kernelgrove-build-") as tmp:
            cabeceras = Path(tmp)
            self.materialize_headers(cabeceras)
            # Y lo que el `.dts` incluya y solo esté en la base: el motor lo
            # resuelve por ahí, así que un árbol que se analiza entero tiene
            # que compilar entero (ver `materialize_includes`).
            texto = self.read_text_file(dts)
            if texto is not None:
                self.materialize_includes(texto, str(dts), cabeceras, dts.parent)
            incluye = [cabeceras]
            resultado = compile_source_file(
                dts, dts.with_suffix(".dtb"), incluye, tools
            )
            anotar(
                BuildStep(
                    "compile",
                    dts,
                    resultado.ok,
                    messages=resultado.messages,
                    output=resultado.output if resultado.ok else None,
                )
            )
            if not resultado.ok:
                return BuildOutcome(False, pasos)

            for overlay in overlays:
                # Los overlays se compilan contra las mismas cabeceras y
                # con la carpeta del `.dts` a mano: es normal que un overlay
                # incluya un `.dtsi` del proyecto. Y por lo mismo que el
                # árbol, lo suyo que solo esté en la base también se escribe.
                texto = self.read_text_file(overlay)
                if texto is not None:
                    self.materialize_includes(
                        texto, str(overlay), cabeceras, overlay.parent
                    )
                salida = compile_source_file(
                    overlay,
                    overlay.with_suffix(".dtbo"),
                    [*incluye, dts.parent],
                    tools,
                )
                fallo = fallo or not salida.ok
                anotar(
                    BuildStep(
                        "compile",
                        overlay,
                        salida.ok,
                        messages=salida.messages,
                        output=salida.output if salida.ok else None,
                    )
                )
        return BuildOutcome(not fallo, pasos)

    def read_text_file(self, path: Path) -> Optional[str]:
        """El texto de un fichero del disco, o `None` si no se puede leer."""
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def materialize_headers(self, directory: Path) -> int:
        """Vuelca a disco las cabeceras `dt-bindings` que guarda la base.

        `cpp` solo sabe leer un sistema de ficheros, y aquí los fuentes
        viven dentro de `bindings.db` — que es lo que permite que la
        aplicación funcione sin el checkout del kernel. Compilar obliga a
        deshacer eso temporalmente. Quien llama es responsable de borrar el
        directorio después.
        """
        return self._sources.write_headers(directory)

    # ------------------------------------------------------------------
    # Bindings
    # ------------------------------------------------------------------
    def list_connectable_bindings(self, bus: Optional[str]) -> List[BindingOption]:
        """Lista los bindings que pueden conectarse a un bus dado.

        Son los que declaran ese bus como `parent_bus`: para un controlador
        I2C se ofrecen los dispositivos que se cuelgan de un I2C (un RTC, una
        EEPROM...), no otros controladores I2C.

        La respuesta se recuerda por bus mientras dure la sesión: el
        Generador y el Visualizador precargan los mismos buses en cuanto se
        carga un perfil, cada uno desde su propio hilo, así que sin memo la
        consulta se hacía dos veces por bus. La lista se devuelve copiada
        para que quien la reciba pueda ordenarla o filtrarla sin tocar la
        que se queda guardada.
        """
        if not bus:
            return []

        cached = self._options_by_bus.get(bus)
        if cached is None:
            cached = [
                BindingOption(
                    compatible=compatible,
                    title=title,
                    child_bus=child_bus,
                    subsystem=subsystem,
                )
                for compatible, title, child_bus, subsystem in (
                    self._bindings.list_devices_for_bus(bus)
                )
                if compatible
            ]
            self._options_by_bus[bus] = cached
        return list(cached)

    def get_binding_info(self, compatible: str) -> BindingInfo:
        """Devuelve la ficha completa de un binding por su compatible."""
        (
            vendor,
            title,
            _binding_id,
            subsystem,
            parent_bus,
            child_bus,
            description,
        ) = self._bindings.get_binding_info(compatible)

        return BindingInfo(
            compatible=compatible,
            vendor=vendor,
            title=title,
            description=description or None,
            subsystem=subsystem,
            parent_bus=parent_bus,
            child_bus=child_bus,
        )

    # ------------------------------------------------------------------
    # Sesión de edición
    # ------------------------------------------------------------------
    def create_slots(self, profile: SoCProfile) -> List[PeripheralSlot]:
        """Crea los slots editables a partir de los nodos conectables del SoC."""
        return [
            PeripheralSlot(descriptor=descriptor) for descriptor in profile.peripherals
        ]

    def connect_binding(self, slot: PeripheralSlot, compatible: str) -> PeripheralSlot:
        """Conecta un dispositivo al controlador `slot` y devuelve el slot creado.

        Si el dispositivo conectado es a su vez un controlador (un mux I2C,
        por ejemplo), hereda su `child_bus` de la base de datos y queda listo
        para que se le cuelguen más nodos por debajo.
        """
        info = self.get_binding_info(compatible)
        # Un MFD no ofrece un bus, pero sí las funciones que lleva dentro: se
        # anotan aparte para que el desplegable del slot las ofrezca.
        subdevices = self.list_subdevices(compatible)
        child = make_connected_slot(
            slot,
            compatible,
            child_bus=info.child_bus,
            subdevice_parent=compatible if subdevices else None,
        )
        slot.children.append(child)
        slot.selected_binding = compatible
        return child

    def disconnect(self, slot: PeripheralSlot, child: PeripheralSlot) -> None:
        """Elimina un dispositivo previamente conectado a un controlador."""
        if child in slot.children:
            slot.children.remove(child)
        if not slot.children:
            slot.selected_binding = None

    def build_model(
        self, profile: SoCProfile, slots: List[PeripheralSlot]
    ) -> InternalDeviceTreeModel:
        """Genera el modelo interno a partir del estado actual de los slots."""
        return build_internal_model(profile, slots)

    def count_connected(self, slots: List[PeripheralSlot]) -> int:
        """Cuenta los dispositivos conectados y habilitados."""
        return count_connected_devices(slots)

    def generate_dts_fragment(
        self, root_slots: List[PeripheralSlot], base_text: str = ""
    ) -> str:
        """Genera el DTS de lo conectado, opcionalmente sobre `base_text`.

        Usa los schemas de binding si la base los trae, para rellenar con
        certeza lo que el schema fija sin ambigüedad y marcar con un TODO lo
        que no; sin ellos (base sin `--table schemas`), el fragmento se
        limita a los `compatible` de lo conectado. Ver `api/dts_writer.py`.

        Con `base_text` (el documento del editor tal cual), el resultado es
        el DTS completo — el mismo fichero más los bloques `&label { … }`
        generados al final — en vez de solo el fragmento suelto: es la misma
        forma que `resolve_label_overrides` ya sabe fundir, así que pegado de
        vuelta en un `.dts` de placa se comporta igual que un override real.
        """
        schema_lookup = self._schemas if self._schemas.is_available() else None
        fragment = generate_fragment(root_slots, schema_lookup)
        if not base_text:
            return fragment
        if not fragment:
            return base_text
        return base_text.rstrip("\n") + "\n\n" + fragment


def _allowed_values(subschema: dict) -> List[str]:
    """Valores que el subschema enumera, para mostrarlos como sugerencia."""
    if not isinstance(subschema, dict):
        return []
    if "const" in subschema:
        return [str(subschema["const"])]
    enum = subschema.get("enum")
    if isinstance(enum, list):
        return [str(value) for value in enum]
    items = subschema.get("items")
    if isinstance(items, list) and len(items) == 1:
        return _allowed_values(items[0])
    if isinstance(items, dict):
        return _allowed_values(items)
    return []


# Lo que un binding acota sin llegar a enumerar. Se copia tal cual del
# subschema: el rango que puede tomar el valor, cuántas entradas admite, el
# patrón que ha de cumplir y su valor por defecto. Queda fuera todo lo que
# no se puede decir en una línea (`oneOf`, `dependencies`…): para eso está
# el botón que abre el binding entero.
_CONSTRAINT_KEYS = (
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "pattern",
    "default",
)


def _constraints(subschema: dict) -> Dict[str, object]:
    """Lo que el subschema acota del valor, sin enumerarlo.

    Baja por `items` igual que `_allowed_values`, y por la misma razón: en
    dt-schema el rango de una propiedad de un solo valor se escribe casi
    siempre un nivel más abajo (`items: [{minimum: 1, maximum: 400000}]`).
    Lo que encuentre arriba manda sobre lo de dentro, que es más general.
    """
    if not isinstance(subschema, dict):
        return {}
    items = subschema.get("items")
    if isinstance(items, list) and len(items) == 1:
        heredado = _constraints(items[0])
    elif isinstance(items, dict):
        heredado = _constraints(items)
    else:
        heredado = {}
    propio = {
        key: subschema[key] for key in _CONSTRAINT_KEYS if key in subschema
    }
    return {**heredado, **propio}


def _macro_tokens(value: str) -> List[str]:
    """Nombres con pinta de macro dentro del valor de una propiedad.

    Una macro de `dt-bindings/*.h` se escribe en mayúsculas y con
    subrayados; lo que va entre `<>` y no es un número es candidato. No hace
    falta afinar más: quien decide de verdad es el índice de macros, que
    solo encuentra las que existen.
    """
    tokens: List[str] = []
    for bruto in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", value):
        if bruto.isupper() and len(bruto) > 2:
            tokens.append(bruto)
    return tokens


def _include_path(header: str) -> Optional[str]:
    """Ruta con la que se incluye una cabecera, desde `dt-bindings/`."""
    marca = "dt-bindings/"
    posicion = header.find(marca)
    return header[posicion:] if posicion != -1 else None


def _find_labelled(root: DeviceTreeNode, label: str) -> Optional[DeviceTreeNode]:
    """Busca en el árbol el nodo que lleva esa etiqueta."""
    stack = [root]
    while stack:
        node = stack.pop()
        if node.label == label:
            return node
        stack.extend(node.children)
    return None


def _one_line(text: str) -> str:
    """La prosa de un binding, aplanada a una línea para la ficha.

    La descripción del YAML viene con saltos y sangría; en una lista se
    enseña elidida en una sola línea, y `drawText` partiría el texto por
    esos saltos en vez de recortarlo.
    """
    return " ".join(text.split())

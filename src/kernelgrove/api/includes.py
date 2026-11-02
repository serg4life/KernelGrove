"""Resolución de las inclusiones declaradas en un device tree.

El parser recoge las directivas tal y como están escritas; aquí se localiza su
contenido. Para un documento abierto de la base de datos, eso significa **la
base de datos**: el checkout del kernel solo se usa para construirla, y la
aplicación instalada no lo tiene, así que no hay ninguna otra fuente posible.

Para un documento abierto del disco (`source_key` es entonces una ruta
absoluta, no una clave de `sources`), la resolución mira primero **junto al
fichero que incluye**, en el disco real: un `.dts` propio puede incluir otros
`.dtsi` propios que nunca han pasado por la ingesta, y sin este paso esos
includes personalizados se veían siempre como no encontrados. Solo si no hay
nada ahí cae a la base de datos, exactamente igual que antes. Esto no reabre
la dependencia de `kernel/` en tiempo de ejecución (ver CLAUDE.md): el disco
que se consulta es el del propio fichero que el usuario abrió explícitamente,
nunca el checkout del kernel.

No siempre se encuentra (un fichero suelto puede incluir rutas que nunca se
ingirieron ni existen a su lado en disco), así que la resolución devuelve el
resultado, encontrado o no, en lugar de fallar.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple

from kernelgrove.api.macros_database import MacrosDatabase
from kernelgrove.api.sources_database import SourcesDatabase, StoredSource
from kernelgrove.dt_model.model import (
    DeviceTreeNode,
    apply_deletions,
    merge_device_tree,
)
from kernelgrove.dts_engine import IncludeDirective, parse_dts_source


@dataclass(frozen=True)
class ResolvedInclude:
    """Una inclusión junto al fuente al que apunta, si se ha encontrado."""

    directive: IncludeDirective
    source: Optional[StoredSource] = None

    @property
    def found(self) -> bool:
        """Indica si el contenido incluido está disponible."""
        return self.source is not None

    @property
    def label(self) -> str:
        """Nombre corto para mostrar en el grafo."""
        return Path(self.directive.target).name

    @property
    def is_device_tree(self) -> bool:
        """Indica si el destino es otro device tree (`.dts` o `.dtsi`).

        Se comprueba la extensión en positivo, no solo que no sea una cabecera
        C: un `#include` puede apuntar a cualquier otra cosa, y al visualizador
        solo le interesa el contenido que aporta nodos al árbol.
        """
        return self.directive.target.lower().endswith((".dts", ".dtsi"))


class IncludeResolver:
    """Busca en la base de datos los ficheros incluidos por un device tree."""

    def __init__(
        self,
        sources: SourcesDatabase,
        macros: Optional[MacrosDatabase] = None,
        cache_size: int = 64,
    ):
        """Recibe el acceso a la tabla de fuentes (y, si hay, al índice de macros).

        `cache_size` limita cuántos árboles ya resueltos se guardan: fusionar
        los includes de una placa obliga a parsear el `.dtsi` del SoC entero
        (cientos de milisegundos), y eso ocurre en cada análisis del editor y
        en cada refresco del visualizador. El contenido de la base no cambia
        mientras la aplicación corre, así que se puede reutilizar.

        `macros` es opcional: sin ella, `macro_names` devuelve el conjunto
        vacío en vez de fallar (bases construidas antes de la tabla
        `header_macros`, o sin ingesta de la capa 3).
        """
        self._sources = sources
        self._macros = macros
        self._cache_size = cache_size
        self._cache: "OrderedDict[str, Tuple[DeviceTreeNode, List[ResolvedInclude]]]"
        self._cache = OrderedDict()
        # (fichero, texto buscado) -> si lo contiene él o alguno de sus
        # includes. Ver `_source_contains`.
        self._text_cache: Dict[Tuple[str, str], bool] = {}
        # Fichero (cabecera o .dtsi) -> macros visibles al incluirlo, en
        # cascada. Ver `macro_names`.
        self._macro_cache: Dict[str, FrozenSet[str]] = {}
        # Igual, pero con el valor ya resuelto de cada una. Ver `macro_values`.
        self._macro_value_cache: Dict[str, Dict[str, int]] = {}
        # La capa 2 del motor corre en un hilo de fondo y también resuelve
        # includes: sin candado, dos hilos podrían desalojar a la vez de la
        # caché LRU y dejarla en un estado inconsistente.
        self._lock = threading.Lock()

    def resolve(
        self, directive: IncludeDirective, base_path: Optional[str] = None
    ) -> ResolvedInclude:
        """Localiza el contenido de una directiva, o lo marca como no encontrado.

        Si `base_path` es una ruta absoluta (el documento se abrió del disco,
        no de la base de datos), se prueba primero **en el disco real**, junto
        al fichero que incluye — igual que resuelve `dtc` las rutas relativas
        — para que un `.dtsi` propio que nunca pasó por la ingesta se pueda
        seguir usando. Solo si eso falla (o `base_path` es una clave de la
        base de datos, no una ruta absoluta) se cae a la base de datos: primero
        junto al fichero que incluye, después por el final de la ruta indicada
        y, por último, solo por el nombre del fichero.
        """
        target = directive.target

        if base_path:
            local = self._resolve_local(base_path, target)
            if local is not None:
                return ResolvedInclude(directive=directive, source=local)

            sibling = f"{Path(base_path).parent.as_posix()}/{target}"
            found = self._sources.get(sibling.lstrip("/"))
            if found is not None:
                return ResolvedInclude(directive=directive, source=found)

        found = self._sources.find_by_suffix(target)
        if found is not None:
            return ResolvedInclude(directive=directive, source=found)

        candidates = self._sources.find_by_name(Path(target).name)
        if len(candidates) == 1:
            return ResolvedInclude(directive=directive, source=candidates[0])

        return ResolvedInclude(directive=directive, source=None)

    @staticmethod
    def _resolve_local(base_path: str, target: str) -> Optional[StoredSource]:
        """Busca `target` en disco junto a `base_path`, si este es una ruta real.

        `base_path` solo apunta a disco cuando el documento que incluye se
        abrió del PC (`EditorTab.open_source` le pone entonces la ruta
        absoluta como `source_key`); una clave de la base de datos nunca es
        absoluta, así que esta función no hace nada en ese caso — ni falsos
        positivos contra el directorio de trabajo, ni dependencia de
        `kernel/`. Envuelto en `StoredSource` para que el resto del resolver
        (fusión de árbol, caché de includes, macros…) no tenga que distinguir
        de dónde vino el contenido.
        """
        base = Path(base_path)
        if not base.is_absolute():
            return None

        candidate = (base.parent / target).resolve()
        if not candidate.is_file():
            return None

        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

        suffix = candidate.suffix.lstrip(".").lower()
        kind = "header" if suffix == "h" else suffix
        return StoredSource(
            path=str(candidate), name=candidate.name, kind=kind, text=text
        )

    def resolve_all(
        self,
        directives: Sequence[IncludeDirective],
        base_path: Optional[str] = None,
    ) -> List[ResolvedInclude]:
        """Resuelve todas las directivas de un fichero."""
        return [self.resolve(directive, base_path) for directive in directives]

    def resolve_tree(
        self,
        root: DeviceTreeNode,
        directives: Sequence[IncludeDirective],
        base_path: Optional[str] = None,
        _visited: Optional[Set[str]] = None,
    ) -> List[ResolvedInclude]:
        """Fusiona en `root` el contenido de sus includes de device tree.

        Reproduce lo que hace `/include/`/`#include` de verdad —el contenido
        del `.dtsi` incluido pasa a formar parte del árbol— en vez de dejarlo
        como un nodo aparte que rompe la jerarquía. Es recursivo, porque un
        `.dtsi` puede a su vez incluir otros, y evita ciclos con `_visited`.

        Solo se fusionan las inclusiones que son device tree y que se
        encuentran en la base de datos; las demás (cabeceras C, o no
        encontradas) se devuelven sin tocar para que la GUI las señale.

        **Cada inclusión se fusiona donde está escrita.** Lo normal es que sea
        a nivel de fichero y su contenido se integre en la raíz, pero un
        `#include` dentro de un nodo aporta sus nodos *ahí* (el `.dts` de la
        Raspberry Pi 5 mete así todo el RP1 dentro de un `dev@0`). Fusionarlo
        en la raíz dejaba ese nodo aparentemente vacío y hacía que las
        comprobaciones echaran en falta lo que sí estaba.
        """
        visited = _visited if _visited is not None else set()
        if base_path:
            visited.add(base_path)

        unresolved: List[ResolvedInclude] = []
        for item in self.resolve_all(directives, base_path):
            if not item.is_device_tree or not item.found:
                unresolved.append(item)
                continue
            if item.source.path in visited:
                continue

            included, nested_unresolved = self._resolved_source(item.source, visited)
            unresolved.extend(nested_unresolved)
            merge_device_tree(
                _target_node(root, item.directive.node_path), included
            )

        return unresolved

    def find_declaring_include(
        self,
        directives: Sequence[IncludeDirective],
        base_path: Optional[str],
        node_path: str,
        _visited: Optional[Set[str]] = None,
    ) -> Optional[Tuple[ResolvedInclude, int]]:
        """Qué inclusión declara el nodo `node_path`, y en qué línea suya.

        Sirve para "ver en el editor" un nodo del grafo: el árbol que dibuja
        el visualizador está fusionado, así que la línea que arrastra un nodo
        traído de un `.dtsi` cuenta sobre *ese* fichero y no sobre el que se
        está editando -saltar a ella a ciegas lleva a una línea cualquiera, o
        a ninguna si el documento es más corto-.

        Se mira el árbol **propio** de cada inclusión, sin lo que ella misma
        incluya, y luego se recursa: si no, un nodo declarado tres ficheros
        más abajo se daría por escrito en el primero, con una línea que allí
        no significa nada. Devuelve el primero que lo declare, recorriendo en
        el orden en que están escritos los `#include`, que es el orden en que
        los aplica el preprocesador.

        Vuelve a parsear en lugar de tirar de la caché de `_resolved_source`,
        que guarda los árboles ya fusionados y por tanto sin decir de dónde
        salió cada nodo. Se paga solo al pulsar la opción del menú, no en
        cada análisis.
        """
        visited = _visited if _visited is not None else set()
        if base_path:
            visited.add(base_path)

        for item in self.resolve_all(directives, base_path):
            if not item.is_device_tree or not item.found:
                continue
            if item.source.path in visited:
                continue
            visited.add(item.source.path)

            parsed = parse_dts_source(item.source.text)
            node = _node_at_path(parsed.root, node_path)
            if node is not None and node.line:
                return item, node.line

            nested = self.find_declaring_include(
                parsed.includes, item.source.path, node_path, visited
            )
            if nested is not None:
                return nested

        return None

    def text_in_includes(
        self,
        directives: Sequence[IncludeDirective],
        base_path: Optional[str],
        needle: str,
        _visited: Optional[Set[str]] = None,
    ) -> bool:
        """Indica si algún fuente incluido (en cascada) contiene ese texto.

        Sirve para las directivas de fichero, que no son nodos y por tanto no
        aparecen en el árbol fusionado: `/dts-v1/;` puede estar en el `.dtsi`
        que la placa incluye, y entonces la placa no la necesita.

        La respuesta se memoriza por fichero y texto buscado. Se llama en cada
        análisis —o sea, en cada pulsación de tecla— y sin la memoria vuelve a
        parsear la cadena entera de includes: eran unos 400 ms por tecla en un
        `.dtsi` con includes, más que todo el resto del análisis junto.
        """
        visited = _visited if _visited is not None else set()
        if base_path:
            visited.add(base_path)

        for item in self.resolve_all(directives, base_path):
            if not item.is_device_tree or not item.found:
                continue
            if item.source.path in visited:
                continue
            visited.add(item.source.path)
            if self._source_contains(item.source, needle, visited):
                return True

        return False

    def _source_contains(
        self, source: StoredSource, needle: str, visited: Set[str]
    ) -> bool:
        """Indica si un fuente incluido, o alguno de los suyos, trae `needle`."""
        # Un fuente local (ruta absoluta) se ha leído del disco en `resolve()`
        # justo ahora, no de la base de datos, y puede seguir cambiando ahí
        # mientras la aplicación corre — al contrario que el contenido de la
        # base, que `text_in_includes` documenta como estable. Cachear su
        # resultado dejaría una edición guardada en un include propio sin
        # efecto hasta reiniciar la aplicación.
        is_local = Path(source.path).is_absolute()
        key = (source.path, needle)
        if not is_local:
            cached = self._text_cache.get(key)
            if cached is not None:
                return cached

        if needle in source.text:
            if not is_local:
                self._text_cache[key] = True
            return True

        # Se marca en falso antes de recurrir: si la cadena de includes tuviera
        # un ciclo, la respuesta parcial evita volver a entrar.
        if not is_local:
            self._text_cache[key] = False
        nested = parse_dts_source(source.text)
        found = self.text_in_includes(nested.includes, source.path, needle, visited)
        if not is_local:
            self._text_cache[key] = found
        return found

    def macro_names(
        self,
        directives: Sequence[IncludeDirective],
        base_path: Optional[str] = None,
        _visited: Optional[Set[str]] = None,
    ) -> FrozenSet[str]:
        """Macros visibles desde `directives`, siguiendo la cascada de includes.

        Igual que `text_in_includes`: un `.dtsi` incluido puede a su vez
        incluir la cabecera que declara `GIC_SPI`, y una board que hereda esa
        visibilidad de su SoC tiene que verla también, no solo lo que ella
        misma incluye directamente. Devuelve conjunto vacío sin índice de
        macros (`self._macros is None`) en vez de fallar.
        """
        if self._macros is None:
            return frozenset()

        visited = _visited if _visited is not None else set()
        if base_path:
            visited.add(base_path)

        names: Set[str] = set()
        for item in self.resolve_all(directives, base_path):
            if not item.found or item.source.path in visited:
                continue
            if item.directive.is_header:
                names |= self._macro_names_for_header(item.source.path)
            else:
                visited.add(item.source.path)
                names |= self._macro_names_from_source(item.source, visited)
        return frozenset(names)

    def _macro_names_for_header(self, header_path: str) -> FrozenSet[str]:
        """Macros de una cabecera concreta, cacheadas por ruta."""
        with self._lock:
            cached = self._macro_cache.get(header_path)
        if cached is None:
            cached = self._macros.names_for(header_path)
            with self._lock:
                self._macro_cache[header_path] = cached
        return cached

    def _macro_names_from_source(
        self, source: StoredSource, visited: Set[str]
    ) -> FrozenSet[str]:
        """Macros visibles al incluir un `.dtsi`: las de sus propios includes."""
        with self._lock:
            cached = self._macro_cache.get(source.path)
        if cached is not None:
            return cached

        nested = parse_dts_source(source.text)
        names = self.macro_names(nested.includes, source.path, visited)
        with self._lock:
            self._macro_cache[source.path] = names
        return names

    def macro_values(
        self,
        directives: Sequence[IncludeDirective],
        base_path: Optional[str] = None,
        _visited: Optional[Set[str]] = None,
    ) -> Dict[str, int]:
        """Valor ya resuelto de las macros visibles desde `directives`.

        Misma cascada que `macro_names`, pero para la capa 5/2 diferida
        (`run_schema_checks`): resolver valores no hace falta en cada
        pulsación de tecla, solo cuando de verdad se va a validar contra un
        schema, así que vive en su propia caché en vez de calcularse siempre
        junto a la existencia.
        """
        if self._macros is None:
            return {}

        visited = _visited if _visited is not None else set()
        if base_path:
            visited.add(base_path)

        result: Dict[str, int] = {}
        for item in self.resolve_all(directives, base_path):
            if not item.found or item.source.path in visited:
                continue
            if item.directive.is_header:
                result.update(self._macro_values_for_header(item.source.path))
            else:
                visited.add(item.source.path)
                result.update(self._macro_values_from_source(item.source, visited))
        return result

    def _macro_values_for_header(self, header_path: str) -> Dict[str, int]:
        """Valores de una cabecera concreta, cacheados por ruta."""
        with self._lock:
            cached = self._macro_value_cache.get(header_path)
        if cached is None:
            cached = self._macros.values_for(header_path)
            with self._lock:
                self._macro_value_cache[header_path] = cached
        return cached

    def _macro_values_from_source(
        self, source: StoredSource, visited: Set[str]
    ) -> Dict[str, int]:
        """Valores visibles al incluir un `.dtsi`: los de sus propios includes."""
        with self._lock:
            cached = self._macro_value_cache.get(source.path)
        if cached is not None:
            return cached

        nested = parse_dts_source(source.text)
        result = self.macro_values(nested.includes, source.path, visited)
        with self._lock:
            self._macro_value_cache[source.path] = result
        return result

    def _resolved_source(
        self, source: StoredSource, visited: Set[str]
    ) -> Tuple[DeviceTreeNode, List[ResolvedInclude]]:
        """Devuelve el árbol ya resuelto de un fuente incluido, y sus faltantes.

        La copia es obligatoria: `merge_device_tree` reengancha los nodos del
        árbol incluido dentro del que incluye, así que entregar el original
        dejaría la caché inservible tras el primer uso.

        Un fuente local (ruta absoluta, ver `_resolve_local`) no entra en esta
        caché: ya se leyó fresco del disco en `resolve()`, pero puede seguir
        cambiando ahí durante la sesión (el usuario lo edita y lo guarda desde
        fuera, o desde otra pestaña de este mismo editor), y la caché asume —
        correctamente para la base de datos — que el contenido no cambia
        mientras la aplicación corre.
        """
        is_local = Path(source.path).is_absolute()

        cached = None
        if not is_local:
            with self._lock:
                cached = self._cache.get(source.path)
                if cached is not None:
                    self._cache.move_to_end(source.path)

        if cached is None:
            parsed = parse_dts_source(source.text)
            # Todo lo que llega por un `#include`/`/include/` es, por
            # definición, contenido que ya estaba en el `.dtsi` incluido y no
            # en el documento que lo abre — el criterio de "propio del SoC"
            # que usa el grafo (`gui/widgets/tree_graph.py`). Se marca aquí,
            # antes de fusionar, porque `merge_device_tree` reengancha estos
            # mismos objetos (no los copia) y `DeviceTreeNode.clone()`
            # conserva la marca.
            for node in parsed.root.iter_tree():
                node.soc_defined = True
            # De qué fichero es cada nodo, para poder ir a su declaración desde
            # el `&label` que lo referencia en otro (ver
            # `DeviceTreeNode.source_key`). La raíz se deja fuera: la comparten
            # todos los ficheros del árbol y no es de ninguno, así que
            # atribuirla al primero que se fusione sería mentir. Va antes de
            # resolver los includes anidados para no pisar la clave de los
            # nodos que traigan ellos.
            for node in parsed.root.iter_tree(include_self=False):
                node.source_key = source.path
            nested_unresolved = self.resolve_tree(
                parsed.root, parsed.includes, source.path, visited
            )
            # Un `.dtsi` puede borrar de lo que él mismo incluye, así que se
            # aplica aquí, con su cadena ya fusionada y antes de entregar el
            # árbol a quien lo incluye a su vez.
            apply_deletions(parsed.root, parsed.deletions)
            cached = (parsed.root, nested_unresolved)
            if not is_local:
                with self._lock:
                    self._cache[source.path] = cached
                    while len(self._cache) > self._cache_size:
                        self._cache.popitem(last=False)

        root, unresolved = cached
        return root.clone(), list(unresolved)


def _node_at_path(root: DeviceTreeNode, node_path: str) -> Optional[DeviceTreeNode]:
    """Nodo de `root` en esa ruta, o None si ese árbol no lo declara.

    A diferencia de `_target_node`, no se conforma con la raíz cuando no
    encuentra la ruta: aquí la pregunta es justo si este fichero declara el
    nodo o no, y contestar «la raíz» sería contestar que sí siempre.
    """
    current = root
    for segment in node_path.split("/"):
        if not segment:
            continue
        current = current.find_child(segment)
        if current is None:
            return None
    return current


def _target_node(root: DeviceTreeNode, node_path: str) -> DeviceTreeNode:
    """Nodo de `root` donde toca fusionar una inclusión.

    `node_path` es la ruta que el parser anotó en la directiva. Si está vacía
    —el caso normal— o no se encuentra (el nodo lo aporta otro fichero), se
    fusiona en la raíz: es mejor que el contenido acabe en el árbol aunque sea
    un nivel más arriba que perderlo.
    """
    if not node_path:
        return root

    current = root
    for segment in node_path.split("/"):
        if not segment:
            continue
        child = current.find_child(segment)
        if child is None:
            return root
        current = child
    return current

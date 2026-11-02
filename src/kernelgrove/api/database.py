from __future__ import annotations

import sqlite3
from typing import List, Optional, Sequence, Tuple

from kernelgrove.api.sqlite_reader import SqliteReader


# El JOIN y la condición de las dos consultas de bindings —la lista y su
# cuenta—, escritos una vez: si dejan de decir lo mismo, el «300 de N»
# cuenta un conjunto distinto del que enseña.
_BINDING_JOIN = "JOIN bindings b ON b.compatible = bc.binding_compatible"


def _binding_where(
    text: str, vendor: str, subsystems: Optional[Sequence[str]]
) -> Tuple[str, List[object]]:
    """Condición SQL y parámetros de una búsqueda de compatibles con filtros."""
    pattern = f"%{text.strip()}%" if text.strip() else "%"
    condiciones = ["(bc.compatible LIKE ? OR b.title LIKE ?)"]
    params: List[object] = [pattern, pattern]
    if vendor:
        condiciones.append("bc.compatible LIKE ?")
        params.append(f"{vendor},%")
    if subsystems:
        marcas = ", ".join("?" * len(subsystems))
        condiciones.append(f"COALESCE(b.subsystem, '') IN ({marcas})")
        params.extend(subsystems)
    return " AND ".join(condiciones), params


class BindingsDatabase(SqliteReader):
    """Lado de lectura de la base de datos de bindings (tabla `bindings`).

    Complementa a `kernelgrove.db_manager.storage`, que es el lado de escritura
    usado durante la ingesta. Toda consulta nueva desde el parser o la GUI
    debe pasar por esta clase.
    """

    def _on_connect(self, conn: sqlite3.Connection) -> None:
        """Migra la columna `subsystem` al abrir la conexión de cada hilo."""
        self._ensure_subsystem_column(conn)

    def _ensure_subsystem_column(self, conn: sqlite3.Connection) -> None:
        """Añade la columna `subsystem` a `bindings` si la base de datos es antigua."""
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(bindings)")
        columns = [row[1] for row in cursor.fetchall()]
        if "subsystem" not in columns:
            cursor.execute("ALTER TABLE bindings ADD COLUMN subsystem TEXT")
            conn.commit()

    def get_binding_info(
        self, compatible: str
    ) -> Tuple[str, str, str, str, str, str, str]:
        """Obtiene (vendor, title, id, subsystem, parent_bus, child_bus,
        description) para un compatible dado.

        La resolución pasa por `resolve_compatible`, es decir por el índice
        `binding_compatibles`: `bindings.compatible` solo guarda el *primer*
        compatible de cada binding, así que sin ese paso los ~20 000
        compatibles declarados que no son el primario de su binding no se
        encontraban. `cdns,i2c-r1p14` (el binding es `cdns,i2c-r1p10`) salía
        como "Unknown", y con él se perdía el `child_bus` que decide si el
        nodo es un controlador en `soc_loader._bus_for_node`.

        No hay respaldo por `LIKE`: devolvía el binding de cualquier
        compatible que contuviera este como subcadena, atribuyéndole al nodo
        los buses y el subsistema de otro dispositivo. Si no hay
        coincidencia exacta se devuelve la tupla "Unknown"/vacíos, que es lo
        que los llamantes ya saben interpretar.
        """
        resolved = self.resolve_compatible(compatible)
        if resolved is None:
            return ("Unknown", "Unknown", None, "other", None, None, "")

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT vendor, title, id, "
                "COALESCE(subsystem, 'other'), "
                "COALESCE(parent_bus, ''), "
                "COALESCE(child_bus, ''), "
                "COALESCE(description, '') "
                "FROM bindings WHERE compatible = ?",
                (resolved,),
            )
            result = cursor.fetchone()

        if result:
            return result
        return ("Unknown", "Unknown", None, "other", None, None, "")

    def resolve_compatible(self, compatible: str) -> Optional[str]:
        """Resuelve un compatible al binding que lo declara, sin aproximaciones.

        Busca primero en `bindings` y después en el índice
        `binding_compatibles`, que recoge todos los compatibles declarados por
        cada binding (no solo el primario). Devuelve None si no existe.

        **No** hay respaldo por `LIKE` en ningún caso: ni el motor semántico
        ni la ficha de `get_binding_info` (que resuelve a través de aquí)
        pueden atribuirle a un nodo lo que declara un binding parecido pero
        distinto.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT compatible FROM bindings WHERE compatible = ?", (compatible,)
            )
            row = cursor.fetchone()
            if row:
                return row[0]

            try:
                cursor.execute(
                    "SELECT binding_compatible FROM binding_compatibles "
                    "WHERE compatible = ?",
                    (compatible,),
                )
            except sqlite3.OperationalError:
                # Base de datos generada antes de que existiera el índice.
                return None

            row = cursor.fetchone()
            return row[0] if row else None

    def search_bindings(
        self,
        text: str = "",
        limit: int = 300,
        vendor: str = "",
        subsystems: Optional[Sequence[str]] = None,
    ) -> List[Tuple[str, str, str, str, str]]:
        """Busca compatibles: (compatible, título, subsistema, binding, prosa).

        Sobre `binding_compatibles`, no sobre `bindings`: ahí están los
        25 458 compatibles **declarados**, y `bindings.compatible` solo
        guarda el primero de cada binding. Quien busca `i2c-r1p14` busca ese
        compatible, no el nombre del fichero que lo documenta.

        Con tope y filtrado en SQL en vez de traérselo todo y esconder
        filas: son 25 000 entradas, y una búsqueda que devuelve más de unos
        cientos no es una búsqueda, es la lista entera otra vez. **Los dos
        filtros van aquí por lo mismo**: lo que vuelve son las primeras 300
        de 25 458, así que quedarse con las de un fabricante *después* de
        traerlas enseñaría solo las que hubiera dentro del recorte —de
        `abracon` no saldría ninguna, porque el recorte se acaba en la a.

        `vendor` es el prefijo del propio compatible, que es de donde la
        ficha lo lee. `subsystems` son los subsistemas crudos del kernel que
        forman un tipo de dispositivo: el agrupado es de la paleta
        (`gui/widgets/binding_groups.py`) y vive ahí, así que lo que baja
        hasta aquí es la lista ya resuelta y no el nombre del grupo.
        """
        where, params = _binding_where(text, vendor, subsystems)
        with self._connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT bc.compatible, COALESCE(b.title, ''), "
                    "COALESCE(b.subsystem, ''), b.compatible, "
                    "COALESCE(b.description, '') "
                    f"FROM binding_compatibles bc {_BINDING_JOIN} WHERE {where} "
                    "ORDER BY bc.compatible LIMIT ?",
                    (*params, limit),
                )
            except sqlite3.OperationalError:
                # Base construida antes del índice de compatibles.
                return []
            return cursor.fetchall()

    def binding_vendors(self) -> List[str]:
        """Fabricantes que declaran algún compatible, por su propio prefijo.

        Del compatible y no de la fila del binding que lo documenta: un
        binding documenta compatibles de varios fabricantes, y leerlo de ahí
        decía «sifive» de un compatible de Aeroflex Gaisler (ver
        `BindingEntry.vendor`).
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT DISTINCT "
                    "substr(compatible, 1, instr(compatible, ',') - 1) "
                    "FROM binding_compatibles WHERE instr(compatible, ',') > 1 "
                    "ORDER BY 1"
                )
            except sqlite3.OperationalError:
                return []
            return [row[0] for row in cursor.fetchall()]

    def binding_subsystems(self) -> List[str]:
        """Subsistemas crudos del kernel presentes en la base.

        Salen de la base y no de una lista escrita a mano por lo mismo que
        los fabricantes del catálogo de hardware: una base construida de
        otro kernel trae otros directorios de `bindings/`.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    "SELECT DISTINCT COALESCE(subsystem, '') FROM bindings ORDER BY 1"
                )
            except sqlite3.OperationalError:
                return []
            return [row[0] for row in cursor.fetchall()]

    def count_bindings(
        self,
        text: str = "",
        vendor: str = "",
        subsystems: Optional[Sequence[str]] = None,
    ) -> int:
        """Cuántos compatibles hay que casen, para decir cuántos se ven de cuántos.

        Con las mismas condiciones que la búsqueda y no el total de la
        tabla: lo que la lista enseña son las primeras 300 de lo que casa, y
        «300 de 25 458» con el filtro puesto en sensores estaría contando
        otra cosa distinta de la que se ve. Así el número dice además
        cuándo el tope está recortando.
        """
        where, params = _binding_where(text, vendor, subsystems)
        with self._connect() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute(
                    f"SELECT COUNT(*) FROM binding_compatibles bc "
                    f"{_BINDING_JOIN} WHERE {where}",
                    params,
                )
            except sqlite3.OperationalError:
                return 0
            row = cursor.fetchone()
            return row[0] if row else 0

    def list_devices_for_bus(
        self, parent_bus: str, limit: int = 5000
    ) -> List[Tuple[str, str, str, str]]:
        """Lista los dispositivos conectables a un bus, con título, bus y subsistema.

        Devuelve `(compatible, title, child_bus, subsystem)`: el `child_bus`
        permite saber si el dispositivo es a su vez un controlador (p. ej. un
        mux I2C) y por tanto puede alojar más nodos por debajo; `subsystem`
        es lo que usa la paleta del visualizador para agruparlos.
        """
        query = (
            "SELECT compatible, title, child_bus, subsystem FROM bindings "
            "WHERE lower(parent_bus) = ? ORDER BY compatible LIMIT ?"
        )
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, (parent_bus.lower(), limit))
            return cursor.fetchall()

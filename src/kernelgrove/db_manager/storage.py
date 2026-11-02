from __future__ import annotations

import json
import re
import sqlite3
import zlib
from pathlib import Path
from typing import Dict, List, Optional

from kernelgrove.db_manager.common import DEFINED_TABLES
from kernelgrove.db_schema import DB_SCHEMA_VERSION, DB_SCHEMA_VERSION_KEY
from kernelgrove.dt_model.model import BUS_TYPES, CHILD_BUS_RULES, PARENT_BUS_RULES


_EXAMPLE_BUS_PATTERNS = {
    bus: re.compile(r"^\s*" + bus + r"(@[0-9a-fA-F]+)?\s*\{")
    for bus in BUS_TYPES
    if bus not in {"platform", "simple-bus"}
}

_COMPATIBLE_LINE = re.compile(r"\bcompatible\s*=")


def _example_is_bus_wrapper(example: str) -> bool:
    """Determina si el nodo más externo de un ejemplo es un bus que envuelve a otro.

    Un envoltorio no declara `compatible` propio (es solo el bus donde se
    enchufa el dispositivo), pero contiene un nodo anidado que sí lo declara.
    Un controlador, en cambio, declara su compatible en el primer nivel.
    """
    depth = 0
    has_own_compatible = False
    has_nested_compatible = False

    for line in example.splitlines():
        if _COMPATIBLE_LINE.search(line):
            if depth == 1:
                has_own_compatible = True
            elif depth >= 2:
                has_nested_compatible = True
        depth += line.count("{") - line.count("}")

    return has_nested_compatible and not has_own_compatible


def infer_parent_bus_from_examples(record, compatible: str = "") -> Optional[str]:
    """Deduce el bus padre de un binding a partir del envoltorio de sus `examples`.

    Muchos bindings de dispositivo no referencian ningún schema de bus en
    `allOf` (un RTC I2C como `dallas,ds1307` solo referencia `rtc.yaml`), así
    que `PARENT_BUS_RULES` los deja sin resolver. Sin embargo, el ejemplo del
    propio binding sí lo delata: envuelve el dispositivo en el nodo del bus al
    que se conecta.

        i2c {                                  <- nivel 1: el bus, sin compatible
            rtc@68 {                           <- nivel 2: el dispositivo
                compatible = "dallas,ds1337";
            };
        };

    No basta con que el nodo más externo se llame como un bus: el ejemplo de
    un *controlador* tiene la misma forma, pero declara su propio compatible
    en el primer nivel.

        mmc@123 {                              <- nivel 1: el propio controlador
            compatible = "fsl,imx21-mmc";
        };

    De ahí la comprobación de `_example_is_bus_wrapper`, que mira dónde
    aparece el `compatible` en lugar de buscar una cadena concreta: los
    ejemplos suelen usar otro modelo de la misma familia (ds1337 por
    ds1307), así que comparar contra el compatible del binding no sirve.

    `compatible` se mantiene por compatibilidad de firma y no se usa.
    """
    examples = record.get("examples")
    if not isinstance(examples, list):
        return None

    for example in examples:
        if not isinstance(example, str):
            continue

        stripped = example.lstrip()
        bus = next(
            (
                name
                for name, pat in _EXAMPLE_BUS_PATTERNS.items()
                if pat.match(stripped)
            ),
            None,
        )
        if bus is not None and _example_is_bus_wrapper(stripped):
            return bus

    return None


def _lookup_rule(ref_name: str, rules: Dict[str, str]) -> Optional[str]:
    """Busca `ref_name` en una tabla de reglas, tolerando prefijos de vendor.

    Compara primero por nombre exacto de fichero, luego normalizando el
    prefijo de vendor (p. ej. "samsung,spi-peripheral-props.yaml") y por
    último por sufijo.
    """
    if ref_name in rules:
        return rules[ref_name]

    normalized_name = ref_name.split(",")[-1]
    if normalized_name in rules:
        return rules[normalized_name]

    for rule_name, value in rules.items():
        if ref_name.endswith(rule_name) or normalized_name.endswith(rule_name):
            return value

    return None


def infer_parent_child_bus(record, compatible: str = "") -> tuple[str, Optional[str]]:
    """Infiere (parent_bus, child_bus) de un binding a partir de sus `allOf.$ref`.

    Las dos dimensiones se resuelven por separado (ver `CHILD_BUS_RULES` y
    `PARENT_BUS_RULES` en dt_model/model.py) y se recorren *todas* las
    referencias, porque un mismo nodo puede colgar de un bus y ofrecer otro:
    un mux I2C cuelga de un I2C y expone un I2C a sus hijos.

    Si las reglas no determinan el bus padre, se recurre a
    `infer_parent_bus_from_examples` antes de aceptar "platform".
    """
    parent_bus: Optional[str] = None
    child_bus: Optional[str] = None

    for entry in record.get("allOf", []):
        if not isinstance(entry, dict):
            continue
        ref = entry.get("$ref")
        if not ref:
            continue

        # Eliminar cualquier fragmento después de '#'
        ref_name = ref.split("#", 1)[0].rsplit("/", 1)[-1]

        if child_bus is None:
            child_bus = _lookup_rule(ref_name, CHILD_BUS_RULES)
        if parent_bus is None:
            parent_bus = _lookup_rule(ref_name, PARENT_BUS_RULES)

    if parent_bus is None:
        parent_bus = infer_parent_bus_from_examples(record, compatible)

    return (parent_bus or "platform", child_bus)


def get_subsystem(path: str) -> Optional[str]:
    """Deriva el subsistema a partir de la ruta del YAML de origen.

    Toma el primer directorio situado justo después de "bindings/" en la
    ruta (p. ej. ".../bindings/net/foo.yaml" -> "net"). Devuelve None si la
    ruta no contiene "bindings" o si el fichero está directamente en esa
    carpeta sin subdirectorio.
    """
    path_obj = Path(path)
    parts = path_obj.parts

    try:
        idx = parts.index("bindings")
        # Solo hay subsistema si queda más de un nivel por debajo de "bindings"
        if idx + 2 < len(parts):
            # Retornar el primer directorio después de bindings
            return parts[idx + 1]
    except ValueError:
        pass

    return None


def init_sqlite_db(db_path: Path) -> sqlite3.Connection:
    """Abre (o crea) la base SQLite en `db_path` y garantiza las tablas
    `bindings` y `socs` con su esquema actual. Devuelve la conexión abierta.
    """
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    # Create bindings and SoCs tables
    # `description` es la prosa del binding, lo único del YAML que hace falta
    # a mano: el documento entero ya está en `schemas.raw`, procesado y
    # comprimido, así que guardarlo aquí otra vez costaba 13,6 MB sin que
    # nadie lo leyera (ver `_drop_legacy_document`).
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS bindings ("
        "id INTEGER PRIMARY KEY NOT NULL UNIQUE, "
        "compatible TEXT NOT NULL UNIQUE, "
        "vendor TEXT, "
        "title TEXT, "
        "description TEXT, "
        "subsystem TEXT, "
        "parent_bus TEXT, "
        "child_bus TEXT"
        ")"
    )

    # Catálogo de SoCs: identidad más `file_path`, la clave del fuente en la
    # tabla `sources`. El árbol parseado **no** se guarda (ver
    # `_drop_legacy_devicetree_document`): era exactamente
    # `parse_dts_source(sources[file_path]).root.to_dict()`, 48 MB sin
    # comprimir de un dato derivable, y el único camino que lo leía —abrir un
    # SoC en el editor— parsea el fuente de todas formas.
    # `compatible` no siempre es un compatible real: un SoC repartido en
    # varios ficheros (familia sunxi) no declara el suyo propio, así que la
    # ingesta cae al nombre de fichero (ver `main.classify_root_directory`).
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS socs ("
        "id INTEGER PRIMARY KEY NOT NULL UNIQUE, "
        "compatible TEXT NOT NULL UNIQUE, "
        "vendor TEXT, "
        "name TEXT, "
        "file_path TEXT"
        ")"
    )

    # Mismo esquema que `socs`: boards y descripciones de hardware completas
    # (`.dts` compilables), distinguidas de los SoCs por `classify_devicetree`
    # (ver db_manager/records.py) en vez de vivir en la misma tabla.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS boards ("
        "id INTEGER PRIMARY KEY NOT NULL UNIQUE, "
        "compatible TEXT NOT NULL UNIQUE, "
        "vendor TEXT, "
        "name TEXT, "
        "file_path TEXT"
        ")"
    )

    # Fuentes de device tree y cabeceras `dt-bindings`, guardados comprimidos.
    # Es lo que permite que la aplicación funcione sin el kernel clonado: el
    # editor abre los `.dtsi` y sus includes desde aquí.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS sources ("
        "path TEXT PRIMARY KEY NOT NULL, "
        "name TEXT NOT NULL, "
        "kind TEXT NOT NULL, "
        "source BLOB NOT NULL"
        ")"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sources_name ON sources(name)")
    conn.commit()

    # Schemas de binding ya procesados por dt-schema (fixups aplicados y
    # notación abreviada expandida), indexados por su `$id`. Están todos, no
    # solo los que describen un dispositivo: `rtc.yaml` o `i2c-controller.yaml`
    # no tienen compatible propio pero son el destino de la mitad de los
    # `$ref`, así que sin ellos no se puede resolver ninguna herencia.
    # `raw` conserva el YAML original, que es lo único que trae las
    # descripciones y los `examples`: los fixups los eliminan.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS schemas ("
        "id TEXT PRIMARY KEY NOT NULL, "
        "path TEXT, "
        "title TEXT, "
        # Un schema con `select` es de los que se aplican por la forma del
        # nodo y no por su compatible: son los bindings genéricos, la capa 2
        # del motor. Marcarlos aquí evita cargar los 5663 para encontrarlos.
        "has_select INTEGER NOT NULL DEFAULT 0, "
        "schema BLOB NOT NULL, "
        "raw BLOB"
        ")"
    )

    # Qué compatible declara cada schema y **en qué nodo suyo** lo declara.
    # `node_path` vacío es el nodo del propio binding; "pwm" sería un subnodo
    # (`ti,twl4030-pwm` dentro de `ti,twl.yaml`). Sin esa ruta, validar el
    # subnodo contra el schema del padre le exigiría propiedades ajenas.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS schema_compatibles ("
        "compatible TEXT NOT NULL, "
        "schema_id TEXT NOT NULL, "
        "node_path TEXT NOT NULL DEFAULT '', "
        "is_pattern INTEGER NOT NULL DEFAULT 0, "
        # Posición del compatible en la lista que declara el nodo: 0 es el
        # que identifica al binding, y a partir de ahí son los genéricos de
        # familia que declaran también otros bindings.
        "position INTEGER NOT NULL DEFAULT 0, "
        "PRIMARY KEY (compatible, schema_id, node_path)"
        ")"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_schema_compatibles_compatible "
        "ON schema_compatibles(compatible)"
    )

    # Metadatos de la ingesta de schemas: versión de dtschema con la que se
    # generaron (los schemas procesados no son compatibles entre versiones) y
    # los tipos de cada propiedad, que dt-schema deduce del conjunto.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta ("
        "key TEXT PRIMARY KEY NOT NULL, "
        "value BLOB NOT NULL"
        ")"
    )
    # Versión del esquema con el que se está construyendo la base. Se escribe
    # en cada ingesta, sea de la tabla que sea, para que la aplicación pueda
    # decir "esta base es de otra versión" en vez de descubrirlo a trozos con
    # una consulta que falla (ver `kernelgrove.db_schema`).
    cursor.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (DB_SCHEMA_VERSION_KEY, _compress_json(DB_SCHEMA_VERSION)),
    )
    conn.commit()

    # Bases creadas con esquemas anteriores no tienen estas columnas.
    ensure_column(conn, "socs", "file_path", "TEXT")

    # Qué hardware describe cada entrada, sacado del propio device tree
    # (`records.extract_hardware`). Va en columnas y no se calcula al vuelo
    # porque el catálogo son ~3700 filas y resolver los includes de cada una
    # para pintar una lista es medio minuto por pantalla. Con `ensure_column`
    # y no en el `CREATE TABLE`: una base ya construida no se altera sola
    # (ver la nota de `init_sqlite_db`), y sin esto los `INSERT` fallarían
    # contra ella.
    for table in ("socs", "boards"):
        ensure_column(conn, table, "arch", "TEXT")
        ensure_column(conn, table, "cores", "INTEGER")
        ensure_column(conn, table, "ram", "INTEGER")
        ensure_column(conn, table, "clock", "INTEGER")
        ensure_column(conn, table, "model", "TEXT")
    ensure_column(conn, "bindings", "description", "TEXT")
    _drop_legacy_document(conn)
    _drop_legacy_devicetree_document(conn)
    ensure_column(conn, "schema_compatibles", "position", "INTEGER NOT NULL DEFAULT 0")
    ensure_column(conn, "schemas", "has_select", "INTEGER NOT NULL DEFAULT 0")
    # Enlace del binding con su schema procesado en la tabla `schemas`.
    ensure_column(conn, "bindings", "schema_id", "TEXT")

    # Un binding declara varios compatibles, pero `bindings.compatible` solo
    # guarda el primero. Este índice registra todos los declarados y a qué
    # binding pertenecen, para poder resolver un compatible cualquiera sin
    # recurrir a búsquedas aproximadas.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS binding_compatibles ("
        "compatible TEXT PRIMARY KEY NOT NULL, "
        "binding_compatible TEXT NOT NULL"
        ")"
    )
    conn.commit()

    # Índice de la capa 3 (existencia de macros de `dt-bindings/*.h`, ver
    # `db_manager/macros.py`). `header_path` ya incluye el cierre transitivo
    # de lo que esa cabecera incluye a su vez, así que una fila por
    # (nombre, cabecera) basta para responder "¿se ve NOMBRE incluyendo esta
    # cabecera?" sin resolver el grafo en cada consulta.
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS header_macros ("
        "name TEXT NOT NULL, "
        "header_path TEXT NOT NULL, "
        # Valor entero ya resuelto con `cpp` en la ingesta (NULL si no había
        # `cpp`/checkout disponibles, o si la macro es de función sin
        # argumentos y por tanto no tiene un valor constante).
        "value INTEGER, "
        "PRIMARY KEY (name, header_path)"
        ")"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_header_macros_name ON header_macros(name)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_header_macros_header "
        "ON header_macros(header_path)"
    )
    conn.commit()

    # Va aquí, y no con el resto de migraciones de más arriba, porque
    # `ensure_column` hace `ALTER TABLE` y por tanto exige que la tabla ya
    # exista: colocada antes del `CREATE TABLE`, cualquier base nueva moría
    # con «no such table: header_macros» en el primer paso de la ingesta.
    ensure_column(conn, "header_macros", "value", "INTEGER")

    return conn


def ensure_column(
    conn: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    """Añade una columna a una tabla existente si aún no la tiene.

    `CREATE TABLE IF NOT EXISTS` no modifica las tablas ya creadas, así que sin
    esto una base construida con un esquema anterior falla al insertar en las
    columnas nuevas.

    Si la tabla todavía no existe no hay nada que migrar: `PRAGMA table_info`
    devuelve vacío y se sale sin tocar nada, en vez de intentar un
    `ALTER TABLE` que fallaría.
    """
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    rows = cursor.fetchall()
    if not rows:
        return
    existing = {row[1] for row in rows}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        conn.commit()


def _drop_legacy_document(conn: sqlite3.Connection) -> None:
    """Retira la columna `bindings.document` de bases construidas antes.

    Guardaba el YAML completo del binding, que ahora vive comprimido en
    `schemas.raw`; nadie leía su contenido y ocupaba 13,6 MB. Si SQLite es
    demasiado antiguo para `DROP COLUMN` se deja estar: `column_names` hace
    que la inserción siga rellenándola con la cadena vacía, porque en el
    esquema viejo era `NOT NULL`.
    """
    if "document" not in column_names(conn, "bindings"):
        return
    try:
        conn.execute("ALTER TABLE bindings DROP COLUMN document")
        conn.commit()
    except sqlite3.OperationalError:
        pass


def _drop_legacy_devicetree_document(conn: sqlite3.Connection) -> None:
    """Retira la columna `document` de `socs`/`boards` construidas antes.

    Guardaba el árbol ya parseado, que resultó ser exactamente lo que sale de
    parsear el fuente que la tabla `sources` ya almacena comprimido: 48 MB de
    los 125 de la base, en JSON sin comprimir, para un dato derivable. Su
    único lector (`SocsDatabase.get_document` -> `load_soc_profile`) no lo
    llamaba nadie, y el camino real —elegir un SoC, que lo abre en el editor—
    parsea el fuente igualmente.

    Si SQLite es demasiado antiguo para `DROP COLUMN` se deja estar:
    `store_records_in_sqlite_devicetree` sigue rellenándola con "{}", porque
    en el esquema viejo era `NOT NULL`.
    """
    for table in ("socs", "boards"):
        if "document" not in column_names(conn, table):
            continue
        try:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN document")
            conn.commit()
        except sqlite3.OperationalError:
            pass


def column_names(conn: sqlite3.Connection, table: str) -> List[str]:
    """Columnas que tiene una tabla, en orden."""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cursor.fetchall()]


def clear_table(conn: sqlite3.Connection, table_name: str) -> None:
    """Vacía la tabla indicada antes de una reingesta completa.

    El almacenado usa `INSERT OR REPLACE`, que actualiza las filas existentes
    pero nunca elimina las que dejan de generarse. Sin este borrado previo,
    los registros de ingestas anteriores (por ejemplo compatibles que ahora
    se descartan por malformados) quedarían para siempre en la base.
    """
    if table_name not in DEFINED_TABLES:
        raise ValueError(
            f"Invalid table name: {table_name}. Must be one of {DEFINED_TABLES}."
        )
    if table_name == "macros":
        # `header_macros` no tiene fila propia por `macros`: es una tabla
        # derivada de `sources`, igual que `schema_compatibles` lo es de
        # `schemas`.
        conn.execute("DELETE FROM header_macros")
        conn.commit()
        return
    conn.execute(f"DELETE FROM {table_name}")
    if table_name == "bindings":
        conn.execute("DELETE FROM binding_compatibles")
    if table_name == "schemas":
        # Los índices derivados se regeneran enteros con la tabla.
        conn.execute("DELETE FROM schema_compatibles")
        # Todo menos la versión del esquema de la base: la escribe
        # `init_sqlite_db` al abrir, antes de este borrado, y no es un
        # metadato de la ingesta de schemas sino del fichero entero.
        conn.execute(
            "DELETE FROM schema_meta WHERE key <> ?", (DB_SCHEMA_VERSION_KEY,)
        )
    conn.commit()


def store_records_in_sqlite_bindings(conn, records) -> int:
    """Inserta/reemplaza `records` en la tabla `bindings`.

    Por cada registro deriva `subsystem` (de la ruta) y `parent_bus`/
    `child_bus` (de sus referencias `allOf`) antes de escribirlo. Los
    registros sin `primary_compatible` se omiten. No hace commit por
    registro; confirma la transacción una vez procesados todos.
    """
    table_name = "bindings"
    cursor = conn.cursor()
    # Una base antigua puede conservar `document NOT NULL` si esta versión de
    # SQLite no admitió quitarla; en ese caso hay que seguir dándole un valor.
    legacy_document = "document" in column_names(conn, table_name)
    for record in records:
        primary_compatible = record.get("primary_compatible", "")
        if not primary_compatible:
            continue
        file_path = record.get("file_path", "")
        subsystem = get_subsystem(file_path)
        parent_bus, child_bus = infer_parent_child_bus(
            record["raw"], primary_compatible
        )

        # `$id` es la clave con la que dt-schema identifica el schema y con
        # la que se guarda en la tabla `schemas`; enlazarlos aquí evita tener
        # que adivinar la correspondencia por la ruta del fichero.
        schema_id = ""
        if isinstance(record.get("raw"), dict):
            schema_id = str(record["raw"].get("$id") or "").rstrip("#")

        columns = [
            "compatible",
            "vendor",
            "title",
            "description",
            "subsystem",
            "parent_bus",
            "child_bus",
            "schema_id",
        ]
        row = [
            primary_compatible,
            record.get("vendor"),
            record["title"],
            record.get("description"),
            subsystem,
            parent_bus,
            child_bus,
            schema_id,
        ]
        if legacy_document:
            columns.append("document")
            row.append("")

        placeholders = ", ".join("?" for _ in columns)
        cursor.execute(
            f"INSERT OR REPLACE INTO {table_name} "
            f"({', '.join(columns)}) VALUES ({placeholders})",
            tuple(row),
        )

        # Registrar todos los compatibles declarados, no solo el primario, para
        # que un `.dts` que use cualquiera de ellos se pueda resolver.
        for declared in record.get("compatible") or []:
            cursor.execute(
                "INSERT OR REPLACE INTO binding_compatibles "
                "(compatible, binding_compatible) VALUES (?, ?)",
                (declared, primary_compatible),
            )

    conn.commit()
    return 0


def store_records_in_sqlite_sources(conn, records) -> int:
    """Guarda los fuentes en la tabla `sources`, comprimidos con zlib.

    Sin comprimir serían unos 70 MB; comprimidos rondan los 12 MB, así que la
    base sigue siendo manejable pese a contener todos los ficheros.
    """
    cursor = conn.cursor()
    for record in records:
        path = record.get("path")
        if not path:
            continue

        cursor.execute(
            "INSERT OR REPLACE INTO sources (path, name, kind, source) "
            "VALUES (?, ?, ?, ?)",
            (
                path,
                record["name"],
                record["kind"],
                zlib.compress(record["text"].encode("utf-8"), 6),
            ),
        )

    conn.commit()
    return 0


def store_records_in_sqlite_schemas(conn, records) -> int:
    """Guarda los schemas procesados y el índice de compatibles que declaran.

    Cada registro trae el schema ya procesado (`schema`), el YAML original
    (`raw`) y la lista `(compatible, node_path, es_patrón)` que ese schema
    declara. Ambos documentos se guardan comprimidos: sin comprimir son unos
    27 MB de schemas y 26 MB de YAML crudo; comprimidos rondan los 3 y 6 MB.
    """
    cursor = conn.cursor()
    for record in records:
        schema_id = record.get("id")
        if not schema_id:
            continue

        raw = record.get("raw")
        cursor.execute(
            "INSERT OR REPLACE INTO schemas "
            "(id, path, title, has_select, schema, raw) VALUES (?, ?, ?, ?, ?, ?)",
            (
                schema_id,
                record.get("path", ""),
                record.get("title"),
                1 if record.get("has_select") else 0,
                _compress_json(record["schema"]),
                _compress_json(raw) if raw is not None else None,
            ),
        )

        for compatible, node_path, pattern, position in record.get("compatibles") or []:
            cursor.execute(
                "INSERT OR REPLACE INTO schema_compatibles "
                "(compatible, schema_id, node_path, is_pattern, position) "
                "VALUES (?, ?, ?, ?, ?)",
                (compatible, schema_id, node_path, 1 if pattern else 0, position),
            )

    conn.commit()
    return 0


def store_schema_meta(conn, version: str, types, pattern_types) -> None:
    """Guarda los metadatos de la ingesta de schemas.

    La versión de dtschema es imprescindible: los schemas procesados no son
    compatibles entre versiones (el propio dtschema rechaza un fichero
    generado por otra), así que la aplicación tiene que poder comprobar con
    qué versión se construyó la base.
    """
    cursor = conn.cursor()
    entries = {
        "version": version,
        "types": types,
        "pattern-types": pattern_types,
    }
    for key, value in entries.items():
        cursor.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            (key, _compress_json(value)),
        )
    conn.commit()


def _compress_json(document) -> bytes:
    """Serializa a JSON y comprime, como se guardan los fuentes."""
    return zlib.compress(json.dumps(document, ensure_ascii=False).encode("utf-8"), 6)


def store_records_in_sqlite_macros(conn, records) -> int:
    """Inserta/reemplaza el índice de macros (`name`, `header_path`, `value`)."""
    cursor = conn.cursor()
    for record in records:
        name = record.get("name")
        header_path = record.get("header_path")
        if not name or not header_path:
            continue
        cursor.execute(
            "INSERT OR REPLACE INTO header_macros (name, header_path, value) "
            "VALUES (?, ?, ?)",
            (name, header_path, record.get("value")),
        )
    conn.commit()
    return 0


def store_records_in_sqlite_devicetree(conn, records, table_name: str) -> int:
    """Inserta/reemplaza `records` en `socs` o `boards` (mismo esquema)."""
    cursor = conn.cursor()
    # Una base antigua puede conservar `document NOT NULL` si esta versión de
    # SQLite no admitió quitarla; en ese caso hay que seguir dándole un valor.
    legacy_document = "document" in column_names(conn, table_name)

    columns = [
        "compatible",
        "vendor",
        "name",
        "file_path",
        "arch",
        "cores",
        "ram",
        "clock",
        "model",
    ]
    if legacy_document:
        columns.append("document")
    placeholders = ", ".join("?" for _ in columns)
    statement = (
        f"INSERT OR REPLACE INTO {table_name} "
        f"({', '.join(columns)}) VALUES ({placeholders})"
    )

    for record in records:
        primary_compatible = record.get("primary_compatible", "")
        if not primary_compatible:
            continue

        row = [
            primary_compatible,
            record.get("vendor"),
            record["name"],
            # Clave relativa hacia `sources`; nunca una ruta absoluta de
            # esta máquina, que no existiría en la del usuario.
            record.get("file_path", ""),
            record.get("arch"),
            record.get("cores"),
            record.get("ram"),
            record.get("clock"),
            record.get("model"),
        ]
        if legacy_document:
            row.append("{}")

        cursor.execute(statement, tuple(row))

    conn.commit()
    return 0


def store_records_in_sqlite(
    conn: sqlite3.Connection,
    records: List[Dict[str, object]],
    table_name: str,
) -> int:
    """Despacha el almacenado de `records` según la tabla destino."""

    if table_name == "bindings":
        return store_records_in_sqlite_bindings(conn, records)
    elif table_name in ("socs", "boards"):
        return store_records_in_sqlite_devicetree(conn, records, table_name)
    elif table_name == "sources":
        return store_records_in_sqlite_sources(conn, records)
    elif table_name == "schemas":
        return store_records_in_sqlite_schemas(conn, records)
    elif table_name == "macros":
        return store_records_in_sqlite_macros(conn, records)
    else:
        raise ValueError(
            f"Invalid table name: {table_name}. Must be one of {DEFINED_TABLES}."
        )

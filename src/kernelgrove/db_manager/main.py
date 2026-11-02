#!/usr/bin/env python3
"""CLI de ingesta: del checkout del kernel a `database/bindings.db`."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Optional

from kernelgrove.db_manager.common import DEFINED_TABLES
from kernelgrove.db_manager.finders import (
    iter_devicetree_files,
    iter_source_files,
    iter_yaml_files,
)
from kernelgrove.db_manager.kernel_versions import (
    binding_key,
    first_release_by_binding,
    version_label,
)
from kernelgrove.db_manager.loader import load_yaml_document
from kernelgrove.db_manager.macros import build_header_macro_records, cpp_binary
from kernelgrove.db_manager.records import (
    build_record_bindings,
    build_record_devicetree,
    build_record_sources,
    classify_devicetree,
    extract_hardware,
    relative_key,
)
from kernelgrove.db_manager.schemas import (
    build_processed_schemas,
    dtschema_version,
    schema_records,
)
from kernelgrove.db_manager.storage import (
    clear_table,
    ensure_column,
    init_sqlite_db,
    store_records_in_sqlite,
    store_schema_meta,
)
from kernelgrove.dts_engine.parser import parse_dts_source


def parse_root_directory_bindings(root_dir: Path) -> list[dict[str, any]]:
    """Recorre `root_dir`, parsea cada YAML y construye un registro de binding.

    Los ficheros que fallan al parsear se registran por consola y se omiten
    en lugar de interrumpir la ingesta completa.
    """
    records = []
    for path in iter_yaml_files(root_dir):
        try:
            doc = load_yaml_document(path)
        except RuntimeError as exc:
            print(f"[ERROR] {exc}")
            continue

        if doc is None:
            continue

        records.append(build_record_bindings(path, doc))
    return records


def classify_root_directory(root_dir: Path) -> dict[str, list[dict[str, any]]]:
    """Recorre `root_dir` **una sola vez** y reparte cada `.dts`/`.dtsi`.

    `socs` y `boards` salen de los mismos ficheros y se distinguen solo por
    lo que `classify_devicetree` ve dentro (un árbol con `/cpus/cpu@...` es un
    SoC; uno completo sin cpus propio es una board). Recorrerlos en dos
    pasadas independientes significaba parsear los ~6600 ficheros dos veces
    —unos 150 s por pasada— para tirar en cada una lo que la otra se
    quedaba. Aquí se parsea cada fichero una vez y se despacha a su tabla.

    Devuelve `{"soc": [...], "board": [...]}`; lo que no es ni una cosa ni la
    otra (PMICs, paneles, overlays...) se descarta.
    """
    records: dict[str, list[dict[str, any]]] = {"soc": [], "board": []}
    # Qué incluye y qué hardware declara **cada** fichero recorrido, incluidos
    # los que no acaban en ninguna tabla: son los eslabones intermedios por
    # los que una board llega hasta el `.dtsi` de su SoC (ver
    # `inherit_from_includes`). Se guarda aquí para no volver a parsearlos.
    catalogo: dict[str, dict[str, any]] = {}
    for path in iter_devicetree_files(root_dir):
        text = path.read_text(encoding="utf-8", errors="replace")
        result = parse_dts_source(text)
        hardware = extract_hardware(result.root)
        catalogo[path.name] = {
            "includes": [
                Path(include.target).name for include in result.includes
            ],
            "hardware": hardware,
        }
        kind = classify_devicetree(text, result.root)
        if kind is None:
            continue

        record = build_record_devicetree(path, result.root)
        if kind == "soc" and not record["primary_compatible"]:
            # Un SoC repartido en varios ficheros (p.ej. la familia sunxi)
            # suele no declarar su propio `compatible` raíz: solo lo hace la
            # board que lo incluye. Es un SoC de todas formas (tiene
            # /cpus/cpu@...), así que sin este fallback se perdería por
            # completo en lugar de quedarse fuera de `socs` por error. El
            # nombre de fichero es la única clave estable disponible aquí.
            record["primary_compatible"] = record["name"]
        # Clave relativa hacia la tabla `sources`, para poder recuperar el
        # fuente original sin depender de rutas de esta máquina.
        record["file_path"] = relative_key(path, root_dir)
        record["_file_name"] = path.name
        records[kind].append(record)

    for kind_records in records.values():
        for record in kind_records:
            inherit_from_includes(record, catalogo)
    return records


def inherit_from_includes(
    record: dict[str, any], catalogo: dict[str, dict[str, any]]
) -> None:
    """Completa lo que el fichero no declara con lo que declara lo que incluye.

    Una board escribe su `/memory` y su `model`, pero la arquitectura y el
    número de núcleos están en el `.dtsi` de su SoC, que incluye. Se sigue la
    cadena de `#include` por nombre de fichero —que es lo único común entre
    la ruta escrita en el `#include` y la del fichero recorrido— hasta
    encontrar quien sí lo declare, y **sin volver a parsear nada**: el
    catálogo se llenó en el mismo recorrido.

    Solo se hereda lo que falta. Si la board declara su propio reloj o su
    propia RAM, la suya manda: es la más específica de las dos.
    """
    pendientes = [name for name in ("arch", "cores", "clock") if not record.get(name)]
    if not pendientes:
        return

    visitados: set[str] = set()
    cola = list(catalogo.get(record.get("_file_name", ""), {}).get("includes", []))
    while cola and pendientes:
        nombre = cola.pop(0)
        if nombre in visitados or nombre not in catalogo:
            continue
        visitados.add(nombre)
        entrada = catalogo[nombre]
        for name in list(pendientes):
            valor = entrada["hardware"].get(name)
            if valor:
                record[name] = valor
                pendientes.remove(name)
        cola.extend(entrada["includes"])


def parse_root_directory_socs(root_dir: Path) -> list[dict[str, any]]:
    """Recorre `root_dir` y construye un registro por cada SoC encontrado."""
    return classify_root_directory(root_dir)["soc"]


def parse_root_directory_boards(root_dir: Path) -> list[dict[str, any]]:
    """Recorre `root_dir` y construye un registro por cada board encontrada."""
    return classify_root_directory(root_dir)["board"]


def ingest_devicetrees(
    root_dir: Path, sqlite_path: Path, reset: bool
) -> dict[str, int]:
    """Puebla `socs` y `boards` con una única pasada sobre `root_dir`.

    Es el camino que usa `scripts/build_database.sh`. `--table socs` y
    `--table boards` siguen existiendo para reconstruir una sola tabla, pero
    hacerlo por separado parsea el árbol entero dos veces.
    """
    records = classify_root_directory(root_dir)
    conn = init_sqlite_db(sqlite_path)
    counts: dict[str, int] = {}
    for kind, table in (("soc", "socs"), ("board", "boards")):
        if reset:
            clear_table(conn, table)
            print(f"Tabla {table} vaciada antes de la reingesta.")
        store_records_in_sqlite(conn, records[kind], table)
        counts[table] = len(records[kind])
    conn.close()
    return counts


def parse_root_directory_sources(root_dir: Path) -> list[dict[str, any]]:
    """Recorre `root_dir` y recoge el texto de todos los fuentes."""
    records = []
    for path in iter_source_files(root_dir):
        try:
            records.append(build_record_sources(path, root_dir))
        except OSError as exc:
            print(f"[ERROR] {path}: {exc}")
    return records


def ingest_schemas(root_dir: Path, sqlite_path: Path, reset: bool) -> int:
    """Procesa con dt-schema todos los YAML bajo `root_dir` y los almacena.

    Camino propio dentro de la ingesta, y no una tabla más del recorrido
    genérico, porque la pasada deja además metadatos —versión de dtschema y
    tipos de propiedad— que no son registros de tabla.

    Es la parte más cara de la ingesta (unos 90 s para los bindings del
    kernel) porque aplica a cada schema los mismos fixups que `dt-mk-schema`:
    expandir la notación abreviada, normalizar tipos y dimensiones y añadir
    las propiedades implícitas. A cambio es lo que permite responder qué
    propiedades admite y cuáles exige un compatible sin reimplementar las
    reglas de composición de los bindings.
    """
    processed = build_processed_schemas(root_dir)
    print(f"dt-schema {processed.version}: {len(processed.schemas)} schemas procesados")

    records = list(schema_records(processed, root_dir))
    conn = init_sqlite_db(sqlite_path)
    if reset:
        clear_table(conn, "schemas")
        print("Tabla schemas vaciada antes de la reingesta.")
    store_records_in_sqlite(conn, records, "schemas")
    store_schema_meta(
        conn, processed.version, processed.types, processed.pattern_types
    )
    conn.close()
    return len(records)


def ingest_macros(
    sqlite_path: Path, reset: bool, include_root: Optional[str]
) -> int:
    """Construye el índice de macros de `dt-bindings/*.h` (capa 3).

    Camino propio como `schemas`, y por el mismo motivo: no recorre `--root`
    sino la tabla `sources` ya poblada (`--table sources`), así que no
    encaja en el despacho genérico de `parse_root_directory`.

    `include_root` es la raíz `-I` para `cpp` (típicamente
    `kernel/linux/include`, la que resuelve `<dt-bindings/…>`): con ella y
    `cpp` en el sistema, además del nombre de cada macro se guarda su valor
    ya expandido; sin alguno de los dos, el índice se queda solo con
    existencia.
    """
    conn = init_sqlite_db(sqlite_path)
    has_sources = conn.execute(
        "SELECT COUNT(*) FROM sources WHERE kind = 'header'"
    ).fetchone()[0]
    if not has_sources:
        conn.close()
        print(
            "La tabla sources no tiene cabeceras: ingiere antes con "
            "--table sources."
        )
        return 0

    if reset:
        clear_table(conn, "macros")
        print("Tabla header_macros vaciada antes de la reingesta.")
    conn.close()

    if include_root is not None and cpp_binary() is None:
        print(
            "Aviso: no se encontró cpp/gcc/cc en el sistema; el índice de "
            "macros se genera solo con existencia, sin valores."
        )

    records = build_header_macro_records(sqlite_path, include_root=include_root)
    conn = init_sqlite_db(sqlite_path)
    store_records_in_sqlite(conn, records, "macros")
    conn.close()
    return len(records)


def parse_root_directory(
    root_dir: Path, table_name: str = "bindings"
) -> list[dict[str, any]]:
    """Despacha el recorrido de `root_dir` según la tabla destino.

    Los bindings se generan a partir de YAML (`Documentation/devicetree/bindings`);
    socs y boards a partir de los mismos ficheros `.dts`/`.dtsi`, clasificados
    por `classify_devicetree` (ver `classify_root_directory`).
    """
    if table_name == "bindings":
        return parse_root_directory_bindings(root_dir)
    elif table_name == "socs":
        return parse_root_directory_socs(root_dir)
    elif table_name == "boards":
        return parse_root_directory_boards(root_dir)
    elif table_name == "sources":
        return parse_root_directory_sources(root_dir)
    else:
        raise ValueError(
            f"Invalid table name: {table_name}. Must be one of {DEFINED_TABLES}."
        )


def ingest_kernel_versions(sqlite_path: Path, repo: Path) -> int:
    """Rellena `schemas.since` con la release del kernel que trae cada binding.

    Camino propio como `schemas` y `macros`: no recorre `--root` sino la
    historia del repositorio, y actualiza filas que ya están puestas en vez
    de insertar nuevas. Sin git, sin repositorio o sin etiquetas no escribe
    nada y lo dice — es un dato de más, no un requisito.

    Los schemas que trae dt-schema y no el kernel (`i2c-controller.yaml` y
    compañía, que viven en `dtschema/schemas/…`) se quedan sin versión, que
    es lo correcto: no son bindings del kernel.
    """
    since = first_release_by_binding(repo)
    if not since:
        print(
            f"No hay historia de git en {repo}: los bindings se quedan sin "
            "versión del kernel."
        )
        return 0

    conn = init_sqlite_db(sqlite_path)
    ensure_column(conn, "schemas", "since", "TEXT")
    filas = conn.execute("SELECT id, path FROM schemas").fetchall()
    actualizadas = 0
    for schema_id, path in filas:
        tag = since.get(binding_key(path or ""))
        if tag is None:
            continue
        conn.execute(
            "UPDATE schemas SET since = ? WHERE id = ?",
            (version_label(tag), schema_id),
        )
        actualizadas += 1
    conn.commit()
    conn.close()
    return actualizadas


def main() -> int:
    """Punto de entrada de la CLI de ingesta.

    Lee el checkout del kernel desde `--root` y puebla la tabla `--table` de
    la base SQLite en `--sqlite`. No se generan volcados JSON: eran 118 MB
    (`bindings.json` + `socs.json` + `boards.json`) que ningún código abría,
    reescritos en cada build.
    """
    parser = argparse.ArgumentParser(
        description="Ingiere los bindings y device trees del kernel en SQLite."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("./kernel/linux/Documentation/devicetree/bindings"),
        help="Directorio raíz donde buscar los ficheros a ingerir.",
    )
    parser.add_argument(
        "--sqlite",
        type=Path,
        default=Path("./database/bindings.db"),
        help="Ruta de la base de datos SQLite.",
    )
    parser.add_argument(
        "--table",
        default="bindings",
        help=(
            "Tabla SQLite donde se almacenará la información: bindings, "
            "devicetrees (socs y boards en una sola pasada), socs, boards, "
            "sources, schemas (necesita dtschema), macros (necesita sources "
            "ya poblada) o kernel (necesita schemas ya poblada y el checkout "
            "con su historia de git)."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "Vacía la tabla antes de insertar. Sin esta opción, los registros "
            "de ingestas anteriores que ya no se generan permanecen en la base."
        ),
    )
    parser.add_argument(
        "--include-root",
        default="kernel/linux/include",
        help=(
            "Solo para --table macros: raíz -I para cpp, con la que además "
            "de existencia se resuelve el valor de cada macro. Pásalo vacío "
            "(--include-root '') para saltarte la resolución de valores."
        ),
    )
    parser.add_argument(
        "--kernel-repo",
        default="kernel/linux",
        help=(
            "Solo para --table kernel: checkout del kernel *con su historia*, "
            "de donde sale desde qué release existe cada binding."
        ),
    )
    args = parser.parse_args()

    if args.table == "schemas":
        if dtschema_version() is None:
            print(
                "dtschema no está instalado: no se pueden generar los schemas "
                "procesados. Instálalo con «pip install -e '.[ingest]'»."
            )
            return 1
        print(f"Procesando schemas de bindings con dt-schema en: {args.root}")
        count = ingest_schemas(args.root, args.sqlite, args.reset)
        print(f"Procesados {count} schemas.")
        print(f"SQLite actualizado: {args.sqlite} (schemas)")
        return 0

    if args.table == "kernel":
        count = ingest_kernel_versions(args.sqlite, Path(args.kernel_repo))
        print(f"Fechadas {count} bindings con su versión del kernel.")
        print(f"SQLite actualizado: {args.sqlite} (schemas.since)")
        return 0

    if args.table == "macros":
        include_root = args.include_root or None
        count = ingest_macros(args.sqlite, args.reset, include_root)
        print(f"Indexadas {count} macros.")
        print(f"SQLite actualizado: {args.sqlite} (macros)")
        return 0

    if args.table == "devicetrees":
        print(f"Buscando dts/dtsi (socs y boards) en: {args.root}")
        counts = ingest_devicetrees(args.root, args.sqlite, args.reset)
        for table, count in counts.items():
            print(f"Procesados {count} archivos de {table}.")
        print(f"SQLite actualizado: {args.sqlite} (socs + boards)")
        return 0

    source_kind = {
        "bindings": "YAML",
        "sources": "fuentes",
        "socs": "dts/dtsi de SoCs",
        "boards": "dts/dtsi de boards",
    }.get(args.table, "dtsi")
    print(f"Buscando archivos {source_kind} en: {args.root}")

    records = parse_root_directory(args.root, args.table)

    conn = init_sqlite_db(args.sqlite)
    if args.reset:
        clear_table(conn, args.table)
        print(f"Tabla {args.table} vaciada antes de la reingesta.")
    store_records_in_sqlite(conn, records, args.table)
    conn.close()

    print(f"Procesados {len(records)} archivos {source_kind}.")
    print(f"SQLite actualizado: {args.sqlite} ({args.table})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

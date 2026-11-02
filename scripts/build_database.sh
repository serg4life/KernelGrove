#!/usr/bin/env bash
# Rellena database/bindings.db con las tablas `bindings` y `schemas` (YAML del
# kernel; `schemas` son los mismos bindings procesados por dt-schema),
# `socs` y `boards` (ambas de ficheros .dts/.dtsi, distinguidas por
# `classify_devicetree`: un árbol con /cpus/cpu@... es un SoC, uno completo
# ("/dts-v1/;") sin cpus propio es una board), `sources` y `macros`.
#
# Uso:
#   scripts/build_database.sh [--bindings-root DIR] [--socs-root DIR]
#                             [--sqlite FILE] [--kernel-repo DIR]
#
# Por defecto:
#   --bindings-root  kernel/linux/Documentation/devicetree/bindings
#   --socs-root      . (raíz del repo, donde viven p. ej. zynqmp.dtsi y las boards)
#   --sqlite         database/bindings.db
#   --kernel-repo    kernel/linux (checkout *con historia*: de ahí sale desde
#                    qué release del kernel existe cada binding)
#
# Nota: --socs-root recorre el directorio de forma recursiva (para socs,
# boards y sources); si apunta a un checkout completo del kernel puede tardar
# más de lo esperado.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

BINDINGS_ROOT="kernel/linux/Documentation/devicetree/bindings"
SOCS_ROOT="."
SQLITE_DB="database/bindings.db"
KERNEL_REPO="kernel/linux"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bindings-root) BINDINGS_ROOT="$2"; shift 2 ;;
        --socs-root) SOCS_ROOT="$2"; shift 2 ;;
        --sqlite) SQLITE_DB="$2"; shift 2 ;;
        --kernel-repo) KERNEL_REPO="$2"; shift 2 ;;
        *) echo "Argumento desconocido: $1" >&2; exit 1 ;;
    esac
done

if [[ -d ".venv" ]]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

echo "== Ingesta de bindings =="
python -m kernelgrove.db_manager.main \
    --root "$BINDINGS_ROOT" \
    --sqlite "$SQLITE_DB" \
    --table bindings \
    --reset

echo
echo "== Ingesta de schemas de bindings (dt-schema) =="
# Los schemas procesados por dt-schema: es lo que responde qué propiedades
# admite y cuáles exige un compatible. Necesita el paquete `dtschema`
# (pip install -e '.[ingest]'); sin él este paso avisa y se salta, y la
# aplicación sigue funcionando sin la capa 5 del motor semántico.
python -m kernelgrove.db_manager.main \
    --root "$BINDINGS_ROOT" \
    --sqlite "$SQLITE_DB" \
    --table schemas \
    --reset || echo "AVISO: sin tabla schemas (¿falta dtschema?)"

echo
echo "== Ingesta de socs y boards (una sola pasada) =="
# Las dos tablas salen de los mismos ficheros y solo las distingue lo que
# `classify_devicetree` ve dentro, así que se recorren y parsean una vez.
python -m kernelgrove.db_manager.main \
    --root "$SOCS_ROOT" \
    --sqlite "$SQLITE_DB" \
    --table devicetrees \
    --reset

echo
echo "== Ingesta de fuentes (.dts/.dtsi y cabeceras dt-bindings) =="
# El kernel clonado solo se usa aquí: la aplicación instalada abre los ficheros
# desde la base de datos, así que su contenido tiene que quedar almacenado.
python -m kernelgrove.db_manager.main \
    --root "$SOCS_ROOT" \
    --sqlite "$SQLITE_DB" \
    --table sources \
    --reset

echo
echo "== Ingesta del índice de macros (capa 3: existencia y valor de dt-bindings/*.h) =="
# Los nombres salen de la tabla sources ya poblada (no toca el checkout para
# eso); los valores sí necesitan el checkout, vía cpp con --include-root
# (por defecto kernel/linux/include). Sin cpp en el sistema, se queda en
# solo existencia y avisa.
python -m kernelgrove.db_manager.main \
    --sqlite "$SQLITE_DB" \
    --table macros \
    --reset

echo
echo "== Fechando los bindings con su versión del kernel =="
# Desde qué release del kernel existe cada binding. No sale del binding sino
# de la historia del repositorio (`--kernel-repo`, por defecto kernel/linux):
# se lee el árbol de cada release y se anota la primera que lo trae. Sin git
# o sin historia, avisa y los bindings se quedan sin versión.
python -m kernelgrove.db_manager.main \
    --sqlite "$SQLITE_DB" \
    --table kernel \
    --kernel-repo "$KERNEL_REPO"

echo
echo "== Compactando la base =="
# Las reingestas con --reset dejan páginas libres, y `init_sqlite_db` retira
# columnas de esquemas antiguos (`DROP COLUMN` tampoco devuelve el espacio).
# Sin este VACUUM el fichero conserva el tamaño de la versión anterior.
python -c "import sqlite3,sys; sqlite3.connect(sys.argv[1]).execute('VACUUM')" "$SQLITE_DB"

echo
echo "Base de datos actualizada: $SQLITE_DB (bindings + schemas + socs + boards + sources + macros + versiones)"

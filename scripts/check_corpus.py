#!/usr/bin/env python3
"""Contrasta las comprobaciones del motor con los device trees del kernel.

Los ficheros de `kernel/linux/arch/**` se dan por correctos: si una regla
nueva dispara masivamente, o está mal planteada o hay que rebajarla. Este
script es la medida de esa disciplina, tanto para el parser como para las
capas de `dts_engine.checks` (ver `docs/SEMANTIC-ENGINE-FLOW.md`).

    python scripts/check_corpus.py                 # todo el corpus
    python scripts/check_corpus.py --db            # como analiza la aplicación
    python scripts/check_corpus.py --db --schema   # la pasada diferida
    python scripts/check_corpus.py --limit 400     # muestra aleatoria
    python scripts/check_corpus.py --code spec-reg-mismatch --examples 20

Agrupa por código, gravedad y forma del mensaje (los textos entre comillas
angulares se sustituyen por «…»), para que cada regla se pueda mirar aparte.
"""

from __future__ import annotations

import argparse
import collections
import random
import re
import sys
from pathlib import Path
from typing import Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO_ROOT / "kernel" / "linux"

sys.path.insert(0, str(REPO_ROOT / "src"))

from kernelgrove.dts_engine.checks import run_checks  # noqa: E402
from kernelgrove.dts_engine.parser import parse_dts_source  # noqa: E402

_QUOTED = re.compile(r"«[^»]*»")
_DIGITS = re.compile(r"\d+")


def parse_args() -> argparse.Namespace:
    """Lee las opciones de la línea de órdenes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="raíz del checkout del kernel (por defecto kernel/linux)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="analizar solo una muestra aleatoria de N ficheros",
    )
    parser.add_argument(
        "--code",
        default=None,
        help="mostrar solo los diagnósticos de este código",
    )
    parser.add_argument(
        "--examples",
        type=int,
        default=3,
        help="cuántos ejemplos mostrar de cada grupo",
    )
    parser.add_argument(
        "--syntax",
        action="store_true",
        help="medir los diagnósticos de sintaxis del parser en vez de los semánticos",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help=(
            "medir lo que valida el propio schema (valores de la capa 5 y "
            "capa 2 entera), que la aplicación ejecuta aparte en segundo "
            "plano; requiere --db"
        ),
    )
    parser.add_argument(
        "--db",
        type=Path,
        nargs="?",
        const=REPO_ROOT / "database" / "bindings.db",
        default=None,
        help=(
            "analizar como lo hace la aplicación: fusionando los includes con "
            "la base de datos indicada (por defecto database/bindings.db)"
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Analiza el corpus y resume los diagnósticos por regla."""
    args = parse_args()
    if not args.root.exists():
        print(f"No existe {args.root}: hace falta el checkout del kernel.")
        return 1

    files = sorted(args.root.rglob("*.dts")) + sorted(args.root.rglob("*.dtsi"))
    if args.limit:
        random.seed(7)
        files = random.sample(files, min(args.limit, len(files)))

    counts: collections.Counter = collections.Counter()
    files_with: collections.Counter = collections.Counter()
    severities: collections.Counter = collections.Counter()
    samples: Dict[str, List[str]] = collections.defaultdict(list)

    service = None
    if args.db is not None:
        from kernelgrove.api.service import KernelGroveService

        service = KernelGroveService(args.db)

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        if service is not None and not args.syntax:
            # La misma llamada que hace el editor, con la ruta que la base de
            # datos usa como clave para resolver los includes relativos.
            key = path.relative_to(REPO_ROOT).as_posix()
            fragment = path.suffix.lower() == ".dtsi"
            if args.schema:
                diagnostics = service.analyze_schema_checks(
                    text, fragment=fragment, base_path=key
                )
            else:
                _, diagnostics = service.analyze_source(
                    text, fragment=fragment, base_path=key
                )
            # Solo lo semántico: los diagnósticos de sintaxis del parser se
            # miden aparte con --syntax.
            diagnostics = [
                item
                for item in diagnostics
                if item.code.value.startswith(
                    ("spec-", "binding-", "generic-", "macro-")
                )
            ]
        else:
            result = parse_dts_source(text)
            diagnostics = (
                result.diagnostics
                if args.syntax
                else run_checks(
                    result, text=text, fragment=path.suffix.lower() == ".dtsi"
                )
            )

        seen = set()
        for item in diagnostics:
            if args.code and item.code.value != args.code:
                continue
            shape = _DIGITS.sub("N", _QUOTED.sub("«…»", item.message))[:70]
            key = f"{item.code.value}|{item.severity.value}|{shape}"
            counts[key] += 1
            severities[item.severity.value] += 1
            seen.add(key)
            if len(samples[key]) < args.examples:
                samples[key].append(f"{path}:{item.line}  {item.message}")
        for key in seen:
            files_with[key] += 1

    print(f"ficheros analizados: {len(files)}")
    print(f"diagnósticos totales: {sum(counts.values())}")
    print(f"por gravedad: {dict(severities)}\n")

    for key, count in counts.most_common():
        print(f"{count:7d}  ({files_with[key]:5d} ficheros)  {key}")
        for sample in samples[key]:
            print(f"          {sample}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

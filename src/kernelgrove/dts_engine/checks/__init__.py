"""Comprobaciones semánticas organizadas por capas.

Cada capa responde a una fuente distinta de verdad y se aplica en el orden
descrito en `docs/SEMANTIC-ENGINE-FLOW.md`. `pipeline.run_checks` ejecuta las
capas baratas —la 1 (especificación), la 3 (existencia de macros) y la 5
(binding del compatible)— y `pipeline.run_schema_checks` lo que hace el propio
schema —los valores de la capa 5 y la capa 2 entera—, que va aparte porque
cuesta milisegundos por nodo.
"""

from kernelgrove.dts_engine.checks.pipeline import run_checks, run_schema_checks
from kernelgrove.dts_engine.checks.spec import check_spec

__all__ = ["run_checks", "run_schema_checks", "check_spec"]

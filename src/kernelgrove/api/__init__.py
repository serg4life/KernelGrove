"""API de KernelGrove: superficie pública sobre el motor semántico.

La GUI debe importar exclusivamente de este paquete, nunca de `db_manager`,
`dt_model` o `dts_engine` directamente. `KernelGroveService` envuelve el acceso a la
base de datos, la carga de SoCs y la generación del modelo interno; los tipos
del modelo se reexportan aquí para que la interfaz tampoco tenga que
importarlos de su paquete de origen.
"""

from kernelgrove.api.database import BindingsDatabase
from kernelgrove.api.binding_schemas import BindingSchemaLookup
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
from kernelgrove.api.git_repo import (
    FileChange,
    GitError,
    GitMissingError,
    GitRepo,
    RepoStatus,
    Version,
    find_repo,
    git_available,
    init_repo,
)
from kernelgrove.api.includes import IncludeResolver, ResolvedInclude
from kernelgrove.api.overrides import PropertyOverride, apply_overrides, node_span
from kernelgrove.api.compile_overlay import (
    CompileResult,
    compile_source_file,
    decompile_blob,
)
from kernelgrove.api.overlays import (
    NodeAddition,
    OverlayChange,
    OverlayFragment,
    OverlayTarget,
    PropertyEdit,
    build_overlay_source,
    format_value,
    label_index,
    parse_overlay,
)
from kernelgrove.api.selection import (
    PeripheralSlot,
    build_internal_model,
    build_node_from_slot,
    count_connected_devices,
    make_connected_slot,
)
from kernelgrove.api.service import KernelGroveService
from kernelgrove.api.soc_loader import extract_connectable_nodes
from kernelgrove.api.socs_database import SocsDatabase
from kernelgrove.api.toolchain import (
    Toolchain,
    cpp_version,
    detect_toolchain,
    dtc_version,
)
from kernelgrove.dt_model.hardware import extract_hardware
from kernelgrove.api.sources_database import SourcesDatabase, StoredSource
from kernelgrove.dt_model.model import (
    DeviceTreeNode,
    find_by_reference,
    InternalDeviceTreeModel,
    PeripheralNode,
    SoCProfile,
)
from kernelgrove.dts_engine import (
    SPEC_OWNED_PROPERTIES,
    Diagnostic,
    DiagnosticCode,
    IncludeDirective,
    ParseResult,
    Severity,
    find_matching_brace,
)

__all__ = [
    # Servicio
    "KernelGroveService",
    # DTOs
    "SoCSummary",
    "BindingOption",
    "BindingEntry",
    "BindingInfo",
    "BindingSchemaLookup",
    "IntegratedController",
    "SocPackage",
    # Estado de edición
    "PeripheralSlot",
    "PropertySuggestion",
    "make_connected_slot",
    "BuildOutcome",
    "BuildStep",
    "CompileResult",
    "compile_source_file",
    "decompile_blob",
    "NodeAddition",
    "OverlayChange",
    "OverlayFragment",
    "OverlayTarget",
    "PropertyEdit",
    "Toolchain",
    "detect_toolchain",
    "extract_hardware",
    "cpp_version",
    "dtc_version",
    "build_overlay_source",
    "format_value",
    "label_index",
    "parse_overlay",
    "build_internal_model",
    "build_node_from_slot",
    "count_connected_devices",
    # Control de versiones (git)
    "GitRepo",
    "GitError",
    "GitMissingError",
    "FileChange",
    "RepoStatus",
    "Version",
    "find_repo",
    "init_repo",
    "git_available",
    # Carga de SoCs
    "extract_connectable_nodes",
    # Acceso directo a la base de datos (uso avanzado)
    "BindingsDatabase",
    "SocsDatabase",
    "SourcesDatabase",
    "StoredSource",
    # Modelo interno reexportado
    "DeviceTreeNode",
    "find_by_reference",
    "PeripheralNode",
    "SoCProfile",
    "InternalDeviceTreeModel",
    # Motor semántico reexportado
    "Diagnostic",
    "DiagnosticCode",
    "Severity",
    "SPEC_OWNED_PROPERTIES",
    "ParseResult",
    "IncludeDirective",
    "ResolvedInclude",
    "IncludeResolver",
    "find_matching_brace",
    "PropertyOverride",
    "apply_overrides",
    "node_span",
]

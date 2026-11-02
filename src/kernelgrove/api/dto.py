"""Objetos de transferencia que la API expone hacia la GUI.

Son estructuras planas y sin lógica: permiten que la interfaz muestre datos
sin conocer el esquema de la base de datos ni las tuplas que devuelve SQLite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:  # pragma: no cover - solo para las anotaciones
    from kernelgrove.dts_engine import Diagnostic


@dataclass(frozen=True)
class SoCSummary:
    """Entrada de la tabla `socs` tal y como se lista en el selector de SoC."""

    name: str
    compatible: str
    vendor: Optional[str] = None
    file_path: Optional[str] = None
    # Qué hardware describe, tal y como lo dice su device tree
    # (`db_manager.records.extract_hardware`). Todo opcional: un `.dtsi` que
    # no declara sus cpus deja `arch` y `cores` vacíos, y decirlo es más
    # honesto que rellenarlo con un valor plausible.
    arch: Optional[str] = None
    cores: Optional[int] = None
    ram: Optional[int] = None  # bytes
    clock: Optional[int] = None  # Hz
    model: Optional[str] = None

    @property
    def label(self) -> str:
        """Texto mostrado en el desplegable: nombre y compatible del SoC."""
        return f"{self.name} ({self.compatible})"

    @property
    def ram_label(self) -> str:
        """RAM en la unidad que toque, o «—» si el árbol no la declara."""
        if not self.ram:
            return "—"
        for unidad, factor in (("GB", 1 << 30), ("MB", 1 << 20)):
            if self.ram >= factor:
                cantidad = self.ram / factor
                entero = int(cantidad)
                if cantidad == entero:
                    return f"{entero} {unidad}"
                return f"{cantidad:.1f} {unidad}"
        return f"{self.ram} B"

    @property
    def clock_label(self) -> str:
        """Frecuencia en MHz o GHz, o «—»."""
        if not self.clock:
            return "—"
        if self.clock >= 1_000_000_000:
            return f"{self.clock / 1_000_000_000:.2f} GHz".replace(".00 ", " ")
        return f"{round(self.clock / 1_000_000)} MHz"

    @property
    def cores_label(self) -> str:
        """Número de núcleos, o «—»."""
        return str(self.cores) if self.cores else "—"


@dataclass(frozen=True)
class BindingOption:
    """Binding candidato a conectarse en un slot de bus."""

    compatible: str
    title: Optional[str] = None
    child_bus: Optional[str] = None
    # Subsistema del binding (i2c, spi, usb, media...), tal como lo deriva
    # `db_manager/storage.py` de la ruta del fichero. Lo usa la paleta del
    # visualizador para agrupar los dispositivos ofrecidos.
    subsystem: Optional[str] = None

    @property
    def is_controller(self) -> bool:
        """Indica si el dispositivo ofrece a su vez un bus (p. ej. un mux I2C)."""
        return bool(self.child_bus)

    @property
    def label(self) -> str:
        """Texto mostrado en el desplegable de dispositivos.

        Los que además son controladores se marcan, porque al conectarlos
        aparecerá un nuevo desplegable para colgarles más nodos.
        """
        text = f"{self.compatible} — {self.title}" if self.title else self.compatible
        if self.child_bus:
            text = f"{text}  [bus {self.child_bus}]"
        return text


@dataclass(frozen=True)
class BindingInfo:
    """Ficha completa de un binding, tal y como la guarda la tabla `bindings`."""

    compatible: str
    vendor: Optional[str] = None
    title: Optional[str] = None
    # Prosa del binding: lo que el YAML explica del dispositivo.
    description: Optional[str] = None
    subsystem: Optional[str] = None
    parent_bus: Optional[str] = None
    child_bus: Optional[str] = None

    @property
    def is_controller(self) -> bool:
        """Indica si el binding expone un bus hijo y admite periféricos."""
        return bool(self.child_bus)


@dataclass(frozen=True)
class IntegratedController:
    """Controlador que el SoC integra de fábrica, con estado editable.

    No es un bus conectable -eso ya lo cubre `PeripheralNode`/`BindingOption`-,
    sino cualquier nodo con `status` propio (encendido o apagado en el
    propio silicio): un UART, el controlador Ethernet, una PWM… Solo se
    dibuja en el grafo si además tiene algo conectado (ver
    `tree_graph.build_graph`); si no, su único rastro visible es esta ficha,
    que alimenta el panel de propiedades del SoC.
    """

    path: str
    label: Optional[str]
    compatible: str
    status: str

    @property
    def enabled(self) -> bool:
        """Indica si `status` vale "okay" (comillas de DTS incluidas)."""
        return self.status.strip('"') == "okay"


@dataclass(frozen=True)
class SocPackage:
    """Lo que queda empaquetado dentro del nodo SoC del visualizador.

    Alimenta el panel de propiedades que se abre al hacer doble clic en el
    círculo central: identidad del SoC y el estado de cada controlador
    integrado. Editar ese estado no cuelga un nodo nuevo del SoC -es una
    modificación de comportamiento sobre lo que ya está empaquetado dentro-.

    `name` y `vendor` son del SoC, no de la placa: `model`/`compatible` en
    la raíz del árbol fusionado suelen ser los de la placa (p. ej. "Raspberry
    Pi 4 Model B"), así que se derivan del compatible propio del SoC -"Zynq"
    a partir de "xlnx,zynq-7000"-, no de la raíz.
    """

    name: Optional[str]
    vendor: Optional[str]
    controllers: List[IntegratedController]


@dataclass(frozen=True)
class PropertySuggestion:
    """Una propiedad que el binding de un compatible admite.

    Es lo que necesita el autocompletado del editor: cómo se llama, si es
    obligatoria, de qué tipo es y qué valores admite. Sale de los schemas
    procesados por dt-schema con la herencia (`allOf`/`$ref`) ya resuelta,
    así que incluye tanto lo que declara el binding como lo que hereda de la
    clase de dispositivo y del bus.
    """

    name: str
    required: bool = False
    # Tipo de device tree según dt-schema: 'uint32', 'string-array',
    # 'phandle-array'... None cuando la propiedad aparece con tipos
    # distintos en bindings distintos y no se puede afirmar ninguno.
    dt_type: Optional[str] = None
    description: Optional[str] = None
    # Schema del que procede: el binding mismo o el `$ref` que lo aporta.
    origin: Optional[str] = None
    # Valores admitidos, si el binding los enumera (`enum`/`const`).
    allowed_values: List[str] = field(default_factory=list)
    # Lo demás que el binding acota sin llegar a enumerar: rango del valor
    # (`minimum`/`maximum`), cuántas entradas admite (`minItems`/`maxItems`),
    # el patrón que ha de cumplir y su valor por defecto. Van como dato y no
    # como frase hecha porque la frase la escribe la interfaz, que es la que
    # está traducida.
    constraints: Dict[str, object] = field(default_factory=dict)
    # Desde qué versión del kernel existe el binding que aporta la
    # propiedad. Sale de la historia del repositorio, no del propio binding
    # (`db_manager/kernel_versions.py`); `None` cuando la base se construyó
    # sin ella o el schema no es del kernel.
    since: Optional[str] = None
    # La entrada describe un nodo hijo, no una propiedad.
    is_node: bool = False

    @property
    def label(self) -> str:
        """Texto de una línea para la lista de sugerencias."""
        marks = []
        if self.required:
            marks.append("required")
        if self.dt_type:
            marks.append(self.dt_type)
        return f"{self.name} ({', '.join(marks)})" if marks else self.name


@dataclass(frozen=True)
class BuildStep:
    """Un paso de una compilación: qué se hizo con qué fichero y cómo fue.

    Un paso y no una línea de texto: quien lo enseña es la interfaz, que es
    la que está traducida, y quien decide qué glifo lleva cada veredicto.
    `messages` es lo que dijeron `cpp` y `dtc` tal cual —incluida la orden
    con la que se les llamó—, que es lo que hay que leer cuando el
    resultado no es el esperado.
    """

    kind: str  # "check" | "compile"
    path: Path
    ok: bool
    messages: List[str] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    diagnostics: List["Diagnostic"] = field(default_factory=list)
    output: Optional[Path] = None


@dataclass(frozen=True)
class BuildOutcome:
    """Cómo terminó una compilación completa, con todos sus pasos."""

    ok: bool
    steps: List[BuildStep] = field(default_factory=list)

    @property
    def outputs(self) -> List[Path]:
        """Los binarios que se han llegado a escribir."""
        return [step.output for step in self.steps if step.output is not None]


@dataclass(frozen=True)
class BindingEntry:
    """Un compatible documentado, tal y como se lista en el catálogo."""

    compatible: str
    title: str = ""
    subsystem: str = ""
    # Compatible primario del binding que lo documenta: dos entradas con el
    # mismo aquí salen del mismo fichero.
    binding: str = ""
    # La prosa del binding, ya en una línea: el catálogo la enseña elidida
    # en la ficha y un texto de varios párrafos no cabe en una línea.
    description: str = ""

    @property
    def vendor(self) -> str:
        """Fabricante según el propio compatible, no según el binding.

        `aeroflexgaisler,i2cmst` lo documenta un binding cuyo primer
        compatible es de otro fabricante, así que leer el vendedor de la
        fila del binding decía «sifive» de un compatible de Aeroflex
        Gaisler. El prefijo del compatible es el dato, y está delante.
        """
        return self.compatible.split(",", 1)[0] if "," in self.compatible else ""

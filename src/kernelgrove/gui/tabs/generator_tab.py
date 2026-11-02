"""Pestaña generadora: conectar dispositivos a los controladores del SoC.

No elige el device tree: eso ocurre en la barra de SoC de la ventana, que es
común a todas las pestañas. Aquí solo se recibe el perfil ya analizado
(`load_profile`) y se configura qué se conecta a cada bus.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSplitter,
    QTabWidget,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import (
    BindingOption,
    KernelGroveService,
    InternalDeviceTreeModel,
    PeripheralSlot,
    SoCProfile,
)
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.models.tree_model import COLUMN_CONNECT, PeripheralTreeModel
from kernelgrove.gui.widgets.binding_delegate import BindingDelegate
from kernelgrove.gui.widgets.details_panel import DetailsPanel
from kernelgrove.gui.widgets.dts_editor import DtsEditor
from kernelgrove.gui.widgets.json_view import JsonView
from kernelgrove.gui.workers import BindingOptionsWorker


class GeneratorTab(Retranslates, QWidget):
    """Árbol de controladores del SoC con sus dispositivos conectables."""

    status_changed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(
        self, service: KernelGroveService, tree_model: PeripheralTreeModel, parent=None
    ):
        """Monta la pestaña, que espera recibir un perfil ya analizado.

        `tree_model` llega inyectado desde `MainWindow`, que lo comparte con
        `VisualizerTab`: conectar un dispositivo arrastrando en el grafo debe
        verse aquí también, y viceversa — mismo motor, dos interfaces.
        """
        super().__init__(parent)
        self.service = service

        self.soc_profile: Optional[SoCProfile] = None
        self.source_text: str = ""
        self.internal_model: Optional[InternalDeviceTreeModel] = None
        self._options_cache: Dict[str, List[BindingOption]] = {}
        self._options_worker: Optional[BindingOptionsWorker] = None

        self.tree_model = tree_model
        self.tree_model.slotStateChanged.connect(self.refresh_internal_model)

        self._build_ui()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        """Monta la cabecera del SoC en curso y el árbol de controladores."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QHBoxLayout()
        bar.setContentsMargins(12, 7, 12, 7)
        bar.setSpacing(8)
        self.soc_label = QLabel()
        self.soc_label.setStyleSheet("font-weight: 600;")
        bar.addWidget(self.soc_label)
        bar.addStretch(1)

        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)
        bar.addWidget(self.filter_edit, 2)

        toolbar = QWidget()
        toolbar.setObjectName("viewToolbar")
        toolbar.setLayout(bar)
        layout.addWidget(toolbar)
        layout.addWidget(self._build_splitter(), 1)
        self.retranslate()

    def retranslate(self) -> None:
        """Rehace los textos fijos y la cabecera del SoC (ver `Retranslates`).

        La cabecera («zynqmp — 7 controladores») se recompone a partir del
        perfil cargado; sin perfil vuelve al texto de "nada cargado".
        """
        self.filter_edit.setPlaceholderText(self.tr("Filter controllers…"))
        self.fragment_view.setPlaceholderText(
            self.tr("Load a SoC in the generator to see the full DTS.")
        )
        self._output_tabs.setTabText(0, self.tr("Internal model (JSON)"))
        self._output_tabs.setTabText(1, self.tr("Full DTS"))
        self._output_tabs.setTabText(2, self.tr("Details"))
        if self.soc_profile is None:
            self.soc_label.setText(self.tr("No device tree loaded"))
        else:
            self.soc_label.setText(
                self.tr("{name} — {count} controllers").format(
                    name=self.soc_profile.soc_name,
                    count=len(self.soc_profile.peripherals),
                )
            )

    def _build_splitter(self) -> QSplitter:
        """Divisor con el árbol de controladores y los paneles de salida."""
        splitter = QSplitter(Qt.Horizontal)

        self.tree_view = QTreeView()
        self.tree_view.setModel(self.tree_model)
        self.tree_view.setUniformRowHeights(True)
        self.tree_view.setEditTriggers(
            QTreeView.DoubleClicked
            | QTreeView.SelectedClicked
            | QTreeView.EditKeyPressed
        )
        self.tree_view.setSelectionBehavior(QTreeView.SelectRows)
        self.tree_view.setItemDelegateForColumn(
            COLUMN_CONNECT, BindingDelegate(self._options_for_slot, self.tree_view)
        )
        self.tree_view.selectionModel().selectionChanged.connect(
            self._on_selection_changed
        )
        splitter.addWidget(self.tree_view)

        right = QTabWidget()
        self.json_view = JsonView()
        self.fragment_view = DtsEditor()
        self.fragment_view.setReadOnly(True)
        self.details_panel = DetailsPanel(self.service)
        self._output_tabs = right
        right.addTab(self.json_view, "")
        right.addTab(self.fragment_view, "")
        right.addTab(self.details_panel, "")
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        return splitter

    def load_profile(self, profile: SoCProfile, source_text: str = "") -> None:
        """Muestra el `SoCProfile` que llega del editor.

        `source_text` es el documento del editor tal cual, usado como base
        del DTS completo que se muestra en la pestaña "DTS completo".
        """
        self.soc_label.setText(
            self.tr("{name} — {count} controllers").format(
                name=profile.soc_name, count=len(profile.peripherals)
            )
        )
        self.soc_profile = profile
        self.source_text = source_text
        self.tree_model.set_root_slots(self.service.create_slots(profile))
        self.tree_view.expandToDepth(0)
        for column in range(self.tree_model.columnCount()):
            self.tree_view.resizeColumnToContents(column)
        self.tree_view.setColumnWidth(COLUMN_CONNECT, 200)

        self._prefetch_options()
        self.refresh_internal_model()

    # ------------------------------------------------------------------
    # Opciones de conexión
    # ------------------------------------------------------------------
    def _prefetch_options(self) -> None:
        """Precarga en segundo plano los dispositivos de cada bus del SoC."""
        buses = sorted(
            {
                slot.child_bus
                for slot in self.tree_model.root_slots()
                if slot.child_bus and slot.child_bus not in self._options_cache
            }
        )
        if not buses:
            return

        if self._options_worker is not None and self._options_worker.isRunning():
            self._options_worker.requestInterruption()

        self._options_worker = BindingOptionsWorker(self.service, buses, self)
        self._options_worker.options_ready.connect(self._on_options_ready)
        self._options_worker.start()

    def _on_options_ready(self, bus: str, options: List[BindingOption]) -> None:
        """Guarda en caché los dispositivos conectables de un bus."""
        self._options_cache[bus] = options

    def _options_for_slot(self, slot: Optional[PeripheralSlot]) -> List[BindingOption]:
        """Devuelve lo que se puede conectar a `slot`.

        Normalmente son los dispositivos del bus que ofrece; si el slot es un
        dispositivo con funciones propias (un MFD), lo que se ofrece son esas
        funciones, que no cuelgan de ningún bus.
        """
        if slot is None:
            return []

        if slot.subdevice_parent:
            key = f"subdevices:{slot.subdevice_parent}"
            if key not in self._options_cache:
                self._options_cache[key] = self.service.list_subdevices(
                    slot.subdevice_parent
                )
            return self._options_cache[key]

        if not slot.child_bus:
            return []
        bus = slot.child_bus
        if bus not in self._options_cache:
            self._options_cache[bus] = self.service.list_connectable_bindings(bus)
        return self._options_cache[bus]

    # ------------------------------------------------------------------
    # Interacción
    # ------------------------------------------------------------------
    def _apply_filter(self, needle: str) -> None:
        """Oculta los controladores que no casan con el texto del filtro."""
        needle = needle.strip().lower()
        for row, slot in enumerate(self.tree_model.root_slots()):
            haystack = " ".join(
                filter(
                    None,
                    [
                        slot.node_name,
                        slot.display_name,
                        slot.child_bus,
                        slot.descriptor.subsystem,
                        " ".join(slot.descriptor.compatibles),
                    ],
                )
            ).lower()
            self.tree_view.setRowHidden(row, QModelIndex(), needle not in haystack)

    def _on_selection_changed(self) -> None:
        """Actualiza el panel de detalles con el nodo seleccionado."""
        indexes = self.tree_view.selectionModel().selectedIndexes()
        if not indexes:
            self.details_panel.show_slot(None)
            return
        self.details_panel.show_slot(self.tree_model.slot_from_index(indexes[0]))

    def disconnect_selected(self) -> None:
        """Desconecta del controlador el dispositivo seleccionado."""
        indexes = self.tree_view.selectionModel().selectedIndexes()
        if not indexes:
            return

        index = indexes[0]
        slot = self.tree_model.slot_from_index(index)
        if slot is None or slot.is_root:
            self.status_changed.emit(
                self.tr("Select a connected device to disconnect it")
            )
            return
        self.tree_model.remove_slot(index)

    def refresh_internal_model(self) -> None:
        """Regenera el modelo interno y el DTS completo, y los vuelca a sus paneles."""
        if self.soc_profile is None:
            return

        root_slots = self.tree_model.root_slots()
        self.internal_model = self.service.build_model(self.soc_profile, root_slots)
        self.json_view.set_payload(self.internal_model.to_dict())

        full_dts = self.service.generate_dts_fragment(root_slots, self.source_text)
        self.fragment_view.setPlainText(full_dts)
        self.fragment_view.set_added_lines(self._generated_line_range(full_dts))

        connected = self.service.count_connected(self.tree_model.root_slots())
        self.status_changed.emit(
            self.tr("{name}: {controllers} controllers, {connected} devices connected")
            .format(
                name=self.soc_profile.soc_name,
                controllers=len(self.soc_profile.peripherals),
                connected=connected,
            )
        )

    def _generated_line_range(self, full_dts: str) -> range:
        """Líneas 1-based de `full_dts` que vienen del generador, no del SoC original.

        `generate_dts_fragment` pega el fragmento tras `source_text.rstrip("\\n")
        + "\\n\\n"`: esa separación en blanco ocupa siempre exactamente una
        línea, así que el fragmento empieza dos líneas después de la última
        del original. Sin `source_text` no hay nada que diferenciar (todo el
        texto es el fragmento suelto), y sin nada conectado no hay líneas
        nuevas que resaltar.
        """
        if not self.source_text or not full_dts:
            return range(0)
        base_lines = len(self.source_text.rstrip("\n").splitlines())
        start = base_lines + 2
        total_lines = self.fragment_view.document().blockCount()
        return range(start, total_lines + 1) if start <= total_lines else range(0)

    def stop_workers(self) -> None:
        """Detiene los hilos en curso (al cerrar la ventana)."""
        for worker in (self._options_worker,):
            if worker is not None and worker.isRunning():
                worker.requestInterruption()
                worker.quit()
                worker.wait(2000)

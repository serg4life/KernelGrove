"""Panel lateral con la ficha del nodo seleccionado.

Consulta los datos que la base de datos ya conoce del binding (vendor, título,
subsistema, buses) a través del servicio de la API.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import KernelGroveService, PeripheralSlot
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates


class DetailsPanel(Retranslates, QWidget):
    """Ficha de solo lectura del slot seleccionado, enriquecida con datos de la DB."""

    def __init__(self, service: KernelGroveService, parent=None):
        """Monta el formulario de campos y guarda el servicio de consulta."""
        super().__init__(parent)
        self._service = service

        self._title = QLabel(self.tr("No node selected"))
        self._title.setWordWrap(True)
        self._title.setObjectName("inspectorTitle")

        self._kind = QLabel("")
        self._kind.setStyleSheet(f"color: {style.MUTED_TEXT_COLOR};")

        separator = QFrame()
        separator.setFrameShape(QFrame.HLine)
        separator.setFrameShadow(QFrame.Sunken)

        self._fields = {
            "node": QLabel("—"),
            "path": QLabel("—"),
            "compatibles": QLabel("—"),
            "vendor": QLabel("—"),
            "titulo": QLabel("—"),
            "descripcion": QLabel("—"),
            "subsystem": QLabel("—"),
            "parent_bus": QLabel("—"),
            "child_bus": QLabel("—"),
        }
        for label in self._fields.values():
            label.setWordWrap(True)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        # Las etiquetas de la izquierda se añaden vacías y las pone
        # `retranslate`, que es también quien las rehace al cambiar de
        # idioma: se llegan a través de `labelForField`, sin guardar una
        # segunda lista de widgets en paralelo.
        self._form = QFormLayout()
        self._form.setLabelAlignment(Qt.AlignRight | Qt.AlignTop)
        self._form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for field in self._fields.values():
            self._form.addRow("", field)
        form = self._form

        # Último slot mostrado: `retranslate` lo vuelve a pintar, porque su
        # texto («Controlador · ofrece bus i2c») también está traducido.
        self._slot: Optional[PeripheralSlot] = None
        self.retranslate()

        layout = QVBoxLayout(self)
        layout.addWidget(self._title)
        layout.addWidget(self._kind)
        layout.addWidget(separator)
        layout.addLayout(form)
        layout.addStretch(1)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

    def retranslate(self) -> None:
        """Rehace las etiquetas fijas y repinta el slot (ver `Retranslates`)."""
        for key, text in {
            "node": self.tr("Node:"),
            "path": self.tr("DT path:"),
            "compatibles": self.tr("Compatibles:"),
            "vendor": self.tr("Vendor:"),
            "titulo": self.tr("Title:"),
            "descripcion": self.tr("Description:"),
            "subsystem": self.tr("Subsystem:"),
            "parent_bus": self.tr("Parent bus:"),
            "child_bus": self.tr("Bus offered:"),
        }.items():
            label = self._form.labelForField(self._fields[key])
            if label is not None:
                label.setText(text)
        self.show_slot(self._slot)

    def show_slot(self, slot: Optional[PeripheralSlot]) -> None:
        """Rellena la ficha con los datos del slot, o la vacía si no hay ninguno."""
        self._slot = slot
        if slot is None:
            self._title.setText(self.tr("No node selected"))
            self._kind.setText("")
            for label in self._fields.values():
                label.setText("—")
            return

        descriptor = slot.descriptor
        self._title.setText(slot.display_name)
        self._kind.setText(
            self.tr("Controller · offers bus {bus}").format(bus=slot.child_bus)
            if slot.is_bus
            else self.tr("Device connected to {bus}").format(
                bus=descriptor.parent_bus or "—"
            )
        )
        self._fields["node"].setText(slot.node_name)
        self._fields["path"].setText(descriptor.path or "—")
        self._fields["compatibles"].setText(", ".join(descriptor.compatibles) or "—")
        self._fields["subsystem"].setText(descriptor.subsystem or "—")
        self._fields["child_bus"].setText(descriptor.child_bus or "—")
        self._fields["parent_bus"].setText(descriptor.parent_bus or "—")

        primary = descriptor.compatibles[0] if descriptor.compatibles else None
        if not primary:
            self._fields["vendor"].setText("—")
            self._fields["titulo"].setText("—")
            self._fields["descripcion"].setText("—")
            return

        info = self._service.get_binding_info(primary)
        self._fields["vendor"].setText(info.vendor or "—")
        self._fields["titulo"].setText(info.title or "—")
        # La descripción es la prosa del binding; se recorta porque algunas
        # ocupan párrafos enteros y este panel es una ficha, no un manual.
        description = (info.description or "").strip().replace("\n", " ")
        if len(description) > 400:
            description = f"{description[:400]}…"
        self._fields["descripcion"].setText(description or "—")
        if not descriptor.subsystem and info.subsystem:
            self._fields["subsystem"].setText(info.subsystem)
        if not descriptor.parent_bus and info.parent_bus:
            self._fields["parent_bus"].setText(info.parent_bus)

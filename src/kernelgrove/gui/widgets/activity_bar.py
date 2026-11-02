"""Franja de iconos a la izquierda del todo, para elegir qué panel lateral ver.

Como la "Activity Bar" de VS Code: una columna estrecha de botones
exclusivos entre sí, cada uno asociado a una sección (su título e índice en
el `QStackedWidget` que `MainWindow` muestra a su lado). No sabe nada del
contenido de cada sección — solo qué botón está activo y avisa cuando
cambia.
"""

from __future__ import annotations

from typing import List, NamedTuple

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QButtonGroup, QToolButton, QVBoxLayout, QWidget

from kernelgrove.gui import style

# El botón y la caja del icono. Los dibuja `widgets/icons.py` a
# `style.ACTIVITY_ICON_SIZE`, así que este es el hueco donde caben: dejarlo
# más pequeño que el icono lo escala hacia abajo y le come el trazo.
ICON_SIZE = style.ACTIVITY_ICON_SIZE
BUTTON_SIZE = style.ACTIVITY_BAR_WIDTH


class ActivitySection(NamedTuple):
    """Una entrada de la barra: título del panel, icono y tooltip."""

    title: str
    icon: QIcon
    tooltip: str


class ActivityBar(QWidget):
    """Columna de botones exclusivos; emite el índice de la sección elegida."""

    sectionChanged = Signal(int)

    def __init__(self, sections: List[ActivitySection], parent=None):
        """Monta un botón por sección, el primero activo de entrada."""
        super().__init__(parent)
        self.setObjectName("activityBar")
        # Una subclase de QWidget no pinta el fondo ni el borde que le
        # da la hoja de estilos si no se le pide: sin esto la franja
        # salía del color de su padre y se fundía con el panel de al
        # lado, que es justo lo que la línea de zona tiene que separar.
        self.setAttribute(Qt.WA_StyledBackground, True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(2)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        for index, section in enumerate(sections):
            button = QToolButton()
            button.setObjectName("activityBarButton")
            button.setIcon(section.icon)
            button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            button.setFixedSize(BUTTON_SIZE, BUTTON_SIZE)
            button.setCheckable(True)
            # Solo llevan icono: sin nombre accesible, un lector de pantalla
            # anuncia «botón» y nada más. El tooltip no lo sustituye. Los
            # textos los pone `set_sections`, que es también por donde entran
            # al cambiar de idioma.
            self._group.addButton(button, index)
            button.setCursor(Qt.PointingHandCursor)
            layout.addWidget(button)

        layout.addStretch(1)
        self.set_sections(sections)
        if sections:
            self._group.button(0).setChecked(True)
        self._group.idClicked.connect(self.sectionChanged)

    def set_sections(self, sections: List[ActivitySection]) -> None:
        """Fija título y ayuda de cada botón; los traduce quien los construye.

        La barra no traduce nada por su cuenta —no sabe qué secciones hay—,
        así que `MainWindow` le vuelve a pasar la lista, ya traducida, cuando
        cambia el idioma.
        """
        for index, section in enumerate(sections):
            button = self._group.button(index)
            if button is None:
                continue
            button.setToolTip(section.tooltip)
            button.setAccessibleName(section.title)
            button.setAccessibleDescription(section.tooltip)

    def set_section_action(self, index: int) -> None:
        """Convierte una sección en un **botón de acción**, sin quedarse fijo.

        Casi todas las secciones son pestañas: una está marcada y su panel es
        el que se ve. El catálogo no: abre una ventana flotante que se queda
        junto al editor, así que dejar su icono marcado diría que estás en
        una sección que no ocupa nada. Sin `checkable` no entra en la
        exclusividad del grupo, la que estuviera marcada se queda marcada, y
        `idClicked` sigue avisando de la pulsación, que es lo único que hace
        falta.
        """
        button = self._group.button(index)
        if button is not None:
            button.setCheckable(False)

    def set_section_visible(self, index: int, visible: bool) -> None:
        """Esconde (o devuelve) el botón de una sección.

        Esconder en vez de no montarla: los índices de sección son la clave
        de media ventana —qué vista central abre cada una, sus atajos, el
        panel que le toca—, y quitar una del medio los correría todos.
        """
        button = self._group.button(index)
        if button is not None:
            button.setVisible(visible)

    def show_section(self, index: int) -> None:
        """Marca una sección desde fuera (p. ej. al abrir otra carpeta).

        `idClicked` solo se emite al pulsar, así que la señal se reenvía a
        mano: quien la escuche tiene que enterarse igual de que el panel
        visible ha cambiado.
        """
        button = self._group.button(index)
        if button is None:
            return
        # Una sección de acción (ver `set_section_action`) no se marca: pedir
        # que se enseñe es pedir que se ejecute, y eso es lo que dice la
        # señal.
        if not button.isCheckable():
            self.sectionChanged.emit(index)
            return
        if button.isChecked():
            return
        button.setChecked(True)
        self.sectionChanged.emit(index)

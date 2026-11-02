"""Barra flotante de búsqueda de texto, al estilo Ctrl+F de VS Code.

Como con el autocompletado de `DtsEditor`, este widget solo sabe mostrar el
campo, los botones de navegación y el contador de coincidencias: quien lo usa
(`DtsEditor`) es quien busca en el texto, decide qué resaltar y mueve el
cursor. Aquí no hay lógica de búsqueda, solo la mecánica de la propia barra.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QToolButton,
)

from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates

from kernelgrove.gui.widgets.tab_close_button import TabCloseButton


class _FindLineEdit(QLineEdit):
    """Campo de texto que distingue Intro de Mayús+Intro, y sale con Esc.

    `QLineEdit.returnPressed` no distingue el estado de Mayús, y ese es
    justo el gesto habitual para "ir hacia atrás" en un buscador de editor.
    """

    findNext = Signal()
    findPrevious = Signal()
    closed = Signal()

    def keyPressEvent(self, event) -> None:
        """Intro/Mayús+Intro navegan; Esc cierra la barra sin perder el texto."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                self.findPrevious.emit()
            else:
                self.findNext.emit()
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.closed.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class FindBar(Retranslates, QFrame):
    """Barra de búsqueda: campo, contador de coincidencias, navegación y cierre."""

    # Texto de búsqueda, en cada pulsación.
    queryChanged = Signal(str)
    findNext = Signal()
    findPrevious = Signal()
    closed = Signal()

    def retranslate(self) -> None:
        """Rehace los textos fijos al cambiar de idioma (ver `Retranslates`)."""
        self._input.setPlaceholderText(self.tr("Find…"))
        self._previous_button.setToolTip(self.tr("Previous match (Shift+Enter)"))
        self._next_button.setToolTip(self.tr("Next match (Enter)"))

    def __init__(self, parent=None):
        """Monta el campo, el contador y los botones, oculta hasta que se abra."""
        super().__init__(parent)
        self.setObjectName("findBar")
        self.setFrameShape(QFrame.StyledPanel)

        self._input = _FindLineEdit(self)
        self._input.setClearButtonEnabled(True)
        self._input.textChanged.connect(self.queryChanged)
        self._input.findNext.connect(self.findNext)
        self._input.findPrevious.connect(self.findPrevious)
        self._input.closed.connect(self.closed)

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {style.MUTED_TEXT_COLOR};")
        self._count_label.setMinimumWidth(style.FIND_BAR_COUNT_LABEL_MIN_WIDTH)

        self._previous_button = QToolButton()
        self._previous_button.setText("↑")
        self._previous_button.clicked.connect(self.findPrevious)
        previous_button = self._previous_button

        self._next_button = QToolButton()
        self._next_button.setText("↓")
        self._next_button.clicked.connect(self.findNext)
        next_button = self._next_button

        self.retranslate()

        close_button = TabCloseButton(self)
        close_button.clicked.connect(self.closed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        layout.addWidget(self._input, 1)
        layout.addWidget(self._count_label)
        layout.addWidget(previous_button)
        layout.addWidget(next_button)
        layout.addWidget(close_button)

        self.hide()

    def open(self, initial_text: Optional[str] = None) -> None:
        """Muestra la barra y enfoca el campo, listo para sustituir lo escrito.

        `initial_text` solo se aplica si se da (p. ej. la selección actual del
        editor); si no, se conserva la última búsqueda para poder repetirla o
        afinarla sin volver a escribirla.
        """
        if initial_text is not None:
            self._input.setText(initial_text)
        self.show()
        self.raise_()
        self._input.setFocus()
        self._input.selectAll()

    def current_text(self) -> str:
        """Texto de búsqueda actualmente escrito."""
        return self._input.text()

    def set_match_label(self, text: str) -> None:
        """Actualiza el contador de coincidencias ("3/12", "Sin resultados"…)."""
        self._count_label.setText(text)

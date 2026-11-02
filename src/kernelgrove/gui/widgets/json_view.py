"""Panel de previsualización del modelo interno serializado a JSON."""

from __future__ import annotations

import json
from typing import Any, Dict

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget

from kernelgrove.gui import style
from kernelgrove.gui.widgets.regex_highlighter import RegexHighlighter


class JsonHighlighter(RegexHighlighter):
    """Colorea claves, cadenas, números y literales de un documento JSON."""

    def __init__(self, document: QTextDocument):
        """Prepara las reglas de resaltado (patrón -> formato de color)."""
        super().__init__(document)

        key_format = QTextCharFormat()
        key_format.setForeground(QColor(style.JSON_KEY_COLOR))

        string_format = QTextCharFormat()
        string_format.setForeground(QColor(style.JSON_STRING_COLOR))

        number_format = QTextCharFormat()
        number_format.setForeground(QColor(style.JSON_NUMBER_COLOR))

        literal_format = QTextCharFormat()
        literal_format.setForeground(QColor(style.JSON_LITERAL_COLOR))

        self._rules = [
            (QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"(?=\s*:)'), key_format),
            (QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"(?!\s*:)'), string_format),
            (QRegularExpression(r"\b-?\d+(\.\d+)?([eE][+-]?\d+)?\b"), number_format),
            (QRegularExpression(r"\b(true|false|null)\b"), literal_format),
        ]


class JsonView(QWidget):
    """Editor de solo lectura que muestra el modelo interno como JSON coloreado."""

    def __init__(self, parent=None):
        """Monta el área de texto monoespaciada con su resaltador."""
        super().__init__(parent)

        self.editor = QPlainTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor.setFont(QFont("monospace", 10))
        self.editor.setPlaceholderText(
            self.tr(
                "Pick a SoC and enable peripherals to see the internal model."
            )
        )
        self._highlighter = JsonHighlighter(self.editor.document())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.editor)

    def set_payload(self, payload: Dict[str, Any]) -> None:
        """Serializa `payload` a JSON indentado conservando la posición de scroll."""
        scrollbar = self.editor.verticalScrollBar()
        previous = scrollbar.value()
        self.editor.setPlainText(json.dumps(payload, indent=2, ensure_ascii=False))
        scrollbar.setValue(min(previous, scrollbar.maximum()))

    def text(self) -> str:
        """Devuelve el JSON actualmente mostrado."""
        return self.editor.toPlainText()

    def clear(self) -> None:
        """Vacía el panel."""
        self.editor.clear()

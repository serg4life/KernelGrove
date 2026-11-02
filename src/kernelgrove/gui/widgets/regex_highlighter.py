"""Resaltador de sintaxis genérico por lista de reglas (patrón, formato).

Común a `DtsHighlighter` y `JsonHighlighter`: cada uno solo define su lista de
reglas, el recorrido de coincidencias por línea es idéntico para cualquier
lenguaje.
"""

from __future__ import annotations

from typing import List, Tuple

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QSyntaxHighlighter, QTextCharFormat, QTextDocument


class RegexHighlighter(QSyntaxHighlighter):
    """Aplica, línea a línea, cada regla `(patrón, formato)` de `self._rules`."""

    def __init__(self, document: QTextDocument):
        """Las subclases rellenan `self._rules` en su propio `__init__`."""
        super().__init__(document)
        self._rules: List[Tuple[QRegularExpression, QTextCharFormat]] = []

    def highlightBlock(self, text: str) -> None:
        """Colorea `text` según todas las reglas que apliquen."""
        for pattern, char_format in self._rules:
            iterator = pattern.globalMatch(text)
            while iterator.hasNext():
                match = iterator.next()
                self.setFormat(
                    match.capturedStart(), match.capturedLength(), char_format
                )

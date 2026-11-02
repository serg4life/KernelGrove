"""Ficha de una propiedad: qué es, qué admite y dónde se usa.

Se abre al pulsar una propiedad en el inspector. El inspector es una lista
—una línea por propiedad, su nombre y su tipo— y ahí no cabe lo que hace
falta para decidir qué escribir: la prosa del binding, los valores que
admite y de qué schema sale. Eso es esto.

**Es una ventana flotante**, no una vista central: se consulta *mientras*
se escribe en el editor, y una vista central habría tapado justo el texto
que se está corrigiendo con lo que explica cómo corregirlo. Flota sobre su
ventana (`Qt.Tool`), así que se puede dejar abierta al lado, y saltar a un
uso lleva el cursor al editor sin cerrarla.

No sabe de bases de datos ni de editores: recibe la ficha ya resuelta
(`show_property`) y avisa de lo que se le pide (
`findUsagesRequested`, `usageActivated`, `closeRequested`). Quien sabe
abrir un schema o buscar por el árbol es la ventana.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import PropertySuggestion
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates
from kernelgrove.gui.widgets.card import Card

# Un uso es dónde aparece la propiedad: la ruta del nodo y su línea.
Usage = Tuple[str, int]

# Ancho máximo de la columna de contenido y cuántas filas se enseñan de una
# lista antes de que se desplace. Las dos listas van dentro del scroll del
# panel, así que sin tope crecen hasta empujar los botones fuera.
_MAX_WIDTH = 760
_MAX_ROWS = 10

# Tamaño con el que se abre la ventana la primera vez; después manda lo que
# el usuario le haya dejado.
_DEFAULT_SIZE = (560, 460)


def _fit(lista: QListWidget) -> None:
    """Da a la lista el alto de sus filas, hasta `_MAX_ROWS`.

    Igual que en el inspector: dentro de un `QScrollArea` una lista con su
    `sizeHint` por defecto ocupa un alto fijo —vacía o con dos filas— y
    empuja lo que va debajo fuera de la vista.
    """
    filas = lista.count()
    alto = lista.sizeHintForRow(0) if filas else 0
    lista.setFixedHeight(min(filas, _MAX_ROWS) * alto + 6 if filas else 0)


class PropertyPanel(Retranslates, QWidget):
    """Vista central con todo lo que se sabe de una propiedad."""

    # Buscar dónde se usa, en el documento que está abierto.
    findUsagesRequested = Signal(str)
    # Ir a una de las líneas encontradas.
    usageActivated = Signal(int)
    # Cerrar la ficha: la vista se quita, no se queda vacía.
    closeRequested = Signal()

    def __init__(self, parent=None):
        """Monta la ficha vacía; el contenido lo pone `show_property`."""
        super().__init__(parent)
        # Ventana propia sobre la principal, no una pestaña: se lee a la vez
        # que se escribe. `Qt.Tool` la mantiene por encima de su padre y la
        # cierra con él, sin salir en la barra de tareas como una segunda
        # aplicación.
        self.setWindowFlag(Qt.Tool, True)
        self.resize(_DEFAULT_SIZE[0], _DEFAULT_SIZE[1])
        self._name = ""
        self._compatible = ""

        content = QWidget()
        # Ancho de lectura: es una vista central y sin tope la prosa del
        # binding se estira a lo ancho de la pantalla entera, que es la
        # forma más rápida de que no se lea.
        content.setMaximumWidth(_MAX_WIDTH)
        column = QVBoxLayout(content)
        column.setContentsMargins(18, 16, 18, 16)
        column.setSpacing(10)

        cabecera = QHBoxLayout()
        self._title = QLabel("")
        self._title.setObjectName("inspectorTitle")
        self._title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cabecera.addWidget(self._title)
        self._required = QLabel("")
        self._required.setObjectName("cardBadge")
        cabecera.addWidget(self._required)
        cabecera.addStretch(1)
        self._close_button = QPushButton()
        self._close_button.clicked.connect(lambda *_: self.closeRequested.emit())
        cabecera.addWidget(self._close_button)
        column.addLayout(cabecera)

        # Tipo y procedencia en una línea: son las dos cosas que sitúan la
        # propiedad —cómo se escribe y quién lo dice—.
        self._subtitle = QLabel("")
        self._subtitle.setObjectName("inspectorDescription")
        self._subtitle.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(self._subtitle)

        self._description = QLabel("")
        self._description.setWordWrap(True)
        self._description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        column.addWidget(self._description)

        self._values_card = Card()
        self._values = QListWidget()
        self._values.setObjectName("inspectorProperties")
        self._values.setFrameShape(QListWidget.NoFrame)
        self._values.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._values_card.set_content(self._values)
        column.addWidget(self._values_card)

        self._usages_card = Card()
        self._usages = QListWidget()
        self._usages.setObjectName("inspectorProperties")
        self._usages.setFrameShape(QListWidget.NoFrame)
        self._usages.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._usages.itemActivated.connect(self._on_usage)
        self._usages.itemClicked.connect(self._on_usage)
        self._usages_card.set_content(self._usages)
        self._usages_card.setVisible(False)
        column.addWidget(self._usages_card)

        acciones = QHBoxLayout()
        acciones.setSpacing(8)
        self._usages_button = QPushButton()
        self._usages_button.setObjectName("primaryButton")
        self._usages_button.clicked.connect(
            lambda *_: self.findUsagesRequested.emit(self._name)
        )
        acciones.addWidget(self._usages_button)
        acciones.addStretch(1)
        column.addLayout(acciones)

        column.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self.retranslate()

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self._required.setText(self.tr("required"))
        self._close_button.setText(self.tr("Close"))
        self._usages_button.setText(self.tr("Find usages"))
        self._values_card.set_title(self.tr("Allowed values"))
        self._usages_card.set_title(self.tr("Usages"))
        self._refresh_subtitle()
        # Los límites son texto traducido, así que se vuelven a escribir; la
        # lista de usos no —es la ruta y la línea de cada uno— y se queda
        # como estaba en vez de obligar a volver a buscarlos.
        self._fill_values()

    @property
    def property_name(self) -> str:
        """La propiedad que se está enseñando."""
        return self._name

    def show_property(
        self, detail: PropertySuggestion, compatible: str = ""
    ) -> None:
        """Rellena la ficha con lo que se sabe de una propiedad."""
        self._name = detail.name
        self._compatible = compatible
        self._detail = detail

        self._title.setText(detail.name)
        # El título de la ventana identifica de qué es la ficha: con dos
        # abiertas -o buscándola en el conmutador de ventanas- «Property» a
        # secas no distingue ninguna.
        self.setWindowTitle(
            f"{detail.name} · {compatible}" if compatible else detail.name
        )
        self._required.setVisible(detail.required)
        self._refresh_subtitle()

        prosa = " ".join((detail.description or "").split())
        self._description.setText(prosa)
        self._description.setVisible(bool(prosa))

        self._fill_values()

        self.clear_usages()

    def _fill_values(self) -> None:
        """Qué valores admite la propiedad: los que enumera y los que acota.

        No solo el `enum`: un entero suele venir acotado por rango
        (`clock-frequency` es de 1 a 400000 en este binding) y un array por
        cuántas entradas admite, y eso es tan «valor permitido» como una
        lista cerrada. Enseñar solo lo enumerado dejaba la mayoría de las
        propiedades sin nada que decir.

        Y cuando no hay ni una cosa ni la otra se dice también: la ficha se
        abre pulsando, así que siempre tiene que responder algo —«el binding
        no lo limita» y «el binding ni la declara» son respuestas distintas
        y las dos importan.
        """
        detail = getattr(self, "_detail", None)
        self._values.clear()
        if detail is None:
            self._values_card.setVisible(False)
            return
        for value in detail.allowed_values:
            self._values.addItem(QListWidgetItem(value))
        for texto in self._constraint_rows(detail.constraints):
            item = QListWidgetItem(texto)
            item.setForeground(QColor(style.MUTED_TEXT_COLOR))
            self._values.addItem(item)
        if not self._values.count():
            item = QListWidgetItem(
                self.tr("no limit declared by the binding")
                if detail.origin
                else self.tr("this binding does not declare this property")
            )
            item.setForeground(QColor(style.MUTED_TEXT_COLOR))
            item.setFlags(Qt.NoItemFlags)
            self._values.addItem(item)
        _fit(self._values)
        self._values_card.setVisible(True)

    def _constraint_rows(self, constraints: dict) -> List[str]:
        """Los límites del binding, en una línea cada uno.

        En forma «rótulo: valor» y no en frase («exactamente 1 entrada»)
        para no arrastrar un plural por idioma a cambio de nada: son datos
        de una ficha técnica, y así se leen en columna.
        """
        filas: List[str] = []
        minimo, maximo = constraints.get("minimum"), constraints.get("maximum")
        if minimo is not None and maximo is not None:
            filas.append(
                self.tr("value: {min} … {max}").format(min=minimo, max=maximo)
            )
        elif minimo is not None:
            filas.append(self.tr("value: at least {min}").format(min=minimo))
        elif maximo is not None:
            filas.append(self.tr("value: at most {max}").format(max=maximo))

        pocos, muchos = constraints.get("minItems"), constraints.get("maxItems")
        if pocos is not None and pocos == muchos:
            filas.append(self.tr("entries: exactly {count}").format(count=pocos))
        elif pocos is not None and muchos is not None:
            filas.append(
                self.tr("entries: {min} to {max}").format(min=pocos, max=muchos)
            )
        elif pocos is not None:
            filas.append(self.tr("entries: at least {min}").format(min=pocos))
        elif muchos is not None:
            filas.append(self.tr("entries: at most {max}").format(max=muchos))

        if constraints.get("pattern"):
            filas.append(
                self.tr("matches {pattern}").format(pattern=constraints["pattern"])
            )
        if "default" in constraints:
            filas.append(
                self.tr("default: {value}").format(value=constraints["default"])
            )
        return filas

    def show_usages(self, usages: Sequence[Usage], searched: str) -> None:
        """Enseña dónde aparece la propiedad, o que no aparece en ningún sitio."""
        self._usages.clear()
        for path, line in usages:
            item = QListWidgetItem(
                self.tr("{path} · line {line}").format(path=path, line=line)
            )
            item.setData(Qt.UserRole, line)
            self._usages.addItem(item)
        if not usages:
            item = QListWidgetItem(
                self.tr("not used in {name}").format(name=searched)
            )
            item.setForeground(QColor(style.MUTED_TEXT_COLOR))
            item.setFlags(Qt.NoItemFlags)
            self._usages.addItem(item)
        _fit(self._usages)
        self._usages_card.set_title(
            self.tr("Usages in {name}").format(name=searched)
        )
        self._usages_card.setVisible(True)

    def clear_usages(self) -> None:
        """Esconde la lista de usos: es de la propiedad que se estaba viendo."""
        self._usages.clear()
        self._usages_card.setVisible(False)

    def refresh_skin(self) -> None:
        """Ajusta las tarjetas a la piel activa."""
        self._values_card.refresh_skin()
        self._usages_card.refresh_skin()

    def _refresh_subtitle(self) -> None:
        """El tipo y de qué binding sale, en una línea."""
        detail = getattr(self, "_detail", None)
        if detail is None:
            self._subtitle.setText("")
            return
        partes: List[str] = [
            detail.dt_type
            or self.tr("type not declared by any single binding")
        ]
        if detail.origin:
            partes.append(self.tr("from {schema}").format(schema=detail.origin))
        # Desde qué kernel se puede usar. Es la única de las tres que no se
        # puede deducir leyendo el binding: sale de la historia del
        # repositorio, y decide si lo que se está escribiendo arrancará en
        # la placa que se tiene delante.
        if detail.since:
            partes.append(self.tr("Linux {version}+").format(version=detail.since))
        self._subtitle.setText(" · ".join(partes))

    def _on_usage(self, item: QListWidgetItem) -> None:
        """Lleva el editor a la línea del uso pulsado."""
        line: Optional[int] = item.data(Qt.UserRole)
        if isinstance(line, int):
            self.usageActivated.emit(line)

"""Panel con la ficha del nodo donde está el cursor del editor.

Distinto de `DetailsPanel` (la ficha de un `PeripheralSlot` del Generador,
con su propio ciclo de conectar/desconectar): este lee directamente el nodo
del árbol analizado bajo el cursor, cualquiera que sea — no hace falta que
esté conectado a nada ni que sea un controlador, solo que el cursor esté
dentro de él.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.gui.widgets.card import Card
from kernelgrove.api import (
    SPEC_OWNED_PROPERTIES,
    DeviceTreeNode,
    KernelGroveService,
    PropertySuggestion,
)
from kernelgrove.gui import style
from kernelgrove.gui.translations import Retranslates


# Cuánto de la prosa del binding se enseña antes de cortar. Es una ficha,
# no un visor de documentación: lo que se viene a leer aquí son las
# propiedades del nodo.
_MAX_DESCRIPTION = 200


class InspectorPanel(Retranslates, QWidget):
    """Ficha de solo lectura del nodo bajo el cursor, con datos del binding."""

    # Propiedad pulsada en la lista: su nombre y el compatible del nodo (o
    # cadena vacía si no tiene). Quien abre la ficha detallada es la
    # ventana; este panel no sabe de pestañas.
    propertyActivated = Signal(str, str)

    def __init__(self, service: KernelGroveService, parent=None):
        """Monta el formulario y las listas de propiedades, vacíos de entrada."""
        super().__init__(parent)
        self._service = service

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        self._title = QLabel(self.tr("No node"))
        self._title.setObjectName("inspectorTitle")
        self._title.setWordWrap(True)
        layout.addWidget(self._title)

        # Qué es el dispositivo, en la prosa de su propio binding. Es lo
        # único que el panel puede decir que no esté ya escrito en el
        # fuente: `compatible`, fabricante, subsistema y título salían en un
        # formulario de cuatro filas donde el compatible repetía una
        # propiedad que la lista de abajo ya enseña, y las otras tres eran
        # el mismo dato troceado.
        self._description = QLabel("")
        self._description.setObjectName("inspectorDescription")
        self._description.setWordWrap(True)
        self._description.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self._description)

        self._properties = QTreeWidget()
        self._properties.setObjectName("inspectorProperties")
        self._properties.setHeaderHidden(True)
        self._properties.setColumnCount(3)
        self._properties.setRootIsDecorated(False)
        self._properties.setFrameShape(QTreeWidget.NoFrame)
        # Alto ajustado a lo que tenga, sin scroll propio: todo el panel ya
        # vive dentro de un `QScrollArea` (`self._scroll`), y una lista
        # anidada con su propia barra sería un scroll dentro de otro scroll.
        self._properties.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # Tampoco horizontal: el panel es estrecho por definición y un valor
        # largo (`reg = <0x0 0xff010000 …>`) sacaba una barra debajo de la
        # lista. Se recorta con puntos suspensivos y el valor entero queda
        # en el tooltip.
        self._properties.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._properties.setTextElideMode(Qt.ElideRight)
        # El nombre cede y las otras dos no: son cortas y de ancho casi fijo,
        # y son las que se leen en diagonal («¿cuáles son obligatorias?»,
        # «¿esto va entre <> o entre comillas?»). Ajustando el nombre a su
        # contenido, un `i2c-analog-filter-cutoff-frequency` se quedaba con
        # el panel entero y las otras dos columnas no se veían.
        header = self._properties.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._properties.setSizeAdjustPolicy(QTreeWidget.AdjustToContents)
        self._properties.setCursor(Qt.PointingHandCursor)
        self._properties.itemClicked.connect(self._on_property_clicked)
        # La mitad derecha del mockup de la web: cada fila en monoespaciada,
        # el nombre atenuado, si el binding la exige o la admite, y de qué
        # tipo es. La tipografía y los colores salen del QSS
        # (`inspectorProperties`).
        # La versión del kernel va **dentro de la tarjeta**, en su propia
        # fila: colgada del final de la descripción se leía como parte de la
        # frase del binding y se perdía. Aquí es un dato con su rótulo, como
        # las propiedades de debajo.
        self._kernel_row = QWidget()
        fila = QHBoxLayout(self._kernel_row)
        fila.setContentsMargins(12, 8, 12, 4)
        fila.setSpacing(8)
        self._kernel_caption = QLabel()
        self._kernel_caption.setObjectName("inspectorDescription")
        self._kernel_value = QLabel("")
        self._kernel_value.setObjectName("cardBadge")
        fila.addWidget(self._kernel_caption, 1)
        fila.addWidget(self._kernel_value)
        self._kernel_row.setVisible(False)

        contenido = QWidget()
        columna = QVBoxLayout(contenido)
        columna.setContentsMargins(0, 0, 0, 0)
        columna.setSpacing(0)
        columna.addWidget(self._kernel_row)
        columna.addWidget(self._properties)

        card = Card()
        card.set_content(contenido)
        self._properties_card = card
        layout.addWidget(card)
        self.refresh_skin()

        # Fila «✓ correcto contra el binding» del mockup, que solo aparece
        # cuando de verdad lo está: decirlo cuando no se ha comprobado nada
        # sería exactamente el tipo de afirmación vacía que el motor evita.
        self._ok_label = QLabel("")
        self._ok_label.setObjectName("cardOk")
        self._ok_label.setVisible(False)
        layout.addWidget(self._ok_label)

        self._missing_label = QLabel("")
        self._missing_label.setWordWrap(True)
        self._missing_label.setStyleSheet(f"color: {style.EDITOR_WARNING_ACCENT};")
        layout.addWidget(self._missing_label)

        layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(content)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        # Último nodo mostrado, para poder repintarlo al cambiar de idioma.
        self._node: Optional[DeviceTreeNode] = None
        # Compatible del nodo que se está enseñando: es lo que hace falta
        # para poder decir algo de una propiedad al pulsarla.
        self._compatible = ""
        self.retranslate()

    def retranslate(self) -> None:
        """Rehace las etiquetas fijas y repinta el nodo (ver `Retranslates`)."""
        self._ok_label.setText(self.tr("✓ valid against binding"))
        self._kernel_caption.setText(self.tr("Kernel support"))
        # El nodo mostrado lleva texto traducido («Ningún nodo», «línea N»,
        # «Obligatorias que faltan»), así que se vuelve a pintar entero.
        self.show_node(self._node)

    def minimumSizeHint(self) -> QSize:  # noqa: N802 - override de Qt
        """Sin mínimo propio, para que `MainWindow` pueda plegar su dock.

        Por defecto, Qt deriva esto del contenido (la lista de propiedades,
        el formulario...), y ese mínimo cuenta para el ancho mínimo del
        `QDockWidget` que lo aloja aunque el panel esté oculto (`hide()` no
        lo excluye) — sin este override, `MainWindow._toggle_inspector`
        nunca conseguía encogerlo más allá de ese tamaño intrínseco.
        """
        return QSize(0, 0)

    def show_node(self, node: Optional[DeviceTreeNode]) -> None:
        """Rellena la ficha con `node`, o la vacía si no hay nodo o no tiene compatible.

        Sin `compatible` no hay binding que resolver, y sin binding la ficha
        no tendría nada propio que decir — solo repetiría lo que el nodo ya
        trae escrito, que el editor enseña al lado. Así que un nodo sin
        compatible se trata igual que "no hay nodo", con un mensaje que dice
        por qué.
        """
        self._node = node
        service = self._service
        if node is None or not node.compatible:
            self._title.setText(
                self.tr("No node") if node is None else _node_title(node)
            )
            self._set_description(
                self.tr("Put the cursor inside a node")
                if node is None
                else self.tr("This node has no compatible")
            )
            self._set_kernel_version(None)
            self._properties.clear()
            self._properties_card.set_title(None)
            self._missing_label.setText("")
            self._ok_label.setVisible(False)
            return

        self._title.setText(_node_title(node))

        # El binding primero: la lista de propiedades enseña **el tipo** de
        # cada una, y el tipo lo sabe el binding. Sin él la lista se pinta
        # igual, con lo que dt-schema deduzca del nombre.
        primary = node.compatible[0]
        self._compatible = primary
        suggestions: List[PropertySuggestion] = []
        if service.binding_schemas_available():
            info = service.get_binding_info(primary)
            self._set_description(_binding_description(info))
            self._set_kernel_version(service.binding_since(primary))
            self._description.setToolTip(
                " ".join((info.description or "").split()) or ""
            )
            suggestions = service.suggest_properties(primary)
        else:
            self._set_description(None)
            self._set_kernel_version(None)

        declaradas = {
            suggestion.name: suggestion
            for suggestion in suggestions
            if not suggestion.is_node
        }
        self._fill_properties(node, declaradas, bool(suggestions))
        # La barra de la tarjeta lleva el nombre **entero**, con su
        # dirección: el título de arriba se queda con lo de antes de la «@»,
        # y la dirección tiene que seguir estando en algún sitio.
        self._properties_card.set_title(node.name)
        self._fit_properties()

        if not suggestions:
            self._missing_label.setText("")
            self._ok_label.setVisible(False)
            return

        missing = _missing_required(node, suggestions)
        self._missing_label.setText(
            self.tr("Missing required: {names}").format(names=", ".join(missing))
            if missing
            else ""
        )
        # El «✓» solo si hay binding y no falta nada suyo: es la única
        # situación en la que la afirmación es cierta.
        self._ok_label.setVisible(not missing)

    def _set_description(self, text: Optional[str]) -> None:
        """Pone la descripción, o esconde la fila entera si no hay ninguna.

        Una línea con «—» ocupa lo mismo que la información y no dice nada.
        """
        self._description.setText(text or "")
        self._description.setVisible(bool(text))

    def _set_kernel_version(self, since: Optional[str]) -> None:
        """Desde qué kernel existe el binding, dentro de la tarjeta.

        Es el único dato de la ficha que no se puede sacar leyendo el fuente
        ni el propio binding —sale de la historia del repositorio— y el que
        decide si esto arrancará en la placa que se tiene delante, así que
        se enseña como dato con su rótulo y no como coletilla de la prosa.
        """
        self._kernel_value.setText(
            self.tr("{version}+").format(version=since) if since else ""
        )
        self._kernel_row.setVisible(bool(since))

    def refresh_skin(self) -> None:
        """Ajusta la tarjeta de propiedades a la piel activa."""
        self._properties_card.refresh_skin()

    def _fit_properties(self) -> None:
        """Da a la lista el alto exacto de sus filas.

        Sin esto se queda en el `sizeHint` de un `QAbstractScrollArea`, que
        es un tamaño fijo y corta la lista a dos filas y media dentro de la
        tarjeta. Puede hacerse porque la lista no tiene scroll propio: el
        panel entero ya vive dentro de un `QScrollArea`.

        La altura sale de `sizeHintForRow` y no de `visualItemRect`: esto se
        llama en la misma pasada en la que se han añadido las filas, y
        entonces la vista todavía no les ha calculado geometría — sus
        rectángulos vienen vacíos y la lista quedaba en dos filas y media.
        """
        filas = self._properties.topLevelItemCount()
        alto = self._properties.sizeHintForRow(0) if filas else 0
        self._properties.setFixedHeight(filas * alto + 6 if filas else 0)

    def _fill_properties(
        self,
        node: DeviceTreeNode,
        declaradas: Dict[str, PropertySuggestion],
        con_binding: bool,
    ) -> None:
        """Una fila por propiedad **del binding**, esté escrita o no.

        La lista no es lo que el nodo tiene: es lo que el binding admite. Un
        `i2c@…` al que le falta `clocks` no la enseñaba, que es justo cuando
        hace falta verla; el editor ya dice lo que está escrito, y el
        inspector está para decir lo que se puede escribir.

        Tres columnas: el nombre, qué dice el binding de ella —la **exige**,
        la **admite** o no la conoce— y de qué tipo es. El valor no: está en
        el editor, a media pantalla de aquí, y repetirlo era gastar el panel
        en enseñar dos veces lo mismo — sigue a mano en el aviso de la fila.
        El tipo,
        en cambio, no está escrito en ninguna parte y es lo que decide si
        `<0x40>` o `"0x40"` es lo correcto.

        Y las obligatorias que faltan van sobre fondo teñido: el aviso
        amarillo de debajo dice cuáles son, esto dice dónde están, y así no
        hay que cruzar las dos listas a mano.

        El orden es «lo que hay que poner, lo que has puesto, lo que
        podrías poner»: obligatorias primero, luego las que el nodo declara
        y por último el resto del catálogo del binding.
        """
        self._properties.clear()
        nombres = set(node.properties) | {
            name
            for name, suggestion in declaradas.items()
            if not suggestion.is_node
        }
        for name in sorted(
            nombres,
            key=lambda item: (
                not (declaradas.get(item) and declaradas[item].required),
                item not in node.properties,
                item,
            ),
        ):
            self._properties.addTopLevelItem(
                self._property_row(
                    name, node, declaradas.get(name), con_binding
                )
            )
        self._fit_properties()

    def _property_row(
        self,
        name: str,
        node: DeviceTreeNode,
        suggestion: Optional[PropertySuggestion],
        con_binding: bool,
    ) -> QTreeWidgetItem:
        """La fila de una propiedad: nombre, qué dice el binding de ella y su tipo."""
        tipo = self._service.property_type_label(
            name, suggestion.dt_type if suggestion else None
        )
        escrita = name in node.properties
        # Con binding, las tres respuestas posibles; sin él, ninguna: decir
        # «sobra» de una propiedad cuando no se ha podido leer ningún
        # binding sería afirmar algo que nadie ha dicho.
        if not con_binding:
            estado, color, ayuda = "", style.FAINT_TEXT_COLOR, ""
        elif suggestion is None and name in SPEC_OWNED_PROPERTIES:
            # La exige (o no) la especificación Device Tree, no el binding
            # de este compatible —igual que `model` en la raíz—, así que el
            # binding no tiene nada que decir de ella. Es la misma exención
            # que ya aplica `checks/bindings/rules.py` al juzgar qué sobra;
            # sin ella el Inspector la marcaba "UNNECESSARY" mientras la capa
            # 1 la exigía, dos diagnósticos contradictorios sobre la misma
            # propiedad.
            estado, color, ayuda = "", style.FAINT_TEXT_COLOR, ""
        elif suggestion is None:
            # Escrita en el fuente y el binding no la declara. En ámbar y no
            # en rojo porque no es necesariamente un error —el binding puede
            # estar incompleto, o venir de un `.txt` sin convertir—, pero sí
            # es lo primero que hay que mirar de esta lista.
            estado = self.tr("UNNECESSARY")
            color = style.EDITOR_WARNING_ACCENT
            ayuda = self.tr("The binding does not declare this property.")
        elif suggestion.required:
            estado = self.tr("REQUIRED")
            # El mismo verde que el «✓ correcto contra el binding» de abajo:
            # las dos dicen «esto es lo que el binding pide».
            color = style.CARD_OK_COLOR
            ayuda = self.tr("The binding requires this property.")
        else:
            estado = self.tr("OPTIONAL")
            color = style.FAINT_TEXT_COLOR
            ayuda = self.tr("The binding admits this property.")

        item = QTreeWidgetItem([name, estado, tipo or "—"])
        item.setData(0, Qt.UserRole, name)
        # El nombre se recorta cuando el panel es estrecho, así que va
        # entero en el aviso, con la prosa del binding debajo si la trae.
        prosa = (suggestion.description or "") if suggestion else ""
        item.setToolTip(0, f"{name}\n\n{prosa}".strip() if prosa else name)
        item.setToolTip(1, ayuda)
        item.setToolTip(2, _format_value(node.properties[name]) if escrita else "")
        # Una obligatoria que falta se marca en el **ámbar del aviso** de
        # debajo: el aviso dice cuáles faltan y la fila dice dónde está,
        # sin cruzar las dos listas a mano. Va en el texto y no en el fondo
        # porque la hoja de estilos pinta `::item` ella misma y con eso Qt
        # ignora el fondo que se le ponga a la fila —comprobado—.
        falta = suggestion is not None and suggestion.required and not escrita
        if falta:
            nombre = style.EDITOR_WARNING_ACCENT
        elif escrita:
            nombre = style.MUTED_TEXT_COLOR
        else:
            nombre = style.FAINT_TEXT_COLOR
        item.setForeground(0, QColor(nombre))
        item.setForeground(1, QColor(color))
        item.setForeground(2, QColor(style.FAINT_TEXT_COLOR))
        return item

    def _on_property_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        """Pide abrir la ficha de la propiedad pulsada."""
        name = item.data(0, Qt.UserRole)
        if name:
            self.propertyActivated.emit(name, self._compatible)


def _node_title(node: DeviceTreeNode) -> str:
    """Cómo se llama el dispositivo: lo que hay antes de la «@».

    `i2c@ff020000` es un controlador de I2C en la dirección `ff020000`; el
    nombre es «i2c» y la dirección es dónde está mapeado, no parte de cómo
    se llama. La dirección entera sigue a la vista en la barra de la
    tarjeta de propiedades, y el `label` es un alias del fuente, no un
    nombre — el que lo escribió ya lo tiene delante.

    La raíz sintética del árbol interno lleva `label="root"` (ver
    `parser.parse_dts_source`), que no es nada que el usuario haya escrito.
    """
    return node.name.split("@", 1)[0] or node.name


def _binding_description(info) -> Optional[str]:
    """Qué es el dispositivo, en una frase.

    La prosa del binding entera no cabe: la de `cpu.yaml` son quince líneas
    con las reglas de escritura del propio documento, y puesta aquí empuja
    la lista de propiedades fuera de la pantalla —el panel pasa a ser un
    visor de documentación en vez de la ficha del nodo—. Así que la primera
    frase, y lo demás en el tooltip.

    "Unknown" es lo que devuelve la base cuando el compatible no está
    documentado: enseñarlo como si fuera la descripción es peor que no
    enseñar nada.
    """
    for texto in (info.description, info.title):
        if not texto or texto == "Unknown":
            continue
        limpio = " ".join(texto.split())
        frase = limpio.split(". ")[0].rstrip(".")
        if len(frase) > _MAX_DESCRIPTION:
            frase = frase[:_MAX_DESCRIPTION].rsplit(" ", 1)[0]
        return frase + "…" if len(frase) < len(limpio.rstrip(".")) else frase
    return None


def _format_value(value: object) -> str:
    """Texto de una propiedad tal como la guarda el parser (cadena cruda o flag)."""
    return "(flag)" if value is True else str(value)


def _missing_required(
    node: DeviceTreeNode, suggestions: List[PropertySuggestion]
) -> List[str]:
    """Nombres obligatorios del binding que este nodo no declara.

    Una propiedad obligatoria se busca en `node.properties`; un nodo
    obligatorio (`is_node`), entre los nombres de sus hijos — son las dos
    formas en que un binding exige algo, y una sugerencia no dice cuál es sin
    mirar `is_node`.
    """
    child_names = {child.name for child in node.children}
    missing = []
    for suggestion in suggestions:
        if not suggestion.required:
            continue
        present = (
            suggestion.name in child_names
            if suggestion.is_node
            else suggestion.name in node.properties
        )
        if not present:
            missing.append(suggestion.name)
    return missing

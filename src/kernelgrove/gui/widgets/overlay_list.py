"""Los overlays de la carpeta abierta, y si cada uno cuadra con su base.

Un overlay no dice a qué árbol se aplica —no puede: incluir la base
duplicaría el device tree entero—, así que «¿este `.dtso` es correcto?» no es
una pregunta que se pueda responder mirando solo el fichero. De ahí las tres
piezas de esta vista:

- **la base de cada overlay**, que se elige a mano con «Validate» —un
  fichero del disco o una entrada del catálogo— y, mientras no se elija,
  es la que haya cargada. No se deduce del fichero: un overlay no lleva
  dentro a qué árbol pertenece, y fingir que sí lo lleva (anotarlo en un
  comentario) ataba el `.dtso` a una procedencia invisible;
- **la comprobación**, que es donde vive la capa 6 y solo aquí: en el editor
  la base es un dato invisible que el usuario no ha elegido, y un error de
  capa 6 allí no se puede ni interpretar ni arreglar con conocimiento de
  causa;
- **el registro**, que cuenta qué se ha comprobado y contra qué — también
  cuando sale bien, porque «no ha pasado nada» y «no se ha comprobado nada»
  se parecen demasiado como para dejarlos indistinguibles. No se enseña
  aquí: se emite (`reportReady`) y lo pinta la franja de registro de abajo,
  la misma que los diagnósticos, porque dos ventanas de registro en la
  misma pantalla es una de más.

Lista todos los `.dtso` de la carpeta, los haya escrito esta herramienta o
no: el asistente se aparta en cuanto genera el fichero, así que a partir de
ahí un overlay suyo y uno ajeno son exactamente lo mismo.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from kernelgrove.api import DeviceTreeNode, Diagnostic, KernelGroveService, Severity
from kernelgrove.gui import style, theme
from kernelgrove.gui.translations import Retranslates

# Ruta del fichero, para abrirlo o comprobarlo.
ROLE_PATH = Qt.UserRole + 1

# La primera columna es el interruptor: entra o no entra en la
# compilación. Con columna propia y no con la casilla nativa del `QTreeView`
# porque lo que se pinta ahí es un interruptor, y la casilla nativa
# comparte celda con el nombre del fichero — el texto acaba pisándolo o
# desplazado a mano.
COLUMN_TOGGLE = 0
COLUMN_FILE = 1
COLUMN_BASE = 2
COLUMN_STATUS = 3

# Tamaño del interruptor y de su columna.
TOGGLE_WIDTH = 26
TOGGLE_HEIGHT = 14
TOGGLE_COLUMN_WIDTH = 38

# Extensiones que se consideran overlay. `.dts` no entra: un `.dts` es un
# device tree completo, y los pocos que además son overlay se reconocen por
# su `/plugin/;`, no por el nombre.
# Cuántos niveles de subcarpeta se miran buscando overlays.
OVERLAY_SCAN_DEPTH = 2

OVERLAY_SUFFIXES = (".dtso",)

# Cuántos diagnósticos se detallan en el registro antes de resumir. Más de
# esto deja de ser un informe y pasa a ser el panel de diagnósticos, que ya
# existe y sale al abrir el fichero.
_MAX_DETALLE = 12

# Los tres glifos con los que se escribe el informe. No son adorno: son lo
# que colorea `OverlayLogHighlighter` —por el glifo y nunca por la palabra,
# que está traducida— y lo que deja leer el registro de un vistazo sin
# depender del color. Los mismos que usa el registro de compilación.
# El neutro existe para que **todas** las líneas de un nivel empiecen en la
# misma columna: sin él, «  base: …» arrancaba dos caracteres antes que
# «  ✗ layer 6: …» y el informe se leía en zigzag.
GLYPH_OK = "✓"
GLYPH_INFO = "·"
GLYPH_FAIL = "✗"
GLYPH_WARN = "!"
# Separador de informes: sin él, veinte comprobaciones seguidas son un muro.
RULE = "─" * 56

# Veredicto de una fila, para poder resumirla sin leer su texto traducido.
ROLE_VERDICT = Qt.UserRole + 2

# Devuelve el árbol fusionado de una base, dada su clave. Lo inyecta la
# ventana, que es quien sabe resolver un `source_key` (documento abierto,
# fichero del disco o entrada del catálogo).
BaseResolver = Callable[[str], Optional[DeviceTreeNode]]


def scan_files(folder: Path, suffixes: Sequence[str], depth: int) -> List[Path]:
    """Los ficheros con esas extensiones, bajando `depth` niveles de carpeta.

    Ni solo el primer nivel ni el árbol entero. Solo el primero dejaba
    fuera lo que todo el mundo guarda en una subcarpeta `overlays/`, que es
    justo donde se buscan; el árbol entero, en una carpeta con un kernel
    dentro, tarda lo suyo y trae los 361 `.dtso` del kernel, que no son de
    este proyecto.

    Las carpetas ocultas se saltan: `.git` tiene miles de ficheros y
    ninguno es un device tree de nadie.
    """
    encontrados: List[Path] = []
    pendientes = [(folder, 0)]
    while pendientes:
        carpeta, nivel = pendientes.pop(0)
        try:
            hijos = sorted(carpeta.iterdir())
        except OSError:
            continue
        for path in hijos:
            if path.is_dir():
                if nivel < depth and not path.name.startswith("."):
                    pendientes.append((path, nivel + 1))
            elif path.suffix.lower() in suffixes:
                encontrados.append(path)
    return encontrados


class ToggleDelegate(QStyledItemDelegate):
    """Pinta el estado marcado de una fila como un interruptor.

    Un interruptor y no una casilla porque lo que dice no es «este fichero
    cumple una condición» sino «este overlay entra en lo que se va a
    compilar»: es un ajuste que se deja puesto, y esa es la forma con la
    que se lee sin instrucciones. Se dibuja a mano —como el resto de los
    iconos de la aplicación— para que siga la piel activa y no la paleta
    nativa del estilo.
    """

    def paint(self, painter: QPainter, option, index) -> None:
        """Dibuja la pastilla y su bolita, encendida o apagada."""
        super().paint(painter, option, index)
        encendido = index.data(Qt.CheckStateRole) == Qt.Checked
        rect = option.rect
        pista = QRectF(
            rect.center().x() - TOGGLE_WIDTH / 2,
            rect.center().y() - TOGGLE_HEIGHT / 2,
            TOGGLE_WIDTH,
            TOGGLE_HEIGHT,
        )
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(
            QColor(theme.ACCENT if encendido else theme.BORDER)
        )
        painter.drawRoundedRect(pista, TOGGLE_HEIGHT / 2, TOGGLE_HEIGHT / 2)
        radio = TOGGLE_HEIGHT / 2 - 2
        centro_x = (
            pista.right() - radio - 2 if encendido else pista.left() + radio + 2
        )
        painter.setBrush(
            QColor(theme.ACCENT_FG if encendido else style.MUTED_TEXT_COLOR)
        )
        painter.drawEllipse(
            QRectF(centro_x - radio, pista.center().y() - radio, radio * 2, radio * 2)
        )
        painter.restore()

    def editorEvent(self, event, model, option, index) -> bool:  # noqa: N802
        """Un clic en la celda cambia el interruptor, no solo en la pastilla.

        La casilla nativa exige acertar en un cuadrado de trece píxeles; la
        celda entera es el objetivo que la forma promete.
        """
        if event.type() == QEvent.MouseButtonRelease:
            marcado = index.data(Qt.CheckStateRole) == Qt.Checked
            model.setData(
                index,
                Qt.Unchecked if marcado else Qt.Checked,
                Qt.CheckStateRole,
            )
            return True
        return super().editorEvent(event, model, option, index)


class OverlayList(Retranslates, QWidget):
    """Tabla de overlays de la carpeta, su comprobación y el registro."""

    # Ruta del overlay que se quiere abrir en el editor.
    overlayActivated = Signal(str)
    # Rutas de los overlays que se quieren comprobar eligiendo base a mano
    # (las seleccionadas): la base se pregunta una vez y vale para todos.
    validateRequested = Signal(list)
    # Informe de una comprobación explícita, ya escrito. Lo enseña el panel
    # de registro de la ventana, no este widget.
    reportReady = Signal(str)
    # Ha cambiado qué overlays entran en la compilación.
    checkedChanged = Signal()

    def __init__(self, service: KernelGroveService, parent=None):
        """Monta la tabla y el registro, vacíos; sin carpeta no hay nada."""
        super().__init__(parent)
        self._service = service
        self._folder: Optional[Path] = None
        self._base: Optional[DeviceTreeNode] = None
        self._resolver: Optional[BaseResolver] = None
        # Base elegida a mano para un overlay concreto, mientras dure la
        # sesión: lo que se declara en el fichero manda, pero una elección
        # explícita manda sobre eso.
        self._chosen: dict = {}
        # Overlays con el interruptor puesto, por ruta. Se guarda aparte de
        # las filas porque la tabla se reconstruye entera en cada `refresh`
        # -y eso pasa al volver a la sección- y perder lo que se había
        # marcado a cada visita haría el interruptor inservible.
        self._checked: set = set()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_toolbar())
        layout.addWidget(self._build_table(), 1)

        self.retranslate()

    # ------------------------------------------------------------------
    # Construcción
    # ------------------------------------------------------------------
    def _build_toolbar(self) -> QWidget:
        """Qué carpeta se lista, contra qué se comprueba y las dos acciones.

        En dos filas y no en una: esto vive en el panel lateral, donde una
        sola fila con dos textos y dos botones dejaba «Validate…» reducido a
        nada —y un botón que no se ve es una función que no existe—.
        """
        bar = QWidget()
        bar.setObjectName("viewToolbar")
        column = QVBoxLayout(bar)
        column.setContentsMargins(12, 7, 12, 7)
        column.setSpacing(6)

        self._base_label = QLabel()
        self._base_label.setObjectName("viewToolbarStatus")
        self.validate_button = QPushButton()
        self.validate_button.setObjectName("primaryButton")
        self.validate_button.clicked.connect(self._on_validate_clicked)
        self.refresh_button = QPushButton()
        # A `recheck` y no a `refresh`: relistar deja la tabla igual que
        # estaba cuando nada ha cambiado, así que el botón parecía no hacer
        # nada. Ahora además cuenta en el registro qué ha comprobado.
        self.refresh_button.clicked.connect(lambda *_: self.recheck())

        # Sin `addStretch`: en este panel todos los textos llevan
        # `QSizePolicy.Ignored` (`MainWindow._allow_narrow`), así que su
        # mínimo es cero y un espaciador elástico se lo queda todo — la
        # etiqueta se quedaba en 0 px y no se leía cuál era la base.
        titles = QHBoxLayout()
        titles.setSpacing(8)
        titles.addWidget(self._base_label, 1)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        actions.addWidget(self.validate_button, 1)
        actions.addWidget(self.refresh_button, 1)

        column.addLayout(titles)
        column.addLayout(actions)
        return bar

    def _build_table(self) -> QWidget:
        """La tabla de overlays."""
        self.table = QTreeWidget()
        self.table.setColumnCount(4)
        self.table.setRootIsDecorated(False)
        self.table.setUniformRowHeights(True)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.itemDoubleClicked.connect(self._on_activated)
        self.table.setItemDelegateForColumn(COLUMN_TOGGLE, ToggleDelegate(self.table))
        self.table.itemChanged.connect(self._on_item_changed)
        header = self.table.header()
        header.setSectionResizeMode(COLUMN_TOGGLE, QHeaderView.Fixed)
        header.resizeSection(COLUMN_TOGGLE, TOGGLE_COLUMN_WIDTH)
        header.setSectionResizeMode(COLUMN_FILE, QHeaderView.Stretch)
        header.setSectionResizeMode(COLUMN_BASE, QHeaderView.Interactive)
        header.resizeSection(COLUMN_BASE, 110)
        header.setSectionResizeMode(COLUMN_STATUS, QHeaderView.Interactive)
        header.resizeSection(COLUMN_STATUS, 130)
        return self.table

    def retranslate(self) -> None:
        """Rehace los textos fijos (ver `Retranslates`)."""
        self.validate_button.setText(self.tr("Validate…"))
        self.validate_button.setToolTip(
            self.tr(
                "Check the selected overlays -all of them if none is "
                "selected- against a base you pick: a file from your "
                "computer or one from the database."
            )
        )
        self.refresh_button.setText(self.tr("Check again"))
        self.table.setHeaderLabels(
            ["", self.tr("File"), self.tr("Base"), self.tr("Checked")]
        )
        self._refresh_base_label()

    # ------------------------------------------------------------------
    # Contexto
    # ------------------------------------------------------------------
    def set_base_resolver(self, resolver: Optional[BaseResolver]) -> None:
        """Fija quién sabe convertir la clave de una base en su árbol."""
        self._resolver = resolver

    def set_context(
        self, folder: Optional[Path], base: Optional[DeviceTreeNode]
    ) -> None:
        """Fija qué carpeta se lista y cuál es la base cargada ahora mismo."""
        if folder == self._folder and base is self._base:
            return
        self._folder = folder
        self._base = base
        self._refresh_base_label()
        self.refresh()

    def _refresh_base_label(self) -> None:
        """Dice cuál es la base cargada, que es la que se usa por defecto."""
        if self._base is None:
            self._base_label.setText(self.tr("no device tree loaded"))
            return
        # El nombre a secas: «loaded:» delante repetía en cada fila y en la
        # cabecera una palabra que no distingue una base de otra, y en un
        # panel estrecho se comía justo lo que sí la distingue.
        self._base_label.setText(self._base_name(self._base))

    def _base_name(self, base: DeviceTreeNode) -> str:
        """Cómo se llama una base en la interfaz: su compatible si lo tiene."""
        if base.compatible:
            return base.compatible[0]
        return self.tr("the open device tree")

    def showEvent(self, event) -> None:
        """Al volver a esta vista se relee: el disco cambia por fuera."""
        super().showEvent(event)
        self.refresh()

    # ------------------------------------------------------------------
    # Comprobación
    # ------------------------------------------------------------------
    def refresh(self, verbose: bool = False) -> None:
        """Relee la carpeta y comprueba cada overlay contra la base que le toque.

        Calla por defecto: esto se dispara al enseñar el panel y cada vez
        que el asistente escribe un fichero, y un informe por overlay en
        cada una de esas veces llenaría el registro de comprobaciones que
        nadie ha pedido. Solo habla cuando lo pide `recheck`.
        """
        self.table.clear()
        if self._folder is None or not self._folder.is_dir():
            return

        for path in sorted(self._overlay_files()):
            item = QTreeWidgetItem(["", path.name, "", ""])
            item.setData(COLUMN_FILE, ROLE_PATH, str(path))
            item.setCheckState(
                COLUMN_TOGGLE,
                Qt.Checked if str(path) in self._checked else Qt.Unchecked,
            )
            self.table.addTopLevelItem(item)
            self._check(item, path, verbose=verbose)

    def recheck(self) -> None:
        """«Check again»: relee la carpeta y **cuenta lo que ha hecho**.

        `refresh` solo por sí sola es invisible —si ningún veredicto ha
        cambiado, la tabla queda idéntica—, y un botón sin respuesta es un
        botón roto. Cuenta lo mismo que «Validate…», con el mismo detalle:
        lo único que las distingue es que aquélla pregunta contra qué base
        comprobar y ésta usa la que cada overlay ya tenía.
        """
        self._append(
            [
                RULE,
                "{time} · {title}".format(
                    time=datetime.now().strftime("%H:%M:%S"),
                    title=self.tr("checked again"),
                ),
            ]
        )
        self.refresh(verbose=True)
        if not self.table.topLevelItemCount():
            self._append(
                [f"  {GLYPH_WARN} " + self.tr("no overlay in this folder")]
            )

    def validate(self, paths, base_key: Optional[str]) -> None:
        """Comprueba los overlays dados contra la base elegida, y lo registra.

        `base_key` es lo que el usuario ha elegido; `None` significa «la
        cargada». La elección se recuerda mientras dure la sesión, así que
        refrescar la lista no la deshace. Acepta varias rutas porque la base
        se pregunta una sola vez: un proyecto tiene varios overlays de la
        misma placa y contestar lo mismo N veces no es una elección, es un
        peaje.
        """
        if isinstance(paths, str):
            paths = [paths]
        for path in paths:
            item = self._item_for(path)
            if item is None:
                continue
            self._chosen[path] = base_key
            self._check(item, Path(path), verbose=True)
            self.table.setCurrentItem(item)

    def _overlay_files(self) -> List[Path]:
        """Los overlays de la carpeta (ver `scan_files`)."""
        return scan_files(self._folder, OVERLAY_SUFFIXES, OVERLAY_SCAN_DEPTH)

    def _item_for(self, path: str) -> Optional[QTreeWidgetItem]:
        """La fila de un overlay por su ruta."""
        for index in range(self.table.topLevelItemCount()):
            item = self.table.topLevelItem(index)
            if item.data(COLUMN_FILE, ROLE_PATH) == path:
                return item
        return None

    def _check(
        self, item: QTreeWidgetItem, path: Path, verbose: bool = False
    ) -> None:
        """Comprueba un overlay y vuelca el resultado en su fila (y en el registro)."""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            item.setText(COLUMN_STATUS, self.tr("cannot be read"))
            item.setToolTip(COLUMN_STATUS, str(error))
            item.setForeground(COLUMN_STATUS, QColor(style.EDITOR_ERROR_ACCENT))
            return

        base, base_label = self._base_for(str(path))
        item.setText(COLUMN_BASE, base_label)

        result, diagnostics = self._service.analyze_source(
            text, fragment=True, overlay_base=base, overlay_checks=True
        )
        targets = self._service.overlay_targets(result, base)

        # Los objetivos no tienen columna propia: en un panel lateral se
        # comían el ancho del nombre del fichero, y lo único accionable que
        # dicen -que uno no exista en la base- es justo lo que el veredicto
        # ya cuenta. Siguen a mano en el aviso de la fila y en el registro.
        item.setToolTip(
            COLUMN_FILE,
            "  ".join(target.reference for target in targets)
            or self.tr("no target"),
        )
        perdidos = [t.reference for t in targets if not t.resolved]
        if base is not None and perdidos:
            item.setForeground(COLUMN_FILE, QColor(style.EDITOR_ERROR_ACCENT))
            item.setToolTip(
                COLUMN_FILE,
                self.tr("Not in this base: {targets}").format(
                    targets=", ".join(perdidos)
                ),
            )
        else:
            item.setForeground(COLUMN_FILE, QColor(style.GRAPH_COLOR_TEXT))

        self._set_status(item, base, diagnostics)
        if verbose:
            self._log_report(path, base, base_label, targets, diagnostics)

    def _base_for(self, path: str) -> Tuple[Optional[DeviceTreeNode], str]:
        """Contra qué base se comprueba este overlay, y cómo se llama.

        Por orden: lo que se haya elegido a mano para él, y si no, la base
        cargada. La elección hay que resolverla —de la clave al árbol— y
        quien sabe hacerlo es la ventana.
        """
        key = self._chosen.get(path)
        if key and self._resolver is not None:
            base = self._resolver(key)
            if base is not None:
                return base, Path(key).name
            return None, self.tr("{base} not found").format(base=Path(key).name)
        if self._base is None:
            return None, self.tr("no base chosen")
        return self._base, self._base_name(self._base)

    def _set_status(
        self,
        item: QTreeWidgetItem,
        base: Optional[DeviceTreeNode],
        diagnostics: Sequence[Diagnostic],
    ) -> None:
        """Resume los diagnósticos del overlay en una celda con su color."""
        if base is None:
            item.setData(COLUMN_STATUS, ROLE_VERDICT, GLYPH_WARN)
            item.setText(COLUMN_STATUS, self.tr("needs a base to be checked"))
            item.setForeground(COLUMN_STATUS, QColor(style.MUTED_TEXT_COLOR))
            item.setToolTip(
                COLUMN_STATUS,
                self.tr("Press «Validate…» and pick the base it applies to."),
            )
            return

        errores = sum(1 for d in diagnostics if d.severity is Severity.ERROR)
        avisos = sum(1 for d in diagnostics if d.severity is Severity.WARNING)
        item.setData(
            COLUMN_STATUS,
            ROLE_VERDICT,
            GLYPH_FAIL if errores else GLYPH_WARN if avisos else GLYPH_OK,
        )
        if errores:
            item.setText(
                COLUMN_STATUS,
                self.tr("{errors} errors · {warnings} warnings").format(
                    errors=errores, warnings=avisos
                ),
            )
            item.setForeground(COLUMN_STATUS, QColor(style.EDITOR_ERROR_ACCENT))
        elif avisos:
            item.setText(
                COLUMN_STATUS,
                self.tr("{warnings} warnings").format(warnings=avisos),
            )
            item.setForeground(COLUMN_STATUS, QColor(style.EDITOR_WARNING_ACCENT))
        else:
            item.setText(COLUMN_STATUS, self.tr("passed"))
            item.setForeground(COLUMN_STATUS, QColor(style.COLOR_DROP_OK))

        if diagnostics:
            item.setToolTip(
                COLUMN_STATUS,
                "\n".join(f"{d.line}: {d.message}" for d in diagnostics[:8]),
            )

    # ------------------------------------------------------------------
    # Registro
    # ------------------------------------------------------------------
    def _log_report(
        self,
        path: Path,
        base: Optional[DeviceTreeNode],
        base_label: str,
        targets,
        diagnostics: Sequence[Diagnostic],
    ) -> None:
        """Cuenta en el registro qué se ha comprobado, contra qué y cómo ha ido."""
        lines = [
            RULE,
            "{time} · {file}".format(
                time=datetime.now().strftime("%H:%M:%S"), file=path.name
            ),
        ]
        if base is None:
            lines.append(
                f"  {GLYPH_WARN} "
                + self.tr("no base: nothing was checked ({base})").format(
                    base=base_label
                )
            )
            self._append(lines)
            return

        lines.append(
            f"  {GLYPH_INFO} " + self.tr("base: {base}").format(base=base_label)
        )
        lines.append(
            f"  {GLYPH_INFO} "
            + self.tr("layer 6 — overlay targets ({count}):").format(
                count=len(targets)
            )
        )
        for target in targets:
            lines.append(
                "    {glyph} {reference}  {verdict}".format(
                    glyph=GLYPH_OK if target.resolved else GLYPH_FAIL,
                    reference=target.reference,
                    verdict=(
                        self.tr("→ {path}").format(path=target.resolved_path)
                        if target.resolved
                        else self.tr("NOT FOUND in this base")
                    ),
                )
            )
        if not targets:
            lines.append(
                f"    {GLYPH_WARN} " + self.tr("this file declares no target")
            )

        perdidos = sum(1 for t in targets if not t.resolved)
        lines.append(
            f"  {GLYPH_FAIL if perdidos else GLYPH_OK} "
            + (
                self.tr("layer 6: {count} targets do not exist in this base").format(
                    count=perdidos
                )
                if perdidos
                else self.tr("layer 6: passed, every target exists in this base")
            )
        )

        errores = [d for d in diagnostics if d.severity is Severity.ERROR]
        avisos = [d for d in diagnostics if d.severity is Severity.WARNING]
        if not errores and not avisos:
            lines.append(
                f"  {GLYPH_OK} "
                + self.tr("all layers: passed, nothing to report")
            )
        else:
            lines.append(
                f"  {GLYPH_FAIL if errores else GLYPH_WARN} "
                + self.tr("all layers: {errors} errors, {warnings} warnings").format(
                    errors=len(errores), warnings=len(avisos)
                )
            )
            for diagnostic in (errores + avisos)[:_MAX_DETALLE]:
                lines.append(
                    "    {glyph} {line}: {message}".format(
                        glyph=(
                            GLYPH_FAIL
                            if diagnostic.severity is Severity.ERROR
                            else GLYPH_WARN
                        ),
                        line=diagnostic.line,
                        message=diagnostic.message,
                    )
                )
            restantes = len(errores) + len(avisos) - _MAX_DETALLE
            if restantes > 0:
                lines.append(
                    f"    {GLYPH_INFO} "
                    + self.tr("…and {count} more, open the file to see them all")
                    .format(count=restantes)
                )
        self._append(lines)

    def _append(self, lines: List[str]) -> None:
        """Publica el informe: quien lo enseña es el panel de registro.

        No se guarda aquí ninguna copia. El registro de comprobaciones y el
        de diagnósticos se leen igual —«qué ha salido de lo último que se ha
        mirado»— y comparten sitio en la franja inferior, así que este
        widget solo cuenta lo que ha hecho.
        """
        self.reportReady.emit("\n".join(lines) + "\n")

    # ------------------------------------------------------------------
    # Acciones
    # ------------------------------------------------------------------
    def _on_validate_clicked(self) -> None:
        """Pide comprobar lo seleccionado eligiendo su base.

        Sin selección se comprueban todos: es lo que quiere decir pulsar
        «Validate» sin haber elegido nada, y obligar a un «seleccionar todo»
        previo solo añade un paso.
        """
        paths = self.selected_paths()
        if paths:
            self.validateRequested.emit(paths)

    def selected_paths(self) -> List[str]:
        """Rutas de las filas seleccionadas, o todas si no hay ninguna.

        El mismo criterio que «Validate»: pulsar una acción sin haber
        elegido nada quiere decir «sobre todo», y obligar a un
        «seleccionar todo» previo solo añade un paso.
        """
        items = self.table.selectedItems() or [
            self.table.topLevelItem(i) for i in range(self.table.topLevelItemCount())
        ]
        paths: List[str] = []
        for item in items:
            path = item.data(COLUMN_FILE, ROLE_PATH)
            if path and path not in paths:
                paths.append(path)
        return paths

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        """Recuerda qué overlays quedan marcados y avisa de ello."""
        if column != COLUMN_TOGGLE:
            return
        path = item.data(COLUMN_FILE, ROLE_PATH)
        if not path:
            return
        if item.checkState(COLUMN_TOGGLE) == Qt.Checked:
            self._checked.add(path)
        else:
            self._checked.discard(path)
        self.checkedChanged.emit()

    def checked_paths(self) -> List[str]:
        """Overlays con el interruptor puesto: los que entran en la compilación.

        Distinto de `selected_paths`, que es lo que esté seleccionado en la
        tabla: seleccionar es mirar y marcar es decidir, y la compilación va
        con lo decidido, que sobrevive a que se pulse en otra fila.
        """
        return [
            path
            for path in (
                self.table.topLevelItem(i).data(COLUMN_FILE, ROLE_PATH)
                for i in range(self.table.topLevelItemCount())
            )
            if path in self._checked
        ]

    def _on_activated(self, item: QTreeWidgetItem, _column: int = 0) -> None:
        """Pide abrir el overlay elegido."""
        path = item.data(COLUMN_FILE, ROLE_PATH)
        if path:
            self.overlayActivated.emit(path)

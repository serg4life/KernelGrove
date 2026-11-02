"""Colores y medidas (tamaños/posición de ventanas) usados en código Python.

Complementa a `theme.py`, que es la hoja QSS del *chrome* de los widgets
estándar (botones, combos, pestañas...). Lo que vive aquí es lo que QSS no
puede cubrir: colores usados en `QPainter`/`QTextCharFormat` (resaltadores,
el grafo dibujado a mano, marcadores de diagnóstico) y tamaños de ventana
fijados por código (`resize`, `setMinimumWidth`...). Un widget no debe
llevar un color o una medida incrustados — se define aquí, con nombre, y se
importa donde haga falta, para poder cambiar el aspecto desde un único
sitio.
"""

from __future__ import annotations

from kernelgrove.gui import theme

# ----------------------------------------------------------------------
# Tamaños y posición de ventanas
# ----------------------------------------------------------------------
MAIN_WINDOW_SIZE = (1460, 920)
SOC_PROPERTIES_DIALOG_SIZE = (560, 420)
# El catálogo de la base, que es una ventana flotante y no una vista central:
# ancha porque cada ficha lleva cuatro columnas de datos, y alta porque se
# recorre una lista de ~3700 entradas. Menos que la ventana principal, para
# que se vea que está encima de ella y no la sustituye.
DATABASE_WINDOW_SIZE = (1000, 680)
# La ficha de un binding: alta y no muy ancha, porque lo que lleva es una
# lista de propiedades y lo que se recorre es hacia abajo.
SCHEMA_DIALOG_SIZE = (720, 620)
# Las licencias (`gui/widgets/legal_dialog.LegalDialog`). Alto: es un
# documento que hay que poder leer, y en un cuadro bajo el desplazamiento
# se come la lectura. Ancho: el de una columna de texto, no el de la
# ventana — una línea de 200 caracteres no se sigue con la vista.
LEGAL_DIALOG_SIZE = (680, 620)
# Bloque de controlador en `SocPropertiesDialog`: más ancho que el del grafo
# (`GRAPH_BLOCK_WIDTH`) porque aquí es lo único que hay que leer -sin ficha
# ni tooltip constante al lado- y un compatible como "xlnx,zynq-7000-i2c" no
# cabe en 78px.
SOC_BLOCK_SIZE = (150, 44)
SOC_BLOCK_SPACING = 6
# La ficha del Inspector es estrecha por diseño (columna lateral, 360px por
# defecto): el diálogo del grafo reusa el mismo ancho en vez de uno propio.
NODE_INSPECTOR_DIALOG_SIZE = (400, 560)
# Paleta de comandos: ancha para que quepa la ruta de un fichero, y no muy
# alta porque solo se enseñan `MAX_RESULTS` filas.
COMMAND_PALETTE_SIZE = (620, 380)
# Banda alrededor del contenido de la paleta. Hace dos cosas a la vez: deja
# ver la esquina redondeada del fondo -sin ella, el campo y la lista, que
# son cuadrados, asoman por las esquinas- y da dónde agarrarla para moverla,
# que va sin marco de ventana y por tanto sin barra de título.
COMMAND_PALETTE_MARGIN = 7
# Ancho de la caja de búsqueda de la franja de arriba. Fijo: es lo que la
# mantiene centrada y del mismo tamaño se estire la ventana o no, como la
# barra de comandos de cualquier IDE.
COMMAND_PALETTE_BUTTON_WIDTH = 320

# Anchos mínimos de controles concretos (no de ventanas, pero es el mismo
# tipo de medida "de cuánto ocupa algo en pantalla").
SOC_COMBO_MIN_WIDTH = 120
# Tope de ancho de los filtros del catálogo. Sin él, el del fabricante pide
# lo que mida el nombre más largo de los 541 y se come la fila entera.
DB_FILTER_MAX_WIDTH = 190
FIND_BAR_COUNT_LABEL_MIN_WIDTH = 70
# Iconos de los indicadores de la franja de estado. Pequeños: la franja
# mide 22 px y no puede crecer.
STATUS_ICON_SIZE = 13
# Iconos de la botonera flotante del lienzo y de los botones de acción de
# los paneles (compilar, ver en el grafo…).
CANVAS_ICON_SIZE = 15
ACTION_ICON_SIZE = 16
# Altura del logotipo del cartel de bienvenida (`gui/brand.py`). Es la única
# pantalla vacía de la aplicación y la única que se permite la marca; a esta
# altura el nombre se lee sin convertirse en una portada.
EMPTY_LOGO_HEIGHT = 56

# Franja de iconos de la izquierda (`ActivityBar`) y tamaño de sus iconos
# dibujados a mano (`widgets/icons.py`). 22 px sobre una franja de 46: es lo
# que mide el icono de la barra de actividad de VS Code, y con 18 sobre 40
# los trazos -que son de un píxel- quedaban tan finos que la sección activa
# no se distinguía de las demás a un vistazo.
ACTIVITY_BAR_WIDTH = 46
ACTIVITY_ICON_SIZE = 22

# Lo que en C++ es `QWIDGETSIZE_MAX`, la constante que Qt entiende como "sin
# límite": PySide6 no la exporta, así que se escribe aquí una vez con su
# valor real en vez de repetir el número mágico donde haga falta devolverle
# a un panel el ancho libre después de haberlo fijado (`setFixedWidth`).
WIDGET_SIZE_MAX = 16777215

# Ancho de un dock lateral plegado (`MainWindow._toggle_inspector`,
# `VisualizerTab._on_palette_collapse_toggled`): lo justo para que quepan su
# cabecera y la flecha de volver a desplegarlo, nada de contenido.
DOCK_COLLAPSED_WIDTH = 34

# Altura de cada fila del desplegable de opciones del combo editable de
# "Conectar dispositivo" (`BindingDelegate`) — el propio combo ya hereda una
# altura cómoda de la fila del árbol (ver `QTreeView::item` en `theme.py`),
# pero su popup es una ventana aparte y por defecto salía con las filas tan
# apretadas como una lista sin estilo.
GENERATOR_CONNECT_POPUP_ITEM_HEIGHT = 30

# ----------------------------------------------------------------------
# Colores compartidos entre varios widgets
# ----------------------------------------------------------------------
# Texto atenuado (subtítulos, contadores, la etiqueta de versión...) — antes
# repetido igual en details_panel.py, find_bar.py y editor_tab.py.
MUTED_TEXT_COLOR = theme.TEXT_MUTED
# El acento **sobre** fondo (`--accent-text` de la web), para texto e
# iconos: es otro tono que el del relleno porque tiene que leerse encima del
# fondo en vez de debajo de un texto blanco.
ACCENT_TEXT_COLOR = theme.ACCENT_TEXT
# Y lo contrario: lo que va **encima** del relleno de acento (el texto de un
# botón primario, y por tanto también su icono).
ON_ACCENT_COLOR = theme.ACCENT_FG
# Apagado, pero todavía legible: 4,8:1 sobre el fondo de la ventana y 4,5:1
# sobre el de la barra de estado, por encima del mínimo de 4,5 que pide WCAG
# AA para texto pequeño. Era `#5c6370` (2,5:1), que no se leía.
FAINT_TEXT_COLOR = theme.TEXT_FAINT
# Comentarios del editor. Van aparte de `FAINT_TEXT_COLOR` a propósito: son
# la única documentación que cabe dentro de un device tree (qué pin es qué,
# por qué ese valor), así que no pueden ser lo menos legible de la pantalla.
# 5,1:1 sobre el fondo del editor.
EDITOR_COMMENT_COLOR = "#7c8798"

# Turquesa: marca lo que viene de la sesión de edición
# (Generador/Visualizador) y no existe todavía en el `.dts` real — línea
# añadida en "DTS completo" (`dts_editor.ADDED_LINE_COLOR`) y borde de nodo
# conectado en el grafo (`tree_graph.COLOR_GENERATED`).
#
# Ha pasado por tres colores, y cada cambio fue por colisión: amarillo se
# confundía con los avisos WARNING; morado, que lo sustituyó, dejó de servir
# en cuanto el morado dioxazina pasó a ser el acento de marca (`theme.ACCENT`)
# y por tanto el color de "lo activo" — un nodo generado y un nodo
# seleccionado no pueden ser del mismo color. El turquesa no coincide con
# ninguna de las dos familias ni con el verde de "destino válido"
# (`COLOR_DROP_OK`), que es lo único parecido en el grafo.
COLOR_GENERATED_BRIGHT = "#3fbfcf"  # borde de nodo en el grafo
COLOR_GENERATED_DARK = "#13323a"  # fondo de línea añadida en el editor

# Verde de confirmación (arrastre válido sobre un nodo del grafo).
COLOR_DROP_OK = theme.SUCCESS

# El verde del «✓ correcto contra el binding» (`#cardOk` en la hoja). Lo usa
# también el distintivo «REQUIRED» del inspector, para que las dos cosas que
# dicen «esto está como el binding pide» sean del mismo verde. No entra en
# `refresh()` a propósito: `theme.OK_GREEN` es el único color con significado
# que la web fija y vale igual para las tres pieles, así que no se rederiva.
CARD_OK_COLOR = theme.OK_GREEN

# ----------------------------------------------------------------------
# Grafo del visualizador (`widgets/tree_graph.py`)
# ----------------------------------------------------------------------
# Un nodo es una **ficha**, no un círculo con la etiqueta debajo: cabecera
# con el nombre y cuerpo con sus propiedades, que es lo que pide el diseño
# del editor visual de nodos y lo que hace que el grafo diga algo sin tener
# que abrir el inspector. El ancho es fijo -190, el del diseño- para que la
# columna de valores caiga siempre en el mismo sitio; el alto lo pone el
# número de filas.
GRAPH_NODE_WIDTH = 190
# La ficha del SoC es más ancha que las demás: es la única que lleva bloques
# dentro, y a 190px una rejilla de veinte salía de dos columnas y más de
# 380px de alto -una tira estrecha en vez de un paquete-. Con este ancho y
# los bloques etiquetados solo con el nombre del nodo (`spi`, `i2c`) caben
# cuatro por fila y la ficha queda aproximadamente cuadrada.
GRAPH_SOC_NODE_WIDTH = 300
GRAPH_NODE_HEADER_HEIGHT = 24
GRAPH_NODE_ROW_HEIGHT = 15
GRAPH_NODE_ROW_PADDING = 6
GRAPH_NODE_PADDING_X = 9
# Cuántas propiedades caben en la ficha. Más allá de esto la ficha crece
# hasta tapar a sus vecinas y deja de leerse de un vistazo; el resto sigue
# estando en el inspector y en el tooltip.
GRAPH_NODE_MAX_ROWS = 4
# Los puntos de conexión de la ficha (arriba el padre, abajo los hijos).
GRAPH_PORT_RADIUS = 3.5
# Esquina de la ficha: la de la piel, no una propia. Con `obsidian` puesta
# el grafo sale a escuadra como el resto de la ventana.
GRAPH_NODE_CORNER_RADIUS = theme.RADIUS_ITEM
GRAPH_TOGGLE_BADGE_RADIUS = 8
# Separación entre fichas: el ancho/alto de una más el aire que las
# despega. Con las medidas de un círculo se solapaban unas con otras.
GRAPH_HORIZONTAL_GAP = 232
GRAPH_VERTICAL_GAP = 150
# Aire mínimo entre el borde inferior de una ficha y el superior de la de
# abajo. `GRAPH_VERTICAL_GAP` mide de centro a centro, así que por sí solo
# no basta en cuanto una ficha crece: la del SoC con veinte bloques dentro
# pasa de 380px de alto y se comía a sus propios hijos. El reparto usa el
# mayor de los dos (ver `TreeGraphView._measure_levels`), así que con fichas
# normales la separación es exactamente la de siempre.
GRAPH_VERTICAL_EDGE_GAP = 60
# Tope de ampliación al encuadrar (`TreeGraphView.fit`). Sin él, un árbol de
# un solo nodo se ampliaba hasta llenar la vista.
GRAPH_MAX_FIT_ZOOM = 1.8

GRAPH_MIN_ZOOM = 0.1
GRAPH_MAX_ZOOM = 8.0

# Los colores de un nodo dicen **qué es**, no si está activo: el acento de
# marca (`theme.ACCENT`) queda reservado para el estado —seleccionado, con
# el foco—, aquí y en el resto de la interfaz. Por eso el SoC no es morado
# aunque sea la pieza principal: destaca por tamaño, posición y etiqueta, no
# por llevarse el color de marca. La jerarquía la da la claridad: el paquete
# es el más claro, un nodo corriente el más oscuro.
GRAPH_COLOR_EDGE = "#2f3742"
GRAPH_COLOR_TEXT = theme.TEXT
GRAPH_COLOR_ROOT = "#333b48"  # el paquete del SoC: grafito, el más claro
GRAPH_COLOR_NODE = "#242931"
GRAPH_COLOR_CONTROLLER = "#25473a"
GRAPH_COLOR_INCLUDE_OK = "#2c3850"  # contenido traído de otro fichero
GRAPH_COLOR_INCLUDE_MISSING = "#4d2529"
GRAPH_SCENE_BACKGROUND = theme.SUNKEN
# Cuerpo de la ficha. La cabecera lleva el color semántico del nodo (qué
# es), y el cuerpo la superficie hundida: así el color dice lo mismo que
# decía el círculo entero sin teñir las propiedades.
GRAPH_CARD_BG = theme.SUNKEN
GRAPH_NODE_DEFAULT_BORDER = "#39414d"
# Plegado: un borde algo más claro. No lleva el acento de marca —eso es
# "seleccionado"— porque además la insignia «+» ya dice que hay algo dentro.
GRAPH_NODE_COLLAPSED_BORDER = "#4a5361"
# Seleccionado: el acento, aquí y en cualquier otro sitio de la interfaz.
GRAPH_NODE_SELECTED_BORDER = theme.ACCENT
GRAPH_TOGGLE_BADGE_BG = theme.RAISED
GRAPH_TOGGLE_BADGE_BORDER = theme.LINE_STRONG
GRAPH_TOGGLE_BADGE_TEXT = theme.TEXT_MUTED
# Tamaño en puntos de la etiqueta de un nodo. El lienzo se escala con el
# zoom, así que lo que aquí parece pequeño puede acabar enorme al encuadrar.
GRAPH_LABEL_POINT_SIZE = 7.5
# Las filas de propiedades, un punto por debajo del nombre.
GRAPH_ROW_POINT_SIZE = 6.5

# Rejilla de fondo del grafo (`TreeGraphView.drawBackground`): apenas por
# encima del fondo para no competir visualmente con los nodos, con una línea
# algo más marcada cada `GRAPH_GRID_MAJOR_EVERY` para dar referencia de
# escala al hacer zoom, como en los editores de nodos habituales.
GRAPH_GRID_MINOR_COLOR = "#161a1f"
GRAPH_GRID_MAJOR_COLOR = "#1c2128"
GRAPH_GRID_SIZE = 40
GRAPH_GRID_MAJOR_EVERY = 5

# Halo que marca, mientras se arrastra un compatible desde la paleta,
# todos los nodos del grafo donde soltarlo sería válido (no solo el que está
# bajo el cursor en cada instante, que ya se marca aparte con un borde verde
# — ver `COLOR_DROP_OK`). Es un `QGraphicsDropShadowEffect` con desplazamiento
# cero, que es como Qt hace un resplandor uniforme alrededor de la forma.
GRAPH_DROP_TARGET_GLOW_COLOR = COLOR_GENERATED_BRIGHT
GRAPH_DROP_TARGET_GLOW_RADIUS = 28

# Bloques de "controlador propio del SoC" (`DeviceTreeNode.soc_defined`):
# pequeños indicadores dentro de la ficha del SoC, no fichas propias con
# arista -eso sigue siendo "el resto", lo que no viene del `.dtsi` del SoC
# sino de un chip conectado. Verde relleno si está encendido, sin relleno
# -solo su borde, los mismos tokens que cualquier ficha apagada- si no: la
# falta de color es justo la señal de "apagado" que pide el diseño. El
# tamaño es pequeño a propósito, son un indicador y no una ficha con
# propiedades -el detalle completo sigue en el tooltip al pasar por encima,
# igual que el resto del grafo.
GRAPH_BLOCK_HEIGHT = 22
GRAPH_BLOCK_GAP = 6
# El ancho de cada bloque sale de repartir el de la ficha entre las columnas
# (`tree_graph.block_rects`), no de una constante propia: son los inquilinos
# de esa ficha y tienen que llenarla.
GRAPH_BLOCK_COLUMNS = 4
# No entra en `refresh()`: mismo motivo que `CARD_OK_COLOR`, es el verde con
# significado propio y vale igual en las tres pieles.
GRAPH_BLOCK_ENABLED_BG = theme.OK_GREEN
GRAPH_BLOCK_ENABLED_TEXT = "#ffffff"

# ----------------------------------------------------------------------
# Editor DTS (`widgets/dts_editor.py`)
# ----------------------------------------------------------------------
# Fondo de línea según la severidad del diagnóstico.
EDITOR_SEVERITY_ERROR_BG = "#3a1f22"
EDITOR_SEVERITY_WARNING_BG = "#3a3018"
EDITOR_SEVERITY_INFO_BG = "#1c2a3c"

EDITOR_BRACE_MATCH_COLOR = "#2b6349"
EDITOR_BRACE_ORPHAN_COLOR = "#8a3239"
EDITOR_BRACE_MATCH_FOREGROUND = "#ffffff"
EDITOR_FIND_MATCH_COLOR = "#3b3520"
EDITOR_FIND_CURRENT_MATCH_COLOR = "#7a5f1c"
EDITOR_CURRENT_LINE_BG = "#171b21"
# Nodo bajo el ratón mientras se elige el objetivo de un overlay. Es el
# relleno del acento porque marca "lo que está a punto de quedar elegido",
# que es justo para lo que sirve el acento en el resto de la interfaz.
EDITOR_NODE_HINT_BG = theme.ACCENT_FILL
EDITOR_LINE_NUMBER_BG = theme.SUNKEN

# Los tres colores de "severidad" que se repiten en más de un sitio del
# editor (número de línea de un diagnóstico, cabecera de nodo, comentarios).
EDITOR_ERROR_ACCENT = theme.DANGER
EDITOR_WARNING_ACCENT = theme.WARNING
EDITOR_INFO_ACCENT = FAINT_TEXT_COLOR
# Azul de "esto se puede pulsar" dentro del código: el subrayado del include
# bajo Ctrl y la dirección de unidad de un nodo. Va aparte del acento de
# marca a propósito — el morado ya significa "seleccionado/activo" en la
# interfaz, y dentro del editor tiene además al lado el magenta de las
# propiedades (`EDITOR_SYNTAX_PROPERTY`): tres morados seguidos no se
# distinguen. El azul de enlace es además la convención que todo el mundo ya
# lee como "pulsable".
EDITOR_LINK_COLOR = "#61afef"
EDITOR_INCLUDE_HINT_COLOR = EDITOR_LINK_COLOR


EDITOR_FOLD_MARKER_WIDTH = 14
EDITOR_FOLD_MARKER_COLOR = MUTED_TEXT_COLOR

# Guía de sangrado del panel de carpetas: la línea vertical que dice de qué
# carpeta cuelga cada fila. Apagada a propósito —es una ayuda de lectura, no
# contenido—, y se deriva del texto sobre el panel para que siga a la piel.
EXPLORER_INDENT_GUIDE = theme._mix(theme.TEXT, theme.PANEL, 0.16)

# Barra de cambios del margen: qué líneas no están en la versión preparada
# (ver `DtsEditor.set_change_lines`). Mismos colores que VS Code, que es de
# donde viene el gesto y donde ya están aprendidos: **verde** lo añadido,
# **azul** lo modificado, **rojo** donde se ha borrado algo. En concreto sus
# `editorGutter.addedBackground` / `modifiedBackground` /
# `deletedBackground` del tema Dark Modern.
#
# El azul del modificado es la única elección que sorprende, y es
# deliberada: el ámbar que había aquí antes es el color de WARNING en el
# resto del editor —número de línea, fondo de la línea, marca del
# minimapa—, así que una línea tocada y una línea con un aviso se leían
# igual. Este azul no lo usa nada más en el margen.
#
# Ancho el suyo también, 3 px. Lo que hacía que no se viera no era el
# grosor sino el color: en ámbar apagado sobre un margen oscuro se confundía
# con el número de línea de un aviso. Con el verde y el azul saturados de VS
# Code, 3 px se ven igual de bien y no le comen sitio al número.
EDITOR_CHANGE_BAR_WIDTH = 3
# Lado del triángulo que marca un borrado. No depende del ancho de la barra
# —a 3 px sería una mota— sino de lo que se ve: es la única marca que tiene
# que reconocerse por su forma y no por su posición.
EDITOR_CHANGE_DELETED_SIZE = 7
EDITOR_CHANGE_ADDED = theme.CHANGE_ADDED
EDITOR_CHANGE_MODIFIED = theme.CHANGE_MODIFIED
EDITOR_CHANGE_DELETED = theme.CHANGE_DELETED

# Minimapa: la vista en miniatura del fichero entero, pegada al borde
# derecho del editor. Cada línea es una barra del ancho de su contenido —no
# se dibuja el texto: a esta escala no se lee, y renderizarlo costaría una
# pasada del resaltador por cada repintado—, y encima van las marcas, con el
# mismo reparto que hace VS Code: los cambios de git en una franja fina
# pegada al borde izquierdo (sus `minimapGutter.*`, que valen lo mismo que
# los del margen) y los errores y avisos como una **banda sobre la línea
# entera** (sus `minimap.errorHighlight` / `warningHighlight`), no como una
# marca al borde: un error tiene que verse aunque el minimapa esté lleno.
MINIMAP_WIDTH = 76
MINIMAP_BG = theme.SUNKEN
MINIMAP_LINE_COLOR = "#3a4049"
# Recuadro de lo que se está viendo ahora mismo en el editor.
MINIMAP_VIEWPORT_BG = theme.ACCENT_FILL
MINIMAP_VIEWPORT_BORDER = theme.ACCENT_DIM
# Anchura de la franja de cambios de git, al borde izquierdo del minimapa.
MINIMAP_MARK_WIDTH = 3
# Bandas de diagnóstico sobre la línea, en los colores de VS Code. INFO no
# entra: es la severidad más numerosa con diferencia (viene apagada de
# fábrica en el filtro por eso mismo) y una banda por cada una dejaría el
# minimapa pintado de arriba abajo sin decir nada.
MINIMAP_ERROR_HIGHLIGHT = "#ff1212"
MINIMAP_WARNING_HIGHLIGHT = "#cca700"
# Opacidad de esas bandas: lo bastante para verse sobre la silueta, lo
# bastante poco para no borrarla.
MINIMAP_HIGHLIGHT_ALPHA = 170
# Alto máximo de una línea en el minimapa. Sin tope, un fichero de veinte
# líneas se estira hasta llenar la franja y deja de parecer un mapa: cada
# línea sale como un bloque de treinta píxeles. Con él, un fichero corto
# ocupa la parte de arriba y ya está.
MINIMAP_MAX_LINE_HEIGHT = 4.0

# Resaltado de sintaxis DTS (`DtsHighlighter`): (color, negrita).
EDITOR_SYNTAX_LABEL = (EDITOR_WARNING_ACCENT, False)  # cabecera de nodo "label:"
EDITOR_SYNTAX_UNIT_ADDRESS = (EDITOR_LINK_COLOR, True)  # "nombre@dirección {"
EDITOR_SYNTAX_PROPERTY = ("#c678dd", False)
EDITOR_SYNTAX_STRING_VALUE = ("#98c379", False)
EDITOR_SYNTAX_CELL_VALUE = ("#d19a66", False)
EDITOR_SYNTAX_REFERENCE = ("#56b6c2", False)  # "&label"
EDITOR_SYNTAX_DIRECTIVE = ("#7f848e", False)  # "#include", "/omit-if-no-ref/"...
EDITOR_SYNTAX_COMMENT = (EDITOR_COMMENT_COLOR, False)

# Familias monoespaciadas del editor, por orden de preferencia. La última
# existe en cualquier sistema; las primeras son las que de verdad se quieren
# si están instaladas.
EDITOR_FONT_FAMILIES = [
    "JetBrains Mono",
    "SF Mono",
    "Cascadia Mono",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "monospace",
]

# ----------------------------------------------------------------------
# Vista JSON (`widgets/json_view.py`)
# ----------------------------------------------------------------------
JSON_KEY_COLOR = "#7cb7ff"
JSON_STRING_COLOR = "#b5cea8"
JSON_NUMBER_COLOR = "#d19a66"
JSON_LITERAL_COLOR = "#c678dd"

# ----------------------------------------------------------------------
# Botón de cierre de pestaña (`widgets/tab_close_button.py`)
# ----------------------------------------------------------------------
TAB_CLOSE_HOVER_BG = "#4a2a2e"
TAB_CLOSE_HOVER_STROKE = theme.TEXT
TAB_CLOSE_STROKE = MUTED_TEXT_COLOR

# ----------------------------------------------------------------------
# Paleta de compatibles del visualizador (`widgets/binding_palette.py`)
# ----------------------------------------------------------------------
PALETTE_ITEM_BG = theme.RAISED
PALETTE_ITEM_BORDER = theme.LINE_STRONG
PALETTE_ITEM_TEXT = GRAPH_COLOR_TEXT
PALETTE_ITEM_SELECTED_BG = theme.ACCENT_FILL
# Cuántas columnas de nodos muestra la paleta, y el tamaño de cada chip.
PALETTE_COLUMNS = 2
PALETTE_ITEM_SIZE = (190, 46)
# Ancho fijo de la cuadrícula: `PALETTE_COLUMNS * PALETTE_ITEM_SIZE[0]` más
# margen para el borde/scrollbar de cada ítem. Sin fijarlo, la cuadrícula se
# estira al ancho que le dé el `QSplitter` del visualizador -habitualmente
# bastante menos de 2 columnas de 190px-, así que en vez de dos columnas
# aparecía una sola y encima con menos alto del que hacía falta (ver
# `_DraggableList.sync_height`, que sí asume `PALETTE_COLUMNS` columnas).
PALETTE_GRID_WIDTH = 404

# Ancho inicial del panel entero de la paleta en el splitter del
# Visualizador (`VisualizerTab`), no solo de la cuadrícula: algo mayor que
# `PALETTE_GRID_WIDTH` para que quede aire alrededor en vez de justo pegada
# al borde.
PALETTE_DEFAULT_WIDTH = 460

# Cabecera desplegable de cada grupo (`widgets/binding_groups.py`).
PALETTE_SECTION_HEADER_BG = "transparent"
PALETTE_SECTION_HEADER_TEXT = theme.TEXT_MUTED
PALETTE_SECTION_HEADER_HOVER_BG = theme.HOVER
# El icono del grupo (el "logo") va en el acento, no en el gris atenuado del
# texto de la cabecera: es lo primero que se lee al recorrer la lista.
PALETTE_GROUP_ICON_SIZE = 16

# ----------------------------------------------------------------------
# Explorador de la base de datos (`tabs/database_tab.py`)
# ----------------------------------------------------------------------
# La ficha de una entrada del catálogo. Alto fijo -dos filas de texto más
# el aire- porque la lista lleva `setUniformItemSizes`: son ~3700 entradas
# y medir cada una obligaría a recorrerlas todas al montar.
DB_CARD_HEIGHT = 132
# La ficha de un binding no lleva pie: ni frecuencia ni los dos botones,
# así que acaba en la descripción y mide lo que ocupa lo que enseña.
DB_BINDING_CARD_HEIGHT = 96
DB_CARD_PADDING = 10
# Los dos botones del pie de la ficha («Load DTS», «Visual Graph»). El
# delegado los pinta, así que su tamaño va aquí y no en una hoja de estilos.
# Con sitio para su icono y para el rótulo entero: son las dos acciones de
# la ficha y a 96x22 quedaban como dos etiquetas, no como dos botones.
DB_CARD_BUTTON_WIDTH = 128
DB_CARD_BUTTON_HEIGHT = 30
DB_CARD_BUTTON_ICON = 15
DB_CARD_SPACING = 3
DB_CARD_ICON_BOX = 36
DB_SEARCH_WIDTH = 260
# Un punto por debajo de la interfaz: las etiquetas de columna y la
# insignia del tipo, que son rótulo y no dato.
DB_SMALL_POINT_SIZE = 7.0
# La descripción, el reloj y los rótulos de los botones. Un punto por
# encima del rótulo de columna: son texto que se lee, no un encabezado.
DB_TEXT_POINT_SIZE = 8.0
DB_MONO_FAMILY = EDITOR_FONT_FAMILIES[0]
DB_CARD_RADIUS = theme.RADIUS_ITEM
DB_CARD_BG = theme.BG_ELEVATED
DB_CARD_HOVER_BG = theme.HOVER
DB_CARD_SELECTED_BG = theme.ACCENT_FILL
DB_CARD_BORDER = theme.BORDER
DB_CARD_SELECTED_BORDER = theme.ACCENT
DB_CARD_TITLE = theme.TEXT
DB_CARD_ICON_BG = theme.RAISED
DB_CARD_ICON_FG = theme.TEXT_MUTED
DB_CARD_ACTION_BG = theme.ACCENT
DB_CARD_ACTION_FG = theme.ACCENT_FG
# Los dos botones de la ficha responden al ratón **ellos**, no la fila: el
# relleno aclara su acento (el mismo tono que usa el QSS para un botón
# primario) y el de borde se levanta sobre la superficie que se pulsa. Su
# fondo en reposo es el de la ficha sin señalar, para que pasar por encima de
# la fila no los tiña de camino.
DB_CARD_ACTION_HOVER_BG = theme.ACCENT_HOVER
DB_CARD_BUTTON_HOVER_BG = theme.RAISED

# ----------------------------------------------------------------------
# Panel de versiones (`widgets/git_panel.py`)
# ----------------------------------------------------------------------
# Color de la letra de estado de cada fichero cambiado. Los mismos tres de
# siempre —aviso, correcto, error— porque significan lo mismo que en el
# resto de la interfaz: algo tocado, algo nuevo, algo que ya no está.
GIT_STATUS_COLORS = {
    "M": theme.WARNING,
    "A": theme.SUCCESS,
    "R": theme.WARNING,
    "D": theme.DANGER,
    # Lo que git aún no sigue es un fichero **nuevo**, y nuevo es verde:
    # el mismo criterio que VS Code (`gitDecoration.untrackedResource`) y el
    # mismo color que una alta ya preparada, que es en lo que se convierte.
    "?": theme.SUCCESS,
}
GIT_STATUS_DEFAULT_COLOR = MUTED_TEXT_COLOR

# Cuántas versiones se listan de una vez. Sobra para la historia de un
# proyecto de device trees; abrir una carpeta que además es un repositorio
# grande no puede volcar cien mil filas en la lista.
GIT_VERSION_LIMIT = 200

# Resaltado del diff (`DiffHighlighter`): (color, negrita).
DIFF_SYNTAX_ADDED = (theme.SUCCESS, False)
DIFF_SYNTAX_REMOVED = (theme.DANGER, False)
DIFF_SYNTAX_HUNK = (EDITOR_LINK_COLOR, False)
DIFF_SYNTAX_HEADER = (MUTED_TEXT_COLOR, True)

# Resaltado del registro de overlays (`OverlayLogHighlighter`): (color,
# negrita). Las reglas van por **glifo** al principio de la línea y no por
# palabra: el informe está traducido, y un color que dependiera de leer
# «passed» se apagaría en cuanto se cambiara de idioma.
LOG_SYNTAX_HEADER = (ACCENT_TEXT_COLOR, True)
LOG_SYNTAX_OK = (theme.SUCCESS, False)
LOG_SYNTAX_ERROR = (theme.DANGER, False)
LOG_SYNTAX_WARNING = (theme.WARNING, False)
LOG_SYNTAX_DETAIL = (FAINT_TEXT_COLOR, False)


# ----------------------------------------------------------------------
# Cambio de modo claro/oscuro
# ----------------------------------------------------------------------
# Todo lo de arriba son los valores del modo con el que arranca el módulo.
# `refresh()` los vuelve a calcular cuando `theme.set_mode` cambia de modo:
# el QSS lo recompone `theme.stylesheet()`, pero estos son los colores que
# usan los `QPainter` (el grafo, el resaltador, el minimapa), donde la hoja
# de estilos no llega.
#
# Los que llevan tono propio —el verde de un controlador, el magenta de una
# propiedad— no se pueden derivar de los tokens, así que van en pares
# (claro, oscuro). Los grises sí se derivan, mezclando texto y fondo, para
# que sigan a la marca sin repetir una tabla de grises por modo.
_PAIRS = {
    # Comentarios del editor: la única documentación que cabe dentro de un
    # device tree, así que no pueden ser lo menos legible de la pantalla.
    "EDITOR_COMMENT_COLOR": ("#6b7280", "#7c8798"),
    # Turquesa de "viene de la sesión de edición, no del `.dts`".
    "COLOR_GENERATED_BRIGHT": ("#0d9aa8", "#3fbfcf"),
    "COLOR_GENERATED_DARK": ("#d9f2f5", "#13323a"),
    # Grafo: los rellenos dicen qué es cada nodo, no si está activo.
    "GRAPH_COLOR_ROOT": ("#d8dae0", "#333b48"),
    "GRAPH_COLOR_NODE": ("#edeef1", "#242931"),
    "GRAPH_COLOR_CONTROLLER": ("#d6ece0", "#25473a"),
    "GRAPH_COLOR_INCLUDE_OK": ("#dbe4f5", "#2c3850"),
    "GRAPH_COLOR_INCLUDE_MISSING": ("#f6d6d8", "#4d2529"),
    # Fondos de línea por severidad: un tinte, no un color.
    "EDITOR_SEVERITY_ERROR_BG": ("#fdeaea", "#3a1f22"),
    "EDITOR_SEVERITY_WARNING_BG": ("#fdf3e0", "#3a3018"),
    "EDITOR_SEVERITY_INFO_BG": ("#e8f1fb", "#1c2a3c"),
    "EDITOR_BRACE_MATCH_COLOR": ("#b7e5c8", "#2b6349"),
    "EDITOR_BRACE_ORPHAN_COLOR": ("#f5b7bb", "#8a3239"),
    "EDITOR_BRACE_MATCH_FOREGROUND": ("#0a0a0c", "#ffffff"),
    "EDITOR_FIND_MATCH_COLOR": ("#fff3b0", "#3b3520"),
    "EDITOR_FIND_CURRENT_MATCH_COLOR": ("#ffd166", "#7a5f1c"),
    # Azul de "esto se puede pulsar" dentro del código.
    "EDITOR_LINK_COLOR": ("#4078f2", "#61afef"),
    # Resaltado de sintaxis: One Light y One Dark, que es de donde venían
    # los oscuros.
    "_SYNTAX_PROPERTY": ("#a626a4", "#c678dd"),
    "_SYNTAX_STRING": ("#50a14f", "#98c379"),
    "_SYNTAX_CELL": ("#986801", "#d19a66"),
    "_SYNTAX_REFERENCE": ("#0184bc", "#56b6c2"),
    # El gris de One Light (#a0a1a7) se queda en 2,6:1 sobre el blanco de
    # la piel `site`: un `#include` es la línea que más se busca y no puede
    # ser lo menos legible del fichero. Bajado hasta 4,7:1.
    "_SYNTAX_DIRECTIVE": ("#6e7076", "#7f848e"),
    "JSON_KEY_COLOR": ("#0184bc", "#7cb7ff"),
    "JSON_STRING_COLOR": ("#50a14f", "#b5cea8"),
    "JSON_NUMBER_COLOR": ("#986801", "#d19a66"),
    "JSON_LITERAL_COLOR": ("#a626a4", "#c678dd"),
    "TAB_CLOSE_HOVER_BG": ("#fbdcdd", "#4a2a2e"),
    # Barra de cambios y minimapa: los valores de VS Code para cada tema
    # (`editorGutter.*` de Light Modern y Dark Modern).
    "EDITOR_CHANGE_ADDED": ("#48985d", "#2ea043"),
    "EDITOR_CHANGE_MODIFIED": ("#2090d3", "#0c7d9d"),
    "EDITOR_CHANGE_DELETED": ("#e51400", "#f14c4c"),
    "MINIMAP_ERROR_HIGHLIGHT": ("#ff1212", "#ff1212"),
    "MINIMAP_WARNING_HIGHLIGHT": ("#bf8803", "#cca700"),
}

# **El resaltado de sintaxis también es de la piel.** `_PAIRS` es One
# Light/One Dark, que es lo que la aplicación ha tenido siempre y lo que
# siguen usando `classic` y `site`; las otras tres lo sustituyen aquí,
# porque en ellas heredarlo era contradecir la piel entera: la de alto
# contraste pintaba el código con los mismos tonos medios que el resto y la
# apta para daltonismo, con el verde de las cadenas y el rojo del error a
# la vez en pantalla, que es justo el par que no se distingue.
#
# Solo se listan los nombres que cambian; el resto sale de `_PAIRS`.
_SKIN_PAIRS = {
    theme.SKIN_OBSIDIAN: {
        # Material 3 sobre gris neutro: la misma familia morada de la piel,
        # no el magenta de One Dark.
        "_SYNTAX_PROPERTY": ("#8a4fd0", "#d8baff"),
        "_SYNTAX_STRING": ("#2f7d55", "#6fd39a"),
        "_SYNTAX_CELL": ("#8a5a1a", "#f0c48a"),
        "_SYNTAX_REFERENCE": ("#1f6f8f", "#8ecbe8"),
        "_SYNTAX_DIRECTIVE": ("#8a8a8a", "#8a8a8a"),
        "EDITOR_LINK_COLOR": ("#3a5fd0", "#a8c8ff"),
        "EDITOR_COMMENT_COLOR": ("#6f6f6f", "#8b8b8b"),
    },
    theme.SKIN_CONTRAST: {
        # Saturados al máximo contra negro puro y contra blanco puro: es la
        # piel que se elige cuando lo demás no se lee, y el código es lo
        # que más se lee de la ventana.
        "_SYNTAX_PROPERTY": ("#8f0075", "#ff8cf0"),
        "_SYNTAX_STRING": ("#005a1e", "#7dffa0"),
        "_SYNTAX_CELL": ("#7a3d00", "#ffc46b"),
        "_SYNTAX_REFERENCE": ("#00456b", "#79e0ff"),
        "_SYNTAX_DIRECTIVE": ("#3c3c3c", "#c6c6c6"),
        "EDITOR_LINK_COLOR": ("#0035c7", "#8ecbff"),
        "EDITOR_COMMENT_COLOR": ("#3f3f3f", "#c0c0c0"),
    },
    theme.SKIN_COLORBLIND: {
        # Okabe-Ito, la misma paleta de la que salen los tres semánticos de
        # la piel: entre sí no bajan de ΔE 25 en ninguna de las tres
        # dicromatías, que es lo que aquí importa más que la convención.
        "_SYNTAX_PROPERTY": ("#8a3c68", "#cc79a7"),
        "_SYNTAX_STRING": ("#00664a", "#29c08a"),
        "_SYNTAX_CELL": ("#8a5a00", "#e69f00"),
        "_SYNTAX_REFERENCE": ("#005a8a", "#56b4e9"),
        "_SYNTAX_DIRECTIVE": ("#5a6068", "#9ba3af"),
        "EDITOR_LINK_COLOR": ("#00539c", "#7fc8f5"),
        "EDITOR_COMMENT_COLOR": ("#4a515c", "#9ba3af"),
    },
}


def refresh() -> None:
    """Recalcula los colores que dependen del modo claro/oscuro."""
    pares = dict(_PAIRS, **_SKIN_PAIRS.get(theme.current_skin(), {}))
    activo = {
        name: par[1] if theme.is_dark() else par[0] for name, par in pares.items()
    }
    globals().update(activo)
    mezcla = theme._mix
    fondo, texto = theme.BG, theme.FG

    globals().update(
        # Grises derivados: siguen a los tokens sin una tabla por modo.
        GRAPH_COLOR_EDGE=mezcla(texto, fondo, 0.22),
        GRAPH_NODE_DEFAULT_BORDER=mezcla(texto, fondo, 0.26),
        GRAPH_NODE_COLLAPSED_BORDER=mezcla(texto, fondo, 0.40),
        GRAPH_GRID_MINOR_COLOR=mezcla(texto, fondo, 0.05),
        GRAPH_GRID_MAJOR_COLOR=mezcla(texto, fondo, 0.10),
        MINIMAP_LINE_COLOR=mezcla(texto, fondo, 0.30),
        # Los que son un token tal cual.
        MUTED_TEXT_COLOR=theme.TEXT_MUTED,
        ACCENT_TEXT_COLOR=theme.ACCENT_TEXT,
        FAINT_TEXT_COLOR=theme.TEXT_FAINT,
        COLOR_DROP_OK=theme.SUCCESS,
        GRAPH_COLOR_TEXT=theme.TEXT,
        GRAPH_SCENE_BACKGROUND=theme.SUNKEN,
        GRAPH_CARD_BG=theme.SUNKEN,
        GRAPH_NODE_CORNER_RADIUS=theme.RADIUS_ITEM,
        GRAPH_NODE_SELECTED_BORDER=theme.ACCENT,
        GRAPH_TOGGLE_BADGE_BG=theme.BG_ELEVATED,
        GRAPH_TOGGLE_BADGE_BORDER=theme.BORDER,
        GRAPH_TOGGLE_BADGE_TEXT=theme.TEXT_MUTED,
        EDITOR_NODE_HINT_BG=theme.ACCENT_FILL,
        EDITOR_LINE_NUMBER_BG=theme.SUNKEN,
        EDITOR_CURRENT_LINE_BG=theme.BG_ELEVATED,
        EDITOR_ERROR_ACCENT=theme.DANGER,
        EDITOR_WARNING_ACCENT=theme.WARNING,
        EDITOR_FOLD_MARKER_COLOR=theme.TEXT_MUTED,
        EXPLORER_INDENT_GUIDE=mezcla(theme.TEXT, theme.PANEL, 0.16),
        MINIMAP_BG=theme.SUNKEN,
        MINIMAP_VIEWPORT_BG=theme.ACCENT_FILL,
        MINIMAP_VIEWPORT_BORDER=theme.ACCENT,
        TAB_CLOSE_HOVER_STROKE=theme.TEXT,
        TAB_CLOSE_STROKE=theme.TEXT_MUTED,
        PALETTE_ITEM_BG=theme.BG_ELEVATED,
        PALETTE_ITEM_BORDER=theme.BORDER,
        PALETTE_ITEM_TEXT=theme.TEXT,
        PALETTE_ITEM_SELECTED_BG=theme.ACCENT_FILL,
        PALETTE_SECTION_HEADER_TEXT=theme.TEXT_MUTED,
        PALETTE_SECTION_HEADER_HOVER_BG=theme.HOVER,
        GIT_STATUS_DEFAULT_COLOR=theme.TEXT_MUTED,
        DB_CARD_RADIUS=theme.RADIUS_ITEM,
        DB_CARD_BG=theme.BG_ELEVATED,
        DB_CARD_HOVER_BG=theme.HOVER,
        DB_CARD_SELECTED_BG=theme.ACCENT_FILL,
        DB_CARD_BORDER=theme.BORDER,
        DB_CARD_SELECTED_BORDER=theme.ACCENT,
        DB_CARD_TITLE=theme.TEXT,
        DB_CARD_ICON_BG=theme.RAISED,
        DB_CARD_ICON_FG=theme.TEXT_MUTED,
        DB_CARD_ACTION_BG=theme.ACCENT,
        DB_CARD_ACTION_FG=theme.ACCENT_FG,
        ON_ACCENT_COLOR=theme.ACCENT_FG,
        DB_CARD_ACTION_HOVER_BG=theme.ACCENT_HOVER,
        DB_CARD_BUTTON_HOVER_BG=theme.RAISED,
        EDITOR_CHANGE_ADDED=theme.CHANGE_ADDED,
        EDITOR_CHANGE_MODIFIED=theme.CHANGE_MODIFIED,
        EDITOR_CHANGE_DELETED=theme.CHANGE_DELETED,
        # Las bandas del minimapa dicen lo mismo que el editor, así que
        # siguen a los mismos tokens: una piel que cambia el aviso tiene que
        # cambiarlo también aquí.
        MINIMAP_ERROR_HIGHLIGHT=theme.DANGER,
        MINIMAP_WARNING_HIGHLIGHT=theme.WARNING,
    )

    # Los que se componen a partir de los anteriores, en su orden.
    globals().update(
        EDITOR_INFO_ACCENT=theme.TEXT_MUTED,
        EDITOR_INCLUDE_HINT_COLOR=activo["EDITOR_LINK_COLOR"],
        GRAPH_DROP_TARGET_GLOW_COLOR=activo["COLOR_GENERATED_BRIGHT"],
        EDITOR_SYNTAX_LABEL=(theme.WARNING, False),
        EDITOR_SYNTAX_UNIT_ADDRESS=(activo["EDITOR_LINK_COLOR"], True),
        EDITOR_SYNTAX_PROPERTY=(activo["_SYNTAX_PROPERTY"], False),
        EDITOR_SYNTAX_STRING_VALUE=(activo["_SYNTAX_STRING"], False),
        EDITOR_SYNTAX_CELL_VALUE=(activo["_SYNTAX_CELL"], False),
        EDITOR_SYNTAX_REFERENCE=(activo["_SYNTAX_REFERENCE"], False),
        EDITOR_SYNTAX_DIRECTIVE=(activo["_SYNTAX_DIRECTIVE"], False),
        EDITOR_SYNTAX_COMMENT=(activo["EDITOR_COMMENT_COLOR"], False),
        GIT_STATUS_COLORS={
            "M": theme.WARNING,
            "A": theme.SUCCESS,
            "R": theme.WARNING,
            "D": theme.DANGER,
            "?": theme.SUCCESS,
        },
        DIFF_SYNTAX_ADDED=(theme.SUCCESS, False),
        DIFF_SYNTAX_REMOVED=(theme.DANGER, False),
        DIFF_SYNTAX_HUNK=(activo["EDITOR_LINK_COLOR"], False),
        DIFF_SYNTAX_HEADER=(theme.TEXT_MUTED, True),
        LOG_SYNTAX_HEADER=(theme.ACCENT_TEXT, True),
        LOG_SYNTAX_OK=(theme.SUCCESS, False),
        LOG_SYNTAX_ERROR=(theme.DANGER, False),
        LOG_SYNTAX_WARNING=(theme.WARNING, False),
        LOG_SYNTAX_DETAIL=(theme.TEXT_FAINT, False),
    )


refresh()

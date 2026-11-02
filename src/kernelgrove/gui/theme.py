"""Hoja de estilos de la aplicación: los tokens del sistema de diseño y el QSS.

Los valores son los de la web de KernelGrove (`landing_page/css/style.css`), y
esto es el equivalente Qt de sus *custom properties*: allí `var(--accent)`
se resuelve en el navegador, aquí el QSS se compone con estas constantes.
Un widget nunca lleva un color propio.

**El sistema, en cuatro decisiones.**

1. **Superficie plana y tarjetas.** Solo dos fondos, `--bg` y `--bg-elevated`,
   separados por **una línea de 1 px** (`--border`). Lo que se eleva —un
   panel, una tarjeta— lo hace con esa línea y una esquina de 12 px, no con
   una sombra ni con un gris intermedio.
2. **Un solo acento.** `--accent` para el relleno de lo primario y para el
   foco; `--accent-text` para el acento *sobre* fondo (texto, iconos), que
   es un tono distinto en cada modo porque tiene que leerse sobre él.
3. **Dos modos, mismos tokens.** Claro y oscuro son el mismo QSS con otra
   tabla de valores. `set_mode()` cambia la tabla y recompone la hoja; nada
   más hay que tocar.
4. **Una tipografía propia.** Inter, empaquetada con la aplicación
   (`gui/fonts/`, SIL Open Font License 1.1) para que se vea igual en los
   tres sistemas, con la pila del sistema detrás por si la carga falla.

Los tamaños de fuente van en `em`, relativos a la del sistema, para no
anular su ajuste de accesibilidad; no queda ningún `font-size` en píxeles
salvo donde hace falta un control deliberadamente pequeño.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:  # pragma: no cover - solo para la anotación de `palette`
    from PySide6.QtGui import QPalette

MODE_LIGHT = "light"
MODE_DARK = "dark"

# Tres **pieles**, con la misma hoja QSS y otra tabla de valores.
#
# `classic` es el sistema con el que creció la aplicación: cuatro
# superficies con un orden fijo, líneas de 1 px para separarlas, radio 3 px
# en lo que se pulsa y 6 px solo en lo que flota, y el morado dioxazina como
# acento. Densa, y pensada para una herramienta en la que se pasan horas.
#
# `site` es el sistema de la web de KernelGrove (`landing_page/css/style.css`)
# aplicado tal cual: dos fondos, un solo borde, tarjetas de 12 px y botones
# de 9 px con relleno de acento. Es la imagen de marca; en pantalla resulta
# más aireada y más de página que de IDE.
#
# `obsidian` es «Obsidian Deep», el sistema de Stitch para la ventana de
# nodos: la misma familia de superficies que la clásica pero en gris
# neutro y más hundida (#131313 el contenido), esquinas **a escuadra** —0
# px en todo lo que es contenedor, 2 px solo en lo pequeño que se pulsa— y
# el morado de Material 3 (`primary` #d8baff con `on-primary` como texto)
# para lo activo. Es la más densa de las tres y la que menos marco pinta.
#
# La tipografía es la misma en las tres y no está aquí: Inter va siempre
# (`FONT_UI`), que es lo único del sistema de la web que no depende de la
# piel.
SKIN_CLASSIC = "classic"
SKIN_SITE = "site"
SKIN_OBSIDIAN = "obsidian"
SKIN_CONTRAST = "contrast"
SKIN_COLORBLIND = "colorblind"

# Lo que define una piel. Los nombres de superficie son los que usa el QSS,
# así que una piel es exactamente esta tabla: no hay reglas que valgan solo
# para una.
_SKINS: Dict[str, Dict[str, Dict[str, object]]] = {
    SKIN_CLASSIC: {
        # Sin modo claro: el sistema clásico nunca lo tuvo, e inventarle uno
        # sería diseñar un tema nuevo, no conservar el que había. Elegir
        # `classic` deja el modo en oscuro.
        MODE_DARK: {
            "sunken": "#0f1216",
            "app": "#171b21",
            "panel": "#1f242c",
            "raised": "#282d37",
            "hover": "#313743",
            "line_soft": "#35383e",
            "line": "#4a4d53",
            "line_strong": "#5a5e64",
            # El límite entre zonas, aparte del borde de un control: son dos
            # decisiones distintas y estaban en el mismo token. Es un
            # **insinuado**, no una raya: quien separa las zonas es el tono
            # (ver la nota de arriba sobre la rampa de superficies), y una
            # línea marcada convertía la ventana en una cuadrícula.
            "edge": "#2b3038",
            "text": "#dfe3ea",
            "text_muted": "#9aa4b2",
            "text_faint": "#828d9c",
            "accent": "#9a70f0",
            "accent_fg": "#241a38",
            "accent_text": "#9a70f0",
            "accent_dim": "#6d43c9",
            "accent_fill": "#2a1e46",
            "danger": "#e4757e",
            "warning": "#e5c07b",
            "success": "#89c398",
            "scroll_handle": "#333944",
            "scroll_handle_hover": "#434a58",
            "button_bg": "#20242b",
            "button_border": "#343a45",
            "button_hover_bg": "#272b34",
            "button_hover_border": "#414855",
            "button_hover_text": "#dfe3ea",
        },
    },
    SKIN_OBSIDIAN: {
        # «Obsidian Deep» (DESIGN.md de Stitch), dark-only como la clásica:
        # su paleta es un esquema oscuro de Material 3 entero, y un modo
        # claro habría que inventarlo.
        #
        # Superficies: las `surface-container-*` del propio sistema, en el
        # orden que fija su apartado de elevación — el editor es lo más
        # hundido (Level 0), el marco y la barra de actividad encima, los
        # paneles laterales encima de eso, y lo que se pulsa arriba del
        # todo. Sin sombras: lo que separa una zona de otra es la línea.
        MODE_DARK: {
            "sunken": "#131313",  # surface: el editor, Level 0
            "app": "#1b1b1c",  # surface-container-low: marco y barras
            "panel": "#242424",  # surface-container: paneles laterales
            "raised": "#2c2c2c",  # surface-container-high
            "hover": "#363636",  # surface-container-highest
            "line_soft": "#3c3b3b",
            "line": "#50504f",
            "line_strong": "#626161",  # outline-variant: campos y menús
            "edge": "#2f2f2f",
            "text": "#e5e2e1",  # on-surface
            "text_muted": "#99929e",  # outline
            "text_faint": "#8f8994",
            # Lo activo lleva el morado tal y como lo reparte Material 3:
            # el relleno es `primary` y el texto encima `on-primary`, que
            # es lo que hace legible un botón primario sin depender de un
            # blanco sobre lavanda. El dioxazina de marca (#53377a) queda
            # como `primary-container` y aquí no rellena nada: a 1,7:1
            # sobre el fondo no se vería ni la raya de la pestaña activa
            # ni la de la barra de actividad, que es justo lo que el
            # sistema pide marcar con él.
            "accent": "#d8baff",  # primary
            "accent_fg": "#3d2163",  # on-primary
            "accent_text": "#d8baff",
            "accent_dim": "#eddcff",  # primary-fixed: el primario al pasar
            # El realce translúcido del sistema (su «Accent Purple al 18%»)
            # precalculado sobre el panel, que es donde se usa.
            "accent_fill": "#373048",
            "danger": "#ffb4ab",  # error
            "warning": "#e5c07b",
            "success": "#2fb673",  # OK_GREEN
            "scroll_handle": "#414142",
            "scroll_handle_hover": "#5a595b",
            # Botón secundario: fantasma con borde, el del sistema.
            "button_bg": "transparent",
            "button_border": "#3c3c3c",
            "button_hover_bg": "#37373d",
            "button_hover_border": "#4a454f",
            "button_hover_text": "#e5e2e1",
            # La franja de abajo va **entera de acento**, con su texto
            # encima: es la firma del diseño y lo único que en toda la
            # ventana lleva el morado de fondo. Las otras dos pieles no
            # dan estos tokens y se quedan con la franja del marco, que es
            # lo que siempre han tenido.
            "statusbar_bg": "#d8baff",
            "statusbar_fg": "#3d2163",
            "statusbar_hover": "#eddcff",
        },
    },
    SKIN_CONTRAST: {
        # **Alto contraste**, en claro y en oscuro. No es una piel de marca:
        # es la que se elige cuando lo demás no se lee. Todo se mide, nada
        # se elige por gusto — el texto llega a 7:1 (AAA) sobre cualquiera
        # de las cuatro superficies, el límite entre zonas a 3:1, y las
        # superficies se separan 5 puntos de L* en vez de los 2 de las
        # pieles normales, así que se distinguen aunque el borde no se vea.
        MODE_DARK: {
            "sunken": "#000000",
            "app": "#101010",
            "panel": "#1b1b1b",
            "raised": "#272727",
            "hover": "#363636",
            "line_soft": "#5e5e5e",
            "line": "#8f8f8f",
            "line_strong": "#b5b5b5",
            "edge": "#a8a8a8",
            "text": "#ffffff",
            "text_muted": "#e3e3e3",
            "text_faint": "#c6c6c6",
            # Amarillo sobre negro, como los temas de alto contraste del
            # sistema: es el par con más separación de luminancia que
            # existe sin salirse de un color que se lea como «activo».
            "accent": "#ffd400",
            "accent_fg": "#000000",
            "accent_text": "#ffd400",
            "accent_dim": "#ffe766",
            "accent_fill": "#4a3c00",
            "danger": "#ff7b72",
            "warning": "#ffd400",
            "success": "#57e08c",
            "scroll_handle": "#6e6e6e",
            "scroll_handle_hover": "#9a9a9a",
            "button_bg": "transparent",
            "button_border": "#a8a8a8",
            "button_hover_bg": "#363636",
            "button_hover_border": "#ffffff",
            "button_hover_text": "#ffffff",
        },
        MODE_LIGHT: {
            "sunken": "#ffffff",
            "app": "#f3f3f3",
            "panel": "#e5e5e5",
            "raised": "#d7d7d7",
            "hover": "#c3c3c3",
            "line_soft": "#8a8a8a",
            "line": "#595959",
            "line_strong": "#2e2e2e",
            "edge": "#454545",
            "text": "#000000",
            "text_muted": "#242424",
            "text_faint": "#3d3d3d",
            "accent": "#0018a8",
            "accent_fg": "#ffffff",
            "accent_text": "#0018a8",
            "accent_dim": "#000f78",
            "accent_fill": "#ccd3ff",
            "danger": "#b3001b",
            "warning": "#6b4600",
            "success": "#005236",
            "scroll_handle": "#8a8a8a",
            "scroll_handle_hover": "#595959",
            "button_bg": "transparent",
            "button_border": "#454545",
            "button_hover_bg": "#d7d7d7",
            "button_hover_border": "#000000",
            "button_hover_text": "#000000",
        },
    },
    SKIN_COLORBLIND: {
        # **Apta para daltonismo**, en claro y en oscuro. Lo que cambia de
        # verdad no son las superficies -grises fríos corrientes- sino los
        # tres colores con significado, que en cualquier otra piel son el
        # rojo, el ámbar y el verde de siempre: simulados con las matrices
        # de Machado (2009), rojo y verde caen a ΔE 12 bajo deuteranopia,
        # o sea el mismo color. Aquí salen del conjunto de Okabe-Ito y
        # ninguna pareja baja de ΔE 25 en ninguna de las tres simulaciones.
        #
        # **El aviso es violeta, y es a propósito.** El ámbar es la
        # convención, pero un ámbar oscuro -el único que tiene contraste
        # sobre fondo claro- cae a ΔE 3 contra el vermellón del error: para
        # media docena de personas de cada cien serían el mismo aviso. El
        # violeta es lo que mantiene los tres separados en los dos modos,
        # que es de lo que trata esta piel.
        MODE_DARK: {
            "sunken": "#141519",
            "app": "#1d1f25",
            "panel": "#272a30",
            "raised": "#2f323b",
            "hover": "#393d48",
            "line_soft": "#3e4550",
            "line": "#5d6674",
            "line_strong": "#737d8c",
            "edge": "#34383f",
            "text": "#e9ecf1",
            "text_muted": "#b8bfc9",
            "text_faint": "#9ba3af",
            # Azul cielo de Okabe-Ito: el acento tiene que distinguirse de
            # los tres semánticos, no solo ellos entre sí.
            "accent": "#56b4e9",
            "accent_fg": "#04202e",
            "accent_text": "#7cc7ef",
            "accent_dim": "#8fd2f3",
            "accent_fill": "#173a4f",
            "danger": "#f07b3f",
            "warning": "#b49ae2",
            "success": "#29c08a",
            # El margen del editor dice lo mismo que los tres de arriba,
            # así que lleva sus mismos colores. En las demás pieles es
            # verde/azul/rojo, y ahí «añadida» y «borrada» son justo el par
            # que no se distingue; el azul de «modificada» tampoco vale,
            # porque en tritanopía cae sobre el verde.
            "change_added": "#29c08a",
            "change_modified": "#b49ae2",
            "change_deleted": "#f07b3f",
            "scroll_handle": "#4c525d",
            "scroll_handle_hover": "#6b7482",
            "button_bg": "transparent",
            "button_border": "#6b7482",
            "button_hover_bg": "#444955",
            "button_hover_border": "#7cc7ef",
            "button_hover_text": "#e9ecf1",
        },
        MODE_LIGHT: {
            "sunken": "#ffffff",
            "app": "#f0f4f8",
            "panel": "#e2e5e9",
            "raised": "#d5d8dd",
            "hover": "#c7cacf",
            "line_soft": "#c0c7d1",
            "line": "#8b94a1",
            "line_strong": "#68717f",
            "edge": "#d3d8de",
            "text": "#12161c",
            "text_muted": "#454d58",
            "text_faint": "#565f6b",
            "accent": "#0072b2",
            "accent_fg": "#ffffff",
            "accent_text": "#005c8f",
            "accent_dim": "#005c8f",
            "accent_fill": "#cfe4f2",
            "danger": "#994300",
            "warning": "#6a4c93",
            "success": "#00674a",
            "change_added": "#00674a",
            "change_modified": "#6a4c93",
            "change_deleted": "#994300",
            "scroll_handle": "#b3bac5",
            "scroll_handle_hover": "#8b94a1",
            "button_bg": "transparent",
            "button_border": "#7d8794",
            "button_hover_bg": "#d4d7db",
            "button_hover_border": "#0072b2",
            "button_hover_text": "#12161c",
        },
    },
    SKIN_SITE: {
        MODE_LIGHT: {
            "bg": "#ffffff",
            "bg_elevated": "#f0f0f2",
            "fg": "#0a0a0c",
            "fg_muted": "#5c5c68",
            "border": "#e7e7ec",
            "edge": "#dcdce0",
            "accent": "#6d5bff",
            "accent_fg": "#ffffff",
            "accent_text": "#5a45e0",
        },
        MODE_DARK: {
            "bg": "#0a0a0c",
            "bg_elevated": "#16161b",
            "fg": "#f4f4f6",
            "fg_muted": "#9a9aa6",
            "border": "#232329",
            "edge": "#232327",
            "accent": "#7261e8",
            "accent_fg": "#ffffff",
            "accent_text": "#a996ff",
        },
    },
}

# ----------------------------------------------------------------------
# La **forma** no es de la piel: es de la aplicación
# ----------------------------------------------------------------------
# Radios, rellenos y tamaños de rótulo son los mismos con cualquier piel;
# lo único que una piel cambia es la paleta. Antes cada una traía además su
# geometría, y cambiar de tema movía de sitio los botones, engordaba las
# pestañas y redondeaba las esquinas: dos cosas distintas metidas en el
# mismo interruptor. Los valores son los de «Obsidian Deep»: esquinas a
# escuadra en todo lo que es contenedor y 2 px solo en lo pequeño que se
# pulsa, que es lo que fija su apartado de formas.
RADIUS_PANEL = 0
RADIUS_CONTROL = 2
RADIUS_ITEM = 2
# Las ventanas flotantes sí se redondean, y es la única excepción a lo de
# arriba: un panel a escuadra está encajado dentro de la ventana y sus
# esquinas las marca la retícula, mientras que una ventana suelta se
# recorta contra lo que haya detrás y el escritorio redondea las suyas. Sin
# esto, la única que dibujamos nosotros -la paleta de comandos, que va sin
# marco- salía a escuadra entre diálogos redondeados por el sistema.
RADIUS_WINDOW = 10
BUTTON_PADDING = "5px 12px"
BUTTON_WEIGHT = "500"
PRIMARY_PADDING = "5px 14px"
HEADER_SIZE = "0.72em"
TAB_PADDING = "7px 14px"

# Verde de "correcto" de la web (la fila «✓ valid against binding» del
# mockup). Es el único color con significado que la web fija, y vale para
# las tres pieles.
OK_GREEN = "#2fb673"

# Margen de cambios del editor, en el orden (añadida, modificada, borrada).
# Son los `editorGutter.*Background` de VS Code y una piel solo los cambia si
# tiene un motivo (ver `SKIN_COLORBLIND`).
_DEFAULT_CHANGE = ("#2ea043", "#0c7d9d", "#f14c4c")

# Familias tipográficas. Inter va empaquetada (`gui/fonts/`); la pila de
# detrás es la de la web, y es la que se usa si la carga falla.
FONT_UI = (
    '"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
)
FONT_MONO = '"JetBrains Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace'

_mode = MODE_DARK
_skin = SKIN_CLASSIC


def _mix(color: str, over: str, amount: float) -> str:
    """`color` al `amount` (0..1) sobre `over`, como el `color-mix` de la web."""

    def parts(value: str):
        value = value.lstrip("#")
        return [int(value[i : i + 2], 16) for i in (0, 2, 4)]

    a, b = parts(color), parts(over)
    return "#" + "".join(
        f"{round(x * amount + y * (1 - amount)):02x}" for x, y in zip(a, b)
    )


def resolve_mode(mode: str = None) -> str:
    """Qué modo toca de verdad, dado lo que la piel activa ofrece.

    Solo claro u oscuro: **no** se sigue al escritorio. Se seguía —el
    equivalente de `prefers-color-scheme` vía `QStyleHints.colorScheme()`—
    y era un tercer estado que decidía por su cuenta cuál de los dos se
    veía, así que «claro» y «oscuro» no eran la elección sino una
    corrección de lo que hubiera pasado. Una piel que solo tiene un modo
    (la clásica) manda sobre lo elegido: no hay otro al que cambiar.
    """
    disponibles = _SKINS[_skin]
    mode = mode or _mode
    if mode not in disponibles:
        return MODE_DARK if MODE_DARK in disponibles else next(iter(disponibles))
    return mode


def current_mode() -> str:
    """Modo elegido (`light` u `dark`), antes de que la piel lo acote."""
    return _mode


def current_skin() -> str:
    """Piel activa (`classic`, `site` u `obsidian`)."""
    return _skin


def modes_of(skin: str) -> tuple:
    """Modos que ofrece una piel. La clásica solo tiene oscuro."""
    return tuple(_SKINS[skin])


def is_dark() -> bool:
    """Si lo que se está pintando ahora mismo es el modo oscuro."""
    return resolve_mode() == MODE_DARK


def set_mode(mode: str, skin: str = None) -> None:
    """Cambia piel y/o modo, y recompone los tokens derivados.

    Reasigna las constantes de este módulo y pide a `style` que recalcule
    las suyas: son las que usan los `QPainter` (el grafo, el resaltador),
    donde el QSS no llega. Quien llama tiene que volver a aplicar
    `stylesheet()` y `palette()` a la aplicación.
    """
    global _mode, _skin
    if skin in _SKINS:
        _skin = skin
    # Un ajuste guardado por una versión anterior puede decir «system»,
    # que ya no existe: cae a oscuro, que es lo que resolvía casi siempre.
    _mode = mode if mode in (MODE_LIGHT, MODE_DARK) else MODE_DARK
    _apply_tokens()

    from kernelgrove.gui import style

    style.refresh()


def _apply_tokens() -> None:
    """Deriva del token activo todo lo que el resto del código nombra.

    Las tres pieles rellenan el **mismo** juego de nombres, que es el que usa
    la hoja QSS: la clásica y la obsidiana los dan uno a uno, y la de la
    web los deriva de sus ocho tokens. Así no hay reglas de estilo que
    valgan solo para una.
    """
    global BG, BG_ELEVATED, FG, FG_MUTED, BORDER, ACCENT, ACCENT_FG, ACCENT_TEXT
    global APP, PANEL, SUNKEN, RAISED, HOVER
    global LINE, LINE_SOFT, LINE_STRONG, EDGE
    global TEXT, TEXT_MUTED, TEXT_FAINT
    global ACCENT_DIM, ACCENT_FILL, ACCENT_HOVER
    global DANGER, WARNING, SUCCESS
    global SCROLL_HANDLE, SCROLL_HANDLE_HOVER
    global BUTTON_BG, BUTTON_BORDER
    global BUTTON_HOVER_BG, BUTTON_HOVER_BORDER, BUTTON_HOVER_TEXT
    global STATUSBAR_BG, STATUSBAR_FG, STATUSBAR_HOVER
    global CHANGE_ADDED, CHANGE_MODIFIED, CHANGE_DELETED

    tokens = _SKINS[_skin][resolve_mode()]

    if _skin == SKIN_SITE:
        BG = tokens["bg"]
        BG_ELEVATED = tokens["bg_elevated"]
        FG = tokens["fg"]
        FG_MUTED = tokens["fg_muted"]
        BORDER = tokens["border"]
        ACCENT = tokens["accent"]
        ACCENT_FG = tokens["accent_fg"]
        ACCENT_TEXT = tokens["accent_text"]

        # El contenido va sobre `--bg` y lo que se eleva sobre
        # `--bg-elevated`, pero los dos fondos de la web se separan 1,08:1:
        # como página funciona, como ventana de cuatro zonas no. El marco y
        # los paneles se derivan de ellos hasta que cada superficie contigua
        # se separa de la siguiente **por tono**, que es lo que hace VS Code
        # y lo que evita tener que dibujar una raya en cada juntura. Siguen
        # siendo los ocho tokens de la web: nada de esto es un color nuevo.
        SUNKEN = BG
        APP = _mix(FG, BG, 0.05)
        PANEL = _mix(FG, BG_ELEVATED, 0.04)
        RAISED = _mix(FG, BG_ELEVATED, 0.09)
        HOVER = _mix(FG, BG_ELEVATED, 0.08)
        LINE = LINE_SOFT = LINE_STRONG = BORDER
        # El límite entre zonas: un insinuado sobre el escalón de tono de
        # arriba, no la raya que antes tenía que sostenerlo todo sola.
        EDGE = tokens["edge"]
        TEXT, TEXT_MUTED, TEXT_FAINT = FG, FG_MUTED, FG_MUTED
        ACCENT_DIM = ACCENT
        ACCENT_FILL = _mix(ACCENT, BG, 0.14)
        # La web aclara el botón primario con `opacity: .92` sobre el fondo
        # de la página; QSS no compone opacidad sobre un relleno sólido, así
        # que el mismo efecto se precalcula mezclando con el fondo.
        ACCENT_HOVER = _mix(ACCENT, BG, 0.92)
        # Los tres con significado, corregidos por contraste: el verde de
        # la web (#2fb673) se queda en 2,6:1 sobre su fondo blanco y el rojo
        # oscuro no llegaba sobre lo elevado. Se oscurece el uno y se aclara
        # el otro lo justo para pasar de 4,5:1 en las cuatro superficies.
        # Los tres con significado, corregidos por contraste hasta pasar de
        # 4,5:1 en las cuatro superficies — `raised` incluida, que con la
        # rampa ensanchada se aleja del extremo y es la que manda.
        DANGER = "#ed7075" if is_dark() else "#ab2126"
        WARNING = "#ffb224" if is_dark() else "#8b4500"
        SUCCESS = OK_GREEN if is_dark() else "#186340"
        SCROLL_HANDLE = _mix(FG, BG, 0.22)
        SCROLL_HANDLE_HOVER = _mix(FG, BG, 0.34)
        BUTTON_BG = "transparent"
        BUTTON_BORDER = BORDER
        BUTTON_HOVER_BG = "transparent"
        BUTTON_HOVER_BORDER = ACCENT
        BUTTON_HOVER_TEXT = ACCENT_TEXT
        STATUSBAR_BG, STATUSBAR_FG, STATUSBAR_HOVER = APP, TEXT_MUTED, HOVER
        CHANGE_ADDED, CHANGE_MODIFIED, CHANGE_DELETED = _DEFAULT_CHANGE
        return

    # Clásica y obsidiana: cada nombre lo da la tabla, uno a uno.
    SUNKEN = tokens["sunken"]
    APP = tokens["app"]
    PANEL = tokens["panel"]
    RAISED = tokens["raised"]
    HOVER = tokens["hover"]
    LINE_SOFT = tokens["line_soft"]
    LINE = tokens["line"]
    LINE_STRONG = tokens["line_strong"]
    EDGE = tokens["edge"]
    TEXT = tokens["text"]
    TEXT_MUTED = tokens["text_muted"]
    TEXT_FAINT = tokens["text_faint"]
    ACCENT = tokens["accent"]
    ACCENT_FG = tokens["accent_fg"]
    ACCENT_TEXT = tokens["accent_text"]
    ACCENT_DIM = tokens["accent_dim"]
    ACCENT_FILL = tokens["accent_fill"]
    ACCENT_HOVER = ACCENT_DIM
    DANGER = tokens["danger"]
    WARNING = tokens["warning"]
    SUCCESS = tokens["success"]
    SCROLL_HANDLE = tokens["scroll_handle"]
    SCROLL_HANDLE_HOVER = tokens["scroll_handle_hover"]
    # Los dos fondos de la web no existen aquí; se apuntan a la superficie
    # más parecida para el poco código que los nombra directamente.
    BG, BG_ELEVATED, FG, FG_MUTED, BORDER = SUNKEN, PANEL, TEXT, TEXT_MUTED, LINE
    BUTTON_BG = tokens["button_bg"]
    BUTTON_BORDER = tokens["button_border"]
    BUTTON_HOVER_BG = tokens["button_hover_bg"]
    BUTTON_HOVER_BORDER = tokens["button_hover_border"]
    BUTTON_HOVER_TEXT = tokens["button_hover_text"]
    # Con `.get`, no por la tabla: la franja de acento es de una sola piel y
    # las demás no tienen por qué declarar tres tokens para repetir lo que
    # ya son sus valores por defecto.
    STATUSBAR_BG = tokens.get("statusbar_bg", APP)
    STATUSBAR_FG = tokens.get("statusbar_fg", TEXT_MUTED)
    STATUSBAR_HOVER = tokens.get("statusbar_hover", HOVER)
    # El margen de cambios del editor. Con `.get` y un valor por defecto:
    # son los de VS Code y valen para cualquier piel salvo la de daltonismo,
    # donde el verde y el rojo de «añadida» y «borrada» son justamente el
    # par que no se distingue.
    CHANGE_ADDED = tokens.get("change_added", _DEFAULT_CHANGE[0])
    CHANGE_MODIFIED = tokens.get("change_modified", _DEFAULT_CHANGE[1])
    CHANGE_DELETED = tokens.get("change_deleted", _DEFAULT_CHANGE[2])


_apply_tokens()


# **Qt no entiende `em` en `font-size`.** Solo `px` y `pt`; un `0.8em` se
# descarta en silencio y el widget se queda con la fuente base. La hoja
# llevaba catorce, así que ni un solo tamaño relativo estaba haciendo nada
# -de ahí que los rótulos de los paneles salieran del tamaño del texto
# normal, en negrita y espaciados-. Se siguen escribiendo en `em`, que es
# lo legible, y se convierten a `pt` sobre la fuente de la aplicación al
# componer la hoja: así siguen siendo relativos al escritorio, que era la
# intención, en vez de fijados en píxeles.
_EM = re.compile(r"font-size:\s*([0-9.]+)em")
# Suelo: por debajo de esto el texto deja de leerse pase lo que pase.
_MIN_PT = 6.0


def _em_a_pt(factor: float) -> str:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    base = app.font().pointSizeF() if app is not None else 9.0
    if base <= 0:  # una fuente fijada en píxeles no da tamaño en puntos
        base = 9.0
    return f"{max(round(base * factor, 1), _MIN_PT)}pt"


def stylesheet() -> str:
    """La hoja QSS con los tokens del modo activo."""
    hoja = _STYLESHEET_TEMPLATE.format(**globals())
    return _EM.sub(lambda m: f"font-size: {_em_a_pt(float(m.group(1)))}", hoja)


_STYLESHEET_TEMPLATE = """
/* Sin `font-size` salvo donde hace falta un control deliberadamente
   pequeño: fijarlo en píxeles para todo anularía el tamaño de fuente del
   escritorio y con él el ajuste de accesibilidad del sistema. */
QWidget {{
    background-color: {APP};
    color: {TEXT};
    font-family: {FONT_UI};
}}

QToolTip {{
    background-color: {BG_ELEVATED};
    color: {TEXT};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 10px;
}}

/* ------------------------------------------------------------------
   Superficies de contenido. Van sobre `--bg` y sin borde: lo que las
   separa es la línea del splitter o del dock, no un marco propio.
   ------------------------------------------------------------------ */
QPlainTextEdit, QTextEdit {{
    background-color: {SUNKEN};
    border: none;
    selection-background-color: {ACCENT_FILL};
    selection-color: {TEXT};
}}

QTreeView, QListView, QTableView, QTreeWidget, QListWidget, QTableWidget {{
    background-color: {PANEL};
    border: none;
    outline: none;
    selection-background-color: {ACCENT_FILL};
    selection-color: {TEXT};
}}

QTreeView::item, QListView::item, QTreeWidget::item, QTableWidget::item {{
    padding: 4px 6px;
    border: none;
}}

QTreeView::item:hover, QListView::item:hover, QTreeWidget::item:hover {{
    background-color: {HOVER};
}}

QTreeView::item:selected, QListView::item:selected,
QTreeWidget::item:selected, QTableWidget::item:selected {{
    background-color: {ACCENT_FILL};
    color: {TEXT};
}}

QHeaderView {{ background-color: {PANEL}; }}

QHeaderView::section {{
    background-color: {PANEL};
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 7px 9px;
    font-weight: 600;
}}

/* ------------------------------------------------------------------
   Botones. Por defecto son el `.btn-ghost` de la web —borde, texto
   normal, y al pasar por encima el borde y el texto se ponen de acento—;
   el primario, con relleno de acento, se pide por nombre.
   ------------------------------------------------------------------ */
QPushButton, QToolButton {{
    background-color: {BUTTON_BG};
    border: 1px solid {BUTTON_BORDER};
    border-radius: {RADIUS_CONTROL}px;
    padding: {BUTTON_PADDING};
    color: {TEXT};
    font-weight: {BUTTON_WEIGHT};
}}

QPushButton:hover, QToolButton:hover {{
    background-color: {BUTTON_HOVER_BG};
    border-color: {BUTTON_HOVER_BORDER};
    color: {BUTTON_HOVER_TEXT};
}}

QPushButton:pressed, QToolButton:pressed {{ background-color: {HOVER}; }}

QPushButton:disabled, QToolButton:disabled {{
    color: {TEXT_MUTED};
    border-color: {BORDER};
    background-color: {BG_ELEVATED};
}}

/* `.btn-primary`: relleno de acento y su texto. La web además lo sube un
   píxel al pasar por encima; QSS no tiene `transform`, así que el estado
   se marca aclarando el relleno. */
QPushButton#primaryButton {{
    background-color: {ACCENT};
    border: 1px solid {ACCENT};
    color: {ACCENT_FG};
    padding: {PRIMARY_PADDING};
}}

QPushButton#primaryButton:hover {{
    background-color: {ACCENT_HOVER};
    border-color: {ACCENT_HOVER};
    color: {ACCENT_FG};
}}

QPushButton#primaryButton:disabled {{
    background-color: {BG_ELEVATED};
    border-color: {BORDER};
    color: {TEXT_MUTED};
}}

/* Distintivo: relleno de acento, versalitas y esquina de 5 px. */
QLabel#badge {{
    background-color: {ACCENT};
    color: {ACCENT_FG};
    border-radius: 5px;
    padding: 2px 7px;
    font-size: 0.65em;
    font-weight: 700;
}}

QComboBox, QLineEdit, QSpinBox {{
    background-color: {SUNKEN};
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
    padding: 5px 9px;
    color: {TEXT};
    selection-background-color: {ACCENT_FILL};
    selection-color: {TEXT};
}}

QComboBox:hover, QLineEdit:hover {{ border-color: {ACCENT}; }}

/* Foco: contorno de 2 px separado 2 px, como el `:focus-visible` de la
   web. Se pone además el borde de acento porque el contorno no lo dibujan
   todos los estilos nativos. */
QPushButton:focus, QToolButton:focus, QComboBox:focus,
QLineEdit:focus, QCheckBox:focus, QTabBar::tab:focus {{
    outline: 2px solid {ACCENT};
    outline-offset: 2px;
    border-color: {ACCENT};
}}

/* Lo que flota por encima de la ventana lleva el radio de tarjeta: es lo
   que lo despega del fondo, ya que no tiene zona propia donde vivir. */
QComboBox QAbstractItemView {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL}px;
    padding: 5px;
    selection-background-color: {ACCENT_FILL};
    selection-color: {TEXT};
}}

/* La casilla y las flechas (del desplegable, del plegado de un árbol) las
   dibuja el estilo nativo, no el QSS: darles fondo por hoja de estilos les
   quita la marca de verificación y el triángulo, y sustituirlos a mano
   obligaría a un fichero de recursos por estado. Lo que sí hace falta es
   que el estilo pinte con estos colores, y de eso se encarga `palette()`.

   Por eso aquí no hay ninguna regla `QComboBox::drop-down`: en cuanto se
   da estilo a ese subcontrol, Qt deja de dibujar la flecha con el estilo
   nativo y solo pinta la que diga `::down-arrow` — que necesita una imagen,
   porque el truco de hacer un triángulo con bordes de una caja de 0x0 sale
   como un cuadrado. Había una y el resultado era que ningún desplegable de
   la aplicación enseñaba su flecha: parecían campos de texto normales.
*/
QCheckBox {{
    spacing: 8px;
    padding: 2px;
    background: transparent;
}}

/* ------------------------------------------------------------------
   Menús
   ------------------------------------------------------------------ */
QMenuBar {{
    background-color: {APP};
    border-bottom: 1px solid {EDGE};
    padding: 3px 5px;
}}

QMenuBar::item {{
    padding: 4px 10px;
    border-radius: {RADIUS_CONTROL}px;
    background: transparent;
}}

QMenuBar::item:selected {{ background-color: {HOVER}; }}

/* Buscador global en la esquina de la barra de menús: una caja de texto
   de mentira -es un botón- porque lo que abre es la paleta, no un campo
   donde escribir aquí. Se ve como un campo para que se lea como uno. */
QPushButton#commandPaletteButton {{
    background-color: {SUNKEN};
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
    color: {TEXT_MUTED};
    font-weight: 400;
    font-size: 0.85em;
    padding: 2px 10px;
    margin: 2px 6px;
    text-align: left;
}}

QPushButton#commandPaletteButton:hover {{
    border-color: {ACCENT};
    color: {TEXT};
}}

QMenu {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL}px;
    padding: 6px;
}}

QMenu::item {{
    padding: 5px 24px 5px 12px;
    border-radius: {RADIUS_CONTROL}px;
}}

QMenu::item:selected {{ background-color: {ACCENT_FILL}; }}

QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 6px 8px;
}}

/* ------------------------------------------------------------------
   Estructura de la ventana: separadores de un píxel
   ------------------------------------------------------------------ */
QMainWindow::separator {{
    background-color: {EDGE};
    width: 1px;
    height: 1px;
}}

QSplitter::handle {{ background-color: {EDGE}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QSplitter::handle:vertical {{ height: 1px; }}
QSplitter::handle:hover {{ background-color: {ACCENT}; }}

QStatusBar {{
    background-color: {STATUSBAR_BG};
    border-top: 1px solid {EDGE};
    color: {STATUSBAR_FG};
}}

QStatusBar::item {{ border: none; }}

/* Lo que se mete dentro de la franja hereda su color, no el de la ventana:
   `QWidget` ya le da a cualquier QLabel el texto general, y sobre una
   franja de acento eso es exactamente lo que no se lee. */
QStatusBar QLabel {{
    background: transparent;
    color: {STATUSBAR_FG};
}}

/* El asa de redimensionar la dibuja el estilo nativo y hereda el fondo de
   `QWidget`: sobre una franja de otro color sale como un recuadro oscuro
   pegado a la esquina. */
QStatusBar QSizeGrip {{ background: transparent; }}

/* Indicadores fijos de la franja: rama, errores, base, posición del
   cursor. Se separan entre sí con relleno propio y no con espaciadores,
   porque la franja no puede crecer. */
QWidget#statusItem {{ background: transparent; }}

QLabel#statusItemText, QLabel#statusItemIcon {{
    color: {STATUSBAR_FG};
    background: transparent;
}}

QLabel#statusVersion {{
    color: {STATUSBAR_FG};
    padding: 0 8px;
}}

/* Acción de la barra de estado («Analizar»): más baja y más apretada que un
   botón normal, para que quepa en la franja sin engordarla. */
QPushButton#statusAction {{
    padding: 2px 10px;
    font-size: 11px;
    font-weight: 600;
    color: {STATUSBAR_FG};
    background: transparent;
    border-color: transparent;
}}

QPushButton#statusAction:hover {{
    color: {STATUSBAR_FG};
    background-color: {STATUSBAR_HOVER};
    border-color: transparent;
}}

QDockWidget {{ border: none; }}

QProgressBar {{
    background-color: {BG_ELEVATED};
    border: none;
    border-radius: 2px;
    max-height: 4px;
    text-align: center;
    color: transparent;
}}

QProgressBar::chunk {{
    background-color: {ACCENT};
    border-radius: 2px;
}}

/* ------------------------------------------------------------------
   Las dos filas de pestañas dicen cosas distintas, así que se ven
   distintas: arriba los ficheros abiertos (solapas, con la marca de
   activo arriba y el fondo del editor debajo); abajo las vistas de ese
   fichero, que son un conmutador de texto subrayado.
   ------------------------------------------------------------------ */
QTabWidget::pane {{
    border: none;
    border-top: 1px solid {EDGE};
}}

QTabBar::tab {{
    background: transparent;
    color: {TEXT_MUTED};
    border: none;
    border-bottom: 2px solid transparent;
    padding: {TAB_PADDING};
    margin: 0;
    font-weight: {BUTTON_WEIGHT};
}}

QTabBar::tab:hover {{ color: {TEXT}; }}

QTabBar::tab:selected {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}

QTabBar#documentBar::tab {{
    background-color: {PANEL};
    color: {TEXT_MUTED};
    border: none;
    border-right: 1px solid {BORDER};
    border-top: 2px solid transparent;
    border-bottom: 1px solid {BORDER};
    padding: 7px 9px 7px 13px;
    margin: 0;
    font-weight: 500;
}}

QTabBar#documentBar::tab:hover {{
    background-color: {HOVER};
    color: {TEXT};
}}

QTabBar#documentBar::tab:selected {{
    background-color: {SUNKEN};
    color: {TEXT};
    border-top: 2px solid {ACCENT};
    border-bottom: 1px solid {SUNKEN};
}}

/* ------------------------------------------------------------------
   Barras de desplazamiento: finas, sin flechas y despegadas del borde,
   para que no parezcan otro marco alrededor del contenido.
   ------------------------------------------------------------------ */
QScrollBar:vertical, QScrollBar:horizontal {{
    background: transparent;
    border: none;
    margin: 0;
}}

QScrollBar:vertical {{ width: 11px; }}
QScrollBar:horizontal {{ height: 11px; }}

QScrollBar::handle {{
    background: {SCROLL_HANDLE};
    border-radius: 3px;
    min-height: 28px;
    min-width: 28px;
    margin: 2px;
}}

QScrollBar::handle:hover {{ background: {SCROLL_HANDLE_HOVER}; }}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ------------------------------------------------------------------
   Barras propias de la aplicación
   ------------------------------------------------------------------ */
/* La franja que ocupa el hueco de la barra de menús: los menús dentro y
   el buscador centrado. Su fondo es el del marco, no el de la ventana. */
QWidget#topBar {{
    background-color: {APP};
    border-bottom: 1px solid {EDGE};
}}

QWidget#topBarSpacer {{ background: transparent; }}

QLabel#topBarCaption {{
    color: {TEXT_MUTED};
    font-weight: 600;
    background: transparent;
}}

QWidget#viewToolbar {{
    background-color: {PANEL};
    border-bottom: 1px solid {EDGE};
}}

/* La leyenda del grafo, que es lo único que queda en su franja: sin fondo
   ni línea, sobre el lienzo. */
QWidget#graphLegendBar {{
    background: transparent;
    border: none;
}}

/* Franja de los dos desplegables del catálogo. Va un escalón más hundida
   que la cabecera que tiene encima: son dos zonas distintas de la misma
   vista y lo que las separa es la superficie, no un marco. */
QWidget#databaseFilters {{
    background-color: {APP};
    border-bottom: 1px solid {EDGE};
}}

QLabel#filterCaption {{
    color: {TEXT_MUTED};
    font-size: {HEADER_SIZE};
    font-weight: 600;
    letter-spacing: 1px;
    background: transparent;
}}

/* La lista de fichas es contenido, no panel: va sobre la superficie
   hundida y las fichas las pinta su delegado. Sin selección de la hoja de
   estilos —el delegado ya la dibuja— o se pintaría dos veces, con el
   rectángulo de Qt asomando por debajo de la esquina de la ficha. */
QListWidget#databaseEntries {{
    background-color: {SUNKEN};
    border: none;
    padding: 8px 10px;
}}

QListWidget#databaseEntries::item,
QListWidget#databaseEntries::item:hover,
QListWidget#databaseEntries::item:selected {{
    background: transparent;
    border: none;
    padding: 0;
}}

QLabel#viewToolbarStatus {{
    color: {TEXT_MUTED};
    background: transparent;
}}

/* ------------------------------------------------------------------
   Paneles laterales
   ------------------------------------------------------------------ */
QDockWidget#leftDock,
QDockWidget#inspectorDock {{
    border: none;
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
}}

QDockWidget#leftDock > QWidget,
QDockWidget#inspectorDock > QWidget {{
    background-color: {PANEL};
    border: none;
}}

QLabel#explorerHeader, QLabel#gitSectionHeader, QWidget#dockHeader {{
    background-color: {PANEL};
    border-bottom: 1px solid {EDGE};
}}

QLabel#explorerHeader, QLabel#gitSectionHeader {{
    color: {TEXT_MUTED};
    font-size: {HEADER_SIZE};
    font-weight: 600;
    letter-spacing: 1px;
    padding: 7px 14px 6px 14px;
}}

/* Cabecera de sección que además pliega lo que hay debajo: se lee como
   las demás cabeceras del panel, no como un botón. */
QToolButton#panelSectionHeader {{
    background-color: {PANEL};
    border: none;
    border-bottom: 1px solid {EDGE};
    color: {TEXT_MUTED};
    font-size: {HEADER_SIZE};
    font-weight: 600;
    letter-spacing: 1px;
    padding: 7px 14px 6px 14px;
    text-align: left;
}}

QToolButton#panelSectionHeader:hover {{
    color: {TEXT};
}}

QLabel#explorerHeaderLabel {{
    color: {TEXT_MUTED};
    font-size: {HEADER_SIZE};
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}}

QToolButton#dockCollapseButton,
QToolButton#paletteCollapseButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_CONTROL}px;
    color: {TEXT_MUTED};
    font-size: 1.05em;
    font-weight: 600;
    padding: 2px 6px;
}}

QToolButton#dockCollapseButton:hover,
QToolButton#paletteCollapseButton:hover {{
    background-color: {HOVER};
    color: {TEXT};
}}

/* Franja de iconos de la izquierda del todo (`ActivityBar`), con la marca
   de acento en el botón activo. */
QWidget#activityBar {{
    background-color: {APP};
    border-right: 1px solid {EDGE};
}}

QToolButton#activityBarButton {{
    background: transparent;
    border: none;
    border-left: 2px solid transparent;
    border-radius: 0;
    color: {TEXT_MUTED};
}}

QToolButton#activityBarButton:hover {{
    color: {TEXT};
    background-color: {HOVER};
}}

QToolButton#activityBarButton:focus {{ background: transparent; }}

/* La sección activa se marca **solo con la barra de acento**, como en VS
   Code. Antes llevaba además el fondo del panel: un cuadro de 46x46 relleno
   alrededor de un icono de 22, del mismo tono exacto que el panel de al
   lado, así que el botón activo parecía un trozo del panel derramado sobre
   la franja en vez de la pestaña que es. El icono ya cambia de color por su
   cuenta (`active_color` en `_activity_sections`), que es la otra mitad de
   la marca. */
QToolButton#activityBarButton:checked {{
    background: transparent;
    border-left: 2px solid {ACCENT};
    color: {TEXT};
}}

QToolButton#activityBarButton:checked:hover {{
    background-color: {HOVER};
}}

/* Los árboles de los paneles laterales son parte del panel: mismo fondo,
   filas compactas y la selección con el relleno de acento del mockup. */
QTreeView#fileExplorerTree,
QTreeWidget#nodeTreePanel,
QTreeWidget#gitChanges,
QListWidget#gitVersions,
QTreeWidget#inspectorProperties {{
    background-color: {PANEL};
    border: none;
    padding: 5px 5px 5px 3px;
}}

QTreeView#fileExplorerTree::item,
QTreeWidget#nodeTreePanel::item,
QTreeWidget#gitChanges::item,
QListWidget#gitVersions::item,
QTreeWidget#inspectorProperties::item {{
    padding: 5px 7px;
    border-radius: {RADIUS_ITEM}px;
    border: none;
}}

QTreeView#fileExplorerTree::item:hover,
QTreeWidget#nodeTreePanel::item:hover,
QTreeWidget#gitChanges::item:hover,
QListWidget#gitVersions::item:hover {{
    background-color: {HOVER};
}}

QTreeView#fileExplorerTree::item:selected,
QTreeWidget#nodeTreePanel::item:selected,
QTreeWidget#gitChanges::item:selected,
QListWidget#gitVersions::item:selected {{
    background-color: {ACCENT_FILL};
    color: {TEXT};
}}

/* El árbol de nodos y la ficha de propiedades son el mockup de la web: en
   monoespaciada, con las filas sangradas por profundidad y la activa con el
   relleno de acento. */
QTreeWidget#nodeTreePanel, QTreeWidget#inspectorProperties {{
    font-family: {FONT_MONO};
    font-size: 0.85em;
}}

/* Pie de un panel lateral: el botón que salta a la otra vista. Va sobre la
   superficie hundida y separado del contenido por la línea de siempre, para
   que se lea como un pie y no como una fila más. */
QWidget#explorerSummary {{
    background-color: {SUNKEN};
    border-top: 1px solid {EDGE};
}}

QPushButton#explorerGraphButton {{
    background-color: {RAISED};
    border: 1px solid {BORDER};
    color: {ACCENT_TEXT};
    font-size: 0.82em;
    font-weight: 600;
    padding: 5px 8px;
    margin-top: 4px;
}}

QPushButton#explorerGraphButton:hover {{
    background-color: {HOVER};
    border-color: {ACCENT};
}}

/* Herramientas de compilación, al pie de la sección de overlays. Zona
   propia, separada de la lista por la línea de siempre. */
QWidget#overlayTools {{
    background-color: {PANEL};
    border-top: 1px solid {EDGE};
}}

QLabel#overlayToolsHint {{
    color: {TEXT_MUTED};
    background: transparent;
    font-size: 0.8em;
}}

QLabel#gitInfo {{
    color: {TEXT_MUTED};
    background-color: {PANEL};
    padding: 9px 14px;
}}

/* Los tres botones de acción sobre un fichero: cuadrados, discretos y con
   el símbolo centrado — la fila de iconos que en VS Code sale al pasar el
   ratón por encima de un cambio. */
QToolButton#gitActionButton {{
    background-color: transparent;
    color: {TEXT_MUTED};
    border: none;
    border-radius: 6px;
    min-width: 22px;
    min-height: 20px;
    padding: 0;
}}

QToolButton#gitActionButton:hover {{
    background-color: {HOVER};
    color: {TEXT};
}}

QToolButton#gitActionButton:disabled {{
    color: {BORDER};
}}

/* Los botones van dentro de la fila del árbol, así que su caja no puede
   pintar fondo propio: taparía el resaltado de la fila seleccionada. */
QWidget#gitRowActions {{ background: transparent; }}

QLabel#inspectorTitle {{
    color: {TEXT};
    font-weight: 700;
    font-size: 1.05em;
    background: transparent;
}}

/* La prosa del binding, debajo del nombre: es contexto, no el dato que se
   viene a leer, así que va atenuada y sin pesar como el título. */
QLabel#inspectorDescription {{
    color: {TEXT_MUTED};
    background: transparent;
}}

/* Distintivo «required» de la ficha de una propiedad: el mismo acento con
   el que se marca en la lista del inspector. */
QLabel#cardBadge {{
    color: {ACCENT_TEXT};
    font-size: {HEADER_SIZE};
    font-weight: 700;
    background: transparent;
}}

QLabel#panelCaption {{
    color: {TEXT_MUTED};
    font-size: {HEADER_SIZE};
    font-weight: 700;
    letter-spacing: 1px;
    background: transparent;
}}

/* Tarjeta: borde de 1 px, esquina de 12 px y fondo elevado. Es la forma de
   la web para un panel, y la usan el mockup del árbol y la ficha. */
QWidget#card {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL}px;
}}

QWidget#cardBar {{
    background-color: {BG_ELEVATED};
    border: none;
    border-bottom: 1px solid {BORDER};
}}

QLabel#cardTitle {{
    color: {TEXT_MUTED};
    font-family: {FONT_MONO};
    font-size: 0.78em;
    background: transparent;
}}

/* Fila de «✓ correcto contra el binding» del mockup. */
QLabel#cardOk {{
    color: {OK_GREEN};
    font-family: {FONT_MONO};
    font-size: 0.78em;
    background: transparent;
    padding: 6px 0 0 0;
}}

/* ------------------------------------------------------------------
   Estado vacío y barra de búsqueda
   ------------------------------------------------------------------ */
QLabel#emptyStateHint {{
    background-color: {SUNKEN};
    border: none;
    color: {TEXT_MUTED};
    padding: 28px;
    line-height: 160%;
}}

QFrame#findBar {{
    background-color: {BG_ELEVATED};
    border: 1px solid {BORDER};
    border-radius: {RADIUS_PANEL}px;
}}

QFrame#findBar QLineEdit {{ background-color: {BG}; }}

QFrame#findBar QToolButton {{
    background: transparent;
    border: none;
    padding: 4px 8px;
}}

QFrame#findBar QToolButton:hover {{ background-color: {HOVER}; }}

/* Botonera flotante sobre el lienzo del grafo: una caja despegada del
   fondo, con el borde y la superficie de lo que se pulsa. Sin sombra —el
   sistema no las usa: lo que separa una capa de otra es la línea. */
QFrame#canvasControls {{
    background-color: {RAISED};
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_CONTROL}px;
}}

QToolButton#canvasControlButton {{
    background: transparent;
    border: none;
    border-radius: {RADIUS_ITEM}px;
    color: {TEXT_MUTED};
    font-size: 13px;
    font-weight: 600;
    min-width: 22px;
    min-height: 20px;
    padding: 0;
}}

QLabel#canvasZoomLabel {{
    background: transparent;
    color: {TEXT_MUTED};
    font-family: {FONT_MONO};
    font-size: 0.72em;
    padding: 0 6px 0 4px;
}}

QToolButton#canvasControlButton:hover {{
    background-color: {HOVER};
    color: {TEXT};
}}

/* Paleta de comandos: flota sobre la ventana, así que lleva el borde y la
   esquina de lo que flota. El campo va sin marco propio -es la cabecera de
   la caja, no un control dentro de ella- y separado de la lista por la
   línea de siempre. */
QDialog#commandPalette {{
    background-color: {BG_ELEVATED};
    border: 1px solid {LINE_STRONG};
    border-radius: {RADIUS_WINDOW}px;
}}

QLineEdit#commandPaletteQuery {{
    background-color: {BG_ELEVATED};
    border: none;
    border-bottom: 1px solid {BORDER};
    border-radius: 0;
    padding: 11px 14px;
    font-size: 1.05em;
}}

QListWidget#commandPaletteResults {{
    background-color: {BG_ELEVATED};
    border: none;
    padding: 5px;
}}

QListWidget#commandPaletteResults::item {{
    padding: 6px 9px;
    border-radius: {RADIUS_ITEM}px;
}}

/* Pestañas del panel inferior (PROBLEMS / OUTPUT): texto con la marca de
   activo debajo, la misma forma que las pestañas de vista. Nada de fondo
   propio: la cabecera del panel ya es una zona. */
QPushButton#logTab {{
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    color: {TEXT_MUTED};
    font-size: {HEADER_SIZE};
    font-weight: 700;
    letter-spacing: 1px;
    padding: 5px 4px;
    margin-right: 12px;
}}

QPushButton#logTab:hover {{ color: {TEXT}; }}

QPushButton#logTab:checked {{
    color: {TEXT};
    border-bottom: 2px solid {ACCENT};
}}

QPlainTextEdit#overlayLog {{
    background-color: {SUNKEN};
    border: none;
}}

/* Deliberadamente sin regla para `::branch`: en Qt, darle cualquier estilo
   -aunque sea solo el fondo- apaga el triángulo nativo de plegado a menos
   que se sustituya a mano con `border-image` por cada estado, y sin eso la
   carpeta (o el nodo) se queda sin ninguna pista de que se puede desplegar.
   Mejor dejar el indicador nativo del estilo Fusion, que ya es la "flecha"
   que hace falta, que uno invisible. */
"""


def palette() -> "QPalette":
    """Paleta Qt equivalente a la hoja de estilos, en el modo activo.

    El QSS no llega a lo que dibuja el propio estilo —la marca de la
    casilla, el triángulo de un desplegable, la flecha de plegado de un
    árbol—: eso sale de la `QPalette`. Sin esto, esos detalles se quedan con
    los colores por defecto de Fusion, que es exactamente el tipo de
    descuido que hace que una interfaz se vea hecha a medias.
    """
    from PySide6.QtGui import QColor, QPalette

    colors = {
        QPalette.Window: APP,
        QPalette.WindowText: TEXT,
        QPalette.Base: BG,
        QPalette.AlternateBase: BG_ELEVATED,
        QPalette.Text: TEXT,
        QPalette.Button: BG_ELEVATED,
        QPalette.ButtonText: TEXT,
        QPalette.BrightText: ACCENT_FG,
        QPalette.Highlight: ACCENT,
        QPalette.HighlightedText: ACCENT_FG,
        QPalette.ToolTipBase: BG_ELEVATED,
        QPalette.ToolTipText: TEXT,
        QPalette.PlaceholderText: TEXT_MUTED,
        QPalette.Link: ACCENT_TEXT,
        QPalette.Mid: BORDER,
        QPalette.Dark: _mix(FG, BG, 0.45),
        QPalette.Light: HOVER,
    }

    result = QPalette()
    for role, value in colors.items():
        result.setColor(role, QColor(value))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        result.setColor(QPalette.Disabled, role, QColor(TEXT_MUTED))
    return result


def load_fonts() -> bool:
    """Registra la Inter empaquetada en la base de fuentes de Qt.

    Se distribuye con la aplicación (`gui/fonts/`, SIL Open Font License
    1.1) en vez de enlazarse desde Google Fonts: esto es un programa de
    escritorio y no puede depender de que haya red para verse bien, ni
    conviene que llame a un servidor de terceros al arrancar.

    Devuelve si se cargó alguna. Si no, la pila del sistema de `FONT_UI`
    hace su trabajo y la aplicación se ve con la fuente de la plataforma —
    peor, pero no rota.
    """
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    carpeta = Path(__file__).resolve().parent / "fonts"
    cargadas = 0
    for fichero in sorted(carpeta.glob("*.ttf")):
        if QFontDatabase.addApplicationFont(str(fichero)) != -1:
            cargadas += 1
    return cargadas > 0

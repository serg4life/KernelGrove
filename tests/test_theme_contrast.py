"""Las paletas se comprueban con números, no a ojo.

Tres cosas, y ninguna es cuestión de gusto:

1. **Dónde acaba un panel y empieza el siguiente.** Se separan **por
   tono**, como en VS Code, y la línea (`EDGE`) es un insinuado encima; la
   piel de alto contraste es la única que hace lo contrario, porque ahí la
   raya visible es justamente el recurso. Así que lo que se mide es que
   cada par de zonas que se tocan se distinga por una vía o por la otra —
   no por las dos, que es lo que dejaba la ventana hecha una cuadrícula.
2. **Lo que se lee, se lee** (WCAG 2.1: 4,5:1 el texto normal, 7:1 en la
   piel de alto contraste, que para eso está).
3. **Los tres colores con significado se distinguen entre sí**, también
   para quien no separa el rojo del verde. Se simula la visión con las
   matrices de Machado (2009) y se mide la distancia en Lab.
"""

from __future__ import annotations

import pytest

from kernelgrove.gui import theme

# ----------------------------------------------------------------------
# Colorimetría: lo justo para medir, sin dependencias nuevas
# ----------------------------------------------------------------------


def _srgb(color: str):
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(c * 2 for c in color)
    return tuple(int(color[i : i + 2], 16) / 255 for i in (0, 2, 4))


def _lineal(v: float) -> float:
    return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4


def luminancia(color: str) -> float:
    """Luminancia relativa de la WCAG."""
    r, g, b = (_lineal(v) for v in _srgb(color))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a: str, b: str) -> float:
    """Razón de contraste de la WCAG, de 1:1 a 21:1."""
    la, lb = luminancia(a), luminancia(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _lab(color: str):
    r, g, b = (_lineal(v) for v in _srgb(color))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def claridad(color: str) -> float:
    """L* de CIELAB: para separar superficies, donde el contraste WCAG se
    satura (dos negros casi iguales dan 1,06:1 estén como estén)."""
    return _lab(color)[0]


def delta_e(a: str, b: str) -> float:
    """Distancia CIE76 entre dos colores."""
    la, lb = _lab(a), _lab(b)
    return sum((la[i] - lb[i]) ** 2 for i in range(3)) ** 0.5


# Matrices de Machado, Oliveira y Fernandes (2009), severidad 1.0, sobre RGB
# lineal. Son las que usan las herramientas de accesibilidad al uso.
_CVD = {
    "protanopia": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deuteranopia": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
    "tritanopia": (
        (1.255528, -0.076749, -0.178779),
        (-0.078411, 0.930809, 0.147602),
        (0.004733, 0.691367, 0.303900),
    ),
}


def simular(color: str, tipo: str) -> str:
    """El mismo color visto por quien tiene esa dicromacia."""
    rgb = [_lineal(v) for v in _srgb(color)]
    m = _CVD[tipo]
    fuera = [sum(m[i][j] * rgb[j] for j in range(3)) for i in range(3)]

    def destino(v):
        v = max(0.0, min(1.0, v))
        return 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055

    return "#" + "".join(f"{round(destino(v) * 255):02x}" for v in fuera)


# ----------------------------------------------------------------------
# Las pieles, cada una en sus modos
# ----------------------------------------------------------------------
PIELES = [
    (piel, modo)
    for piel in (
        theme.SKIN_CLASSIC,
        theme.SKIN_SITE,
        theme.SKIN_OBSIDIAN,
        theme.SKIN_CONTRAST,
        theme.SKIN_COLORBLIND,
    )
    for modo in theme.modes_of(piel)
]


@pytest.fixture(autouse=True)
def _restaura_tema():
    """Deja el tema como estaba: es estado de módulo y lo lee media GUI."""
    piel, modo = theme.current_skin(), theme.current_mode()
    yield
    theme.set_mode(modo, piel)


@pytest.mark.parametrize("piel,modo", PIELES)
def test_las_zonas_contiguas_se_distinguen(piel, modo):
    """Dos paneles que se tocan tienen que verse como dos.

    Es la queja que trajo esta revisión: al lado uno de otro parecían el
    mismo. Vale cualquiera de las dos vías —que las superficies se separen
    solas, o que la línea de en medio se vea—, porque en pantalla es lo
    mismo; lo que no vale es ninguna de las dos.
    """
    theme.set_mode(modo, piel)
    # Los pares que se tocan de verdad en pantalla: el editor con el marco,
    # el marco con el panel lateral, y el panel con lo que se pulsa encima.
    pares = (
        ("editor", "sunken", "marco", "app"),
        ("marco", "app", "panel lateral", "panel"),
        ("panel lateral", "panel", "lo elevado", "raised"),
    )
    for nombre_a, a, nombre_b, b in pares:
        color_a = getattr(theme, a.upper())
        color_b = getattr(theme, b.upper())
        salto = abs(claridad(color_a) - claridad(color_b))
        linea = min(contraste(theme.EDGE, color_a), contraste(theme.EDGE, color_b))
        assert salto >= 3.5 or linea >= 1.9, (
            f"{piel}/{modo}: {nombre_a} y {nombre_b} no se distinguen — "
            f"{salto:.1f} L* de escalón y la línea a {linea:.2f}:1"
        )


@pytest.mark.parametrize("piel,modo", PIELES)
def test_el_texto_se_lee_sobre_cualquier_superficie(piel, modo):
    """WCAG 2.1 nivel AA, y AAA en la piel que se llama de alto contraste."""
    theme.set_mode(modo, piel)
    minimo = 7.0 if piel == theme.SKIN_CONTRAST else 4.5
    superficies = (theme.SUNKEN, theme.APP, theme.PANEL, theme.RAISED)
    for fondo in superficies:
        assert contraste(theme.TEXT, fondo) >= minimo
        # El texto apagado y los tres semánticos son texto: la barra de
        # estado, los diagnósticos y las letras del árbol de ficheros.
        for color in (theme.TEXT_MUTED, theme.DANGER, theme.WARNING, theme.SUCCESS):
            assert contraste(color, fondo) >= 4.5, (
                f"{piel}/{modo}: {color} sobre {fondo}"
            )
    # Y lo que va escrito **encima** del acento.
    assert contraste(theme.ACCENT_FG, theme.ACCENT) >= 4.5


@pytest.mark.parametrize("modo", theme.modes_of(theme.SKIN_COLORBLIND))
def test_la_piel_para_daltonismo_separa_error_aviso_y_correcto(modo):
    """Los tres colores con significado, vistos con cada dicromacia.

    Es lo único que esta piel hace distinto, y lo que la justifica: con la
    paleta normal, el rojo del error y el verde del «correcto» caen a ΔE 12
    bajo deuteranopia —el mismo color para una de cada doce personas—. El
    umbral de 25 es holgado: por debajo de ~10 dos colores son el mismo.
    """
    theme.set_mode(modo, theme.SKIN_COLORBLIND)
    semanticos = {
        "error": theme.DANGER,
        "aviso": theme.WARNING,
        "correcto": theme.SUCCESS,
    }
    # El margen del editor dice lo mismo con otras tres marcas, y tiene el
    # mismo problema: añadida es verde y borrada es roja en todas las demás.
    margen = {
        "añadida": theme.CHANGE_ADDED,
        "modificada": theme.CHANGE_MODIFIED,
        "borrada": theme.CHANGE_DELETED,
    }
    for grupo in (semanticos, margen):
        nombres = list(grupo)
        for tipo in _CVD:
            for i, a in enumerate(nombres):
                for b in nombres[i + 1 :]:
                    distancia = delta_e(
                        simular(grupo[a], tipo), simular(grupo[b], tipo)
                    )
                    assert distancia >= 25, (
                        f"{modo}/{tipo}: «{a}» y «{b}» se ven igual "
                        f"(ΔE {distancia:.1f})"
                    )


def test_la_paleta_corriente_es_la_que_tiene_el_problema():
    """Por qué existe la piel de arriba, medido y no supuesto.

    Si algún día la paleta clásica dejara de confundir rojo y verde, esta
    prueba avisaría de que el motivo escrito en `SKIN_COLORBLIND` ya no es
    cierto.
    """
    theme.set_mode(theme.MODE_DARK, theme.SKIN_CLASSIC)
    confundidos = delta_e(
        simular(theme.DANGER, "deuteranopia"), simular(theme.SUCCESS, "deuteranopia")
    )
    assert confundidos < 20, "el rojo y el verde de siempre ya no se confunden"

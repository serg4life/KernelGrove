#!/usr/bin/env python3
"""togif.py <escena> [ancho] [centesimas] -- los fotogramas de una escena a GIF.

Sustituye al `convert` de ImageMagick, que en las escenas largas no llega:
`convert` carga **todos** los fotogramas antes de escribir nada y la politica
del sistema (`/etc/ImageMagick-6/policy.xml`) le corta la cache en 2 GiB, que
son unos 600 fotogramas de 1280x800 -menos de lo que dura el recorrido-.

Y hace bien lo que `-layers OptimizePlus` hacia mal (ver `togif.sh`): al
encontrar dos fotogramas identicos seguidos no los funde perdiendo el tiempo
del segundo, sino que **suma** su duracion al primero. Que es justo lo que
`hold()` necesita -una pausa se graba repitiendo el mismo fotograma-, y de
paso quita del GIF los cientos de repetidos.

Necesita Pillow (`pip install pillow`); no es dependencia de la aplicacion,
solo de esta herramienta de promocion.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from PIL import Image

# Cuantos fotogramas se miran para decidir la paleta. Repartidos por toda la
# escena y no los primeros: el catalogo, el editor y una ficha acercada no
# tienen los mismos colores, y una paleta sacada solo del principio deja el
# resto con bandas.
MUESTRAS = 72


def paleta(frames, ancho: int, colores: int) -> Image.Image:
    """Una sola paleta para toda la escena, sacada de una muestra repartida.

    Una paleta por fotograma daria mejor color, pero entonces dos fotogramas
    iguales dejarian de serlo byte a byte y se acabaria el ahorro: ni las
    pausas se sumarian ni los recortes por diferencia servirian de nada.
    """
    paso = max(1, len(frames) // MUESTRAS)
    muestra = frames[::paso][:MUESTRAS]
    tira = None
    for indice, ruta in enumerate(muestra):
        imagen = abrir(ruta, ancho)
        if tira is None:
            tira = Image.new("RGB", (imagen.width, imagen.height * len(muestra)))
        tira.paste(imagen, (0, imagen.height * indice))
    return tira.quantize(colors=colores, method=Image.Quantize.MEDIANCUT)


def abrir(ruta: Path, ancho: int) -> Image.Image:
    with Image.open(ruta) as imagen:
        imagen = imagen.convert("RGB")
        if imagen.width != ancho:
            alto = round(imagen.height * ancho / imagen.width)
            imagen = imagen.resize((ancho, alto), Image.LANCZOS)
        return imagen


def cuantizar(frames, ancho: int, pal: Image.Image):
    """Los fotogramas, ya en la paleta comun, de uno en uno.

    Sin difuminado: el ruido que mete cambia de un fotograma al siguiente
    aunque la pantalla no haya cambiado, y convierte cada pausa en
    fotogramas distintos. Con colores planos de interfaz no se echa de menos.
    """
    for ruta in frames:
        yield abrir(ruta, ancho).quantize(palette=pal, dither=Image.Dither.NONE)


def repartir(centesimas: float, cuantos: int) -> list[int]:
    """Duraciones en ms, en centesimas enteras que de media dan `centesimas`.

    El GIF solo guarda centesimas enteras: 6.4 se reparte como 6 y 7
    alternados, arrastrando lo que sobra de un fotograma al siguiente. Las
    pausas de `hold()` suman varios fotogramas, asi que salen con su duracion
    exacta; en los de movimiento, una centesima arriba o abajo no se ve.
    """
    duraciones, llevadas = [], 0
    for indice in range(1, cuantos + 1):
        estas = round(centesimas * indice) - llevadas
        llevadas += estas
        duraciones.append(estas * 10)
    return duraciones


def main() -> int:
    escena = sys.argv[1]
    ancho = int(sys.argv[2]) if len(sys.argv) > 2 else 960
    retardo = float(sys.argv[3]) if len(sys.argv) > 3 else 10
    colores = int(sys.argv[4]) if len(sys.argv) > 4 else 256

    raiz = Path(os.environ.get("KERNELGROVE_GIF_DIR", tempfile.gettempdir()))
    raiz = raiz / "kernelgrove-gifs"
    frames = sorted((raiz / "frames" / escena).glob("*.png"))
    if not frames:
        print(f"no hay fotogramas en {raiz / 'frames' / escena}", file=sys.stderr)
        return 1

    salida = raiz / "out" / f"{escena}.gif"
    salida.parent.mkdir(parents=True, exist_ok=True)

    pal = paleta(frames, ancho, colores)
    imagenes = cuantizar(frames, ancho, pal)
    primero = next(imagenes)
    primero.save(
        salida,
        save_all=True,
        append_images=imagenes,
        duration=repartir(retardo, len(frames)),
        loop=0,
        # 1 = dejar el fotograma anterior puesto. Es lo que hace falta para
        # que un fotograma recortado a la zona que cambia se vea sobre lo de
        # antes en vez de sobre un fondo vacio.
        disposal=1,
        optimize=False,
    )
    print(f"{salida}  {salida.stat().st_size / 1e6:.1f} MB  {len(frames)} fotogramas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

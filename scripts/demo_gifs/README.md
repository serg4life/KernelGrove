# GIFs de demostración

Un GIF por funcionalidad, grabados **de la aplicación de verdad**: se monta
`MainWindow` con `QT_QPA_PLATFORM=offscreen`, se la conduce paso a paso y cada
paso se guarda con `QWidget.grab()`. No hay maquetas ni capturas retocadas; lo
que se ve es lo que hace el programa contra `database/bindings.db`.

## Grabar

```bash
source .venv/bin/activate
cd scripts/demo_gifs
python scenes.py editor          # una escena -> fotogramas PNG
bash togif.sh editor             # esos fotogramas -> out/editor.gif
```

Todas de una vez:

```bash
for s in editor inspector graph catalogue completion overlay build connect git themes tour; do
    python scenes.py "$s" && bash togif.sh "$s"
done
```

Lo generado va a `$TMPDIR/kernelgrove-gifs` (`KERNELGROVE_GIF_DIR` lo cambia),
nunca al repositorio: son miles de PNG. Los GIFs terminados se copian a mano
donde hagan falta (el del README es `docs/kernelgrove-demo.gif`).

Hace falta `database/bindings.db`, el checkout de `kernel/` (de donde sale la
copia de trabajo) y **Pillow** en algún Python del sistema (`pip install
pillow`) — no en el entorno virtual del proyecto, que no lo lleva: no es
dependencia de la aplicación. Las escenas `build` y `connect` piden además
`dtc`/`cpp`; `git`, `git`.

## Cómo está montado

- `rec.py` — el grabador. Fija el entorno (inglés,
  ajustes en un `XDG_CONFIG_HOME` aparte para no tocar los del usuario), monta
  la ventana a 1280x800 y ofrece `shot()`/`hold()`, el puntero dibujado
  (`point*`) y los atajos para abrir carpeta y fichero. `shot()` pega encima
  las ventanas flotantes —el catálogo, la ficha de una propiedad, el popup del
  autocompletado— que en Qt son ventanas aparte y no saldrían en el `grab()`
  de la principal.
- **El puntero y la cámara, para las escenas que se miran enteras.** `point*`
  coloca el puntero de golpe, que es lo que vale para una captura suelta; en
  un GIF, un cursor que aparece en otro sitio entre dos fotogramas no se
  sigue con la vista. `move*` (`move_to`, `move`, `move_at`, `move_item`)
  recorre el camino dibujando un fotograma por paso, con arranque y frenada
  suaves, y `click()` marca la pulsación con un anillo que se abre —sin él,
  entre el fotograma de antes y el de después no hay nada que diga que se ha
  pulsado y el cambio de pantalla parece espontáneo.
  `zoom_to`/`zoom_widget`/`zoom_out` acercan la cámara **recortando el
  fotograma ya compuesto**: la aplicación no se entera, la ventana sigue
  midiendo 1280x800 y nada se recoloca. Es lo que hace legible a 960 px la
  ficha del Inspector o el popup del autocompletado, que si no son letra de
  seis píxeles. El puntero se dibuja *después* de encuadrar, así que conserva
  su tamaño en vez de salir escalado y borroso.
- `scenes.py` — un guion por funcionalidad, decorado con `@scene()`. La copia
  de trabajo (`ensure_workspace`) son los device trees de
  `kernel/linux/arch/arm64/boot/dts/xilinx` copiados a un repositorio git
  temporal: compilar deja `.dtb` junto al fuente y el asistente de overlays
  escribe en la carpeta abierta, y ninguna de las dos cosas puede pasar dentro
  del checkout del kernel.
- `togif.py` (y `togif.sh`, que solo busca un Python con Pillow y se lo
  pasa) — el montaje: 960 px, 10 cs por fotograma y una sola paleta para toda
  la escena, sacada de una muestra repartida. Era `convert -layers
  OptimizeFrame` de ImageMagick y ya no lo es, por dos motivos. Uno: `convert`
  carga **todos** los fotogramas antes de escribir nada y la política del
  sistema le corta la caché en 2 GiB, unos 600 fotogramas de 1280x800 — menos
  de lo que dura `tour`. Y dos: Pillow hace bien lo que `OptimizePlus` hacía
  mal —al encontrar dos fotogramas idénticos seguidos **suma** la duración del
  segundo al primero en vez de fundirlos perdiendo su tiempo, que es justo lo
  que `hold()` necesita (una pausa se graba repitiendo el mismo fotograma)—, y
  de paso escribe cada fotograma recortado a la zona que cambia. En `tour`,
  953 fotogramas quedan en 454 guardados con los 95 s intactos.

## Las escenas

| Escena | Qué enseña |
|---|---|
| `editor` | Abrir un SoC real y los diagnósticos del motor semántico; pulsar uno salta a su línea. |
| `inspector` | El Inspector: qué dice el binding del nodo bajo el cursor, y la ficha de una propiedad. |
| `graph` | El mismo árbol como grafo, desplegable y navegable. |
| `catalogue` | El catálogo: SoCs y placas, y los bindings del kernel, buscables. |
| `completion` | Autocompletado sacado del binding del nodo, no de una lista fija. |
| `overlay` | El asistente de overlays: señalar el nodo, marcar qué cambia, generar el `.dtso`. |
| `build` | Comprobar y compilar: los overlays se validan contra la base antes de llamar a `dtc`. |
| `connect` | Colgar un chip de un bus desde la paleta. |
| `git` | Control de versiones de la carpeta abierta, con el margen del editor marcando lo tocado. |
| `themes` | Las cinco pieles, los dos modos y el idioma, en caliente. |
| `tour` | El recorrido largo, sobre un solo nodo: abrir una placa (zcu102) del catálogo, pulsar un warning para ir a su línea, leer el Inspector de ese nodo, añadir con el autocompletado una propiedad que el nodo no tenía y ver el documento como grafo. El puntero se mueve y la cámara se acerca a lo que hay que leer. |

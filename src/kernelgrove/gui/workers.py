"""Tareas de fondo para no bloquear el hilo de la interfaz.

Cargar un SoC implica una consulta a la base de datos por cada `compatible`
del árbol, lo que en SoCs grandes tarda lo suficiente como para congelar la
ventana. Todo el trabajo se delega al servicio de la API y el resultado vuelve
por señales.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, QTimer, Signal

from kernelgrove.api import BindingOption, Diagnostic, KernelGroveService

# Hilos de comprobación que no llegaron a terminar antes de que se cerrara
# quien los lanzó (ver `_SchemaChecksScheduler.stop`). Un `QThread` no se
# puede matar a medias, y **destruir su objeto mientras `run()` sigue dentro
# revienta el proceso**: se guardan aquí, sueltos de su padre, hasta que
# acaban solos y se descartan. Es global y no del planificador porque lo que
# hay que sobrevivir es justo la desaparición del planificador.
_UNFINISHED_WORKERS: set = set()


class BindingOptionsWorker(QThread):
    """Precarga los dispositivos conectables de cada bus presente en el SoC.

    Se lanza tras cargar un SoC para que, cuando el usuario despliegue el
    selector, las opciones ya estén en memoria.
    """

    options_ready = Signal(str, list)

    def __init__(
        self,
        service: KernelGroveService,
        buses: List[str],
        parent: Optional[QObject] = None,
    ):
        """Recibe los buses cuyos dispositivos conectables hay que listar."""
        super().__init__(parent)
        self._service = service
        self._buses = buses

    def run(self) -> None:
        """Consulta los dispositivos de cada bus y los emite uno a uno."""
        for bus in self._buses:
            if self.isInterruptionRequested():
                return
            try:
                options: List[BindingOption] = self._service.list_connectable_bindings(
                    bus
                )
            except Exception:  # noqa: BLE001 - un bus sin datos no rompe el resto
                options = []
            self.options_ready.emit(bus, options)


class SchemaChecksWorker(QThread):
    """Ejecuta en segundo plano lo que valida el propio schema.

    Son los valores del binding concreto (capa 5) y los bindings genéricos
    (capa 2): milisegundos por nodo cada cosa, así que no caben en el camino
    que se recorre en cada pulsación de tecla. El editor lanza este hilo tras
    cada análisis y añade los avisos cuando llegan.

    `token` identifica el texto que se analizó: el editor lo compara al
    recibir el resultado para descartar el de una versión anterior del
    documento.
    """

    checks_ready = Signal(str, list)

    def __init__(
        self,
        service: KernelGroveService,
        text: str,
        token: str,
        fragment: bool = False,
        base_path: Optional[str] = None,
        parent: Optional[QObject] = None,
    ):
        """Recibe el texto a comprobar y con qué identificarlo al volver."""
        super().__init__(parent)
        self._service = service
        self._text = text
        self._token = token
        self._fragment = fragment
        self._base_path = base_path

    def run(self) -> None:
        """Comprueba el documento y emite los diagnósticos encontrados."""
        if self.isInterruptionRequested():
            return
        try:
            diagnostics: List[Diagnostic] = self._service.analyze_schema_checks(
                self._text, fragment=self._fragment, base_path=self._base_path
            )
        except Exception:  # noqa: BLE001 - un fallo aquí no puede tirar la GUI
            diagnostics = []
        if self.isInterruptionRequested():
            return
        self.checks_ready.emit(self._token, diagnostics)


class SchemaCheckScheduler(QObject):
    """Encola y lanza `SchemaChecksWorker`, una comprobación detrás de otra.

    Extraído de `EditorTab` para no mezclar la programación del hilo (el
    temporizador de espera, "hay uno en marcha, pido que pare y relanzo
    cuando termine") con la gestión de documentos y diagnósticos, que es cosa
    de quien la usa. Solo sabe de texto, token y parámetros de análisis: no
    conoce `Document` ni decide si un resultado sigue vigente, eso lo hace el
    llamante comparando el token recibido.
    """

    checks_ready = Signal(str, list)
    # Hay (o ya no hay) una comprobación en marcha. Entre el retardo y el
    # cómputo pasan hasta tres segundos y medio desde la última tecla, y la
    # lista de diagnósticos se repoblaba sola sin que nada dijera que
    # todavía faltaban comprobaciones por llegar.
    busy_changed = Signal(bool)

    def __init__(
        self,
        service: KernelGroveService,
        delay_ms: int,
        parent: Optional[QObject] = None,
    ):
        """Guarda el servicio y arma el temporizador de espera tras cada edición."""
        super().__init__(parent)
        self._service = service
        self._worker: Optional[SchemaChecksWorker] = None
        self._pending: Optional[Tuple[str, str, bool, Optional[str]]] = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._launch)

    def schedule(
        self, token: str, text: str, fragment: bool, base_path: Optional[str]
    ) -> None:
        """Anota la versión de texto a comprobar y reprograma el temporizador."""
        if not self._service.binding_schemas_available():
            return
        self._pending = (token, text, fragment, base_path)
        self._timer.start()

    def _launch(self) -> None:
        """Arranca el hilo si no hay otro en marcha; si lo hay, le pide que pare."""
        pending = self._pending
        if pending is None:
            self.busy_changed.emit(False)
            return
        if self._worker is not None and self._worker.isRunning():
            # No se puede cortar un hilo por la mitad: se le pide que pare y
            # este mismo método se vuelve a llamar cuando termine (`finished`).
            self._worker.requestInterruption()
            return

        self._pending = None
        token, text, fragment, base_path = pending
        self._worker = SchemaChecksWorker(
            self._service,
            text,
            token=token,
            fragment=fragment,
            base_path=base_path,
            parent=self,
        )
        self._worker.checks_ready.connect(self.checks_ready)
        self._worker.finished.connect(self._launch)
        self._worker.start()
        self.busy_changed.emit(True)

    def stop(self) -> None:
        """Detiene el temporizador y espera al hilo en marcha, si lo hay.

        `run()` solo mira la interrupción al entrar —dentro ya está en manos
        de `jsonschema`—, así que una comprobación larga puede agotar la
        espera. Cuando pasa, **no se puede dar por muerto el hilo**: quien
        llama a esto está cerrando la ventana, y destruir el objeto `QThread`
        con `run()` todavía dentro tira el proceso entero con un fallo de
        segmentación en medio de la validación. Así que se le suelta del
        padre y se guarda en `_UNFINISHED_WORKERS` hasta que termine por su
        cuenta: acabará en unos segundos, sin nadie escuchando, y se
        descartará solo.
        """
        self._timer.stop()
        self._pending = None
        self.busy_changed.emit(False)

        worker = self._worker
        self._worker = None
        if worker is None or not worker.isRunning():
            return

        worker.requestInterruption()
        if worker.wait(5000):
            return

        # Se le cortan las señales antes de soltarlo: su resultado ya no le
        # interesa a nadie, y `finished` volvería a llamar a `_launch` sobre
        # un planificador que puede estar destruyéndose.
        worker.checks_ready.disconnect()
        worker.finished.disconnect()
        worker.setParent(None)
        _UNFINISHED_WORKERS.add(worker)
        worker.finished.connect(lambda w=worker: _UNFINISHED_WORKERS.discard(w))

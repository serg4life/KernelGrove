"""Interfaz gráfica de KernelGrove (PySide6).

Organización del paquete:

- `app`: arranque del `QApplication` y aplicación del tema.
- `main_window`: ventana principal, que solo orquesta.
- `models`: estado de los slots, modelo de árbol Qt y generación del modelo interno.
- `widgets`: componentes reutilizables (delegado de bindings, vista JSON, detalles).
- `workers`: tareas de fondo para no bloquear el hilo de la interfaz.
"""

from kernelgrove.gui.app import run_app

__all__ = ["run_app"]

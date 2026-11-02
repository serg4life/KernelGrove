"""Las vistas principales de la aplicación."""

from kernelgrove.gui.tabs.database_tab import DatabaseTab
from kernelgrove.gui.tabs.editor_tab import EditorTab
from kernelgrove.gui.tabs.generator_tab import GeneratorTab
from kernelgrove.gui.tabs.overlay_tab import OverlayTab
from kernelgrove.gui.tabs.visualizer_tab import VisualizerTab

__all__ = [
    "DatabaseTab",
    "EditorTab",
    "GeneratorTab",
    "OverlayTab",
    "VisualizerTab",
]

"""El mapeo de subsistemas del kernel a grupos "bonitos" de la paleta.

Pura lógica de diccionario (`widgets/binding_groups.py`): sin `QApplication`
ni base de datos. Lo que puede romperse aquí es de un solo tipo — un grupo
al que apunta `_SUBSYSTEM_TO_GROUP` que no está en `GROUP_ORDER`, y entonces
`BindingPalette._section_for` (que busca su posición con
`GROUP_ORDER.index`) lanzaría `ValueError` al construir la sección.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from kernelgrove.gui.widgets import binding_groups


def test_todo_subsistema_mapeado_apunta_a_un_grupo_del_orden_curado():
    for group in binding_groups._SUBSYSTEM_TO_GROUP.values():
        assert group in binding_groups.GROUP_ORDER


def test_subsistema_desconocido_cae_en_otros():
    assert binding_groups.group_for_subsystem("un-directorio-nuevo") == "other"
    assert binding_groups.group_for_subsystem(None) == "other"


def test_subsistemas_reales_de_buses_y_perifericos():
    assert binding_groups.group_for_subsystem("i2c") == "buses"
    assert binding_groups.group_for_subsystem("iio") == "sensors"
    assert binding_groups.group_for_subsystem("sound") == "audio"
    assert binding_groups.group_for_subsystem("mfd") == "power"


def test_cada_grupo_del_orden_tiene_etiqueta_e_icono():
    for group in binding_groups.GROUP_ORDER:
        assert binding_groups.group_label(group)
        assert group in binding_groups._GROUP_ICONS

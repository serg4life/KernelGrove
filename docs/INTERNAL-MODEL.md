# Modelo interno para el generador de Device Tree

Este módulo define el lenguaje común interno que usan el generador, la GUI y los demás módulos del programa.

## Por qué no usar DTS ni JSON como interfaz

- DTS es una representación de texto de Device Tree, útil para salida final.
- JSON es un formato de intercambio, pero puede ser demasiado cercano al almacenamiento.
- El modelo interno permite separar:
  - datos de SoC y periféricos
  - selección de bindings
  - generación de nodos independientes del formato de exportación

## Clases principales

### `DeviceTreeNode`
Representa un nodo interno del árbol Device Tree.

- `name`: nombre técnico del nodo
- `label`: etiqueta opcional
- `compatible`: lista de cadenas `compatible`
- `properties`: propiedades del nodo
- `children`: nodos hijos

### `PeripheralDescriptor`
Describe un periférico descubierto en la descripción `*.dtsi`.

- `node_name`
- `display_name`
- `compatibles`
- `path`

### `SoCProfile`
Describe un SoC cargado desde un archivo `*.dtsi`.

- `soc_name`
- `compatible`
- `peripherals`

### `InternalDeviceTreeModel`
Modelo compartido por la GUI y el generador.

- `soc_profile`
- `selected_peripheral`
- `selected_binding`
- `nodes`

## Flujo de datos

1. El usuario selecciona un SoC en la GUI.
2. `dtgen.dtsi_parser.build_soc_profile()` parsea el fichero `.dtsi`.
3. El resultado se convierte en `SoCProfile` y una lista de `PeripheralDescriptor`.
4. Al elegir un periférico, `dtgen.bindings_db.BindingsDatabase` busca bindings en `database/bindings.db`.
5. El modelo interno se genera en `InternalDeviceTreeModel`.
6. El modelo interno puede volver a exportarse a JSON o a DTS más adelante.

## Uso rápido

```bash
python3 -m dtgen.app
```

> Nota: este fichero documenta el lenguaje interno del generador.

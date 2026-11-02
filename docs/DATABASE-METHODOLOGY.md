# Metodología para parsear bindings YAML y almacenar en SQLite

## Objetivo
Esta metodología describe cómo funciona el parser de bindings YAML y cómo se almacena la información en JSON y SQLite.

> Nota para la IA: este fichero `yaml_bindings/METHODOLOGY.md` contiene la metodología de uso y debe leerse al iniciar nuevas conversaciones relacionadas con este proyecto.

## Estructura de módulos

- `parse_yaml_bindings.py`
  - Script principal de línea de comandos.
  - Usa los módulos del paquete `yaml_bindings`.

- `yaml_bindings/finders.py`
  - Busca archivos `*.yaml` y `*.yml` recursivamente.

- `yaml_bindings/loader.py`
  - Carga documentos YAML válidos desde cada archivo.

- `yaml_bindings/records.py`
  - Extrae los campos `title`, `description` y `compatible`.
  - Construye el registro final que se escribirá en JSON y SQLite.

- `yaml_bindings/storage.py`
  - Genera el fichero JSON de salida.
  - Inicializa la base de datos SQLite.
  - Inserta o actualiza los registros en SQLite.

## Uso

1. Instala dependencias:

```bash
python3 -m pip install pyyaml
```

2. Ejecuta el parser desde la raíz del proyecto:

```bash
cd kernelgrove  # raíz del repositorio
python3 parse_yaml_bindings.py --root kernel/linux/Documentation/devicetree/bindings --json bindings.json --sqlite bindings.db
```

3. Opciones disponibles:

- `--root`: directorio raíz para buscar los archivos YAML.
- `--json`: fichero JSON de salida.
- `--sqlite`: fichero de base de datos SQLite.
- `--table`: nombre de la tabla SQLite (por defecto `bindings`).

## Pruebas unitarias

- Archivo de pruebas: `tests/test_yaml_bindings.py`
- Se verifica:
  - la detección de archivos YAML/YML,
  - la carga de documentos YAML,
  - la extracción de `compatible`, `title`, `description` y `vendor`,
  - la escritura de JSON,
  - el almacenamiento en SQLite usando los campos reales:
    - `compatible` (texto único),
    - `vendor` (prefijo del compatible),
    - `title`,
    - `document` (JSON crudo del YAML).

### Ejecutar tests

```bash
cd kernelgrove  # raíz del repositorio
python3 -m pytest tests/test_yaml_bindings.py
```

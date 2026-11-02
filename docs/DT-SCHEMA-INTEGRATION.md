# Integración con dt-schema

Qué aporta [dt-schema](https://github.com/devicetree-org/dt-schema) a KernelGrove,
qué se ha integrado, **qué no** y qué queda pendiente. dt-schema es la
implementación de referencia con la que el kernel valida sus propios bindings
(`make dt_binding_check`), así que usarla evita reimplementar las reglas de
composición de los schemas.

## Resumen

| | Antes | Ahora |
|---|---|---|
| Extracción de compatibles | recorrido propio del YAML | `dtschema.extract_node_compatibles` |
| Compatibles registrados | 26 603, de los que **1 161 no eran compatibles** | 25 458 en `binding_compatibles` y 26 460 en `schema_compatibles`, con su schema y su nodo (753 son de subnodos) |
| Filas de `bindings` falsas | 62 (`iface`, `host`, `pcie`, `gpio30`…) | 0 |
| Propiedades de un binding | las que el YAML enumera | las que enumera **más las que hereda** (+18,9 de media) |
| `required` | los del YAML crudo | los del YAML **y sus `$ref`** (1 988 entradas que antes no se veían) |
| Tipos de propiedad | — | 4 761 por nombre + 84 por patrón |
| Validación contra bindings | — | capas 2 y 5 del motor semántico |
| Validación de valores | — | el propio schema, con `jsonschema` |
| Autocompletado | — | lista en el editor, con plantilla de valor |
| Subdispositivos de un MFD | — | desplegable propio en el generador |

Cifras medidas sobre el kernel 7.2-rc5 con dtschema 2026.6.

## Qué hace la ingesta

`scripts/build_database.sh` añade un paso, `--table schemas`, que procesa con
dt-schema todos los YAML de `Documentation/devicetree/bindings` (unos 90 s) y
guarda el resultado en la base. Es lo mismo que hace `dt-mk-schema -j`, con
los *fixups* aplicados: notación abreviada expandida, tipos y dimensiones
normalizados y propiedades implícitas (`status`, `phandle`, `pinctrl-*`)
añadidas.

Tablas nuevas:

| Tabla | Contenido |
|-------|-----------|
| `schemas` | los 5 663 schemas procesados, indexados por `$id`, con el YAML original al lado (`raw`) porque los fixups borran `description` y `examples` |
| `schema_compatibles` | los 26 460 compatibles declarados: qué schema los declara, **en qué nodo suyo** (`node_path`) y **en qué posición** de la lista, incluidos los 753 de subnodos y los declarados por `select` |
| `schema_meta` | versión de dtschema usada y el mapa de tipos de propiedad |

Además, `bindings.schema_id` enlaza cada binding con su schema.

Coste: **+17 MB** sobre la base, que pasa de 87 a 104 MB (3,3 MB de schemas y
5,0 MB de YAML crudo, ambos comprimidos, más los índices), y ~100 s de
ingesta.

**La dependencia es solo de construcción.** `dtschema` se declara en
`pyproject.toml` como extra `ingest` (`pip install -e '.[ingest]'`); la
aplicación instalada no lo importa nunca: lee los schemas ya procesados de la
base. Sin `dtschema` instalado la ingesta de bindings sigue funcionando y el
paso `schemas` avisa y se salta.

## Qué hace la aplicación con ellos

### Resolución de un compatible

`api/binding_schemas.BindingSchemaLookup` responde «qué dice el binding de
este nodo». El trabajo real es seguir la herencia: un binding no enumera sus
propiedades, referencia con `allOf`/`$ref` los schemas de su clase de
dispositivo y de su bus. El controlador I2C de Cadence declara 14 propiedades
y hereda hasta 48, con `#address-cells`/`#size-cells` fijados a 1 y 0.

Reglas que sigue la resolución:

- **Exacta**: `schema_compatibles` con el `node_path`, para que
  `ti,twl4030-pwm` se valide contra el subnodo del MFD y no contra el MFD
  entero.
- **Ramas condicionales solo en sentido permisivo**: lo que declara un
  `if/then`, un `oneOf` o un `anyOf` cuenta como propiedad *admitida* pero
  nunca como *obligatoria*. Es lo que impide que la capa sea más estricta que
  el binding.
- **Compatibles genéricos descartados**: `simple-bus`, `simple-mfd`, `syscon`
  y `arm,primecell` no identifican un dispositivo cuando el schema declara
  algún otro. Los tres primeros son el criterio del propio dtschema;
  `arm,primecell` se añadió porque lo declaran 32 bindings distintos (ningún
  otro compatible repetido pasa de seis) y resolver por él llevaba a validar
  una UART contra un schema de CoreSight.
- **Empates resueltos por identidad, no por orden alfabético.** Cuando varios
  schemas declaran el mismo compatible gana, por este orden: el binding que
  *se llama* como el compatible (`panel-lvds` → `panel-lvds.yaml`, y no el
  primero de los seis paneles concretos que lo declaran detrás del suyo), el
  que lo declara en primera posición de la lista, y el que lo describe como
  nodo propio y no como subnodo. Sin esto, una pantalla LVDS genérica se
  validaba contra el binding de un panel Advantech y heredaba sus medidas
  exactas (`width-mm = 223`) como valores obligatorios.

### Capa 5 del motor semántico

`dts_engine/checks/bindings/` (ver `SEMANTIC-ENGINE-FLOW.md`). El motor no
conoce la base: recibe un `SchemaLookup` que le inyecta `api/service.py`.
Cinco reglas:

| Código | Gravedad | Qué dice |
|--------|----------|----------|
| `binding-missing-property` | ERROR | el binding exige una propiedad que no está |
| `binding-missing-node` | ERROR | el binding exige un subnodo que no está |
| `binding-unknown-property` | WARNING / INFO | el binding —cerrado— no admite esa propiedad |
| `binding-property-value` | WARNING | el valor no está en el `enum`/`const` o se sale del rango |
| `binding-rejected-compatible` | WARNING | el compatible está en `incomplete-devices.yaml`, la lista de compatibles rechazados del kernel |
| `binding-unknown-compatible` | INFO | ningún binding YAML documenta ese compatible |

Las mismas cautelas que la capa 1: valores con macros sin resolver (capa 3)
no se juzgan, un nodo `disabled` no tiene que cumplir sus requisitos —igual
que hace `dt-validate`— y lo que no se puede afirmar se rebaja de gravedad
explicando por qué en la pista del diagnóstico. De una reapertura
(`&gpio1 { … }`) en un `.dtsi` no se dice que le falte nada: solo se está
viendo un trozo del nodo.

Los valores no los interpreta el motor: **se los da al schema**.
`checks/bindings/instance.py` traduce el nodo a la instancia que espera un
JSON Schema —un `uint32` es un entero, un `uint32-matrix` una lista de listas,
`reg` se parte en filas según `#address-cells`/`#size-cells` del padre— y
`jsonschema` lo valida. Lo que no se puede traducir con certeza se queda
fuera y nadie habla de ello: macros de `dt-bindings/*.h`, referencias `&label`
(sus celdas las decide el nodo apuntado) y matrices como `interrupts`, cuyo
tamaño de fila depende del `#interrupt-cells` de su controlador.

Del resultado del schema solo se cuentan los problemas de **valor** —`enum`,
`const`, `type`, `maxItems`, rangos— y uno por propiedad: `required` y
`additionalProperties` ya los cubren las reglas de arriba, que saben mirar el
árbol fusionado.

### Capa 2 del motor semántico

`dts_engine/checks/generic/`, con los schemas que dt-schema marca con
`select`: los que se aplican por la forma del nodo y no por su compatible
(228 de 5 663). Ahí está lo que vale para una *clase* de dispositivo:

| Código | Gravedad | Qué dice |
|--------|----------|----------|
| `generic-missing-property` | ERROR | la clase exige una propiedad: `gpio-controller` obliga a `#gpio-cells`, `pinctrl-names` a `pinctrl-0` |
| `generic-property-value` | WARNING | el valor incumple la clase: un bus I2C no pasa de 5 MHz |
| `generic-vendor-prefix` | WARNING | el prefijo de fabricante de una propiedad no está en el registro del kernel |

Se ejecuta **aparte**, en la pasada diferida (`run_schema_checks`), junto con
los valores de la capa 5: las dos consisten en darle el nodo a un validador de
JSON Schema y las dos cuestan milisegundos por nodo, así que la GUI las lanza
en un hilo de fondo (`SchemaChecksWorker`) tras cada análisis y añade sus
avisos cuando llegan. Si las dos capas dicen lo mismo de la misma propiedad,
se conserva la del binding concreto (`KernelGroveService.merge_deferred`).

Medido sobre un `.dts` de placa: el análisis que corre en cada tecla son 17 ms
y la pasada diferida 432 ms; sobre `zynqmp.dtsi`, con 330 nodos, 155 ms y
2,4 s.

El registro de prefijos (`vendor-prefixes.yaml`) va fuera de ese bucle: sus
966 patrones costaban el 86 % del tiempo de la capa y la respuesta solo
depende del nombre de la propiedad, así que se resuelve con una expresión
regular y se recuerda.

### Autocompletado

La lista sale sola al escribir dentro de un nodo cuyo `compatible` se conoce
(y con `Ctrl+Space` siempre). Al aceptar una propiedad se inserta con el
esqueleto de su valor según el tipo, con el cursor dentro:

```
clock-frequency   →   clock-frequency = <|>;
clock-names       →   clock-names = "|";
gpio-controller   →   gpio-controller;|
ports             →   ports {|};
```

Y si la propiedad tiene valores enumerados, detrás aparece una segunda lista
con ellos. No se ofrecen las que ya están escritas en el nodo, salvo la de la
línea que se está editando.

De qué nodo se trata se averigua **sobre el texto** (`api/completion.py`), no
sobre el árbol: mientras se escribe, el último análisis va con retraso. El
recorrido es local —hacia atrás hasta la llave que abre el nodo— así que
cuesta lo que ocupe el nodo. Si el nodo es una reapertura (`&uart0 { … }`), el
compatible se busca por la etiqueta en el árbol fusionado.

La parte de datos está en `KernelGroveService`:

```python
svc.completion_context(text, position, base_path)  # nodo y compatible del cursor
svc.suggest_properties("nxp,pcf8563")   # propiedades con tipo, obligatoriedad,
                                        # descripción, valores admitidos y origen
svc.suggest_compatibles("nxp,pcf85")    # compatibles documentados por prefijo
svc.is_documented_compatible("acme,x")  # ¿lo describe algún binding?
```

Las descripciones salen del YAML original guardado en `schemas.raw`; los
tipos, del mapa de dt-schema (`uint32`, `string-array`, `phandle-array`…).

### Subdispositivos en el generador

Un MFD como `ti,twl4030` describe en su propio binding las funciones que
lleva dentro (`ti,twl4030-pwm`, `-gpio`, `-keypad`, `-audio`: 20 en total).
No cuelgan de ningún bus, así que no aparecían por `parent_bus`. Ahora, al
conectar un dispositivo con subnodos declarados, su slot ofrece un desplegable
con ellos (`PeripheralSlot.subdevice_parent`, `KernelGroveService.list_subdevices`).
Va en un campo aparte y no en `child_bus` a propósito: `child_bus` es un
nombre de bus real y de él dependen los colores del visualizador y
`CONTROLLER_LIST`.

## Qué NO hace dt-schema (y por qué seguimos haciéndolo nosotros)

- **No infiere buses.** No existe ningún `i2c-peripheral-props.yaml`: los
  bindings de dispositivos I2C no referencian nada que diga que son I2C. Solo
  SPI tiene un schema de propiedades de periférico (237 bindings lo
  referencian). `parent_bus`/`child_bus` siguen saliendo de
  `storage.infer_parent_child_bus` y de los ejemplos de cada binding.
- **No parsea DTS.** Su entrada es un DTB desaplanado con `pylibfdt`. El
  parser de `dts_engine/parser.py` sigue siendo la única entrada de texto.
- **No conserva la documentación.** Los fixups borran `description` y
  `examples`; por eso se guarda también el YAML crudo.
- **No valida el `rol`** ni ninguna noción propia de KernelGrove.

## Qué queda pendiente

Los ocho pendientes de la primera integración están hechos. Lo que queda es de
otra escala, y ninguna de las tres cosas depende de dt-schema:

1. **Capa 3: expandir las macros de `dt-bindings/*.h`.** Es el techo de todo
   lo demás. Mientras un `interrupts = <GIC_SPI 42 IRQ_TYPE_LEVEL_HIGH>` no se
   resuelva a números, su valor no se codifica y por tanto no se valida —y son
   la mayoría de los valores interesantes de un device tree real. El texto de
   las 7 500 cabeceras ya está en la tabla `sources`: falta el evaluador de
   `#define` (incluida la aritmética de las macros con argumentos).
2. **Resolver phandles.** Cuántas celdas ocupa cada referencia de un
   `clocks = <&clk 3>` lo dice el `#clock-cells` del nodo apuntado, así que
   hace falta el árbol fusionado con sus etiquetas resueltas —que ya existe—
   y un paso que anote cada referencia con su tamaño. Con eso entran en
   validación `gpios`, `clocks`, `dmas`, `interrupts-extended` y todo lo que
   hoy se queda fuera.
3. **Ancho de los enteros (`typeSize`).** dt-schema distingue `uint32` de
   `uint64` por el tamaño real del valor en el binario. Desde el texto, cada
   celda son 32 bits y no se sabe cuántas forma un valor de 64, así que esa
   palabra clave se ignora. Se resolvería junto con lo anterior.

Y dos cosas menores, anotadas para no perderlas:

- El esqueleto que inserta el autocompletado sale del tipo de la propiedad, y
  cuando dt-schema no lo sabe fijar (`wakeup-source` aparece como `flag` en
  unos bindings y como `phandle-array` en otro) se ofrece la forma más común,
  `= <>;`, que a veces habrá que corregir a mano.
- El generador ofrece los subnodos que declara el binding del dispositivo,
  pero no los que declara *por patrón* (`^dsi@[0-9a-f]+$`): son 91 y habría
  que decidir qué nombre de nodo proponer.

## Qué sale sobre el kernel entero

`scripts/check_corpus.py` sobre los 6 347 `.dts`/`.dtsi` del kernel, que es la
medida de falsos positivos del proyecto. Las dos pasadas se miden por separado
porque la aplicación también las ejecuta por separado.

**En cada análisis** (`--db`): 17 915 diagnósticos, 2,8 por fichero.

| Capa | Total | ERROR | WARNING | INFO |
|------|-------|-------|---------|------|
| 1 (especificación) | 9 161 | 391 | 4 690 | 4 080 |
| 5 (reglas del binding) | 8 754 | 562 | 3 049 | 5 143 |

De la capa 5, 4 930 son `binding-unknown-compatible` (INFO): el kernel
conserva alrededor de mil bindings en el formato `.txt` antiguo, que nunca
pasaron a YAML, y de esos nodos no se puede comprobar nada más. Es lo que dice
el aviso.

La capa 1 no ha dejado de bajar según mejora la vista fusionada del árbol:
10 986 antes de la integración, 10 079 al plegar las reaperturas
`&label { … }`, y 9 161 ahora que un `#include` escrito dentro de un nodo se
fusiona dentro de ese nodo. Sus errores se han quedado en 391 todo el camino.

**En la pasada diferida** (`--db --schema`): 1 167 diagnósticos, 0,18 por
fichero. Es la parte más precisa del motor, y también la que más ha costado
afinar: la primera versión sacaba 934 avisos de valor en 400 ficheros, casi
todos por errores de codificación propios (ver más abajo).

| Código | Total | ERROR | WARNING |
|--------|-------|-------|---------|
| `binding-property-value` | 509 | | 509 |
| `generic-missing-property` | 624 | 216 | 408 |
| `generic-property-value` | 30 | | 30 |
| `generic-vendor-prefix` | 4 | | 4 |

**El corpus del kernel no es verdad absoluta para estas capas**, a diferencia
de la capa 1. El kernel no valida limpio contra sus propios bindings —
`make dtbs_check` saca miles de avisos — así que cada grupo hay que mirarlo a
mano. De los verificados: `arm,pl080` en `spear3xx.dtsi` no tiene `#dma-cells`
ni `clocks`, `ti,tfp410` en `dove-sbc-a510.dts` no tiene el nodo `ports`,
`st,stmpe-ts` en las placas SPEAr usa el prefijo antiguo `ts,` en lugar de
`st,`, y el `qcom,ci-hdrc` de `qcom-msm8960.dtsi` declara `clock-names` en el
orden contrario al que fija su binding. Los cuatro son incumplimientos reales
que `dt_binding_check` también señala.

**Lo que enseñó medir.** Cuatro fallos propios salieron solo al pasar el
corpus, y ninguno se habría visto probando a mano:

- Sin `compatible` en la instancia, los `if/then` de los schemas se cumplían
  todos: en JSON Schema, un `properties` sobre algo que no está se da por
  bueno. Un `qcom,geni-i2c` acababa exigiendo los `clock-names` de otra
  variante. 934 → 48 avisos de valor en 400 ficheros.
- Las celdas de `reg` se tomaban del padre *escrito*, que en una reapertura
  `&usb_dwc3_0 { … }` es la raíz, no el bus donde el nodo vive de verdad.
- Los valores de 64 bits se escriben como dos celdas de 32 y el schema los
  espera como un número.
- Validar un subnodo con su trozo de schema suelto rompía sus `$ref` locales
  (`#/$defs/…`), que apuntan al documento entero. Ese reventaba el análisis
  con una excepción, no daba un falso positivo.

## Comprobar la integración

```bash
pip install -e '.[ingest]'            # dtschema, solo para construir la base
scripts/build_database.sh             # incluye el paso «schemas»
python -m pytest tests                # 82 pruebas (2 ficheros antiguos aparte)
python scripts/check_corpus.py --db            # lo que corre en cada análisis
python scripts/check_corpus.py --db --schema   # la pasada diferida
```

Las pruebas del motor usan un `SchemaLookup` de mentira, así que no necesitan
la base; las de `api` (`test_binding_schemas.py`) sí, y se saltan solas si no
está.

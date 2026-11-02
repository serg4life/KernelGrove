# Flujo de comprobaciones del motor semántico

Este documento fija **en qué orden** valida KernelGrove un device tree y **de dónde
sale cada regla**. El objetivo es no inventar reglas propias: cada aviso que
el editor muestra tiene que poder señalarse en una fuente externa (la
especificación, un binding, una cabecera o el código del kernel).

El motor anterior mezclaba niveles: preguntaba a la base de datos de bindings
antes de haber comprobado siquiera si el fichero cumplía la sintaxis del
lenguaje. Sus reglas están reimplantadas cada una en su capa (ver [«Qué quedó
del motor antiguo»](#qué-quedó-del-motor-antiguo)) y el módulo que las
guardaba, `dts_engine/semantic_old.py`, ya no existe.

## El orden y por qué es ese

```
     texto .dts/.dtsi
            |
            v
   [0] parser (sintaxis)          llaves, «;», cabeceras de nodo
            |
            v
   [1] Especificación DT          reglas del lenguaje, valen SIEMPRE      <-- implementada
            |
            v
   [2] Bindings genéricos         clases de dispositivo y buses comunes    <-- implementada
            |
            v
   [3] dt-bindings/*.h            constantes: qué significan los números  <-- parcial (existencia y valor)
            |
            v
   [4] Drivers del kernel         lo que el código exige de verdad
            |
            v
   [5] Bindings específicos       el binding del «compatible» concreto     <-- parcial
```

Las capas 1, 5 y la parte barata de la 2 se recorren en cada análisis; lo que
valida el propio schema (los valores de la capa 5 y la capa 2 entera) va en
una segunda pasada, `run_schema_checks`, que la GUI ejecuta en un hilo de
fondo. Es la diferencia entre microsegundos por nodo y milisegundos.

La regla de oro es que **una capa nunca contradice a la anterior**, y que una
capa solo habla de lo que su fuente afirma. Si una comprobación necesita algo
que aún no se ha resuelto (una macro sin expandir, un include sin fusionar),
se calla en lugar de inventarse un error.

El orden va de lo universal a lo particular:

| Capa | Fuente de verdad | Alcance | Estado |
|------|------------------|---------|--------|
| 1 | Devicetree Specification v0.4 | Todo device tree, sin excepción | **Implementada** |
| 2 | Bindings genéricos (los schemas con `select` de dt-schema: cap. 4 de la especificación y bindings comunes del kernel) | Clases de dispositivo y buses | **Implementada** |
| 3 | Cabeceras `dt-bindings/*.h` | Valores de las propiedades | **Parcial** (existencia, y valor si hubo `cpp` en la ingesta) |
| 4 | Drivers del kernel (`drivers/**`) | Lo que el código lee de verdad | Pendiente |
| 5 | Binding del `compatible`, procesado por dt-schema (`Documentation/devicetree/bindings/**`) | Un dispositivo concreto | **Parcial** |

### Capa 1 — Especificación Device Tree *(implementada)*

Fuente: <https://github.com/devicetree-org/devicetree-specification>
(Devicetree Specification v0.4, capítulos 2, 3 y 6).

Es la única capa que puede afirmar algo de *cualquier* device tree, venga del
kernel, de un fabricante o del propio editor. Comprueba nombres, tipos de
valor de las propiedades estándar, direccionamiento y estructura del
documento. Está detallada más abajo.

### Capa 2 — Bindings genéricos *(implementada)*

Código: `src/kernelgrove/dts_engine/checks/generic/`.

El capítulo 4 de la propia especificación ya define bindings genéricos
(clase serial, clase red, `simple-bus`, controladores Open PIC), y el kernel
añade los suyos: `i2c-controller.yaml`, `gpio.yaml`, `pinctrl.yaml`,
`regulator.yaml`, `property-units.yaml`…

**Cuáles son, exactamente**: los que dt-schema marca con `select`. Un binding
normal se busca por su `compatible`; uno genérico se prueba contra *todos* los
nodos y su `select` decide si le toca. En el kernel son 228 de 5 663, y en
ellos está lo que vale para una *clase*: que un controlador GPIO declare
`#gpio-cells`, que un bus I2C no pase de 5 MHz, que una propiedad acabada en
`-microvolt` sea un entero, o que `pinctrl-names` venga con su `pinctrl-0`.

Aquí también se comprueba el registro de prefijos de fabricante
(`vendor-prefixes.yaml`): un `noexiste,propiedad` suele ser una errata. Va
aparte del bucle porque sus 966 patrones costaban el 86 % del tiempo de la
capa, y la respuesta solo depende del nombre, así que se resuelve con una
expresión regular y se recuerda.

**Se ejecuta en la pasada diferida.** `run_schema_checks` reúne todo lo que
consiste en darle un nodo entero a un validador de JSON Schema —esta capa
completa (≈10 ms por nodo) y los valores de la capa 5 (≈2,6 ms)— porque
ninguna de las dos cabe en cada pulsación de tecla. La GUI la lanza en un hilo
de fondo tras cada análisis y añade sus avisos cuando llegan
(`SchemaChecksWorker`). Cuando las dos capas dicen lo mismo de la misma
propiedad —el binding de Cadence limita `clock-frequency` a 400 kHz y la clase
I2C a 5 MHz— se conserva el primero, que es el del binding concreto
(`KernelGroveService.merge_deferred`).

| Código | Gravedad | Qué comprueba |
|--------|----------|----------------|
| `generic-missing-property` | ERROR | la clase exige una propiedad que no está (incluidas las dependencias: `gpio-controller` obliga a `#gpio-cells`) |
| `generic-property-value` | WARNING | el valor incumple lo que la clase declara |
| `generic-vendor-prefix` | WARNING | el prefijo de fabricante de una propiedad no está registrado |

Lo que **no** vuelve aquí es la comprobación de bus del motor antiguo
(`_check_placement`): dt-schema no dice de qué bus cuelga un dispositivo (no
existe ningún `i2c-peripheral-props.yaml`), así que eso sigue saliendo de la
inferencia propia de la ingesta.

### Capa 3 — Cabeceras `dt-bindings/*.h` *(parcial: existencia y valor)*

Código: `dts_engine/checks/macros.py`. Ingesta: `db_manager/macros.py` (tabla
`--table macros`, nombres derivados de `sources`, valores de `cpp` contra el
checkout).

Los valores de los device trees reales no son números sino macros
(`GIC_SPI`, `IRQ_TYPE_LEVEL_HIGH`, `RK3399_CLK_...`), y esta capa tiene dos
niveles:

**Existencia**, siempre disponible: si `GPIO_HIGH` aparece en un valor,
¿está esa macro definida en algún sitio? La ingesta indexa cada cabecera
`dt-bindings/*.h` con un `#\s*define NOMBRE` por línea (tabla
`header_macros`, sin preprocesador), incluido el cierre transitivo de lo
que esa cabecera incluye a su vez (el grafo es minúsculo, 24 aristas en
todo el árbol). En tiempo de análisis, `api/service.py` calcula qué macros
ve el documento por sus propios `#include` en cascada
(`IncludeResolver.macro_names`) y se lo pasa al motor como `local_macros`,
igual que `merged_root` para la fusión de includes — el motor no toca la
base de datos.

Dos gravedades, según la fuerza de la evidencia:

| Código | Gravedad | Qué comprueba |
|--------|----------|----------------|
| `macro-missing-include` | WARNING | el nombre existe en alguna cabecera `dt-bindings/*.h` conocida, pero no entre las que este documento incluye — probablemente falta un `#include` |
| `macro-unknown` | INFO | el nombre no existe en ninguna cabecera `dt-bindings/*.h` conocida (podría ser una macro local de un driver, fuera de `dt-bindings/`) |

Es una comprobación barata (consultas a diccionario, sin `jsonschema`), así
que corre en `run_checks`, no en la pasada diferida.

**Valor**, solo si la base se construyó con `cpp` disponible: la ingesta le
pide a `cpp` que expanda cada macro en el contexto real de su cabecera —una
sola invocación por cabecera, con todos sus nombres detrás de un marcador
que sobrevive a que `cpp` reordene líneas— y lo que queda, si es una
expresión de solo números y operadores, se evalúa con un intérprete mínimo
y restringido (`db_manager/macros.evaluate_c_int_expr`). Una macro de
función sin argumentos (`GIC_CPU_MASK_RAW`) no se expande sin paréntesis y
se queda sin valor, aunque sigue en el índice de existencia. `cpp` corre
**solo en ingesta**, contra el checkout del kernel — nunca en tiempo de
análisis ni sobre texto del usuario, la misma disciplina que el resto de la
base de datos.

El valor resuelto se usa en `checks/bindings/instance.py`: una celda que no
es un literal numérico se busca en `ctx.local_macro_values`
(`IncludeResolver.macro_values`, misma cascada que `macro_names` pero solo
calculada en la pasada diferida, que es la única que necesita valores) antes
de darla por no codificable. Con esto, propiedades como
`hisilicon,fixed-mode = <ALGUNA_MACRO>;` pasan a validarse contra el `enum`
de su binding en vez de quedarse invisibles — pero **no** todo lo que lleva
una macro se beneficia: `interrupts` sigue sin codificarse aunque su celda
de tipo se resuelva, porque su forma de matriz depende del
`#interrupt-cells` del controlador (capa 4), una limitación distinta y
anterior a esta.

### Capa 4 — Drivers del kernel *(pendiente)*

Un binding describe lo que *debería* ser; el driver es lo que realmente se
lee. `of_property_read_*`, `of_device_id`, los `of_match_table`… permiten
detectar propiedades que el binding no documenta, valores por defecto, y
compatibles que existen en el código pero no en `Documentation/`.

Es la capa más costosa (hay que analizar C) y la última que aporta reglas
duras: sirve sobre todo para explicar *por qué* algo hace falta.

### Capa 5 — Bindings específicos *(parcial)*

Código: `src/kernelgrove/dts_engine/checks/bindings/`. Detalle de la integración con
dt-schema en [`DT-SCHEMA-INTEGRATION.md`](DT-SCHEMA-INTEGRATION.md).

El binding del `compatible` concreto: sus `required`, sus propiedades
admitidas, sus valores y sus nodos hijo obligatorios. Es lo más preciso y lo
más frágil, y por eso va al final: solo se aplica a un nodo cuyo compatible se
ha resuelto **de forma exacta**, incluido el nodo dentro del schema al que
corresponde (un `ti,twl4030-pwm` se valida contra el subnodo del MFD, no
contra el MFD).

La fuente no es el YAML crudo sino el schema ya procesado por dt-schema
durante la ingesta, con la herencia `allOf`/`$ref` resuelta: sin ella, 1 988
entradas `required` del kernel —entre ellas `reg` en 221 bindings— serían
invisibles.

| Código | Gravedad | Qué comprueba |
|--------|----------|----------------|
| `binding-missing-property` | ERROR | falta una propiedad que el binding exige |
| `binding-missing-node` | ERROR | falta un subnodo que el binding exige |
| `binding-unknown-property` | WARNING / INFO | el binding, cerrado (`additionalProperties: false`), no admite esa propiedad |
| `binding-property-value` | WARNING | el valor no está en el `enum`/`const` o se sale de `minimum`/`maximum` |
| `binding-rejected-compatible` | WARNING | el compatible está en `incomplete-devices.yaml` |
| `binding-unknown-compatible` | INFO | ningún binding YAML lo documenta, así que no se puede comprobar nada más |
| `binding-newer-than-kernel` | WARNING | el binding se documenta en una release posterior al kernel objetivo |

`binding-newer-than-kernel` es la única regla que necesita un dato que no
está en ningún device tree: contra qué kernel se trabaja. Lo aporta el
usuario desde la barra de estado (`KernelGroveService.kernel_target`) y sin él la
regla se calla. Compara con `schemas.since`, la primera release cuyo árbol
trae el fichero del binding, y por eso habla de cuándo se **documentó**: un
compatible puede haber existido antes en un binding `.txt` con otro nombre.

Los valores se comprueban dándole el nodo entero al schema del binding, como
hace `dt-validate`, y **en la pasada diferida** junto con la capa 2: `checks/bindings/instance.py` traduce cada propiedad a la
forma que el schema espera (un `uint32` es un entero, un `uint32-matrix` una
lista de listas) y `jsonschema` hace el resto. **Lo que no se puede traducir
con certeza se queda fuera** y nadie habla de ello: valores con macros de
`dt-bindings/*.h` (capa 3), referencias `&label` —cuántas celdas ocupa cada
una lo dice el nodo apuntado— y matrices cuyo tamaño de fila depende de otro
nodo, como `interrupts` y su `#interrupt-cells`. La excepción es `reg`, cuyas
filas salen de `#address-cells`/`#size-cells` del padre.

Del resultado del schema solo se cuentan los problemas de **valor**: `required`
y `additionalProperties` los cubren las reglas propias, que saben mirar el
árbol fusionado y rebajar el aviso cuando no es concluyente. Las ramas
condicionales del schema (`if/then`, `oneOf`) se recorren solo para saber qué
propiedades *pueden* ser válidas, nunca para exigir nada.

## Capa 1 en detalle

Código: `src/kernelgrove/dts_engine/checks/spec/`, un módulo por bloque de la
especificación.

| Módulo | Apartados | Qué comprueba |
|--------|-----------|----------------|
| `naming.py` | §2.2.1, §2.2.3.1, §6.2, §6.3 | node-name y unit-address (juego de caracteres, longitud, empezar por letra), nombres de propiedad, etiquetas, choque nodo/propiedad, propiedades antes que nodos hijo |
| `properties.py` | §2.3, §2.4, §3.2 | tipo de valor de las propiedades estándar (`<empty>`, `<u32>`, `<string>`, `<stringlist>`), valores admitidos de `status` y `chassis-type`, formato de `compatible`, propiedades obsoletas, reglas de interrupciones |
| `addressing.py` | §2.2.1, §2.3.5, §2.3.6 | `reg` frente a `unit-address`, número de celdas de `reg`, `#address-cells`/`#size-cells` en nodos con hijos direccionados |
| `structure.py` | §3.1-§3.8, §6.4 | propiedades obligatorias de la raíz, `/cpus` y `/memory`, nombres de `/aliases`, nodos `cpu`, `/dts-v1/;` |

`values.py` y `context.py` ya no viven en `spec/` sino un nivel más arriba, en
`checks/`, porque los comparten todas las capas:

| Módulo | Qué aporta |
|--------|------------|
| `checks/values.py` | leer un valor DTS (cadenas, celdas, bytestrings, referencias) y detectar lo que no se puede resolver todavía (§6.3) |
| `checks/context.py` | estado común: árbol propio y fusionado, línea de cada propiedad, resolución de las reaperturas `&label { … }` y política de cuándo se puede afirmar que algo falta |

### De la especificación a la gravedad

| La especificación dice | Gravedad | Ejemplo |
|------------------------|----------|---------|
| «shall» / «must» | ERROR | `status = "enabled"` no es un valor admitido (§2.3.4) |
| «should» / «recommended» | WARNING | un `compatible` con mayúsculas o guiones bajos (§2.3.1) |
| obsoleto | WARNING / INFO | `name` (§2.3.11), `device_type` fuera de cpu y memory (§2.3.12) |
| límite que nadie aplica | INFO | los 31 caracteres de nombres y etiquetas: es la norma, pero ni dtc ni el kernel lo respetan |

### Cuándo puede el motor decir que «falta» algo

Afirmar una ausencia exige ver el árbol entero, y el fichero que se está
editando casi nunca lo contiene: una placa hereda `/cpus`, `/memory` y media
docena de propiedades obligatorias del `.dtsi` que incluye.

**Lo primero es mirar el árbol correcto.** Antes de comprobar nada,
`KernelGroveService.analyze_source` fusiona una copia del árbol con el contenido de
sus includes —lo mismo que hace el visualizador, resolviéndolos contra la
tabla `sources` de la base de datos— y se lo pasa a las comprobaciones como
`merged_root`. La presencia de un nodo o de una propiedad se consulta ahí
(`SpecContext.effective_properties` / `effective_children`); **la línea del
aviso sale siempre del árbol del documento**, que es el único cuyas líneas
corresponden al texto que el usuario tiene delante.

Con eso, hay dos clases de exigencia:

- **Del documento entero** (`model` y `compatible` en la raíz, `/cpus`,
  `/memory`, `/dts-v1/;`): solo significan algo en un device tree completo y
  visto entero, así que no se comprueban en un `.dtsi` ni en un fichero cuyos
  includes no se han podido fusionar (`SpecContext.is_complete_document`).
- **De un nodo concreto** (un `cpu` sin `reg`, un `memory` sin `device_type`,
  un controlador de interrupciones sin `#interrupt-cells`): el nodo está
  escrito en este fichero, así que la comprobación vale siempre.

Cuando la comprobación vale pero no se puede ser concluyente —el documento es
un fragmento, algún include no se encontró, o el nodo solo se reabre aquí con
`&label { … }`— el diagnóstico **se rebaja un escalón** (error → aviso,
aviso → informativo) y se explica el motivo en la pista, en lugar de callarse.
Eso lo decide `SpecContext.report(..., missing=True)`, en un solo sitio.

La versión anterior de esta capa silenciaba las comprobaciones en cuanto el
documento tenía un `#include`, que es el caso normal: borrar `model` de la
raíz o `reg` de un `cpu` no producía nada. La regla honesta no es callar, es
mirar el árbol completo y, si no se puede, decirlo con menos gravedad.

### Lo que la capa 1 deliberadamente NO comprueba

- **Nada que dependa de una macro sin expandir.** Es la capa 3.
- **Nada específico de un bus.** Que la unit-address de un dispositivo PCI sea
  `dev,fn` o que un chip select SPI valga menos que `#cs-lines` lo define el
  binding del bus (capa 2). Por eso `_parse_unit_address` solo compara
  unit-address que son hexadecimal puro.
- **Nada específico de un dispositivo.** Qué propiedades necesita un
  `atmel,24c02` es la capa 5.
- **La coherencia de las referencias.** Resolver `&label` contra el árbol y
  seguir `interrupt-parent` exige fusionar includes primero; hoy el parser deja
  las reapariciones `&label { … }` como pseudonodos sueltos.
- **Nada basado en la indentación**: DTS no tiene reglas de indentación (ver
  `CLAUDE.md`).

### Verificación contra el kernel

Toda regla nueva se contrasta con los 6347 ficheros `.dts`/`.dtsi` del
checkout (`kernel/linux/arch/**`), que se dan por correctos: si una regla
dispara masivamente, o la regla está mal planteada o hay que rebajarla.

La medida que vale es la del camino que usa la aplicación (`--db`, con los
includes fusionados); sin base de datos no se resuelve nada y las cifras solo
sirven para comparar entre sí.

Estado actual con `--db`: **10 986 diagnósticos en 6347 ficheros** (1,7 por
fichero), y **3464 ficheros sin ningún diagnóstico**. Por gravedad: 397
ERROR, 4940 WARNING y 5649 INFO. Los ERROR salen en 156 ficheros y se han
revisado grupo a grupo:

| Nº | Diagnóstico | Verificado |
|----|-------------|-----------|
| 231 | alias con `_`, mayúsculas o comas (§3.3) | 27 ficheros, sobre todo powerpc y layerscape |
| 90 | falta `/cpus` (§3.1) | placas ARM y MIPS antiguas que no declaran CPUs en ninguno de sus ficheros |
| 35 | la raíz no declara `model`/`compatible` (§3.2) | p. ej. `mips/…/octeon_3xxx.dts`, que no los tiene |
| 17 | nodo `memory` sin `device_type` (§3.4) | real |
| 16 | `interrupt-map` sin `#interrupt-cells`/`#address-cells` (§2.4.3) | 6 ficheros powerpc |
| 4 | alias mal formado, `/cpus` sin celdas, nodo que repite el nombre de una propiedad | real |

Los avisos más frecuentes —unit-address que no coincide con `reg`,
unit-address sin `reg`, compatibles con mayúsculas o guiones bajos— también
son desviaciones reales, las mismas que señala `dtc`.

Se mide con:

```sh
python scripts/check_corpus.py --db                # como la aplicación
python scripts/check_corpus.py --db --limit 400    # muestra rápida
python scripts/check_corpus.py --code spec-reg-mismatch --examples 20
python scripts/check_corpus.py --syntax            # diagnósticos del parser
```

Las falsas alarmas que ya costó eliminar una vez, y que hay que vigilar al
tocar reglas:

- nombres y etiquetas generados por macros de C (`DIE_NODE(pmgr)`,
  `EFUSE(10, 27)`);
- la barra de continuación `\` dentro de un valor;
- `stdout-path = &uart0`: una referencia donde se espera una ruta (§6.3);
- `/dts-v1/;` escrito en un `.dtsi` que la placa incluye —la marca vale esté
  donde esté, porque `dtc` ve el texto de todos los ficheros pegados, así que
  se busca también dentro de los includes
  (`IncludeResolver.text_in_includes`);
- las reaperturas `&label { … }`, que el parser cuelga de la raíz y no son
  hijos declarados en el cuerpo del nodo;
- un fichero que reabre un nodo suyo (`soc { … }; soc { … };`): el parser
  fusiona ambas apariciones en un solo nodo, como hace `dtc`. Cuando creaba
  dos hermanos idénticos, la fusión de includes solo alcanzaba a uno y el
  otro parecía no declarar `#address-cells`.

## Qué quedó del motor antiguo

`dts_engine/semantic_old.py` se ha borrado. Se conservó mientras se
reconstruían las capas 2 y 5, como referencia de lo que había que recuperar;
hoy cada regla vive en su capa y el módulo no lo instanciaba nadie:

| Regla antigua | Dónde está hoy |
|---------------|----------------|
| `_check_placement` (nodo colgado del bus equivocado) | No vuelve tal cual: dt-schema no dice de qué bus cuelga un dispositivo, así que eso sigue saliendo de la inferencia de la ingesta (ver capa 2) |
| `_check_required` (propiedades y nodos hijo obligatorios) | Capa 5, `checks/bindings/rules.py` (`binding-missing-property`, `binding-missing-node`) |
| Aviso de `compatible` desconocido | Capa 5, `binding-unknown-compatible` |
| `BindingSpec` / `BindingLookup` (contrato con la base de datos) | `checks/bindings/lookup.py`, que habla de schemas ya procesados por dt-schema en lugar del YAML crudo |
| `check_compatible_format` de `parser.py` | Capa 1 (§2.3.1) |

De aquella reimplantación siguen en pie las dos cosas que había que conservar
sí o sí: la resolución **exacta** del compatible y el trato de los `.dtsi`
como fragmentos.

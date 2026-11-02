# Tipos de nodos y bindings en Device Tree

## Introducción

Un nodo del Device Tree **no representa necesariamente un periférico**. Su objetivo es describir cualquier elemento del hardware que el kernel necesite conocer para inicializar correctamente la plataforma.

Dependiendo de su función, un nodo puede representar un dispositivo final, un proveedor de recursos, un controlador de bus o simplemente información descriptiva del hardware.

---

# 1. Periféricos

## Propósito

Representan dispositivos hardware finales que realizan una función concreta (UART, SPI, Ethernet, USB, PWM, etc.).

## Características

- Tienen un driver asociado.
- El kernel crea un `platform_device` (o un dispositivo del bus correspondiente).
- El driver realiza el `probe()` utilizando la información del Device Tree.

## Ejemplos

- UART
- SPI Controller
- Ethernet MAC
- USB Controller
- CAN
- ADC
- PWM

---

# 2. Controladores de bus

## Propósito

Representan un bus físico al que pueden conectarse otros dispositivos.

No describen los dispositivos hijos, sino el controlador que administra dicho bus.

## Características

- Tienen driver.
- Descubren los nodos hijos.
- Crean dinámicamente los dispositivos conectados al bus.

## Ejemplos

- I²C Controller
- SPI Controller
- PCI Host Controller
- MDIO Bus
- USB Host Controller

---

# 3. Proveedores de recursos (Resource Providers)

## Propósito

Proporcionan recursos compartidos que utilizan otros dispositivos.

No suelen ser dispositivos finales.

## Características

- Implementan un framework del kernel.
- Otros nodos hacen referencia a ellos mediante phandles.
- Exportan un servicio al resto del sistema.

Los principales proveedores son:

### 3.1 Clock Controllers

Proporcionan relojes a otros dispositivos.

Propiedad utilizada por los consumidores:

```dts
clocks = <&clk>;
```

Framework:

- Common Clock Framework (CCF)

---

### 3.2 Reset Controllers

Permiten reiniciar dispositivos hardware.

Propiedad:

```dts
resets = <&rst>;
```

Framework:

- Reset Framework

---

### 3.3 GPIO Controllers

Exportan líneas GPIO que pueden ser utilizadas por otros dispositivos.

Propiedad:

```dts
reset-gpios = <&gpio0 5 GPIO_ACTIVE_LOW>;
```

Framework:

- GPIO Framework

---

### 3.4 Regulators

Describen fuentes de alimentación.

Propiedad:

```dts
vdd-supply = <&reg_3v3>;
```

Framework:

- Regulator Framework

---

### 3.5 Interrupt Controllers

Gestionan interrupciones hardware.

Propiedad:

```dts
interrupt-parent = <&gic>;
```

Framework:

- IRQ Domain Framework

---

### 3.6 DMA Controllers

Proporcionan canales DMA.

Propiedad:

```dts
dmas = <&dma0 3>;
```

Framework:

- DMA Engine

---

### 3.7 PHY

Representan la capa física de interfaces como USB, Ethernet, SATA o PCIe.

Propiedad:

```dts
phys = <&usb_phy>;
```

Framework:

- Generic PHY Framework

---

### 3.8 Power Domains

Controlan el encendido y apagado de bloques hardware.

Propiedad:

```dts
power-domains = <&pd>;
```

Framework:

- Generic PM Domains

---

### 3.9 IOMMU

Describen una unidad de gestión de memoria para dispositivos DMA.

Propiedad:

```dts
iommus = <&smmu>;
```

Framework:

- IOMMU Framework

---

# 4. Nodos descriptivos

## Propósito

Describen características de la plataforma, pero no representan dispositivos controlables.

Normalmente no tienen driver.

---

## 4.1 CPU

Describe los procesadores presentes.

Información típica:

- tipo de CPU
- método de arranque
- topología
- cachés

Utilizado por:

- Scheduler
- SMP
- CPUFreq
- CPUIdle

---

## 4.2 Memory

Describe la memoria RAM disponible.

Información:

- dirección base
- tamaño

Utilizado por:

- Memory Manager

---

## 4.3 Reserved Memory

Describe regiones de memoria que el kernel no debe utilizar libremente.

Ejemplos:

- Firmware
- Buffers DMA
- Framebuffers
- Secure Memory

---

# 5. Nodos organizativos

## Propósito

Sirven únicamente para organizar el árbol.

No representan hardware.

No tienen driver.

## Ejemplos

### soc

Agrupa todos los periféricos integrados en el SoC.

### aliases

Define nombres cortos.

Ejemplo:

```dts
serial0 = &uart0;
```

---

### chosen

Comunica información al kernel durante el arranque.

Ejemplos:

- bootargs
- stdout-path
- initrd

---

### firmware

Describe interfaces proporcionadas por el firmware.

---

# 6. Nodos auxiliares

## Propósito

Definen configuraciones utilizadas por otros dispositivos.

No suelen tener driver propio.

---

## 6.1 Pin Configuration

Describe configuraciones de multiplexación y parámetros eléctricos.

Utilizado mediante:

```dts
pinctrl-0 = <&uart0_pins>;
```

---

## 6.2 OPP Tables

Definen Operating Performance Points.

Asocian:

- frecuencia
- voltaje

Utilizadas por:

- CPUFreq
- Devfreq

---

## 6.3 Thermal Zones

Describen sensores y políticas térmicas.

Utilizadas por:

- Thermal Framework

---

## 6.4 Graph Endpoints

Describen conexiones entre dispositivos multimedia.

Muy utilizados en:

- cámaras
- display
- CSI
- DSI

---

# ¿Cómo se conectan entre sí?

Los nodos no se conectan mediante punteros ni por jerarquía necesariamente.

La mayoría de las relaciones se realizan mediante **phandles**.

Ejemplo:

```
UART
 │
 ├── clocks --------> Clock Controller
 ├── resets --------> Reset Controller
 ├── dmas ----------> DMA Controller
 ├── power-domains -> Power Domain
 └── pinctrl-0 -----> Pin Controller
```

Cada framework del kernel resuelve automáticamente estas referencias cuando el driver solicita el recurso correspondiente.

---

# Resumen

| Categoría | Tiene driver | Representa hardware final | Proporciona recursos |
|------------|--------------|---------------------------|----------------------|
| Periférico | Sí | Sí | No |
| Controlador de bus | Sí | No | Sí (crea dispositivos hijos) |
| Clock Controller | Sí | No | Sí |
| GPIO Controller | Sí | No | Sí |
| Reset Controller | Sí | No | Sí |
| Regulator | Sí | No | Sí |
| Interrupt Controller | Sí | No | Sí |
| DMA Controller | Sí | No | Sí |
| PHY | Sí | No | Sí |
| Power Domain | Sí | No | Sí |
| IOMMU | Sí | No | Sí |
| CPU | No (driver de plataforma) | No | No |
| Memory | No | No | No |
| Reserved Memory | No | No | No |
| Pin Configuration | No | No | Configuración |
| OPP Table | No | No | Configuración |
| Thermal Zone | No | No | Configuración |
| Graph Endpoint | No | No | Describe conexiones |
| `soc`, `aliases`, `chosen`, `firmware` | No | No | Organización del árbol |
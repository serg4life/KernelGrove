# Node types and bindings in the Device Tree

## Introduction

A Device Tree node **does not necessarily represent a peripheral**. Its purpose is to describe any element of the hardware the kernel needs to know about to initialise the platform correctly.

Depending on its function, a node can represent an end device, a resource provider, a bus controller, or simply descriptive information about the hardware.

---

# 1. Peripherals

## Purpose

They represent end hardware devices that perform a specific function (UART, SPI, Ethernet, USB, PWM, etc.).

## Characteristics

- They have an associated driver.
- The kernel creates a `platform_device` (or a device on the corresponding bus).
- The driver performs its `probe()` using the information in the Device Tree.

## Examples

- UART
- SPI Controller
- Ethernet MAC
- USB Controller
- CAN
- ADC
- PWM

---

# 2. Bus controllers

## Purpose

They represent a physical bus other devices can be connected to.

They do not describe the child devices, but the controller that manages that bus.

## Characteristics

- They have a driver.
- They discover the child nodes.
- They dynamically create the devices connected to the bus.

## Examples

- I²C Controller
- SPI Controller
- PCI Host Controller
- MDIO Bus
- USB Host Controller

---

# 3. Resource providers

## Purpose

They provide shared resources used by other devices.

They are not usually end devices.

## Characteristics

- They implement a kernel framework.
- Other nodes refer to them through phandles.
- They export a service to the rest of the system.

The main providers are:

### 3.1 Clock Controllers

They provide clocks to other devices.

Property used by consumers:

```dts
clocks = <&clk>;
```

Framework:

- Common Clock Framework (CCF)

---

### 3.2 Reset Controllers

They allow hardware devices to be reset.

Property:

```dts
resets = <&rst>;
```

Framework:

- Reset Framework

---

### 3.3 GPIO Controllers

They export GPIO lines that other devices can use.

Property:

```dts
reset-gpios = <&gpio0 5 GPIO_ACTIVE_LOW>;
```

Framework:

- GPIO Framework

---

### 3.4 Regulators

They describe power supplies.

Property:

```dts
vdd-supply = <&reg_3v3>;
```

Framework:

- Regulator Framework

---

### 3.5 Interrupt Controllers

They manage hardware interrupts.

Property:

```dts
interrupt-parent = <&gic>;
```

Framework:

- IRQ Domain Framework

---

### 3.6 DMA Controllers

They provide DMA channels.

Property:

```dts
dmas = <&dma0 3>;
```

Framework:

- DMA Engine

---

### 3.7 PHY

They represent the physical layer of interfaces such as USB, Ethernet, SATA or PCIe.

Property:

```dts
phys = <&usb_phy>;
```

Framework:

- Generic PHY Framework

---

### 3.8 Power Domains

They control powering hardware blocks on and off.

Property:

```dts
power-domains = <&pd>;
```

Framework:

- Generic PM Domains

---

### 3.9 IOMMU

They describe a memory management unit for DMA devices.

Property:

```dts
iommus = <&smmu>;
```

Framework:

- IOMMU Framework

---

# 4. Descriptive nodes

## Purpose

They describe characteristics of the platform, but do not represent controllable devices.

They usually have no driver.

---

## 4.1 CPU

Describes the processors present.

Typical information:

- CPU type
- boot method
- topology
- caches

Used by:

- Scheduler
- SMP
- CPUFreq
- CPUIdle

---

## 4.2 Memory

Describes the available RAM.

Information:

- base address
- size

Used by:

- Memory Manager

---

## 4.3 Reserved Memory

Describes memory regions the kernel must not use freely.

Examples:

- Firmware
- DMA buffers
- Framebuffers
- Secure Memory

---

# 5. Organisational nodes

## Purpose

They only serve to organise the tree.

They do not represent hardware.

They have no driver.

## Examples

### soc

Groups all the peripherals integrated in the SoC.

### aliases

Defines short names.

Example:

```dts
serial0 = &uart0;
```

---

### chosen

Passes information to the kernel at boot.

Examples:

- bootargs
- stdout-path
- initrd

---

### firmware

Describes interfaces provided by the firmware.

---

# 6. Auxiliary nodes

## Purpose

They define configurations used by other devices.

They do not usually have a driver of their own.

---

## 6.1 Pin Configuration

Describes multiplexing configurations and electrical parameters.

Used through:

```dts
pinctrl-0 = <&uart0_pins>;
```

---

## 6.2 OPP Tables

They define Operating Performance Points.

They associate:

- frequency
- voltage

Used by:

- CPUFreq
- Devfreq

---

## 6.3 Thermal Zones

They describe sensors and thermal policies.

Used by:

- Thermal Framework

---

## 6.4 Graph Endpoints

They describe connections between multimedia devices.

Widely used in:

- cameras
- display
- CSI
- DSI

---

# How do they connect to each other?

Nodes are not necessarily connected through pointers or through the hierarchy.

Most relationships are expressed through **phandles**.

Example:

```
UART
 │
 ├── clocks --------> Clock Controller
 ├── resets --------> Reset Controller
 ├── dmas ----------> DMA Controller
 ├── power-domains -> Power Domain
 └── pinctrl-0 -----> Pin Controller
```

Each kernel framework resolves these references automatically when the driver requests the corresponding resource.

---

# Summary

| Category | Has a driver | Represents end hardware | Provides resources |
|----------|--------------|-------------------------|--------------------|
| Peripheral | Yes | Yes | No |
| Bus controller | Yes | No | Yes (creates child devices) |
| Clock Controller | Yes | No | Yes |
| GPIO Controller | Yes | No | Yes |
| Reset Controller | Yes | No | Yes |
| Regulator | Yes | No | Yes |
| Interrupt Controller | Yes | No | Yes |
| DMA Controller | Yes | No | Yes |
| PHY | Yes | No | Yes |
| Power Domain | Yes | No | Yes |
| IOMMU | Yes | No | Yes |
| CPU | No (platform driver) | No | No |
| Memory | No | No | No |
| Reserved Memory | No | No | No |
| Pin Configuration | No | No | Configuration |
| OPP Table | No | No | Configuration |
| Thermal Zone | No | No | Configuration |
| Graph Endpoint | No | No | Describes connections |
| `soc`, `aliases`, `chosen`, `firmware` | No | No | Tree organisation |

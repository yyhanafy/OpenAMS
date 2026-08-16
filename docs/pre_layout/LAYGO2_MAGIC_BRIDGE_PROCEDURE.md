# OpenAMS → Magic SKY130 → Laygo2 → Magic Extraction Bridge

## Purpose

This note records the exact procedure that was successfully demonstrated on the OpenAMS workstation for preserving arbitrary OpenAMS transistor geometry through a physical-layout flow.

The proof-of-concept device was:

- Model: `sky130_fd_pr__nfet_01v8`
- Width: `W = 10 µm`
- Length: `L = 0.5 µm`
- Fingers: `nf = 1`

The important result was that Magic generated the requested SKY130 transistor, Laygo2 accepted it as an external native template and placed two copies, and Magic extraction recovered a hierarchical layout whose underlying physical MOS remained `w=10 l=0.5`.

## Why this bridge exists

The existing ALIGN and Laygo2 SKY130 MOS generators use technology-specific fixed transistor tiles. That is inconvenient for OpenAMS because OpenAMS may choose transistor lengths and widths that are valid in SKY130 but are not represented by those fixed templates.

The bridge separates responsibilities:

```text
OpenAMS
  chooses W/L
      ↓
Magic / open_pdks SKY130 PCell
  generates the real legal transistor geometry
      ↓
Laygo2 NativeInstanceTemplate
  stores bbox + routable pin abstraction
      ↓
Laygo2
  placement and later routing
      ↓
Magic
  final physical layout / GDS / extraction
      ↓
ngspice
  post-layout simulation
```

Magic therefore remains the authority for technology-correct device geometry. Laygo2 is used as the placement/routing layer.

## What has been proven

### 1. Magic can generate arbitrary valid W/L

The installed Magic SKY130 generator was called with:

```tcl
magic::gencell \
    sky130::sky130_fd_pr__nfet_01v8 \
    MTEST \
    w 10.0 \
    l 0.5 \
    nf 1 \
    m 1
```

Magic extraction produced:

```text
sky130_fd_pr__nfet_01v8 ... w=10 l=0.5
```

Therefore the `L=0.15 µm` behavior seen in the prior ALIGN experiment was not a SKY130 limitation.

### 2. The generated Magic device is a real hierarchical PCell

The generated child cell had a physical bounding box of approximately:

```text
x = -1.25 ... +1.25 µm
y = -6.07 ... +6.07 µm
```

or in the Magic integer coordinates used in the experiment:

```text
[-125,-607] → [125,607]
```

The `.mag` file also retained the generator properties:

```text
gencell sky130_fd_pr__nfet_01v8
parameters w 10.0 l 0.5 ... nf 1 ...
```

### 3. Electrical terminal identity was recovered from Magic extraction

The extracted transistor was:

```text
X0 drain gate source bulk sky130_fd_pr__nfet_01v8 ... w=10 l=0.5
```

with the extracted node identities corresponding to D/G/S/B.

### 4. A Laygo2 native template can represent the external Magic cell

Laygo2's `NativeInstanceTemplate` constructor in the checked-out workspace is:

```python
NativeInstanceTemplate(libname, cellname, bbox, pins)
```

A custom template was created with:

```python
tnfet = laygo2.object.template.NativeInstanceTemplate(
    libname="openams_magic",
    cellname=child,
    bbox=np.array([[0,0],[250,1214]]),
    pins=pins,
)
```

Two instances were generated and translated independently:

```python
m0 = tnfet.generate(name="M0")
m1 = tnfet.generate(name="M1")
m0.xy = np.array([0,0])
m1.xy = np.array([400,0])
```

Laygo2 correctly translated the abstract pin coordinates for each instance.

### 5. Laygo2's Magic interface can export the external cell

Laygo2 generated Magic commands of the form:

```text
_laygo2_generate_instance M0 ... openams_magic_sky130_fd_pr__nfet_01v8_... ...
_laygo2_generate_instance M1 ... openams_magic_sky130_fd_pr__nfet_01v8_... ...
```

A practical detail discovered during the experiment: the external `.mag` child was copied into the same directory as the generated top-level Magic cell so Magic could resolve it reliably in batch mode.

### 6. Final Magic extraction preserved both hierarchy and geometry

The top-level `.mag` contained two child instances:

```text
use openams_magic_sky130_fd_pr__nfet_01v8_... M0
use openams_magic_sky130_fd_pr__nfet_01v8_... M1
```

Final extraction produced a child subcircuit containing:

```text
sky130_fd_pr__nfet_01v8 ... w=10 l=0.5
```

and the top cell contained:

```text
XM0 SUB openams_magic_sky130_fd_pr__nfet_01v8_...
XM1 SUB openams_magic_sky130_fd_pr__nfet_01v8_...
```

Only one `w=10 l=0.5` line appears because the transistor geometry is defined once in the hierarchical child cell and instantiated twice at the top level. This is expected.

## Reproduce the proven experiment

Use the accompanying regression script:

```bash
bash run_laygo2_magic_bridge_demo.sh
```

Default paths assumed by the script:

```text
OpenAMS:  ~/AMS-Tutorial/openams
Laygo2:   ~/AMS-Tutorial/laygo2_workspace_sky130
Magic:    /usr/local/share/pdk/sky130A/libs.tech/magic/sky130A.tech
Output:   /tmp/openams_laygo2_magic_bridge_demo
```

They may be overridden, for example:

```bash
LAYGO2_WS=~/AMS-Tutorial/laygo2_workspace_sky130 \
OPENAMS_ROOT=~/AMS-Tutorial/openams \
OUT=/tmp/my_bridge_run \
bash run_laygo2_magic_bridge_demo.sh
```

The script intentionally supports only the proven regression point:

```text
W = 10 µm
L = 0.5 µm
nf = 1
```

because the current Laygo2 abstract pin rectangles were derived from that exact Magic-generated PCell.

## Current non-generic piece

The device-generation part is already parameterized in Magic, but the Laygo2 pin abstraction is not yet generic.

For the proven W=10/L=0.5/nf=1 NFET, the normalized Laygo2 abstraction used:

```text
bbox: [0,0] → [250,1214]

D locali: [156,105] → [174,1109]
G locali: [100,70]  → [150,88]
S locali: [76,105]  → [94,1109]
B locali: [18,19]   → [67,36]
```

These rectangles were derived from the actual generated `.mag` geometry. They must not be assumed to apply to arbitrary W/L/nf values.

The next engineering task is therefore:

```text
Magic PCell generated for arbitrary W/L/nf
        ↓
automatically derive bbox + D/G/S/B routable access rectangles
        ↓
create Laygo2 NativeInstanceTemplate automatically
```

Once that exists, OpenAMS can generate a template per unique transistor geometry automatically.

## Next validation step

The next physical milestone should be routing rather than more device-generation experiments.

Recommended minimal test:

```text
M0.D ───── M1.G
```

The validation should prove:

1. Laygo2 routes between two Magic-backed devices.
2. Magic accepts the generated route.
3. Extraction shows the intended two terminals on the same electrical node.
4. The child MOS geometry is still `w=10 l=0.5`.

After that, use a small analog primitive such as a current mirror or differential pair before moving to the full two-stage op-amp.

## Intended OpenAMS Stage-2 architecture

```text
pre-layout OpenAMS witness
        ↓
numeric W/L device list
        ↓
Magic SKY130 PCell generation
        ↓
automatic Laygo2 template creation
        ↓
Laygo2 analog placement + routing
        ↓
Magic DRC / extraction
        ↓
Netgen LVS
        ↓
PEX SPICE
        ↓
ngspice post-layout verification
        ↓
post-layout optimization loop
```

This keeps OpenAMS responsible for electrical sizing, Magic responsible for technology-correct physical devices, and Laygo2 responsible for physical composition.

# OpenAMS Core Object Model

## Purpose

This document defines the smallest canonical object model required by OpenAMS.

The objective is to maintain one consistent representation throughout topology
extraction, constraint compilation, synthesis, optimization, simulation, and
result evaluation.

The model must remain:

- topology-generic;
- technology-independent at the circuit level;
- simulator-independent;
- simple to inspect and serialize;
- extensible to analog, digital, and mixed-signal systems;
- free of topology-specific assumptions.

## Design rule

Each core object answers one primary question.

| Object | Primary question |
|---|---|
| Circuit | What components and connections define the design? |
| Node | Which electrical connection is being referenced? |
| Terminal | How does a device connect to a node? |
| Device | What physical or behavioral element is connected? |
| Variable | What quantity may be assigned, derived, or measured? |
| Constraint | What relationship must hold? |
| Assignment | What values are currently known? |
| DeviceQuery | What device behavior must the technology model solve? |
| DeviceSolution | What did the technology model determine? |
| TechnologyModel | How does a physical device behave in this technology? |
| Analysis | What verification is requested? |
| SimulationResult | What did the simulator report? |
| Specification | What performance is required? |
| EvaluationResult | Did the result satisfy the requirements? |

---

# 1. Circuit

A `Circuit` is the canonical representation of one design hierarchy.

It contains:

- circuit name;
- nodes;
- devices;
- variables;
- constraints;
- analyses;
- specifications;
- optional hierarchy references.

Conceptually:

```python
Circuit(
    name="two_stage_opamp",
    nodes={...},
    devices={...},
    variables={...},
    constraints=[...],
    analyses=[...],
    specifications=[...],
)
```

A circuit stores design information.

It does not perform synthesis, simulation, evaluation, or optimization itself.

Required properties:

- every node name is unique within the circuit;
- every device name is unique within the circuit;
- every device terminal references an existing node;
- every variable has a globally unique canonical name;
- every constraint references existing variables or constants.

---

# 2. Node

A `Node` represents one electrical connection.

Minimal fields:

```python
Node(
    name="vout",
    kind="electrical",
)
```

The initial implementation requires only electrical nodes.

Possible future node kinds include:

- digital;
- clock;
- thermal;
- mechanical;
- abstract signal.

A node does not store an operating-point voltage directly.

Voltage is represented by a variable such as:

```text
node.vout.voltage
```

This keeps circuit topology separate from a particular operating point.

---

# 3. Terminal

A `Terminal` identifies one named connection on a device.

Example:

```python
Terminal(
    name="drain",
    node="vout",
)
```

For a MOS transistor, canonical terminal names are:

- drain;
- gate;
- source;
- bulk.

SPICE terminal ordering is normalized during parsing.

The rest of OpenAMS must not depend on raw SPICE terminal order.

---

# 4. Device

A `Device` represents a physical or behavioral circuit element.

Example:

```python
Device(
    name="M1",
    kind="mos",
    model="sky130_fd_pr__nfet_01v8",
    terminals={
        "drain": "n1",
        "gate": "vinp",
        "source": "tail",
        "bulk": "vss",
    },
    parameters={
        "length": "device.M1.length",
        "width": "device.M1.width",
    },
)
```

Initial supported device kinds:

- mos;
- resistor;
- capacitor;
- voltage_source;
- current_source.

Future device kinds may include:

- diode;
- bipolar transistor;
- inductor;
- transmission line;
- digital gate;
- behavioral block;
- extracted parasitic network.

A device stores:

- identity;
- device kind;
- model reference;
- terminal-to-node connectivity;
- references to parameter variables.

A device does not directly contain technology-specific equations.

---

# 5. Variable

A `Variable` represents a named quantity whose value may be:

- fixed;
- selected;
- derived;
- technology-solved;
- simulator-measured;
- optimized.

Example:

```python
Variable(
    name="device.M1.width",
    quantity="length",
    unit="m",
    role="technology_solved",
)
```

Initial variable roles:

- `constant`
- `independent`
- `derived`
- `technology_solved`
- `simulator_measured`
- `objective`

Canonical examples:

```text
node.vout.voltage
device.M1.width
device.M1.length
device.M1.current.drain
device.M1.voltage.vgs
device.M1.voltage.vds
device.M1.region.saturated
analysis.ac.gain_db
analysis.ac.ugb_hz
analysis.ac.phase_margin_deg
```

Variables store identity and metadata.

Values belong in assignments or results.

---

# 6. Constraint

A `Constraint` represents one relationship that must hold.

Initial constraint kinds:

- equality;
- inequality;
- range;
- membership;
- logical;
- technology_query;
- topology_derived.

Examples:

```text
device.M1.width == device.M2.width
device.M1.current.drain == device.M2.current.drain
node.vout.voltage >= 0.5
device.M1.region.saturated == true
```

Conceptual form:

```python
Constraint(
    name="input_pair_width_match",
    kind="equality",
    expression="device.M1.width == device.M2.width",
    source="design_intent",
)
```

Constraint sources may include:

- topology;
- KCL;
- device terminal relations;
- design intent;
- design rules;
- technology;
- simulation requirements;
- specifications.

Constraints must be represented as data, not as topology-specific Python code.

---

# 7. Assignment

An `Assignment` maps canonical variable names to values.

Example:

```python
Assignment(
    name="assignment_000001",
    values={
        "node.vout.voltage": 1.5,
        "device.M1.length": 0.5e-6,
        "device.M1.width": 12.0e-6,
    },
)
```

An assignment may be:

- partial;
- resolved;
- simulation_ready;
- simulated;
- rejected;
- accepted.

An assignment does not duplicate circuit topology or constraints.

It references a circuit and contains only:

- assigned values;
- assignment status;
- optional diagnostics;
- optional provenance.

---

# 8. DeviceQuery

A `DeviceQuery` describes one device-behavior problem for the active technology
model.

Example:

```python
DeviceQuery(
    device_kind="mos",
    polarity="nmos",
    model="sky130_fd_pr__nfet_01v8",
    known={
        "length": 0.5e-6,
        "vgs": 0.8,
        "vds": 0.8,
        "vbs": 0.0,
        "id": 10e-6,
    },
    solve_for=("width",),
    conditions={
        "saturated": True,
    },
)
```

A query contains:

- device identity or class;
- known physical quantities;
- requested unknown quantities;
- required operating conditions;
- optional tolerances.

The query does not expose the implementation details of the active technology
backend.

---

# 9. DeviceSolution

A `DeviceSolution` contains the result of a technology query.

Example:

```python
DeviceSolution(
    values={
        "width": 2.98e-6,
    },
    valid=True,
    diagnostics={
        "method": "inverse_width_interpolation",
    },
)
```

A solution may contain:

- solved values;
- validity status;
- residuals;
- model confidence;
- interpolation or extrapolation information;
- operating-region information;
- diagnostic messages.

---

# 10. TechnologyModel

A `TechnologyModel` answers device-behavior queries.

Conceptual interface:

```python
class TechnologyModel:
    def solve(self, query: DeviceQuery) -> DeviceSolution:
        ...
```

The circuit and synthesis layers must not know whether the backend uses:

- characterization tables;
- an MLP surrogate;
- BSIM evaluation;
- interpolation;
- comparison between models;
- another future model.

Synthesis interacts only with the canonical query interface.

The technology layer owns:

- physical device behavior;
- interpolation;
- surrogate inference;
- backend-specific validity;
- model diagnostics.

---

# 11. Analysis

An `Analysis` describes requested verification.

Initial analysis kinds:

- `dc_operating_point`
- `ac`
- `transient`

Example:

```python
Analysis(
    name="dc",
    kind="dc_operating_point",
    options={},
)
```

Analysis definitions remain simulator-independent.

A simulator adapter translates them into ngspice or another simulator format.

---

# 12. SimulationResult

A `SimulationResult` stores raw and normalized simulator output.

Example:

```python
SimulationResult(
    assignment_name="assignment_000001",
    simulator="ngspice",
    analyses={
        "dc": {...},
        "ac": {...},
    },
    success=True,
    diagnostics=[],
)
```

A simulation result may contain:

- node voltages;
- branch currents;
- device operating-point data;
- frequency-domain metrics;
- transient metrics;
- convergence diagnostics;
- raw artifact references.

Simulator-specific naming must be normalized before entering the canonical
result.

---

# 13. Specification

A `Specification` defines an acceptance requirement or optimization objective.

Example:

```python
Specification(
    name="phase_margin",
    variable="analysis.ac.phase_margin_deg",
    relation=">=",
    target=60.0,
    unit="deg",
    severity="required",
)
```

Specification severities:

- `required`
- `preferred`
- `objective`
- `informational`

Specifications reference normalized result variables.

They do not perform measurement themselves.

---

# 14. EvaluationResult

An `EvaluationResult` records specification screening.

Example:

```python
EvaluationResult(
    assignment_name="assignment_000001",
    passed=True,
    checks={
        "gain": True,
        "phase_margin": True,
        "power": True,
    },
    score=0.94,
)
```

Evaluation remains separate from simulation because:

- simulation success does not imply design acceptance;
- one simulation may be evaluated against multiple specification sets;
- scoring rules may change without rerunning simulation.

---

# 15. Canonical relationships

```text
Circuit
 ├── Nodes
 ├── Devices
 │    └── Terminals reference Nodes
 ├── Variables
 ├── Constraints
 ├── Analyses
 └── Specifications

Assignment
 └── maps Circuit Variables to values

TechnologyModel
 ├── consumes DeviceQuery
 └── produces DeviceSolution

Simulator
 ├── consumes Circuit + Assignment + Analyses
 └── produces SimulationResult

Evaluator
 ├── consumes SimulationResult + Specifications
 └── produces EvaluationResult
```

---

# 16. Ownership boundaries

## Topology layer owns

- nodes;
- devices;
- terminals;
- hierarchy;
- connectivity.

## Constraint layer owns

- equations;
- inequalities;
- ranges;
- logical conditions;
- dependency information.

## Synthesis layer owns

- independent-value selection;
- derived-value propagation;
- technology queries;
- assignment completion;
- consistency rejection.

## Technology layer owns

- device behavior;
- interpolation;
- surrogate inference;
- model-specific validity;
- model diagnostics.

## Simulation layer owns

- simulator input rendering;
- simulator execution;
- raw result extraction;
- normalized simulation results.

## Evaluation layer owns

- specification checks;
- scores;
- pass/fail decisions.

## Optimization layer owns

- candidate selection;
- objective search;
- exploration of unresolved ranges.

---

# 17. What the core model must not contain

The canonical model must not contain:

- hard-coded two-stage op-amp stages;
- left-branch or right-branch concepts;
- M1-through-M7 assumptions;
- direct pandas DataFrames;
- direct CSV table objects;
- ngspice command syntax;
- optimizer-specific tensors;
- generated file paths as primary state;
- duplicate representations of the same variable;
- operating-point values embedded directly in topology objects.

---

# 18. Initial implementation boundary

The first implementation supports only:

- flat electrical circuits;
- MOS transistors;
- resistors;
- capacitors;
- voltage sources;
- current sources;
- scalar variables;
- equality, inequality, and range constraints;
- partial and resolved assignments;
- DC operating-point analysis.

The following are intentionally postponed:

- hierarchy;
- digital events;
- statistical variables;
- post-layout parasitic networks;
- mixed-signal behavioral blocks;
- advanced optimization;
- automatic analog-function recognition;
- AC surrogate modeling.

These capabilities will be added only after the basic DC synthesis model is
validated.

---

# 19. Acceptance criteria

The object model is acceptable when it can represent both:

1. the two-stage op-amp;
2. the folded-cascode OTA;

without adding topology-specific fields or classes.

The same synthesis, technology, simulation, and evaluation interfaces must be
usable for both circuits.

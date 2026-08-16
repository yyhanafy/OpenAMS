# OpenAMS Witness Generation Pipeline

## 1. Purpose

This document describes how to execute the OpenAMS pipeline from a circuit SPICE netlist to a set of complete correlated circuit witnesses.

The emphasis is on:

- the sequence of pipeline stages;
- the exact commands used at each stage;
- the input and output artifacts;
- the metadata that controls each stage;
- topology partitioning into basic sub-components;
- generation and training of the sub-component MLP models;
- hierarchical witness generation.

The reference circuit used throughout this document is the SKY130 two-stage operational amplifier under:

```text
examples/two_stage_opamp/
```

The pipeline covered here ends when OpenAMS has generated complete transistor-level circuit witnesses. SPICE performance characterization and post-layout optimization are downstream stages.

---

# 2. Pipeline Overview

The current OpenAMS witness-generation flow is:

```text
netlist.spice
      │
      ▼
STEP 01
Topology extraction and validation
      │
      ▼
STEP 02
Metadata normalization
      │
      ▼
STEP 03
Constraint classification
      │
      ▼
STEP 04
Constraint compilation
      │
      ▼
STEP 05
Technology model validation
      │
      ▼
Compiled circuit model
      │
      ▼
STEP 06
Independent design-space generation
      │
      ▼
STEP 07
Topology partitioning and
hierarchical interface definition
      │
      ▼
STEP 08
Basic-component dataset generation
using the device-MLP witness engine
      │
      ▼
STEP 09
Basic-component MLP training
      │
      ▼
STEP 10
Component-MLP validation
      │
      ▼
STEP 11
Hierarchical contract compilation
      │
      ▼
STEP 12
Generic hierarchical witness search
      │
      ▼
Complete correlated circuit witnesses
      │
      ▼
ngspice validation
      │
      ▼
Valid circuit witness pool
```

Steps 01–05 constitute the OpenAMS front end. The existing production frontend driver executes topology extraction, metadata normalization, constraint classification, constraint compilation, technology validation, and construction of the canonical compiled circuit model.

The later stages add the hierarchical synthesis method used by the current OpenAMS implementation.

---

# 3. Setup

All commands in this guide assume execution from the OpenAMS repository root.

```bash
cd ~/AMS-Tutorial/openams

source .venv-openams/bin/activate

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
```

For the two-stage reference circuit:

```bash
INPUT=examples/two_stage_opamp/inputs
GEN=examples/two_stage_opamp/generated
```

The principal user-provided circuit files are:

```text
examples/two_stage_opamp/inputs/
├── netlist.spice
├── specs.yaml
├── design_rules.yaml
├── design_intent.yaml
├── simulation.yaml
├── deck_template.spice
└── two_stage_mlp_witness_plan.yaml
```

---

# 4. Input Metadata

## `netlist.spice`

Defines the physical circuit topology.

It provides:

- MOS devices;
- device terminals;
- electrical nodes;
- subcircuit hierarchy;
- initial transistor dimensions where present.

The topology parser uses this file to determine the actual circuit connectivity.

---

## `specs.yaml`

Defines circuit-level design requirements.

These specifications are primarily used downstream for performance validation and optimization rather than for determining circuit connectivity.

Examples include requirements such as:

```text
gain
bandwidth
phase margin
power
output range
```

---

## `design_rules.yaml`

Defines electrical and physical rules used during synthesis.

These rules constrain allowable device operation and circuit assignments.

Examples include:

```text
device operating constraints
saturation requirements
allowed voltage/current ranges
width ranges
symmetry or matching requirements
```

---

## `design_intent.yaml`

Defines how OpenAMS should interpret and synthesize the circuit.

This is one of the most important metadata files in the pipeline.

It contains declarations for such things as:

```text
independent design variables
dependent quantities
assignment groups
circuit relationships
current relationships
topology partitioning
component interfaces
component MLP checkpoints
component MLP features
exact realization methods
final witness fields
```

The current hierarchical two-stage declaration contains two components:

```text
input_bias_network
output_stage
```

and defines the dependency:

```text
input_bias_network
        │
        ▼
output_stage
```

The interface connecting them is:

```text
first_second_stage_cut
```

with shared coordinates including:

```text
vy_v
vbias_v
```

and a propagated quantity:

```text
stage_ratio
```

The current hierarchical intent also identifies the MLP checkpoints and exact-realizer functions for each component.

---

## `simulation.yaml`

Defines the electrical simulation environment.

Typical information includes:

```text
supply voltage
input bias conditions
temperature
technology corner
analysis configuration
simulation tolerances
```

---

## `two_stage_mlp_witness_plan.yaml`

Controls the device-level MLP witness realizer.

This file is used when the circuit or its components must be realized using the transistor technology MLP.

It provides the base configuration used by the component teacher during dataset generation and by the exact realizer during hierarchical Step 5.

---

# 5. STEP 01 — Topology Extraction

## Purpose

The first executable stage parses the SPICE circuit and constructs OpenAMS's normalized topology representation.

This stage answers:

```text
What devices exist?
What type is each device?
Which nodes connect them?
What is the selected subcircuit?
```

No circuit-design search is performed at this point.

## Command

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python tools/validation/validate_gate_02_topology.py \
  --netlist examples/two_stage_opamp/inputs/netlist.spice \
  --subcircuit two_stage_opamp \
  --output-dir docs/validation/evidence/gate_02_topology
```

This is the command used by the existing frontend production driver.

## Output

The primary artifacts are:

```text
docs/validation/evidence/gate_02_topology/
├── topology.json
└── topology_summary.json
```

The production driver copies these into:

```text
examples/two_stage_opamp/generated/
├── topology.json
└── topology_summary.json
```

To reproduce that handoff manually:

```bash
cp docs/validation/evidence/gate_02_topology/topology.json \
   examples/two_stage_opamp/generated/topology.json

cp docs/validation/evidence/gate_02_topology/topology_summary.json \
   examples/two_stage_opamp/generated/topology_summary.json
```

## Check

Confirm that both files exist:

```bash
ls -lh \
  examples/two_stage_opamp/generated/topology.json \
  examples/two_stage_opamp/generated/topology_summary.json
```

The topology validation script is part of the current repository tool set.

---

# 6. STEP 02 — Metadata Normalization

## Purpose

The topology tells OpenAMS what the circuit **is**.

The metadata tells OpenAMS how the circuit is intended to be **designed and searched**.

Step 02 reads the project YAML files and converts them into the normalized internal OpenAMS metadata representation.

The principal inputs are:

```text
specs.yaml
design_rules.yaml
design_intent.yaml
simulation.yaml
```

## Command

```bash
python tools/validation/validate_gate_03_metadata.py \
  --input-dir examples/two_stage_opamp/inputs \
  --output-dir docs/validation/evidence/gate_03_metadata
```

This is also the exact metadata-validation command used in the existing frontend pipeline.

## Output

The immediate validation output includes:

```text
docs/validation/evidence/gate_03_metadata/
└── metadata_summary.json
```

Copy the summary into the generated circuit directory:

```bash
cp docs/validation/evidence/gate_03_metadata/metadata_summary.json \
   examples/two_stage_opamp/generated/metadata_summary.json
```

The full production frontend additionally serializes the normalized project input object as:

```text
examples/two_stage_opamp/generated/project_inputs.normalized.json
```

That object combines the normalized forms of:

```text
specifications
design_intent
design_rules
simulation
```

The existing `run_frontend_steps_0_to_5.sh` script contains the serialization procedure and builds this artifact automatically.

---

# 7. STEP 03 — Constraint Classification

## Purpose

At this stage OpenAMS examines the design-intent and design-rule declarations and determines what role each declaration plays.

Conceptually, the declarations are separated into things such as:

```text
synthesis parameters
dependent quantities
dependency groups
electrical constraints
topology relationships
```

This stage is important because it separates the quantities OpenAMS is allowed to search independently from quantities that must later be derived.

## Command

```bash
python tools/validation/validate_gate_04_constraint_classification.py \
  --design-intent examples/two_stage_opamp/inputs/design_intent.yaml \
  --design-rules examples/two_stage_opamp/inputs/design_rules.yaml \
  --output-dir docs/validation/evidence/gate_04_constraints
```

## Output

```text
docs/validation/evidence/gate_04_constraints/
├── constraint_classification.json
└── compiler_constraints.json
```

Copy the canonical artifacts:

```bash
cp docs/validation/evidence/gate_04_constraints/constraint_classification.json \
   examples/two_stage_opamp/generated/constraint_classification.json

cp docs/validation/evidence/gate_04_constraints/compiler_constraints.json \
   examples/two_stage_opamp/generated/compiler_constraints.json
```

These commands correspond directly to the current frontend driver.

---

# 8. STEP 04 — Constraint Compilation

## Purpose

Constraint classification identifies what each declaration means.

Constraint compilation turns those declarations into forms that the synthesis engine can execute.

For example, relationships involving circuit currents or dependent quantities are converted from metadata declarations into executable constraints.

## Command

```bash
python tools/validation/validate_gate_04b_constraint_compiler.py \
  --constraints examples/two_stage_opamp/generated/compiler_constraints.json \
  --output-dir docs/validation/evidence/gate_04b_constraint_compiler
```

## Output

```text
docs/validation/evidence/gate_04b_constraint_compiler/
├── compiled_constraints.json
├── compiler_diagnostics.json
└── execution_results.json
```

Copy the production artifacts:

```bash
cp docs/validation/evidence/gate_04b_constraint_compiler/compiled_constraints.json \
   examples/two_stage_opamp/generated/compiled_constraints.json

cp docs/validation/evidence/gate_04b_constraint_compiler/compiler_diagnostics.json \
   examples/two_stage_opamp/generated/compiler_diagnostics.json
```

The `execution_results.json` produced here is validation evidence. It is **not** yet a set of synthesized circuit witnesses. The production frontend explicitly distinguishes this validation artifact from real synthesis results.

---

# 9. STEP 05 — Technology Model Validation

## Purpose

Before searching for transistor realizations, OpenAMS verifies that the configured technology model is available and valid.

The technology model supplies the device-level electrical information later required by the witness engine.

## Command

```bash
python tools/validation/validate_gate_05_technology.py \
  --input-dir examples/two_stage_opamp/inputs \
  --output-dir docs/validation/evidence/gate_05_technology
```

## Output

```text
docs/validation/evidence/gate_05_technology/
└── technology_summary.json
```

Copy it into the generated circuit directory:

```bash
cp docs/validation/evidence/gate_05_technology/technology_summary.json \
   examples/two_stage_opamp/generated/technology_summary.json
```

The production frontend performs this technology validation before constructing the canonical compiled circuit model.

---

# 10. Running Steps 01–05 Together

The existing frontend driver can execute all of the preceding stages in one command:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate

bash scripts/run_frontend_steps_0_to_5.sh
```

The script checks the required input files, runs topology extraction, metadata normalization, constraint classification, constraint compilation, technology validation, supporting tests, and constructs the frontend handoff artifact.

The principal output is:

```text
examples/two_stage_opamp/generated/
    compiled_circuit_model.json
```

Its declared status is:

```text
READY_FOR_ASSIGNMENT_SYNTHESIS
```

This is the handoff between the OpenAMS frontend and witness-generation stages.

At this point:

```text
The topology is known.
The metadata is normalized.
The design constraints are compiled.
The technology source is available.
```

But:

```text
No complete correlated circuit witnesses have been generated yet.
```

The next stage constructs the actual independent circuit design space.
# OpenAMS Witness Generation Pipeline — SPICE Validation and Final Witness Set

# 53. STEP 14 — Validate Synthesized Witnesses with ngspice

## Purpose

The hierarchical Step-5 engine produces:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    hierarchical_witnesses.csv
```

These witnesses are internally consistent according to the OpenAMS device/component models and the exact realization procedure.

The final pre-layout validation stage is to verify them independently using ngspice.

The purpose is:

```text
OpenAMS witness
      │
      ▼
parameterize SPICE circuit
      │
      ▼
run ngspice
      │
      ▼
verify actual circuit operating point
      │
      ▼
PASS / FAIL
```

The repository contains the following validation path:

```text
src/openams/validation/ngspice_witness.py

tools/validation/run_ngspice_witness_parallel.py
tools/validation/select_spice_candidates.py
tools/validation/build_spice_training_dataset.py

scripts/validate_witnesses.sh
```

These files are present in the current pipeline inventory.

---

# 54. Important Validation Principle

The component MLP and device MLP are used to efficiently locate likely feasible circuit operating points.

ngspice is an independent circuit simulator.

Therefore:

```text
MLP feasibility
      ≠
SPICE validation
```

The intended sequence is:

```text
component MLP
      ↓
exact device-MLP realization
      ↓
complete correlated witness
      ↓
ngspice
      ↓
validated witness
```

A witness should only be promoted into the final valid circuit pool after the SPICE validation policy accepts it.

---

# 55. Witness-to-SPICE Mapping

Each hierarchical witness contains the quantities needed to instantiate one concrete version of the parameterized circuit.

For the two-stage amplifier, this includes transistor dimensions such as:

```text
w_m1_um
w_m2_um
w_m3_um
w_m4_um
w_m5_um
w_m6_um
w_m7_um
```

and operating-point/interface quantities such as:

```text
vbias_v
vout_v
vy_v
```

where applicable.

Conceptually:

```text
hierarchical witness row

W1 = ...
W2 = ...
W3 = ...
W4 = ...
W5 = ...
W6 = ...
W7 = ...

VBIAS = ...
VOUT  = ...
...

       │
       ▼

parameterized SPICE deck

       │
       ▼

ngspice
```

The important requirement is that all values come from the **same witness row**.

Do not independently combine dimensions from different witnesses.

---

# 56. Parameterized SPICE Netlist

The circuit input netlist should remain the topology source.

A generated validation deck applies the particular witness parameters to that topology.

Conceptually:

```text
netlist.spice
      +
witness row
      +
simulation.yaml / validation deck
      │
      ▼
generated witness simulation deck
```

The repository also contains:

```text
examples/two_stage_opamp/inputs/deck_template.spice
```

in the current project structure used by the frontend and simulation flow.

The generated simulation deck should be treated as a temporary artifact. The original input SPICE topology should not be modified for every witness.

---

# 57. Parallel SPICE Validation

The current repository contains:

```text
tools/validation/run_ngspice_witness_parallel.py
```

for evaluating multiple witnesses in parallel.

The intended workload is:

```text
hierarchical_witnesses.csv
          │
          ▼
    divide witnesses
     across workers
          │
    ┌─────┼─────┐
    ▼     ▼     ▼
 ngspice ngspice ngspice
    │     │     │
    └─────┼─────┘
          ▼
   validation results
```

This is preferable to serially launching one ngspice process after another when validating a large witness pool.

---

# 58. Production Validation Wrapper

The current repository also provides:

```text
scripts/validate_witnesses.sh
```

which is the user-facing script intended to drive the validation stage.

The production-style invocation should therefore be documented at the wrapper level as:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

bash scripts/validate_witnesses.sh
```

## Important

The attached script inventory establishes that this wrapper exists, but the attachment does **not include the body of `validate_witnesses.sh` or the CLI definition of `run_ngspice_witness_parallel.py`**.

Therefore the exact internal flags, output filenames, and current PASS thresholds should be copied from those scripts before they are frozen into this guide.

They should not be guessed.

This is one place where the cleanup work should make the production interface explicit and stable.

---

# 59. Required Acceptance Conditions

At a minimum, a SPICE-validated witness should satisfy:

```text
1. The generated SPICE deck is valid.

2. ngspice executes successfully.

3. The required operating-point analysis converges.

4. The result contains the required circuit quantities.

5. The simulated operating point passes the validation rules
   defined for the witness flow.
```

The exact electrical PASS rules must come from:

```text
src/openams/validation/ngspice_witness.py
```

and/or the validation wrapper rather than being redefined independently in the documentation.

The current inventory confirms that `ngspice_witness.py` is the OpenAMS validation implementation.

---

# 60. Reject Simulator Failures

A circuit should not be considered a valid witness merely because ngspice produced a log file.

Simulation failures include conditions such as:

```text
failed operating-point convergence
invalid model/subcircuit
singular circuit behavior
missing output values
other validation failures
```

The exact list recognized by the current pre-layout validation implementation must be documented directly from `ngspice_witness.py`.

This distinction should remain explicit:

```text
ngspice ran
    ≠
witness passed
```

Instead:

```text
ngspice ran
    +
analysis converged
    +
validation rules passed
    =
valid circuit witness
```

---

# 61. Preserve the Original Witness ID

Every SPICE result should retain a stable connection to its originating OpenAMS witness.

For example:

```text
point_index
witness_rank
```

or a canonical witness identifier derived from them.

The validation data should therefore allow:

```text
OpenAMS witness
      │
      ▼
SPICE run directory
      │
      ▼
SPICE result
      │
      ▼
PASS/FAIL
```

to be traced without ambiguity.

This traceability becomes important when the valid witness pool is later used to generate circuit-performance datasets.

---

# 62. Validation Output

The validation stage should conceptually produce two categories:

```text
all SPICE validation results
        │
        ├───────────────┐
        ▼               ▼
       PASS            FAIL
        │               │
        ▼               ▼
 valid witnesses     diagnostics
```

The final production artifacts should make this distinction explicit.

Recommended canonical names are:

```text
ngspice_witness_results.csv
valid_circuit_witnesses.csv
```

However, these filenames should only be adopted during cleanup if they match or replace the filenames currently written by the scripts.

The attached file listing does not expose those current output names.

---

# 63. Candidate Selection

The repository also contains:

```text
tools/validation/select_spice_candidates.py
```

which indicates that the current validation flow can select a subset of synthesized witnesses for SPICE evaluation.

This stage is useful when:

```text
the Step-5 witness pool is very large
```

and we initially want to simulate a representative or prioritized subset.

The logical flow becomes:

```text
hierarchical_witnesses.csv
          │
          ▼
 select_spice_candidates.py
          │
          ▼
selected witness subset
          │
          ▼
run_ngspice_witness_parallel.py
```

For the final characterization dataset, however, candidate-selection policy needs to be documented separately from witness validity.

Selection means:

```text
which witnesses do we simulate?
```

Validation means:

```text
which simulated witnesses pass?
```

Those are different operations.

---

# 64. Building the SPICE Training Dataset

The repository contains:

```text
tools/validation/build_spice_training_dataset.py
```

after the candidate-selection and ngspice-validation utilities.

This belongs downstream from witness validation.

Conceptually:

```text
valid circuit witnesses
        +
SPICE measurements
        │
        ▼
build_spice_training_dataset.py
        │
        ▼
circuit-level performance dataset
```

This dataset can later be used to train the circuit-level model for performance prediction and optimization.

It is therefore **not required to discover valid witnesses**.

The witness-generation pipeline ends logically at:

```text
valid circuit witnesses
```

while circuit-level MLP generation begins after that point.

---

# 65. Final Witness Pipeline

The complete pre-layout OpenAMS workflow documented in this guide is therefore:

```text
                    INPUT
                      │
                      ▼
                netlist.spice
                      │
                      ▼
             topology extraction
                      │
                      ▼
            metadata normalization
                      │
                      ▼
           constraint compilation
                      │
                      ▼
       independent design-space generation
                      │
                      ▼
             topology partition
                      │
          ┌───────────┴───────────┐
          ▼                       ▼
     Component A              Component B
     teacher data             teacher data
          │                       │
          ▼                       ▼
       A MLP                    B MLP
          │                       │
          └───────────┬───────────┘
                      │
                      ▼
        hierarchical component contract
                      │
                      ▼
       generic hierarchical Step-5 engine
                      │
                      ▼
          component MLP filtering
                      │
                      ▼
           exact device realization
                      │
                      ▼
             component joining
                      │
                      ▼
           hierarchical_witnesses.csv
                      │
                      ▼
             ngspice validation
                      │
             ┌────────┴────────┐
             ▼                 ▼
            PASS              FAIL
             │
             ▼
        VALID CIRCUIT
         WITNESS SET
```

---

# 66. Pipeline Boundary

For the purpose of this document, the main OpenAMS witness-generation pipeline ends here:

```text
SPICE netlist
      ↓
...
      ↓
hierarchical search
      ↓
exact correlated witnesses
      ↓
ngspice validation
      ↓
VALID CIRCUIT WITNESSES
```

The following tasks are downstream and should be documented separately:

```text
SPICE AC/performance characterization

circuit-level training-dataset generation

circuit-level MLP training

FA-BO optimization

physical quantization

layout generation

PEX

post-layout verification

post-layout optimization
```

This keeps the witness-generation documentation focused on one clear objective:

> Given a circuit topology and its design metadata, find a broad set of correlated transistor-level realizations that correspond to valid circuit operating points.

---

# 67. Production Scripts Used by This Pipeline

The executable pipeline should eventually expose only a small number of user-facing commands.

The current repository contains:

```text
scripts/run_frontend_steps_0_to_5.sh
scripts/run_assignment_step_03.sh
scripts/run_assignment_step_04.sh
scripts/run_assignment_step_05.sh
scripts/generate_witnesses.sh
scripts/validate_witnesses.sh
scripts/run_openams_production_pipeline.sh
```

along with the lower-level tools that implement each operation.

The intended organization should become:

```text
run_openams_production_pipeline.sh
    │
    ├── frontend
    │
    ├── independent domains
    │
    ├── hierarchical preparation
    │
    ├── witness generation
    │
    └── witness validation
```

while individual stage scripts remain available for debugging and development.

---

# 68. One-Command Production Goal

After cleanup, the desired user interface should ultimately be:

```bash
bash scripts/run_openams_production_pipeline.sh \
  examples/two_stage_opamp
```

or an equivalent stable command.

Internally it should execute the same individually documented stages.

The individual commands remain important because they allow a developer to stop after any stage, inspect its output, change metadata, and resume.

Thus OpenAMS should support both:

```text
ONE-COMMAND PRODUCTION FLOW
```

and:

```text
STEP-BY-STEP DEVELOPMENT FLOW
```

without implementing two different algorithms.

---

# 69. Artifact Summary

At the end of the complete flow, the important artifacts are conceptually:

```text
INPUT
-----
examples/two_stage_opamp/inputs/
    netlist.spice
    specs.yaml
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    two_stage_mlp_witness_plan.yaml


FRONTEND
--------
examples/two_stage_opamp/generated/
    topology.json
    metadata_summary.json
    compiled_constraints.json
    compiled_circuit_model.json


ASSIGNMENT SYNTHESIS
--------------------
examples/two_stage_opamp/generated/assignment_synthesis/
    independent_regions.json
    dependent_regions.json
    hierarchical_component_contract.json
    hierarchical_witnesses.csv


COMPONENT MODELS
----------------
technology/component_models/
    two_stage_input_bias_network_v3.pt
    two_stage_output_stage_v3.pt


COMPONENT TRAINING DATA
-----------------------
runtime/two_stage_component_training_v2/datasets/
    A_dataset.csv
    B_dataset.csv


FINAL VALIDATION
----------------
SPICE validation results
    ↓
valid circuit witness pool
```

The exact final SPICE filenames should be filled in only after inspecting the bodies of `validate_witnesses.sh` and `run_ngspice_witness_parallel.py`; the attached source list confirms their presence but does not provide their CLI/output contract.
# OpenAMS Hierarchical Witness Pipeline — Exact Execution Commands

## 1. Purpose

This document is the short execution reference for the current OpenAMS hierarchical witness-generation pipeline.

The reference example is:

```text
examples/two_stage_opamp
```

The pipeline starts from:

```text
netlist.spice
```

and ends at:

```text
hierarchical_witnesses.csv
```

followed by independent ngspice validation.

The full flow is:

```text
SPICE netlist
    ↓
frontend compilation
    ↓
independent design space
    ↓
topology partition metadata
    ↓
component training datasets
    ↓
component MLPs
    ↓
component hierarchy validation
    ↓
hierarchical component contract
    ↓
hierarchical Step-5 witness search
    ↓
hierarchical_witnesses.csv
    ↓
ngspice validation
    ↓
valid circuit witnesses
```

---

# 2. Repository Setup

Run from the repository root:

```bash
cd ~/AMS-Tutorial/openams

source .venv-openams/bin/activate

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
```

All following commands assume:

```text
~/AMS-Tutorial/openams
```

is the current directory.

---

# 3. Input Metadata

The two-stage circuit uses:

```text
examples/two_stage_opamp/inputs/
├── netlist.spice
├── specs.yaml
├── design_rules.yaml
├── design_intent.yaml
├── simulation.yaml
├── deck_template.spice
├── two_stage_mlp_witness_plan.yaml
└── ngspice_validation.yaml
```

Briefly:

| File | Function |
|---|---|
| `netlist.spice` | Circuit devices, nodes and connectivity |
| `specs.yaml` | Circuit performance requirements |
| `design_rules.yaml` | Electrical/design constraints |
| `design_intent.yaml` | Independent variables, dependencies, component partition and interfaces |
| `simulation.yaml` | General simulation configuration |
| `deck_template.spice` | SPICE test/deck template |
| `two_stage_mlp_witness_plan.yaml` | Device-MLP exact realization configuration |
| `ngspice_validation.yaml` | Independent ngspice validation configuration |

---

# PART I — FRONTEND

# 4. Run Frontend Steps 0–5

This validates:

```text
inputs
topology
metadata
constraint classification
constraint compilation
technology model
```

and creates the compiled circuit model.

Run:

```bash
bash scripts/run_frontend_steps_0_to_5.sh
```

The script explicitly validates all required metadata, parses `two_stage_opamp`, compiles the constraints, validates the technology source, and creates the canonical frontend model.

Main output:

```text
examples/two_stage_opamp/generated/
    compiled_circuit_model.json
```

Expected state:

```text
READY_FOR_ASSIGNMENT_SYNTHESIS
```

---

# 5. Generate Independent Design Regions

Run:

```bash
bash scripts/run_assignment_step_03.sh
```

Equivalent underlying operation:

```bash
python tools/validation/validate_assignment_step_03_independent_domains.py \
  --compiled-model \
  examples/two_stage_opamp/generated/compiled_circuit_model.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json \
  --report \
  examples/two_stage_opamp/generated/assignment_synthesis/STEP3_INDEPENDENT_REGIONS_REPORT.md
```

Output:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    independent_regions.json
```

This contains the circuit-level independent design space.

---

# 6. Generate Dependent Regions

Run:

```bash
bash scripts/run_assignment_step_04.sh
```

Equivalent operation:

```bash
python tools/validation/validate_assignment_step_04_dependent_regions.py \
  --compiled-model \
  examples/two_stage_opamp/generated/compiled_circuit_model.json \
  --independent-regions \
  examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/dependent_regions.json \
  --report \
  examples/two_stage_opamp/generated/assignment_synthesis/STEP4_DEPENDENT_REGIONS_REPORT.md
```

Output:

```text
dependent_regions.json
```

---

# 7. Do Not Use the Old Assignment Step 5 as the Final Hierarchical Search

The repository still contains:

```bash
bash scripts/run_assignment_step_05.sh
```

which creates:

```text
complete_assignments.json
complete_assignments.csv
```

This is the older generic assignment Step 5.

For the current component-MLP hierarchical flow, the final witness generation is instead performed later by:

```text
hierarchical_witness_engine.py
```

The old Step-5 script can remain as a regression/reference flow, but should not be confused with the current hierarchical witness search.

---

# PART II — HIERARCHICAL MODEL PREPARATION

These steps only need to be repeated when the component models need to be rebuilt.

Typical reasons include:

```text
topology changed
component partition changed
interface variables/ranges changed
device technology MLP changed
component-model architecture changed
training dataset policy changed
```

If validated component checkpoints already exist and remain current, continue directly to **Part III**.

---

# 8. Define / Update the Topology Partition

For the current two-stage amplifier:

```text
Component A:
    input_bias_network

Component B:
    output_stage
```

with:

```text
input_bias_network
        ↓
output_stage
```

The partition is stored under:

```text
hierarchical_feasibility:
```

inside:

```text
examples/two_stage_opamp/inputs/design_intent.yaml
```

If creating the current two-stage hierarchical metadata from the helper script:

```bash
python tools/update_two_stage_hierarchical_intent_v2.py \
  --intent examples/two_stage_opamp/inputs/design_intent.yaml
```

This should normally be a **one-time metadata construction/update operation**.

Do not rerun it automatically on every production execution if `design_intent.yaml` has already been finalized.

Inspect the resulting section:

```bash
grep -n -A180 "hierarchical_feasibility:" \
  examples/two_stage_opamp/inputs/design_intent.yaml
```

---

# 9. Generate Basic-Component Training Data

Remove the previous temporary training directory if rebuilding:

```bash
rm -rf runtime/two_stage_component_training_v2
```

Generate Component-A and Component-B teacher datasets:

```bash
python tools/validation/generate_two_stage_component_datasets_v2.py \
  --root . \
  --work-dir runtime/two_stage_component_training_v2
```

Expected outputs:

```text
runtime/two_stage_component_training_v2/datasets/
├── A_dataset.csv
└── B_dataset.csv
```

Inspect:

```bash
ls -lh \
  runtime/two_stage_component_training_v2/datasets/A_dataset.csv \
  runtime/two_stage_component_training_v2/datasets/B_dataset.csv
```

Check class balance:

```bash
python - <<'PY'
import pandas as pd

for name in ["A", "B"]:
    p = f"runtime/two_stage_component_training_v2/datasets/{name}_dataset.csv"
    d = pd.read_csv(p)

    print(f"\n{name}")
    print("rows    :", len(d))
    print("valid   :", int(d["valid"].sum()))
    print("invalid :", int((d["valid"] == 0).sum()))
PY
```

The device-level MLP witness engine acts as the teacher for these datasets.

---

# 10. Train the Component MLPs

Create the model directory:

```bash
mkdir -p technology/component_models
```

Train both component models:

```bash
python tools/technology/train_two_stage_component_mlps_v3.py \
  --a-dataset \
  runtime/two_stage_component_training_v2/datasets/A_dataset.csv \
  --b-dataset \
  runtime/two_stage_component_training_v2/datasets/B_dataset.csv \
  --a-output \
  technology/component_models/two_stage_input_bias_network_v3.pt \
  --b-output \
  technology/component_models/two_stage_output_stage_v3.pt
```

Expected checkpoints:

```text
technology/component_models/
├── two_stage_input_bias_network_v3.pt
└── two_stage_output_stage_v3.pt
```

Check:

```bash
ls -lh \
  technology/component_models/two_stage_input_bias_network_v3.pt \
  technology/component_models/two_stage_output_stage_v3.pt
```

---

# 11. Validate the Component-MLP Hierarchy

Run:

```bash
python tools/validation/validate_two_stage_component_mlp_hierarchy.py
```

This compares the component-MLP hierarchy with the device-level teacher.

Important quantities to inspect include:

```text
Component-A recall
Component-A precision
final joined recall
final joined precision
MLP-only runtime
```

The important property is that the component MLP does not remove an unacceptable fraction of valid teacher states.

If validation fails, correct:

```text
dataset coverage
training
component interface ranges
classification threshold
partition definition
```

rather than introducing topology-specific fixes into the generic hierarchical engine.

---

# PART III — NORMAL HIERARCHICAL WITNESS RUN

Once the component checkpoints have been trained and validated, the following is the normal execution path.

---

# 12. Compile the Hierarchical Component Contract

Run:

```bash
python tools/compile_hierarchical_component_contract.py \
  --intent \
  examples/two_stage_opamp/inputs/design_intent.yaml \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json
```

Output:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    hierarchical_component_contract.json
```

Inspect:

```bash
python -m json.tool \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  | less
```

The contract contains the executable description of:

```text
independent variables
component order
component MLP checkpoints
component MLP features
component interfaces
interface grids
propagated variables
exact realization methods
final witness fields
```

It is generated metadata and should not normally be edited manually.

---

# 13. Hierarchical Step-5 Smoke Test

Always test a small independent-point subset first.

```bash
rm -rf runtime/generic_step5_two_stage_smoke
```

Run:

```bash
/usr/bin/time -f '\nREAL=%e sec\nMAX_RSS=%M KB' \
python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/generic_step5_smoke.csv \
  --work-dir \
  runtime/generic_step5_two_stage_smoke \
  --max-points 25 \
  --workers 12
```

Check that the run reports:

```text
components
component order
independent points
component MLP evaluations
MLP-positive cells
exact component witnesses
exact joined tuples
points with >=1 witness
coverage
final exact witnesses
```

Output:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    generic_step5_smoke.csv
```

Inspect:

```bash
head -5 \
  examples/two_stage_opamp/generated/assignment_synthesis/generic_step5_smoke.csv
```

---

# 14. Full Hierarchical Witness Generation

After the smoke test passes, remove `--max-points`.

Clean the runtime directory:

```bash
rm -rf runtime/generic_step5_two_stage_full
```

Run:

```bash
/usr/bin/time -f '\nREAL=%e sec\nMAX_RSS=%M KB' \
python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv \
  --work-dir \
  runtime/generic_step5_two_stage_full \
  --workers 12
```

Canonical hierarchical output:

```text
examples/two_stage_opamp/generated/assignment_synthesis/
    hierarchical_witnesses.csv
```

This is the OpenAMS model-based correlated circuit witness pool.

---

# 15. Inspect the Witness Pool

Basic checks:

```bash
ls -lh \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv
```

```bash
head -5 \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv
```

```bash
wc -l \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv
```

A witness should contain one complete correlated realization rather than independently combined device values.

---

# PART IV — DEVICE-LEVEL GENERIC WITNESS ENGINE

The repository also retains the generic device-level witness-engine wrapper.

It is used by the teacher/exact-realization side of the pipeline and can also be run directly.

---

# 16. Serial Device-Level Witness Engine

Wrapper:

```bash
scripts/generate_witnesses.sh \
  examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml
```

Equivalent:

```bash
python -m openams.synthesis.witness_engine \
  --root "$PWD" \
  --plan examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml
```

`generate_witnesses.sh` simply accepts the plan as the first positional argument and forwards the remaining arguments to the synthesis witness engine.

---

# 17. Parallel Device-Level Witness Engine

Example:

```bash
python tools/validation/run_witness_engine_parallel.py \
  --plan examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml \
  --workers 12 \
  --witnesses-per-point 5 \
  --output-csv \
  examples/two_stage_opamp/generated/assignment_synthesis/two_stage_all_mlp_witnesses.csv \
  --overwrite
```

The parallel wrapper:

```text
loads the original witness plan
        ↓
reads its coverage CSV
        ↓
splits points across workers
        ↓
creates one temporary plan per worker
        ↓
runs witness_engine.py independently
        ↓
merges by point_index / witness_rank
```

The wrapper does not contain topology-specific circuit behavior. Only the per-worker `coverage_csv` and `output_csv` are changed.

---

# PART V — NGSPICE VALIDATION

# 18. Update the ngspice Validation Input

Before using the latest hierarchical pipeline, ensure:

```text
examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

contains:

```yaml
input_csv: examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv
```

rather than an older witness CSV.

Expected output:

```yaml
output_csv: examples/two_stage_opamp/generated/ngspice_validation.csv
```

---

# 19. Small ngspice Smoke Test

Run:

```bash
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml \
  --top-n 10
```

The wrapper requires the validation YAML as its first argument and passes additional arguments directly to:

```text
openams.validation.ngspice_witness
```

---

# 20. Normal ngspice Validation

If the plan contains:

```yaml
top_n: 100
```

run:

```bash
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

Equivalent:

```bash
python -m openams.validation.ngspice_witness \
  --root "$PWD" \
  --plan examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

Expected result:

```text
examples/two_stage_opamp/generated/
    ngspice_validation.csv
```

---

# 21. Test Without Overwriting the Production Result

```bash
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml \
  --top-n 10 \
  --output-csv /tmp/two_stage_ngspice_smoke.csv
```

---

# 22. Inspect ngspice Results

```bash
head -5 \
  examples/two_stage_opamp/generated/ngspice_validation.csv
```

Summary:

```bash
python - <<'PY'
import pandas as pd

p = "examples/two_stage_opamp/generated/ngspice_validation.csv"
d = pd.read_csv(p)

print("rows:", len(d))

print("\nvalidation_status")
print(d["validation_status"].value_counts(dropna=False))

print("\ndc_validation_status")
print(d["dc_validation_status"].value_counts(dropna=False))

print("\nmax DC difference:")
print(d["max_abs_voltage_delta_v"].max())

print("\nmedian DC difference:")
print(d["max_abs_voltage_delta_v"].median())
PY
```

---

# 23. Final Valid Witness Pool

The desired final artifact is:

```text
valid_circuit_witnesses.csv
```

It should contain the complete rows from:

```text
hierarchical_witnesses.csv
```

for witnesses accepted by:

```text
ngspice_validation.csv
```

using:

```text
point_index
witness_rank
```

as the join keys.

At present, the supplied pipeline scripts do not establish one canonical wrapper for this final join.

Therefore this should be treated as a remaining cleanup item rather than silently inventing a production command.

---

# 24. Normal Execution — Short Version

If:

```text
component datasets already exist
component MLPs are already trained
component MLPs have already been validated
design_intent.yaml already contains the partition
```

the normal current execution becomes only:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# 1. Frontend
bash scripts/run_frontend_steps_0_to_5.sh

# 2. Independent domains
bash scripts/run_assignment_step_03.sh

# 3. Dependent-region metadata
bash scripts/run_assignment_step_04.sh

# 4. Compile hierarchical contract
python tools/compile_hierarchical_component_contract.py \
  --intent examples/two_stage_opamp/inputs/design_intent.yaml \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json

# 5. Hierarchical witness generation
rm -rf runtime/generic_step5_two_stage_full

/usr/bin/time -f '\nREAL=%e sec\nMAX_RSS=%M KB' \
python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv \
  --work-dir runtime/generic_step5_two_stage_full \
  --workers 12

# 6. ngspice validation
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

This is the most important command sequence in this document.

---

# 25. Full Rebuild — Short Version

When rebuilding the component models as well:

```bash
cd ~/AMS-Tutorial/openams
source .venv-openams/bin/activate
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

# Frontend
bash scripts/run_frontend_steps_0_to_5.sh
bash scripts/run_assignment_step_03.sh
bash scripts/run_assignment_step_04.sh

# Build component teacher datasets
rm -rf runtime/two_stage_component_training_v2

python tools/validation/generate_two_stage_component_datasets_v2.py \
  --root . \
  --work-dir runtime/two_stage_component_training_v2

# Train basic-component MLPs
mkdir -p technology/component_models

python tools/technology/train_two_stage_component_mlps_v3.py \
  --a-dataset runtime/two_stage_component_training_v2/datasets/A_dataset.csv \
  --b-dataset runtime/two_stage_component_training_v2/datasets/B_dataset.csv \
  --a-output technology/component_models/two_stage_input_bias_network_v3.pt \
  --b-output technology/component_models/two_stage_output_stage_v3.pt

# Validate component hierarchy
python tools/validation/validate_two_stage_component_mlp_hierarchy.py

# Compile executable hierarchical contract
python tools/compile_hierarchical_component_contract.py \
  --intent examples/two_stage_opamp/inputs/design_intent.yaml \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json

# Generate complete correlated witnesses
rm -rf runtime/generic_step5_two_stage_full

/usr/bin/time -f '\nREAL=%e sec\nMAX_RSS=%M KB' \
python tools/validation/hierarchical_witness_engine.py \
  --contract \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_component_contract.json \
  --output \
  examples/two_stage_opamp/generated/assignment_synthesis/hierarchical_witnesses.csv \
  --work-dir runtime/generic_step5_two_stage_full \
  --workers 12

# Independently validate with ngspice
scripts/validate_witnesses.sh \
  examples/two_stage_opamp/inputs/ngspice_validation.yaml
```

---

# 26. Canonical Pipeline Outputs

The major handoff artifacts are:

```text
examples/two_stage_opamp/generated/
│
├── compiled_circuit_model.json
│
├── assignment_synthesis/
│   ├── independent_regions.json
│   ├── dependent_regions.json
│   ├── hierarchical_component_contract.json
│   └── hierarchical_witnesses.csv
│
└── ngspice_validation.csv
```

Component models:

```text
technology/component_models/
├── two_stage_input_bias_network_v3.pt
└── two_stage_output_stage_v3.pt
```

Component-model training data:

```text
runtime/two_stage_component_training_v2/datasets/
├── A_dataset.csv
└── B_dataset.csv
```

The final desired artifact after cleanup is:

```text
valid_circuit_witnesses.csv
```

---

# 27. Remaining Cleanup Before Calling the Pipeline Fully Productionized

Three items remain:

1. Update `ngspice_validation.yaml` so that its canonical input is `hierarchical_witnesses.csv`.

2. Add a canonical script that joins ngspice PASS results with the complete hierarchical witness rows and creates:

```text
valid_circuit_witnesses.csv
```

3. Update:

```text
scripts/run_openams_production_pipeline.sh
```

because the current version still executes the older path:

```text
frontend
    ↓
independent_regions
    ↓
dependent_regions
    ↓
complete_assignments
```

and stops there.

The eventual production wrapper should instead execute:

```text
frontend
    ↓
independent regions
    ↓
hierarchical contract
    ↓
hierarchical witness engine
    ↓
ngspice validation
    ↓
valid circuit witness set
```

Component dataset generation and component-model training should normally remain separate preparation commands rather than being repeated on every production witness run.
# OpenAMS Steps 0–5 Validation Log

## Objective

Execute and validate the current OpenAMS repository from its two-stage-op-amp
inputs through constraint compilation, using the repository's gate validators
as the canonical execution path.

## Scope

- Step 0: repository and input baseline
- Step 1: input loading
- Step 2: topology extraction
- Step 3: metadata normalization and validation
- Step 4: constraint classification
- Step 5: constraint compilation

Technology intersection, assignment synthesis, simulation, and optimization are
outside this initial run.

## Validation rule

A step is considered verified only when it has:

1. An executed command.
2. A passing result.
3. An identifiable output or evidence artifact.
4. A recorded interpretation of what was proven.

---

## Step 0 — Repository baseline

```text
Date: 2026-07-31T20:08:19-04:00
Repository: /home/yhanafy/AMS-Tutorial/openams
Python: Python 3.12.3
Commit: 832f76aa7b5bcb9cb9ef52df58b255e0677d7e30

Git status:
 M src/openams/adapters/technology_csv.py
?? config/
?? docs/architecture/45_VALIDATED_OPTIMIZATION_LAUNCH.md
?? docs/validation/OPENAMS_STEP_0_TO_5_VALIDATION_LOG.md
?? docs/validation/evidence/gate_06b_physical_assignment/
?? docs/validation/evidence/gate_06b_physical_assignment_dense/
?? folded_cascode.tgz
?? koko.txt
?? scripts/
?? src/openams/cli/launch_validated_optimization.py
?? technology/sky130_tt_27c_mlp_dense.csv
?? tests/adapters/test_technology_csv_nonfinite.py
?? tests/cli/test_launch_validated_optimization.py
?? tests/cli/test_launch_validated_optimization_argv.py
?? tests/cli/test_launch_validated_optimization_real_preflight.py
?? tests/validation/test_gate_06b_physical_assignment.py
?? tools/validation/validate_gate_06b_physical_assignment.py
?? tools/validation/validate_two_stage_assignments.py

Two-stage-op-amp inputs:
deck_template.spice
design_intent.yaml
design_rules.yaml
design_rules.yaml.before_gate3_migration
design_rules.yaml.before_mlp_run
netlist.spice
simulation.yaml
specs.yaml
```

### Step 0 result

- Status: **PASS**
- Evidence: all five required two-stage-op-amp inputs exist.
- Repository commit: `832f76a`
- Important: the working tree contains uncommitted and untracked work;
  therefore all later evidence applies to this exact working-tree state,
  not merely to the recorded commit.

## Step 2 — Topology extraction

```text
Command:
python tools/validation/validate_gate_02_topology.py \
  --netlist examples/two_stage_opamp/inputs/netlist.spice \
  --subcircuit two_stage_opamp \
  --output-dir docs/validation/evidence/gate_02_topology

Exit status: 0
```

### Evidence artifacts


### Step 2 result

- Status: **PASS**
- Circuit: `two_stage_opamp`
- Ports: `inp, inn, out, vdd, vss, vbias`
- Devices: 8
- Nodes: 9
- Device kinds: `capacitor=1, mos=7`
- Missing devices: `None`
- Unexpected devices: `None`
- Failed checks: `None`
- What this proves: the named two-stage-op-amp subcircuit can be extracted from the official netlist and represented as the canonical OpenAMS circuit topology with verified ports, devices, and key connectivity.

### Supporting regression tests

```text
..................                                                       [100%]
18 passed in 0.05s
```

### Gate 02 evidence artifact list correction

- `docs/validation/evidence/gate_02_topology/raw/netlist.spice`
- `docs/validation/evidence/gate_02_topology/raw/selected_subcircuit.spice`
- `docs/validation/evidence/gate_02_topology/topology.json`
- `docs/validation/evidence/gate_02_topology/TOPOLOGY_REPORT.md`
- `docs/validation/evidence/gate_02_topology/topology_summary.json`


## Step 3 — Metadata normalization

- Exit status: 0
- Evidence directory: docs/validation/evidence/gate_03_metadata

### Artifacts
- `docs/validation/evidence/gate_03_metadata/METADATA_REPORT.md`
- `docs/validation/evidence/gate_03_metadata/metadata_summary.json`
- `docs/validation/evidence/gate_03_metadata/raw/design_intent.yaml`
- `docs/validation/evidence/gate_03_metadata/raw/design_rules.yaml`
- `docs/validation/evidence/gate_03_metadata/raw/simulation.yaml`
- `docs/validation/evidence/gate_03_metadata/raw/specs.yaml`


## Step 4 — Constraint classification

- Exit status: 2
- Evidence directory: `docs/validation/evidence/gate_04_constraint_classification`

### Artifacts


## Step 5 — Constraint compilation

- Input: `docs/validation/evidence/gate_04_constraints/compiler_constraints.json`
- Exit status: 0
- Evidence directory: `docs/validation/evidence/gate_04b_constraint_compiler`

### Artifacts
- `docs/validation/evidence/gate_04b_constraint_compiler/compiled_constraints.json`
- `docs/validation/evidence/gate_04b_constraint_compiler/compiler_diagnostics.json`
- `docs/validation/evidence/gate_04b_constraint_compiler/compiler_input.json`
- `docs/validation/evidence/gate_04b_constraint_compiler/COMPILER_REPORT.md`
- `docs/validation/evidence/gate_04b_constraint_compiler/execution_results.json`


## Gate 05 — Technology model and region validation

- Validator: `tools/validation/validate_gate_05_technology.py`
- Exit status: 0

### Evidence artifacts
- `docs/validation/evidence/gate_05_technology/TECHNOLOGY_REPORT.md`
- `docs/validation/evidence/gate_05_technology/technology_summary.json`

### Supporting tests

```text
...........................................................              [100%]
59 passed in 0.12s
```


## Production front-end rerun — Steps 0–5

- Status: **PASS**
- Generated directory: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated`
- Canonical handoff: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- Manifest: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`

### Production artifacts

- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_diagnostics.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_classification.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_compiler_validation_results.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/metadata_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/project_inputs.normalized.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/STEP5_REPORT.md`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/technology_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology_summary.json`


## Production front-end rerun — Steps 0–5

- Status: **PASS**
- Generated directory: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated`
- Canonical handoff: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- Manifest: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`

### Production artifacts

- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_diagnostics.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_classification.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_compiler_validation_results.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/metadata_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/project_inputs.normalized.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/STEP5_REPORT.md`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/technology_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology_summary.json`


## Production front-end rerun — Steps 0–5

- Status: **PASS**
- Generated directory: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated`
- Canonical handoff: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- Manifest: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`

### Production artifacts

- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_diagnostics.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_classification.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_compiler_validation_results.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/metadata_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/project_inputs.normalized.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/STEP5_REPORT.md`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/technology_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology_summary.json`


## Production front-end rerun — Steps 0–5

- Status: **PASS**
- Generated directory: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated`
- Canonical handoff: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- Manifest: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`

### Production artifacts

- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_diagnostics.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_classification.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_compiler_validation_results.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/metadata_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/project_inputs.normalized.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/STEP5_REPORT.md`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/technology_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology_summary.json`


## Production front-end rerun — Steps 0–5

- Status: **PASS**
- Generated directory: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated`
- Canonical handoff: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- Manifest: `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`

### Production artifacts

- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_circuit_model.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiled_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_constraints.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/compiler_diagnostics.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_classification.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/constraint_compiler_validation_results.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/frontend_pipeline_manifest.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/metadata_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/project_inputs.normalized.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/STEP5_REPORT.md`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/technology_summary.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology.json`
- `/home/yhanafy/AMS-Tutorial/openams/examples/two_stage_opamp/generated/topology_summary.json`


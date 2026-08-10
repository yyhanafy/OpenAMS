# OpenAMS Clean Correlated-Witness Pipeline

This directory is the cleaned target for the OpenAMS DC-witness pipeline.  It deliberately contains only the generic post-frontend mechanism plus the circuit declarations needed to exercise it.

## Boundary

The existing OpenAMS frontend remains responsible for:

```text
SPICE + design_rules.yaml + design_intent.yaml + simulation.yaml
                              |
                              v
                    compiled circuit/design
                              |
                              v
                   independent design space
```

The cleaned pipeline begins at that stable handoff and performs:

```text
independent design-space CSV
          +
correlated witness plan
          +
NMOS/PMOS MLP models
          |
          v
src/openams/synthesis/witness_engine.py
          |
          v
witnesses.csv
          |
          v
src/openams/validation/ngspice_witness.py
```

No topology-specific device sequence is hard-coded in Python.  Device stages, equations, sweeps, constraints, and output aliases live in the circuit witness-plan YAML.  ngspice-specific nodes and circuit instantiation live in the circuit validation YAML.

## Core code

```text
src/openams/synthesis/witness_engine.py
src/openams/technology/mlp_oracle.py
src/openams/validation/ngspice_witness.py
```

The MLP oracle uses the existing `openams.technology.ml_surrogate` model loader.

## Circuit declarations

Two-stage:

```text
examples/two_stage_opamp/inputs/
    netlist.spice
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    two_stage_mlp_witness_plan.yaml
    ngspice_validation.yaml
```

Folded cascode:

```text
examples/folded_cascode/inputs/
    folded_cascode.spice
    design_rules.yaml
    design_intent.yaml
    simulation.yaml
    folded_cascode_mlp_witness_plan.yaml
    ngspice_validation.yaml
```

## Technology/model inputs

```text
technology/train_sky130_mos_mlp.py
technology/sky130_tt_27c_mlp_dense.csv              # copied from the working repo during installation
technology/sky130_tt_27c_mlp_dense.csv.metadata.json
runtime/mlp_models/sky130_nmos_mlp.pt
runtime/mlp_models/sky130_pmos_mlp.pt
runtime/mlp_models/training_summary.json
```

The review snapshot did not contain the dense CSV itself or a verified current technology-table generation script.  Do not invent those files during cleanup.  Copy the real dense CSV from the working repository, and preserve the historical table-generation/training scripts from `MVP_archive_July_30` until their roles are verified.

## Run witnesses

From the repository root:

```bash
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python -m openams.synthesis.witness_engine \
  --plan examples/two_stage_opamp/inputs/two_stage_mlp_witness_plan.yaml

python -m openams.synthesis.witness_engine \
  --plan examples/folded_cascode/inputs/folded_cascode_mlp_witness_plan.yaml
```

The frontend must have already produced the design-space CSV referenced by each plan.

## Verify witnesses

```bash
python -m openams.validation.ngspice_witness \
  --plan examples/two_stage_opamp/inputs/ngspice_validation.yaml

python -m openams.validation.ngspice_witness \
  --plan examples/folded_cascode/inputs/ngspice_validation.yaml
```

## Migration rule

Do not delete the specialized/experimental scripts until the generic pipeline reproduces the frozen reference outputs in `archive_manifest/`.  After equivalence is established, move the obsolete experiments to the pre-clean archive rather than leaving them in the production tree.

# OpenAMS Generic Step-5 Refactor

## Scope

This patch preserves the existing two-stage `build_complete_assignments()` path
and adds a separate topology-generic candidate-construction path.

The generic path guarantees:

- all declared independent and dependent quantities are populated;
- compiled current equations are evaluated exactly;
- matched-width groups use common technology rows and total widths;
- width/finger realizations obey the configured width policy;
- per-device technology-row provenance is retained.

It intentionally does **not** claim that conservative Step-4 voltage intervals
prove a simultaneous physical DC operating point. Generic candidates are marked
`REQUIRES_NGSPICE_DC_CONFIRMATION` and routed to ngspice DC confirmation.

## Install

```bash
cd ~/AMS-Tutorial/openams

cp src/openams/synthesis/complete_assignments.py \
   src/openams/synthesis/complete_assignments.py.before_generic_step5

cp tools/validation/validate_assignment_step_05_complete_assignments.py \
   tools/validation/validate_assignment_step_05_complete_assignments.py.before_generic_step5

tar -xzf ~/Downloads/openams_step5_generic_refactor_patch.tgz

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python -m py_compile \
  src/openams/synthesis/generic_complete_assignments.py \
  src/openams/synthesis/complete_assignments.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py

pytest -q tests/synthesis/test_complete_assignments.py
```

## Folded-cascode generic Step 5

```bash
rm -f \
  examples/folded_cascode/generated/assignment_synthesis/complete_assignments.json \
  examples/folded_cascode/generated/assignment_synthesis/complete_assignments.csv \
  examples/folded_cascode/generated/assignment_synthesis/STEP5_COMPLETE_ASSIGNMENTS_REPORT.md

python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model \
    examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions \
    examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions \
    examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --output-json \
    examples/folded_cascode/generated/assignment_synthesis/complete_assignments.json \
  --output-csv \
    examples/folded_cascode/generated/assignment_synthesis/complete_assignments.csv \
  --report \
    examples/folded_cascode/generated/assignment_synthesis/STEP5_COMPLETE_ASSIGNMENTS_REPORT.md \
  --mode generic
```

Expected route:

```text
ngspice_dc_confirmation
```

Expected proof level:

```text
candidate_not_yet_simulator_confirmed
```

## Two-stage legacy regression

```bash
rm -rf docs/validation/evidence/two_stage_assignment_step_05_regression
mkdir -p docs/validation/evidence/two_stage_assignment_step_05_regression

python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model \
    examples/two_stage_opamp/generated/compiled_circuit_model.json \
  --independent-regions \
    examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions \
    examples/two_stage_opamp/generated/assignment_synthesis/dependent_regions.json \
  --output-json \
    docs/validation/evidence/two_stage_assignment_step_05_regression/complete_assignments.json \
  --output-csv \
    docs/validation/evidence/two_stage_assignment_step_05_regression/complete_assignments.csv \
  --report \
    docs/validation/evidence/two_stage_assignment_step_05_regression/STEP5_REPORT.md \
  --mode legacy
```

# OpenAMS Generic Inverse-Feasible Step 5

## Purpose

This patch makes the dense forward characterization CSV the canonical source
for a current-conditioned inverse-feasible view.  The solver queries compact
`(W, VGS, VDS_min..VDS_max)` realizations and joins matched device groups by
shared width and circuit-node constraints.

The implementation is topology generic: device names and group membership are
read from the compiled circuit model and design intent.

## Install

```bash
cd ~/AMS-Tutorial/openams

cp -a src/openams/synthesis/generic_complete_step5.py \
  src/openams/synthesis/generic_complete_step5.py.before_inverse_feasible

cp -a tools/validation/validate_assignment_step_05_complete_assignments.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py.before_inverse_feasible

tar -xzf ~/Downloads/openams_inverse_feasible_step5_v1.tgz

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python -m py_compile \
  src/openams/synthesis/inverse_feasible_provider.py \
  src/openams/synthesis/generic_complete_step5.py \
  tools/validation/validate_assignment_step_05_complete_assignments.py

pytest -q \
  tests/synthesis/test_inverse_feasible_provider.py \
  tests/synthesis/test_generic_complete_step5.py \
  tests/synthesis/test_complete_assignments.py
```

## Folded-cascode run

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
  --mode generic \
  --provider inverse \
  --continuous-samples w_m1_um=25 \
  --range w_m1_um=1:50 \
  --max-device-candidates 16 \
  --max-group-choices 32 \
  --max-solutions-per-point 32
```

## Algorithm

For each independent tuple:

1. Propagate compiled current equations.
2. Order matched-width groups by how strongly independent variables and known
   supply/input nodes constrain them.
3. Query the dense dataset inversely for each device's feasible `(W, VGS)`
   tuples near the target current.
4. Collapse multiple saturated VDS rows into one realization carrying
   `minimum_saturated_vds_v` and `maximum_characterized_vds_v`.
5. Intersect group members on common width.
6. Backtrack over group choices and propagate exact VGS node equations.
7. Treat VDS as a saturation range, not as a falsely exact node voltage.
8. Enforce compiled headroom and other declarative constraints.
9. Emit every retained solution up to the configured per-point and global
   limits, with technology-row provenance.

## Current boundary

The patch implements the inverse-feasible dataset path.  A targeted forward-MLP
fallback/cache remains the next provider-layer addition.  The provider interface
is unchanged, so that fallback does not require another circuit-solver rewrite.

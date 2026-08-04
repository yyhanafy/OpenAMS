# OpenAMS Generic Complete Step 5

This patch replaces the one-point generic smoke constructor with a real independent-grid enumerator and a topology-generic device/circuit join engine.

## Architecture

1. Enumerate every declared independent-variable combination.
2. Propagate compiled current equations.
3. Group devices by declarative matched-width relations.
4. Request device realizations from a pluggable provider.
5. Propagate device-row voltage equations onto the extracted topology.
6. Reject inconsistent node joins, width joins, device realizations, and headroom.
7. Emit only `model_valid_dc_operating_point` assignments.

## Providers

- `table`: characterized CSV, deterministic reference implementation.
- `plugin`: Python `module:function` hook for an MLP or other surrogate.

The plugin receives `DeviceRequest` plus tolerances and returns `DeviceRealization` records. This keeps Step 5 topology-generic and device-model-agnostic.

## Folded-cascode command: 14,175 independent combinations

```bash
python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --output-json examples/folded_cascode/generated/assignment_synthesis/complete_assignments.json \
  --output-csv examples/folded_cascode/generated/assignment_synthesis/complete_assignments.csv \
  --report examples/folded_cascode/generated/assignment_synthesis/STEP5_COMPLETE_ASSIGNMENTS_REPORT.md \
  --mode generic \
  --provider table \
  --continuous-samples w_m1_um=25 \
  --range w_m1_um=1:50
```

The grid size is `25 × 7 × 81 = 14,175`.

## MLP use

After exposing the trained MLP through a plugin function, replace:

```bash
--provider table
```

with:

```bash
--provider plugin \
--provider-plugin openams.technology.ml_surrogate.step5_provider:predict_candidates
```

The same Step-5 engine and circuit constraints remain unchanged.

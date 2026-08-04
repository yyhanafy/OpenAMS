# OpenAMS Generic Step-4 Refactor

This patch adds a topology-independent dependency-region engine alongside the
legacy two-stage adapters.

## Semantics

The generic engine performs:

1. linear interval propagation from design-intent current/size equations;
2. technology-backed total-width recovery for devices with known current regions;
3. conservative supply-bounded voltage recovery with technology provenance;
4. ordered dependency-group reporting.

Full row correlation, shared-node equality, KCL/KVL joins, and final physical
operating-point construction remain explicitly deferred to Step 5.

## Install

From the repository root:

```bash
tar -xzf ~/Downloads/openams_step4_generic_refactor_patch.tgz
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
python -m py_compile \
  src/openams/synthesis/generic_dependency.py \
  src/openams/synthesis/dependent_regions.py \
  tools/validation/validate_assignment_step_04_dependent_regions.py \
  tools/migrate_step4_to_generic_dependency.py
pytest -q tests/synthesis/test_dependent_regions.py
```

Migrate the folded-cascode source intent and already-built compiled model:

```bash
python tools/migrate_step4_to_generic_dependency.py \
  --design-intent examples/folded_cascode/inputs/design_intent.yaml \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json
```

Run generic Step 4:

```bash
python tools/validation/validate_assignment_step_04_dependent_regions.py \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --output examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --report examples/folded_cascode/generated/assignment_synthesis/STEP4_DEPENDENT_REGIONS_REPORT.md \
  --mode generic
```

The legacy two-stage design remains on its existing adapter solvers unless it
is explicitly migrated. This preserves the current regression path.

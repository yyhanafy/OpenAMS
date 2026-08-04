# Unified coarse independent scan

The public command remains:

```text
tools/validation/run_coarse_independent_ac_scan.py
```

The current two-stage implementation is preserved byte-for-byte as the legacy
regression backend. The new generic backend reads the topology, independent
variables, equations, matching groups, tolerances, and technology requirements
from the compiled model and uses the same continuous MLP oracle.

## Install

```bash
cd ~/AMS-Tutorial/openams

cp tools/validation/run_coarse_independent_ac_scan.py \
   tools/validation/run_coarse_independent_ac_scan_two_stage_legacy.py

tar -xzf ~/Downloads/openams_unified_coarse_scan_v1.tgz

chmod +x \
  tools/validation/run_coarse_independent_ac_scan.py \
  tools/validation/run_generic_compiled_scan.py

export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"

python -m py_compile \
  tools/validation/run_coarse_independent_ac_scan.py \
  tools/validation/run_coarse_independent_ac_scan_two_stage_legacy.py \
  tools/validation/run_generic_compiled_scan.py \
  src/openams/synthesis/generic_complete_step5.py \
  src/openams/synthesis/mlp_step5_provider.py

pytest -q \
  tests/validation/test_unified_coarse_scan_dispatch.py \
  tests/synthesis/test_generic_complete_step5.py \
  tests/validation/test_coarse_scan_schema_v3.py \
  tests/validation/test_two_stage_small_signal_ac_phase.py
```

## Two-stage regression

Use the original command unchanged. Because it has no `--compiled-model`, the
unified entry point dispatches to the preserved legacy implementation.

## Folded-cascode 14,175-point MLP scan

```bash
OUTPUT_DIR="$PWD/examples/folded_cascode/generated/assignment_synthesis/coarse_independent_scan_mlp_v1"

test ! -e "$OUTPUT_DIR" || {
  echo "[FAIL] Output directory already exists: $OUTPUT_DIR"
  exit 1
}

python tools/validation/run_coarse_independent_ac_scan.py \
  --compiled-model examples/folded_cascode/generated/compiled_circuit_model.json \
  --independent-regions examples/folded_cascode/generated/assignment_synthesis/independent_regions.json \
  --dependent-regions examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json \
  --continuous-samples w_m1_um=25 \
  --range w_m1_um=1:50 \
  --progress-every 25 \
  --checkpoint-every 25 \
  --output-dir "$OUTPUT_DIR" \
  2>&1 | tee "$OUTPUT_DIR/run.log"
```

The generic branch prints the same core operational statistics as the frozen
two-stage run: grid points, pass/reject counts, exact MLP queries, MLP queries
per point, elapsed time, throughput, checkpoints, and rejection funnel.

AC estimation remains topology-dependent. The folded-cascode run first performs
the same MLP-based DC construction stage. A generic nodal AC builder is the next
shared layer; the two-stage AC estimator remains unchanged for regression.

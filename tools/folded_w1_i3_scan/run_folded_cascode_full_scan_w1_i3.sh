#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONUNBUFFERED=1
OUT="$ROOT/runtime/folded_inverse_full_scan_w1_i3"
MODEL="$ROOT/examples/folded_cascode/generated/compiled_circuit_model.json"
INDEPENDENT="$ROOT/examples/folded_cascode/generated/assignment_synthesis/independent_regions.json"
DEPENDENT="$ROOT/examples/folded_cascode/generated/assignment_synthesis/dependent_regions.json"
rm -rf "$OUT"
mkdir -p "$OUT"
export OPENAMS_STEP5_PROGRESS_EVERY="${OPENAMS_STEP5_PROGRESS_EVERY:-25}"
export OPENAMS_STEP5_PROGRESS_FILE="$OUT/progress.json"
python tools/validation/validate_assignment_step_03_independent_domains.py \
  --compiled-model "$MODEL" \
  --output "$INDEPENDENT" \
  --report examples/folded_cascode/generated/assignment_synthesis/STEP3_INDEPENDENT_REGIONS_REPORT.md \
  --mode generic
python tools/validation/validate_assignment_step_04_dependent_regions.py \
  --compiled-model "$MODEL" \
  --independent-regions "$INDEPENDENT" \
  --output "$DEPENDENT" \
  --report examples/folded_cascode/generated/assignment_synthesis/STEP4_DEPENDENT_REGIONS_REPORT.md \
  --mode generic
set -o pipefail
time python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model "$MODEL" \
  --independent-regions "$INDEPENDENT" \
  --dependent-regions "$DEPENDENT" \
  --output-json "$OUT/complete_assignments.json" \
  --output-csv "$OUT/complete_assignments.csv" \
  --report "$OUT/REPORT.md" \
  --mode generic \
  --provider inverse \
  --technology-csv technology/sky130_tt_27c_mlp_dense.csv \
  --mlp-fallback \
  --adaptive-cache "$OUT/adaptive_inverse_cache.csv" \
  --continuous-samples w_m1_um=25 \
  --range w_m1_um=1:50 \
  --max-device-candidates 8 \
  --max-group-choices 8 \
  --max-solutions-per-point 8 \
  2>&1 | tee "$OUT/run.log"

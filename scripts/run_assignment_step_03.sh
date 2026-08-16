#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

MODEL="$ROOT/examples/two_stage_opamp/generated/compiled_circuit_model.json"
OUTDIR="$ROOT/examples/two_stage_opamp/generated/assignment_synthesis"
OUTPUT="$OUTDIR/independent_regions.json"
REPORT="$OUTDIR/STEP3_INDEPENDENT_REGIONS_REPORT.md"

[[ -f "$MODEL" ]] || {
  echo "[FAIL] Missing compiled model: $MODEL" >&2
  exit 1
}

mkdir -p "$OUTDIR"

python tools/validation/validate_assignment_step_03_independent_domains.py \
  --compiled-model "$MODEL" \
  --output "$OUTPUT" \
  --report "$REPORT"

pytest -q tests/synthesis/test_independent_domains.py

[[ -s "$OUTPUT" ]] || {
  echo "[FAIL] Missing output: $OUTPUT" >&2
  exit 1
}

echo "[PASS] Assignment synthesis Step 3 complete."
echo "[PASS] Output: $OUTPUT"
echo "[PASS] Report: $REPORT"

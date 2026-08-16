#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

MODEL="$ROOT/examples/two_stage_opamp/generated/compiled_circuit_model.json"
INDEPENDENT="$ROOT/examples/two_stage_opamp/generated/assignment_synthesis/independent_regions.json"
OUT="$ROOT/examples/two_stage_opamp/generated/assignment_synthesis/dependent_regions.json"
REPORT="$ROOT/examples/two_stage_opamp/generated/assignment_synthesis/STEP4_DEPENDENT_REGIONS_REPORT.md"

[[ -s "$MODEL" ]] || { echo "[FAIL] missing $MODEL" >&2; exit 1; }
[[ -s "$INDEPENDENT" ]] || { echo "[FAIL] missing $INDEPENDENT" >&2; exit 1; }

python tools/validation/validate_assignment_step_04_dependent_regions.py \
  --compiled-model "$MODEL" \
  --independent-regions "$INDEPENDENT" \
  --output "$OUT" \
  --report "$REPORT"

pytest -q tests/synthesis/test_dependent_regions.py

[[ -s "$OUT" ]] || { echo "[FAIL] missing $OUT" >&2; exit 1; }

echo "[PASS] Assignment synthesis Step 4 complete."
echo "[PASS] Output: $OUT"
echo "[PASS] Report: $REPORT"

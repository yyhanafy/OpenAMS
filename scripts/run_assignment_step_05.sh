#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

BASE="$ROOT/examples/two_stage_opamp/generated/assignment_synthesis"
MODEL="$ROOT/examples/two_stage_opamp/generated/compiled_circuit_model.json"
INDEPENDENT="$BASE/independent_regions.json"
DEPENDENT="$BASE/dependent_regions.json"
JSON_OUT="$BASE/complete_assignments.json"
CSV_OUT="$BASE/complete_assignments.csv"
REPORT="$BASE/STEP5_COMPLETE_ASSIGNMENTS_REPORT.md"

for path in "$MODEL" "$INDEPENDENT" "$DEPENDENT"; do
  [[ -s "$path" ]] || { echo "[FAIL] missing $path" >&2; exit 1; }
done

python tools/validation/validate_assignment_step_05_complete_assignments.py \
  --compiled-model "$MODEL" \
  --independent-regions "$INDEPENDENT" \
  --dependent-regions "$DEPENDENT" \
  --output-json "$JSON_OUT" \
  --output-csv "$CSV_OUT" \
  --report "$REPORT"

pytest -q tests/synthesis/test_complete_assignments.py

[[ -s "$JSON_OUT" ]] || { echo "[FAIL] missing $JSON_OUT" >&2; exit 1; }
[[ -s "$CSV_OUT" ]] || { echo "[FAIL] missing $CSV_OUT" >&2; exit 1; }

echo "[PASS] Assignment synthesis Step 5 complete."
echo "[PASS] JSON: $JSON_OUT"
echo "[PASS] CSV:  $CSV_OUT"
echo "[PASS] Report: $REPORT"

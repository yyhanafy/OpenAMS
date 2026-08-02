#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

BASE="$ROOT/examples/two_stage_opamp/generated/assignment_synthesis"

python tools/validation/audit_complete_assignments.py \
  --json "$BASE/complete_assignments.json" \
  --csv "$BASE/complete_assignments.csv" \
  --compiled-model "$ROOT/examples/two_stage_opamp/generated/compiled_circuit_model.json" \
  --output-dir "$BASE/integrity_audit"

echo "[PASS] Assignment integrity audit completed."
echo "[INFO] Review:"
echo "       $BASE/integrity_audit/ASSIGNMENT_INTEGRITY_AUDIT.md"

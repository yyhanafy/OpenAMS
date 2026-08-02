#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python tools/validation/run_exact_assignment_rule_funnel.py

echo "[PASS] Exact assignment rule funnel completed."
echo "[INFO] Review:"
echo "examples/two_stage_opamp/generated/assignment_synthesis/"
echo "exact_rule_funnel/EXACT_ASSIGNMENT_RULE_FUNNEL.md"

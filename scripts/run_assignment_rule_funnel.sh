#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python tools/validation/audit_assignment_rule_funnel.py

echo "[PASS] Wrote the current-count audit."
echo "[INFO] This audit will explicitly state that production instrumentation"
echo "       is still required for a trustworthy per-rule funnel."

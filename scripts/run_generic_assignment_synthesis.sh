#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

python tools/build_two_stage_generic_contract.py

pytest -q tests/synthesis/test_generic_topology_solver.py

python tools/validation/validate_generic_topology_solver.py \
  --max-solutions "${MAX_SOLUTIONS:-5}" \
  --max-partials "${MAX_PARTIALS:-5000}" \
  --progress-every "${PROGRESS_EVERY:-500}"

echo "[PASS] Generic complete-physical assignment smoke run finished."

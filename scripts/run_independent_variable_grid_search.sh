#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
python tools/validation/run_independent_variable_grid_search.py \
  --w1-step-um "${W1_STEP_UM:-1.0}" \
  --vout-step-v "${VOUT_STEP_V:-0.1}" \
  --i5-stride "${I5_STRIDE:-1}" \
  --start-index "${START_INDEX:-0}" \
  --max-grid-points "${MAX_GRID_POINTS:-1000}" \
  --max-partials-per-point "${MAX_PARTIALS_PER_POINT:-5000}" \
  --progress-every "${PROGRESS_EVERY:-100}"

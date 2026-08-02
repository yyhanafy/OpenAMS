#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

ARGS=(
  --i5-count "${I5_COUNT:-40}"
  --w1-count "${W1_COUNT:-25}"
  --vout-count "${VOUT_COUNT:-10}"
  --w1-min-um "${W1_MIN_UM:-1}"
  --w1-max-um "${W1_MAX_UM:-50}"
  --vout-min-v "${VOUT_MIN_V:-0.6}"
  --vout-max-v "${VOUT_MAX_V:-1.5}"
  --n1-v "${N1_V:-0.6}"
  --vbias-v "${VBIAS_V:-0.6}"
  --progress-every "${PROGRESS_EVERY:-25}"
  --checkpoint-every "${CHECKPOINT_EVERY:-25}"
  --max-points "${MAX_POINTS:-0}"
)

if [[ "${RESUME:-0}" == "1" ]]; then
  ARGS+=(--resume)
fi

python tools/validation/run_coarse_independent_ac_scan.py "${ARGS[@]}"

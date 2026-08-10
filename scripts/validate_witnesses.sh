#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PLAN="${1:?usage: scripts/validate_witnesses.sh NGSPICE_PLAN.yaml [extra args...]}"
shift
python -m openams.validation.ngspice_witness --root "$ROOT" --plan "$PLAN" "$@"

#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
PLAN="${1:?usage: scripts/generate_witnesses.sh PLAN.yaml [extra args...]}"
shift
python -m openams.synthesis.witness_engine --root "$ROOT" --plan "$PLAN" "$@"

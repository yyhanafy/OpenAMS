#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

ASSIGNMENTS="${ASSIGNMENTS:-examples/two_stage_opamp/generated/assignment_synthesis/generic_assignments_smoke.json}"
COMPILED_MODEL="${COMPILED_MODEL:-examples/two_stage_opamp/generated/compiled_circuit_model.json}"
DECK_TEMPLATE="${DECK_TEMPLATE:-examples/two_stage_opamp/inputs/deck_template.spice}"
INPUT_DIR="${INPUT_DIR:-examples/two_stage_opamp/inputs}"
OUTPUT_DIR="${OUTPUT_DIR:-examples/two_stage_opamp/generated/generic_ngspice_validation}"
LIMIT="${LIMIT:-100}"
TIMEOUT_S="${TIMEOUT_S:-60}"
AC_START_HZ="${AC_START_HZ:-1}"
AC_STOP_HZ="${AC_STOP_HZ:-1e10}"
POINTS_PER_DECADE="${POINTS_PER_DECADE:-100}"

python tools/validation/run_generic_100_case_ngspice_ac.py \
  --assignments "$ASSIGNMENTS" \
  --compiled-model "$COMPILED_MODEL" \
  --deck-template "$DECK_TEMPLATE" \
  --input-dir "$INPUT_DIR" \
  --output-dir "$OUTPUT_DIR" \
  --limit "$LIMIT" \
  --timeout-s "$TIMEOUT_S" \
  --ac-start-hz "$AC_START_HZ" \
  --ac-stop-hz "$AC_STOP_HZ" \
  --points-per-decade "$POINTS_PER_DECADE"

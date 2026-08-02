#!/usr/bin/env bash
set -euo pipefail

ROOT="$HOME/AMS-Tutorial/openams"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

: "${SKY130_LIB:?Set SKY130_LIB to the SKY130 ngspice library}"

EXAMPLE="$ROOT/examples/two_stage_opamp_broad_optimizer"
INPUTS="$EXAMPLE/inputs"
GENERATED="$EXAMPLE/generated"
RUN_DIR="$ROOT/runtime/two_stage_opamp_broad_optimizer"

for file in \
  "$INPUTS/netlist.spice" \
  "$INPUTS/deck_template.spice" \
  "$INPUTS/specs.yaml" \
  "$INPUTS/design_rules.yaml" \
  "$INPUTS/simulation.yaml"
do
  if [[ ! -f "$file" ]]; then
    echo "[FAIL] Missing required file: $file" >&2
    exit 1
  fi
done

if [[ ! -f "$SKY130_LIB" ]]; then
  echo "[FAIL] SKY130 library not found: $SKY130_LIB" >&2
  exit 1
fi

if ! command -v ngspice >/dev/null 2>&1; then
  echo "[FAIL] ngspice is not available in PATH" >&2
  exit 1
fi

rm -rf "$RUN_DIR"
mkdir -p "$GENERATED" "$RUN_DIR"

echo "[INFO] Validating metadata"

python -m openams.cli.validate_metadata \
  --specs "$INPUTS/specs.yaml" \
  --rules "$INPUTS/design_rules.yaml" \
  --simulation "$INPUTS/simulation.yaml"

echo "[INFO] Building executable contract"

python -m openams.cli.build_contract \
  --netlist "$INPUTS/netlist.spice" \
  --specs "$INPUTS/specs.yaml" \
  --rules "$INPUTS/design_rules.yaml" \
  --simulation "$INPUTS/simulation.yaml" \
  --output "$GENERATED/executable_contract.json"

echo "[INFO] Running broad optimizer search"

python -m openams.cli.run_bias \
  --contract "$GENERATED/executable_contract.json" \
  --output "$RUN_DIR" \
  --backend ngspice \
  --n-init 24 \
  --n-iter 72 \
  --seed 7

echo
echo "[PASS] Broad optimizer run completed"
echo "[INFO] Contract: $GENERATED/executable_contract.json"
echo "[INFO] Results:  $RUN_DIR"

if [[ -f "$RUN_DIR/run_summary.json" ]]; then
  echo
  echo "===== RUN SUMMARY ====="
  cat "$RUN_DIR/run_summary.json"
fi


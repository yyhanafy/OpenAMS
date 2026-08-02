#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

INPUT="$ROOT/examples/two_stage_opamp/inputs"
GEN="$ROOT/examples/two_stage_opamp/generated"
SYNTH="$GEN/assignment_synthesis"

FIXED_RESULTS="$GEN/fixed_assignment_results"
CONTRACT="$GEN/executable_contract.json"
OPT_RESULTS="$GEN/optimization_results"

BACKEND="${BACKEND:-ngspice}"
N_INIT="${N_INIT:-24}"
N_ITER="${N_ITER:-72}"
SEED="${SEED:-7}"

mkdir -p \
  "$GEN" \
  "$SYNTH" \
  "$FIXED_RESULTS" \
  "$OPT_RESULTS"

echo "===== OPENAMS PIPELINE ====="
echo "root:       $ROOT"
echo "input:      $INPUT"
echo "generated:  $GEN"
echo "backend:    $BACKEND"
echo

required_files=(
  "$INPUT/netlist.spice"
  "$INPUT/specs.yaml"
  "$INPUT/design_rules.yaml"
  "$INPUT/simulation.yaml"
  "$INPUT/design_intent.yaml"
)

for path in "${required_files[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "[FAIL] Required input does not exist: $path" >&2
    exit 1
  fi
done

echo "===== 1. VALIDATE METADATA ====="

python -m openams.cli.validate_metadata \
  --specs "$INPUT/specs.yaml" \
  --rules "$INPUT/design_rules.yaml" \
  --simulation "$INPUT/simulation.yaml"

echo
echo "===== 2. COMPILE DESIGN RULES ====="

python -m openams.cli.compile_design_rules \
  --rules "$INPUT/design_rules.yaml" \
  --output "$GEN/design_rules.compiled.yaml" \
  --report "$GEN/design_rule_validation.json"

echo
echo "===== 3. EXTRACT TOPOLOGY ====="

python -m openams.cli.extract_topology \
  --netlist "$INPUT/netlist.spice" \
  --output "$GEN/topology.json"

echo
echo "===== 4. COMPILE DESIGN INTENT ====="

python -m openams.cli.compile_design_intent \
  --netlist "$INPUT/netlist.spice" \
  --intent "$INPUT/design_intent.yaml" \
  --rules "$INPUT/design_rules.yaml" \
  --topology-output "$GEN/topology.intent.json" \
  --expanded-output "$GEN/design_intent.expanded.yaml"

echo
echo "===== 5. BUILD VALID ASSIGNMENTS ====="

python -m openams.cli.build_valid_assignments \
  --expanded-rules "$GEN/design_intent.expanded.yaml" \
  --output-dir "$SYNTH" \
  --report-json "$SYNTH/synthesis_report.json"

if [[ ! -f "$SYNTH/synthesis_report.json" ]]; then
  echo "[FAIL] Assignment synthesis did not create:" >&2
  echo "       $SYNTH/synthesis_report.json" >&2
  exit 1
fi

echo
echo "===== 6. DETERMINE EXECUTION ROUTE ====="

ROUTE="$(
  python - \
    "$SYNTH/synthesis_report.json" \
    "$SYNTH/assignment_classification.json" <<'PY_ROUTE'
import json
import sys
from pathlib import Path


def load_json(path: Path) -> dict:
    if not path.is_file():
        return {}

    data = json.loads(path.read_text())

    if not isinstance(data, dict):
        raise SystemExit(f"Expected a JSON object in {path}")

    return data


def route_from(report: dict) -> str | None:
    # Direct fields, as used by assignment_classification.json.
    for key in ("recommended_route", "route"):
        value = report.get(key)
        if isinstance(value, str) and value:
            return value

    # Nested fields, as used by synthesis_report.json.
    classification = report.get("classification")
    if isinstance(classification, dict):
        for key in ("recommended_route", "route"):
            value = classification.get(key)
            if isinstance(value, str) and value:
                return value

    return None


def counts_from(report: dict) -> tuple[int, int]:
    classification = report.get("classification")
    source = classification if isinstance(classification, dict) else report

    fixed = int(source.get("fixed_assignment_count", 0) or 0)
    ranged = int(source.get("ranged_assignment_count", 0) or 0)

    return fixed, ranged


paths = [Path(arg) for arg in sys.argv[1:]]
reports = [load_json(path) for path in paths]

# First use an explicit route from either report.
for report in reports:
    route = route_from(report)
    if route:
        print(route)
        raise SystemExit(0)

# Then infer the route from classification counts.
fixed_count = 0
ranged_count = 0

for report in reports:
    fixed, ranged = counts_from(report)
    fixed_count = max(fixed_count, fixed)
    ranged_count = max(ranged_count, ranged)

if fixed_count > 0 and ranged_count == 0:
    print("direct_simulation")
    raise SystemExit(0)

if ranged_count > 0:
    print("optimization")
    raise SystemExit(0)

raise SystemExit(
    "Unable to determine recommended route from:\n  "
    + "\n  ".join(str(path) for path in paths)
)
PY_ROUTE
)"
echo "[INFO] recommended_route=$ROUTE"

case "$ROUTE" in
  direct_simulation|fixed_assignments|simulate_fixed)
    echo
    echo "===== 7A. RUN FIXED ASSIGNMENTS ====="

    FIXED_ASSIGNMENTS=""

    for candidate in \
      "$SYNTH/fixed_assignments.csv" \
      "$SYNTH/complete_assignments.csv" \
      "$SYNTH/assignments.csv"
    do
      if [[ -f "$candidate" ]]; then
        FIXED_ASSIGNMENTS="$candidate"
        break
      fi
    done

    if [[ -z "$FIXED_ASSIGNMENTS" ]]; then
      echo "[FAIL] Direct-simulation route was selected, but no assignment CSV was found." >&2
      echo "[INFO] Files currently present under $SYNTH:" >&2
      find "$SYNTH" -maxdepth 2 -type f -print >&2
      exit 1
    fi

    echo "[INFO] assignments=$FIXED_ASSIGNMENTS"
    echo "[INFO] output=$FIXED_RESULTS"

    rm -rf "$FIXED_RESULTS"
    mkdir -p "$FIXED_RESULTS"

    python -m openams.cli.run_fixed_assignments \
      --netlist "$INPUT/netlist.spice" \
      --specs "$INPUT/specs.yaml" \
      --rules "$INPUT/design_rules.yaml" \
      --simulation "$INPUT/simulation.yaml" \
      --assignments "$FIXED_ASSIGNMENTS" \
      --output "$FIXED_RESULTS" \
      --backend "$BACKEND"

    echo
    echo "[PASS] Fixed assignments were simulated."
    echo "[PASS] Results: $FIXED_RESULTS"
    ;;

  optimization|contract_optimization|run_bias)
    echo
    echo "===== 7B. BUILD EXECUTABLE CONTRACT ====="

    python -m openams.cli.build_contract \
      --netlist "$INPUT/netlist.spice" \
      --specs "$INPUT/specs.yaml" \
      --rules "$INPUT/design_rules.yaml" \
      --simulation "$INPUT/simulation.yaml" \
      --output "$CONTRACT"

    if [[ ! -f "$CONTRACT" ]]; then
      echo "[FAIL] Contract generation did not create: $CONTRACT" >&2
      exit 1
    fi

    echo
    echo "===== 8B. RUN BIAS OPTIMIZATION ====="

    rm -rf "$OPT_RESULTS"
    mkdir -p "$OPT_RESULTS"

    python -m openams.cli.run_bias \
      --contract "$CONTRACT" \
      --output "$OPT_RESULTS" \
      --backend "$BACKEND" \
      --n-init "$N_INIT" \
      --n-iter "$N_ITER" \
      --seed "$SEED"

    echo
    echo "[PASS] Bias optimization completed."
    echo "[PASS] Results: $OPT_RESULTS"
    ;;

  no_assignments|infeasible|none)
    echo "[FAIL] Synthesis produced no executable assignments." >&2
    python -m json.tool "$SYNTH/synthesis_report.json" >&2
    exit 1
    ;;

  *)
    echo "[FAIL] Unsupported recommended route: $ROUTE" >&2
    echo "[INFO] Synthesis report:" >&2
    python -m json.tool "$SYNTH/synthesis_report.json" >&2
    exit 1
    ;;
esac

echo
echo "===== PIPELINE COMPLETE ====="
echo "[PASS] Assignment synthesis and selected execution route completed."

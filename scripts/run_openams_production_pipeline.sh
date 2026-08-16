#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_openams_production_pipeline.sh PROJECT_DIR [SUBCIRCUIT] [NETLIST]

Examples:
  scripts/run_openams_production_pipeline.sh examples/two_stage_opamp
  scripts/run_openams_production_pipeline.sh examples/folded_cascode

Optional environment variables:
  OPENAMS_CLEAN=1       Remove the project's generated directory first.
  OPENAMS_RUN_TESTS=1   Run the supporting pytest regression suites (default: 1).

Defaults:
  PROJECT_DIR/inputs/netlist.spice is used when present.
  Otherwise, the only non-hierarchical *.spice file containing a .subckt is used.
  SUBCIRCUIT is inferred when the selected netlist declares exactly one .subckt.
EOF
}

[[ $# -ge 1 && $# -le 3 ]] || { usage >&2; exit 2; }

PROJECT_ARG="$1"
SUBCIRCUIT="${2:-}"
NETLIST_ARG="${3:-}"

if [[ "$PROJECT_ARG" = /* ]]; then
  PROJECT="$PROJECT_ARG"
else
  PROJECT="$ROOT/$PROJECT_ARG"
fi

INPUT="$PROJECT/inputs"
GEN="$PROJECT/generated"
EVIDENCE="$GEN/evidence"
LOG="$GEN/OPENAMS_PRODUCTION_PIPELINE_LOG.md"
ASSIGN="$GEN/assignment_synthesis"

[[ -d "$INPUT" ]] || { echo "[FAIL] Missing input directory: $INPUT" >&2; exit 1; }

if [[ -n "$NETLIST_ARG" ]]; then
  if [[ "$NETLIST_ARG" = /* ]]; then
    NETLIST="$NETLIST_ARG"
  else
    NETLIST="$INPUT/$NETLIST_ARG"
  fi
elif [[ -f "$INPUT/netlist.spice" ]]; then
  NETLIST="$INPUT/netlist.spice"
elif [[ -f "$INPUT/$(basename "$PROJECT").spice" ]]; then
  NETLIST="$INPUT/$(basename "$PROJECT").spice"
else
  mapfile -t NETLIST_CANDIDATES < <(
    grep -li '^[[:space:]]*\.subckt[[:space:]]' "$INPUT"/*.spice 2>/dev/null \
      | grep -v '\.hierarchical\.spice$' \
      | sort
  )
  if [[ ${#NETLIST_CANDIDATES[@]} -ne 1 ]]; then
    echo "[FAIL] Could not infer one flat production netlist in $INPUT." >&2
    echo "       Pass the netlist filename as the third argument." >&2
    printf '       candidate: %s\n' "${NETLIST_CANDIDATES[@]:-none}" >&2
    exit 1
  fi
  NETLIST="${NETLIST_CANDIDATES[0]}"
fi

[[ -f "$NETLIST" ]] || { echo "[FAIL] Missing netlist: $NETLIST" >&2; exit 1; }

if [[ -z "$SUBCIRCUIT" ]]; then
  mapfile -t SUBCKTS < <(
    awk 'BEGIN{IGNORECASE=1} /^[[:space:]]*\.subckt[[:space:]]+/ {print $2}' "$NETLIST"
  )
  if [[ ${#SUBCKTS[@]} -ne 1 ]]; then
    echo "[FAIL] Could not infer one subcircuit from $NETLIST." >&2
    echo "       Pass the subcircuit name as the second argument." >&2
    printf '       declared: %s\n' "${SUBCKTS[*]:-none}" >&2
    exit 1
  fi
  SUBCIRCUIT="${SUBCKTS[0]}"
fi

if [[ "${OPENAMS_CLEAN:-0}" == "1" ]]; then
  rm -rf "$GEN"
fi

mkdir -p "$GEN" "$ASSIGN" "$EVIDENCE"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

required_files=(
  "$NETLIST"
  "$INPUT/specs.yaml"
  "$INPUT/design_rules.yaml"
  "$INPUT/design_intent.yaml"
  "$INPUT/simulation.yaml"
  "$INPUT/deck_template.spice"
)

for path in "${required_files[@]}"; do
  [[ -f "$path" ]] || { echo "[FAIL] Missing required input: $path" >&2; exit 1; }
done

echo "============================================================"
echo " OpenAMS Generic Production Pipeline"
echo "============================================================"
echo "project:     $PROJECT"
echo "inputs:      $INPUT"
echo "netlist:     $NETLIST"
echo "subcircuit:  $SUBCIRCUIT"
echo "generated:   $GEN"
echo

run_gate() {
  local label="$1"
  shift
  echo
  echo "===== $label ====="
  "$@"
}

TOPOLOGY_EVIDENCE="$EVIDENCE/gate_02_topology"
METADATA_EVIDENCE="$EVIDENCE/gate_03_metadata"
CLASSIFICATION_EVIDENCE="$EVIDENCE/gate_04_constraints"
COMPILER_EVIDENCE="$EVIDENCE/gate_04b_constraint_compiler"
TECHNOLOGY_EVIDENCE="$EVIDENCE/gate_05_technology"

rm -rf "$TOPOLOGY_EVIDENCE"
run_gate "STEP 1 / GATE 02: TOPOLOGY" \
  python tools/validation/validate_gate_02_topology.py \
    --netlist "$NETLIST" \
    --subcircuit "$SUBCIRCUIT" \
    --output-dir "$TOPOLOGY_EVIDENCE"
cp "$TOPOLOGY_EVIDENCE/topology.json" "$GEN/topology.json"
cp "$TOPOLOGY_EVIDENCE/topology_summary.json" "$GEN/topology_summary.json"

rm -rf "$METADATA_EVIDENCE"
run_gate "STEP 2 / GATE 03: METADATA" \
  python tools/validation/validate_gate_03_metadata.py \
    --input-dir "$INPUT" \
    --output-dir "$METADATA_EVIDENCE"
cp "$METADATA_EVIDENCE/metadata_summary.json" "$GEN/metadata_summary.json"

python - "$INPUT" "$GEN/project_inputs.normalized.json" <<'PY'
from __future__ import annotations
import dataclasses, enum, json, sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from openams.io import load_yaml_mapping
from openams.metadata import normalize_project_inputs

def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {f.name: jsonable(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum): return jsonable(value.value)
    if isinstance(value, Path): return str(value)
    if isinstance(value, Mapping): return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [jsonable(v) for v in value]
    if isinstance(value, (set, frozenset)): return sorted((jsonable(v) for v in value), key=repr)
    if hasattr(value, "__dict__"):
        return {str(k): jsonable(v) for k, v in vars(value).items() if not str(k).startswith("_")}
    return value

input_dir, output = Path(sys.argv[1]), Path(sys.argv[2])
project = normalize_project_inputs(
    specifications=load_yaml_mapping(input_dir / "specs.yaml"),
    design_intent=load_yaml_mapping(input_dir / "design_intent.yaml"),
    design_rules=load_yaml_mapping(input_dir / "design_rules.yaml"),
    simulation=load_yaml_mapping(input_dir / "simulation.yaml"),
)
payload = {"artifact": "openams.project_inputs", "schema_version": 1,
           "source_directory": str(input_dir), "project_inputs": jsonable(project)}
output.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
print(f"[PASS] wrote {output}")
PY

rm -rf "$CLASSIFICATION_EVIDENCE"
run_gate "STEP 3 / GATE 04A: CONSTRAINT CLASSIFICATION" \
  python tools/validation/validate_gate_04_constraint_classification.py \
    --design-intent "$INPUT/design_intent.yaml" \
    --design-rules "$INPUT/design_rules.yaml" \
    --output-dir "$CLASSIFICATION_EVIDENCE"
cp "$CLASSIFICATION_EVIDENCE/constraint_classification.json" "$GEN/constraint_classification.json"
cp "$CLASSIFICATION_EVIDENCE/compiler_constraints.json" "$GEN/compiler_constraints.json"

rm -rf "$COMPILER_EVIDENCE"
run_gate "STEP 4 / GATE 04B: CONSTRAINT COMPILATION" \
  python tools/validation/validate_gate_04b_constraint_compiler.py \
    --constraints "$GEN/compiler_constraints.json" \
    --output-dir "$COMPILER_EVIDENCE" \
    --mode generic
cp "$COMPILER_EVIDENCE/compiled_constraints.json" "$GEN/compiled_constraints.json"
cp "$COMPILER_EVIDENCE/compiler_diagnostics.json" "$GEN/compiler_diagnostics.json"
cp "$COMPILER_EVIDENCE/execution_results.json" "$GEN/constraint_compiler_validation_results.json"

rm -rf "$TECHNOLOGY_EVIDENCE"
run_gate "STEP 5 / GATE 05: TECHNOLOGY" \
  python tools/validation/validate_gate_05_technology.py \
    --input-dir "$INPUT" \
    --output-dir "$TECHNOLOGY_EVIDENCE"
cp "$TECHNOLOGY_EVIDENCE/technology_summary.json" "$GEN/technology_summary.json"

python - "$GEN" "$INPUT" "$NETLIST" "$SUBCIRCUIT" <<'PY'
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path
from typing import Any

generated, inputs, netlist = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
subcircuit = sys.argv[4]

def load(name: str) -> Any:
    path = generated / name
    if not path.is_file(): raise SystemExit(f"missing required artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()

topology = load("topology.json")
project_inputs = load("project_inputs.normalized.json")
classification = load("constraint_classification.json")
compiler_constraints = load("compiler_constraints.json")
compiled_constraints = load("compiled_constraints.json")
compiler_diagnostics = load("compiler_diagnostics.json")
technology = load("technology_summary.json")
statuses = [x.get("status") for x in compiler_diagnostics if isinstance(x, dict)]
input_files = [netlist, inputs / "specs.yaml", inputs / "design_rules.yaml",
               inputs / "design_intent.yaml", inputs / "simulation.yaml",
               inputs / "deck_template.spice"]
model = {
    "artifact": "openams.compiled_circuit_model", "schema_version": 1,
    "circuit_name": topology.get("circuit_name", subcircuit),
    "status": "READY_FOR_ASSIGNMENT_SYNTHESIS",
    "source_inputs": {p.name: {"path": str(p), "sha256": sha256(p)} for p in input_files},
    "topology": topology,
    "project_inputs": project_inputs.get("project_inputs", project_inputs),
    "constraint_model": {
        "classification_count": classification.get("classification_count", 0),
        "category_counts": classification.get("category_counts", {}),
        "canonical_constraints": compiler_constraints,
        "compiled_constraints": compiled_constraints,
        "compiler_diagnostics": compiler_diagnostics,
        "all_constraints_compiled": bool(statuses) and all(s == "compiled" for s in statuses),
        "topology_specific_relations": [x for x in classification.get("classified_items", [])
                                        if x.get("category") == "topology_heuristic"],
    },
    "synthesis_interface": {
        "independent_variables": [x for x in classification.get("classified_items", [])
                                  if x.get("category") == "synthesis_parameter"],
        "dependent_quantities": [x for x in classification.get("classified_items", [])
                                 if x.get("category") == "dependent_quantity_declaration"],
        "dependency_groups": [x for x in classification.get("classified_items", [])
                              if x.get("category") == "dependency_group"],
    },
    "technology": technology,
    "handoff": {"next_stage": "assignment_synthesis",
                "expected_output_directory": str(generated / "assignment_synthesis")},
}
out = generated / "compiled_circuit_model.json"
out.write_text(json.dumps(model, indent=2, default=str) + "\n", encoding="utf-8")
manifest_names = ["topology.json", "topology_summary.json", "metadata_summary.json",
                  "project_inputs.normalized.json", "constraint_classification.json",
                  "compiler_constraints.json", "compiled_constraints.json",
                  "compiler_diagnostics.json", "constraint_compiler_validation_results.json",
                  "technology_summary.json", "compiled_circuit_model.json"]
manifest = {"artifact": "openams.frontend_pipeline_manifest", "schema_version": 1,
            "status": "PASS", "completed_through_step": 5,
            "artifacts": {n: {"path": str(generated / n), "sha256": sha256(generated / n)}
                          for n in manifest_names},
            "next_stage": "assignment_synthesis"}
(generated / "frontend_pipeline_manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(f"[PASS] wrote {out}")
PY

MODEL="$GEN/compiled_circuit_model.json"
INDEPENDENT="$ASSIGN/independent_regions.json"
DEPENDENT="$ASSIGN/dependent_regions.json"
JSON_OUT="$ASSIGN/complete_assignments.json"
CSV_OUT="$ASSIGN/complete_assignments.csv"

run_gate "ASSIGNMENT STEP 3: INDEPENDENT REGIONS" \
  python tools/validation/validate_assignment_step_03_independent_domains.py \
    --compiled-model "$MODEL" \
    --output "$INDEPENDENT" \
    --report "$ASSIGN/STEP3_INDEPENDENT_REGIONS_REPORT.md" \
    --mode generic

run_gate "ASSIGNMENT STEP 4: DEPENDENT REGIONS" \
  python tools/validation/validate_assignment_step_04_dependent_regions.py \
    --compiled-model "$MODEL" \
    --independent-regions "$INDEPENDENT" \
    --output "$DEPENDENT" \
    --report "$ASSIGN/STEP4_DEPENDENT_REGIONS_REPORT.md" \
    --mode generic

run_gate "ASSIGNMENT STEP 5: COMPLETE ASSIGNMENTS" \
  python tools/validation/validate_assignment_step_05_complete_assignments.py \
    --compiled-model "$MODEL" \
    --independent-regions "$INDEPENDENT" \
    --dependent-regions "$DEPENDENT" \
    --output-json "$JSON_OUT" \
    --output-csv "$CSV_OUT" \
    --report "$ASSIGN/STEP5_COMPLETE_ASSIGNMENTS_REPORT.md" \
    --mode generic

if [[ "${OPENAMS_RUN_TESTS:-1}" == "1" ]]; then
  run_gate "SUPPORTING REGRESSION TESTS" pytest -q \
    tests/topology tests/metadata tests/io tests/constraints tests/planning \
    tests/synthesis/test_constraint_compiler.py \
    tests/synthesis/test_independent_domains.py \
    tests/synthesis/test_dependent_regions.py \
    tests/synthesis/test_complete_assignments.py \
    tests/validation/test_gate_04b_constraint_compiler.py \
    tests/technology tests/adapters/test_technology_csv_adapter.py \
    tests/adapters/test_technology_csv_nonfinite.py
fi

for path in "$MODEL" "$INDEPENDENT" "$DEPENDENT" "$JSON_OUT" "$CSV_OUT"; do
  [[ -s "$path" ]] || { echo "[FAIL] Missing or empty output: $path" >&2; exit 1; }
done

{
  echo "# OpenAMS Production Pipeline Run"
  echo
  echo "- Status: **PASS**"
  echo "- Project: \`$PROJECT\`"
  echo "- Netlist: \`$NETLIST\`"
  echo "- Subcircuit: \`$SUBCIRCUIT\`"
  echo "- Compiled model: \`$MODEL\`"
  echo "- Complete assignments: \`$JSON_OUT\`"
  echo "- Completed: \`$(date --iso-8601=seconds)\`"
} > "$LOG"

echo
echo "============================================================"
echo "[PASS] GENERIC PRODUCTION PIPELINE COMPLETE"
echo "[PASS] Circuit:              $SUBCIRCUIT"
echo "[PASS] Compiled model:       $MODEL"
echo "[PASS] Independent regions:  $INDEPENDENT"
echo "[PASS] Dependent regions:    $DEPENDENT"
echo "[PASS] Complete assignments: $JSON_OUT"
echo "[PASS] Log:                  $LOG"
echo "============================================================"

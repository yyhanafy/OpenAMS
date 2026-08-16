#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

INPUT="$ROOT/examples/two_stage_opamp/inputs"
GEN="$ROOT/examples/two_stage_opamp/generated"
EVIDENCE="$ROOT/docs/validation/evidence"
LOG="$ROOT/docs/validation/OPENAMS_STEP_0_TO_5_VALIDATION_LOG.md"

TOPOLOGY_EVIDENCE="$EVIDENCE/gate_02_topology"
METADATA_EVIDENCE="$EVIDENCE/gate_03_metadata"
CLASSIFICATION_EVIDENCE="$EVIDENCE/gate_04_constraints"
COMPILER_EVIDENCE="$EVIDENCE/gate_04b_constraint_compiler"
TECHNOLOGY_EVIDENCE="$EVIDENCE/gate_05_technology"

mkdir -p \
  "$GEN" \
  "$GEN/assignment_synthesis" \
  "$GEN/fixed_assignment_results" \
  "$GEN/optimization_results" \
  "$EVIDENCE" \
  "$(dirname "$LOG")"

echo "============================================================"
echo " OpenAMS Front-End Pipeline: Steps 0–5"
echo "============================================================"
echo "root:       $ROOT"
echo "inputs:     $INPUT"
echo "generated:  $GEN"
echo "evidence:   $EVIDENCE"
echo

###############################################################################
# STEP 0 — Verify required project inputs
###############################################################################

echo "===== STEP 0: VERIFY INPUTS ====="

required_files=(
  "$INPUT/netlist.spice"
  "$INPUT/specs.yaml"
  "$INPUT/design_rules.yaml"
  "$INPUT/design_intent.yaml"
  "$INPUT/simulation.yaml"
  "$INPUT/deck_template.spice"
)

for path in "${required_files[@]}"; do
  if [[ ! -f "$path" ]]; then
    echo "[FAIL] Missing required input: $path" >&2
    exit 1
  fi
  echo "[PASS] $path"
done

###############################################################################
# STEP 1 / GATE 02 — Parse the real two-stage-op-amp topology
###############################################################################

echo
echo "===== STEP 1: TOPOLOGY EXTRACTION ====="

rm -rf "$TOPOLOGY_EVIDENCE"

python tools/validation/validate_gate_02_topology.py \
  --netlist "$INPUT/netlist.spice" \
  --subcircuit two_stage_opamp \
  --output-dir "$TOPOLOGY_EVIDENCE"

cp "$TOPOLOGY_EVIDENCE/topology.json" \
   "$GEN/topology.json"

cp "$TOPOLOGY_EVIDENCE/topology_summary.json" \
   "$GEN/topology_summary.json"

###############################################################################
# STEP 2 / GATE 03 — Normalize the actual project metadata
###############################################################################

echo
echo "===== STEP 2: METADATA NORMALIZATION ====="

rm -rf "$METADATA_EVIDENCE"

python tools/validation/validate_gate_03_metadata.py \
  --input-dir "$INPUT" \
  --output-dir "$METADATA_EVIDENCE"

cp "$METADATA_EVIDENCE/metadata_summary.json" \
   "$GEN/metadata_summary.json"

# Serialize the complete normalized ProjectInputs object, rather than only
# storing the Gate 03 summary.
python - "$INPUT" "$GEN/project_inputs.normalized.json" <<'PY'
from __future__ import annotations

import dataclasses
import enum
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from openams.io import load_yaml_mapping
from openams.metadata import normalize_project_inputs


def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return {
            field.name: jsonable(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }

    if isinstance(value, enum.Enum):
        return jsonable(value.value)

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, Mapping):
        return {
            str(key): jsonable(item)
            for key, item in value.items()
        }

    if isinstance(value, (tuple, list)):
        return [jsonable(item) for item in value]

    if isinstance(value, (set, frozenset)):
        return sorted(
            (jsonable(item) for item in value),
            key=repr,
        )

    if hasattr(value, "__dict__"):
        return {
            str(key): jsonable(item)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }

    return value


input_dir = Path(sys.argv[1])
output = Path(sys.argv[2])

project = normalize_project_inputs(
    specifications=load_yaml_mapping(input_dir / "specs.yaml"),
    design_intent=load_yaml_mapping(input_dir / "design_intent.yaml"),
    design_rules=load_yaml_mapping(input_dir / "design_rules.yaml"),
    simulation=load_yaml_mapping(input_dir / "simulation.yaml"),
)

payload = {
    "artifact": "openams.project_inputs",
    "schema_version": 1,
    "source_directory": str(input_dir),
    "project_inputs": jsonable(project),
}

output.write_text(
    json.dumps(payload, indent=2, default=str) + "\n",
    encoding="utf-8",
)

print(f"[PASS] wrote {output}")
PY

###############################################################################
# STEP 3 / GATE 04A — Classify actual two-stage design-intent declarations
###############################################################################

echo
echo "===== STEP 3: CONSTRAINT CLASSIFICATION ====="

rm -rf "$CLASSIFICATION_EVIDENCE"

python tools/validation/validate_gate_04_constraint_classification.py \
  --design-intent "$INPUT/design_intent.yaml" \
  --design-rules "$INPUT/design_rules.yaml" \
  --output-dir "$CLASSIFICATION_EVIDENCE"

cp "$CLASSIFICATION_EVIDENCE/constraint_classification.json" \
   "$GEN/constraint_classification.json"

cp "$CLASSIFICATION_EVIDENCE/compiler_constraints.json" \
   "$GEN/compiler_constraints.json"

###############################################################################
# STEP 4 / GATE 04B — Compile actual canonical circuit-current constraints
###############################################################################

echo
echo "===== STEP 4: CONSTRAINT COMPILATION ====="

rm -rf "$COMPILER_EVIDENCE"

python tools/validation/validate_gate_04b_constraint_compiler.py \
  --constraints "$GEN/compiler_constraints.json" \
  --output-dir "$COMPILER_EVIDENCE"

cp "$COMPILER_EVIDENCE/compiled_constraints.json" \
   "$GEN/compiled_constraints.json"

cp "$COMPILER_EVIDENCE/compiler_diagnostics.json" \
   "$GEN/compiler_diagnostics.json"

# execution_results.json is validation evidence using representative rows.
# It is copied with an explicit validation-only name so it is not mistaken
# for a synthesized circuit operating-point result.
cp "$COMPILER_EVIDENCE/execution_results.json" \
   "$GEN/constraint_compiler_validation_results.json"

###############################################################################
# STEP 5 / GATE 05 — Load and validate the configured SKY130 technology source
###############################################################################

echo
echo "===== STEP 5: TECHNOLOGY MODEL ====="

rm -rf "$TECHNOLOGY_EVIDENCE"

python tools/validation/validate_gate_05_technology.py \
  --input-dir "$INPUT" \
  --output-dir "$TECHNOLOGY_EVIDENCE"

cp "$TECHNOLOGY_EVIDENCE/technology_summary.json" \
   "$GEN/technology_summary.json"

###############################################################################
# STEP 5 FINAL HANDOFF — Build canonical compiled circuit model
###############################################################################

echo
echo "===== STEP 5: BUILD COMPILED CIRCUIT MODEL ====="

python - "$GEN" "$INPUT" <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


generated = Path(sys.argv[1])
inputs = Path(sys.argv[2])


def load_json(name: str) -> Any:
    path = generated / name
    if not path.is_file():
        raise SystemExit(f"missing required Step 5 artifact: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


topology = load_json("topology.json")
project_inputs = load_json("project_inputs.normalized.json")
classification = load_json("constraint_classification.json")
compiler_constraints = load_json("compiler_constraints.json")
compiled_constraints = load_json("compiled_constraints.json")
compiler_diagnostics = load_json("compiler_diagnostics.json")
technology = load_json("technology_summary.json")

diagnostic_statuses = [
    item.get("status")
    for item in compiler_diagnostics
    if isinstance(item, dict)
]

input_files = [
    inputs / "netlist.spice",
    inputs / "specs.yaml",
    inputs / "design_rules.yaml",
    inputs / "design_intent.yaml",
    inputs / "simulation.yaml",
    inputs / "deck_template.spice",
]

model = {
    "artifact": "openams.compiled_circuit_model",
    "schema_version": 1,
    "circuit_name": topology.get("circuit_name"),
    "status": "READY_FOR_ASSIGNMENT_SYNTHESIS",
    "source_inputs": {
        path.name: {
            "path": str(path),
            "sha256": sha256(path),
        }
        for path in input_files
    },
    "topology": topology,
    "project_inputs": project_inputs.get(
        "project_inputs",
        project_inputs,
    ),
    "constraint_model": {
        "classification_count": classification.get(
            "classification_count",
            0,
        ),
        "category_counts": classification.get(
            "category_counts",
            {},
        ),
        "canonical_constraints": compiler_constraints,
        "compiled_constraints": compiled_constraints,
        "compiler_diagnostics": compiler_diagnostics,
        "all_constraints_compiled": (
            bool(diagnostic_statuses)
            and all(
                status == "compiled"
                for status in diagnostic_statuses
            )
        ),
        "topology_specific_relations": [
            item
            for item in classification.get("classified_items", [])
            if item.get("category") == "topology_heuristic"
        ],
    },
    "synthesis_interface": {
        "independent_variables": [
            item
            for item in classification.get("classified_items", [])
            if item.get("category") == "synthesis_parameter"
        ],
        "dependent_quantities": [
            item
            for item in classification.get("classified_items", [])
            if item.get("category")
            == "dependent_quantity_declaration"
        ],
        "dependency_groups": [
            item
            for item in classification.get("classified_items", [])
            if item.get("category") == "dependency_group"
        ],
    },
    "technology": technology,
    "handoff": {
        "next_stage": "assignment_synthesis",
        "expected_output_directory": str(
            generated / "assignment_synthesis"
        ),
        "note": (
            "This artifact contains the real topology, normalized metadata, "
            "canonical and compiled design-intent constraints, and configured "
            "SKY130 technology metadata. It does not yet contain synthesized "
            "full-circuit assignments or ngspice results."
        ),
    },
}

output = generated / "compiled_circuit_model.json"
output.write_text(
    json.dumps(model, indent=2, default=str) + "\n",
    encoding="utf-8",
)

manifest_files = [
    "topology.json",
    "topology_summary.json",
    "metadata_summary.json",
    "project_inputs.normalized.json",
    "constraint_classification.json",
    "compiler_constraints.json",
    "compiled_constraints.json",
    "compiler_diagnostics.json",
    "constraint_compiler_validation_results.json",
    "technology_summary.json",
    "compiled_circuit_model.json",
]

manifest = {
    "artifact": "openams.frontend_pipeline_manifest",
    "schema_version": 1,
    "status": "PASS",
    "completed_through_step": 5,
    "artifacts": {
        name: {
            "path": str(generated / name),
            "sha256": sha256(generated / name),
        }
        for name in manifest_files
    },
    "next_stage": "assignment_synthesis",
}

(generated / "frontend_pipeline_manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n",
    encoding="utf-8",
)

report = f"""# OpenAMS Steps 0–5 Front-End Report

## Result

- **Status:** PASS
- **Circuit:** `{model["circuit_name"]}`
- **Completed through:** Step 5
- **Next stage:** Assignment synthesis

## Topology

- **Devices:** {topology.get("device_count")}
- **Nodes:** {topology.get("node_count")}

## Constraint Model

- **Classified declarations:** {classification.get("classification_count")}
- **Canonical compiler constraints:** {len(compiler_constraints)}
- **Compiled constraints:** {len(compiled_constraints)}
- **All compiler diagnostics passed:** {model["constraint_model"]["all_constraints_compiled"]}

## Technology

- **Technology:** `{technology.get("technology_name")}`
- **Provider:** `{technology.get("provider")}`
- **Rows:** {technology.get("row_count")}
- **Status:** `{technology.get("status")}`

## Canonical Step 5 Output

`{output}`

This file is the production handoff from the OpenAMS front end to assignment
synthesis. The constraint-compiler execution-results file is validation-only
because its candidate rows are representative test rows, not actual synthesized
two-stage-op-amp assignments.
"""

(generated / "STEP5_REPORT.md").write_text(
    report,
    encoding="utf-8",
)

print(f"[PASS] wrote {output}")
print(f"[PASS] wrote {generated / 'frontend_pipeline_manifest.json'}")
print(f"[PASS] wrote {generated / 'STEP5_REPORT.md'}")
PY

###############################################################################
# Verify all canonical Step 5 outputs
###############################################################################

echo
echo "===== VERIFY CANONICAL STEP 5 ARTIFACTS ====="

expected_artifacts=(
  "$GEN/topology.json"
  "$GEN/topology_summary.json"
  "$GEN/metadata_summary.json"
  "$GEN/project_inputs.normalized.json"
  "$GEN/constraint_classification.json"
  "$GEN/compiler_constraints.json"
  "$GEN/compiled_constraints.json"
  "$GEN/compiler_diagnostics.json"
  "$GEN/constraint_compiler_validation_results.json"
  "$GEN/technology_summary.json"
  "$GEN/compiled_circuit_model.json"
  "$GEN/frontend_pipeline_manifest.json"
  "$GEN/STEP5_REPORT.md"
)

for path in "${expected_artifacts[@]}"; do
  if [[ ! -s "$path" ]]; then
    echo "[FAIL] Missing or empty artifact: $path" >&2
    exit 1
  fi
  echo "[PASS] $path"
done

###############################################################################
# Supporting regression tests
###############################################################################

echo
echo "===== RUN SUPPORTING TESTS ====="

pytest -q \
  tests/topology \
  tests/metadata \
  tests/io \
  tests/constraints \
  tests/planning \
  tests/synthesis/test_constraint_compiler.py \
  tests/validation/test_gate_04b_constraint_compiler.py \
  tests/technology \
  tests/adapters/test_technology_csv_adapter.py \
  tests/adapters/test_technology_csv_nonfinite.py

###############################################################################
# Append permanent execution record
###############################################################################

{
  echo
  echo "## Production front-end rerun — Steps 0–5"
  echo
  echo "- Status: **PASS**"
  echo "- Generated directory: \`$GEN\`"
  echo "- Canonical handoff: \`$GEN/compiled_circuit_model.json\`"
  echo "- Manifest: \`$GEN/frontend_pipeline_manifest.json\`"
  echo
  echo "### Production artifacts"
  echo
  while IFS= read -r path; do
    printf -- '- `%s`\n' "$path"
  done < <(
    find "$GEN" \
      -maxdepth 1 \
      -type f \
      | sort
  )
  echo
} >> "$LOG"

echo
echo "============================================================"
echo "[PASS] STEPS 0–5 COMPLETE"
echo "[PASS] Compiled model:"
echo "       $GEN/compiled_circuit_model.json"
echo "[PASS] Manifest:"
echo "       $GEN/frontend_pipeline_manifest.json"
echo "============================================================"

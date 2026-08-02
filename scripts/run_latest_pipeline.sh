#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

INPUT="examples/two_stage_opamp/inputs"
GEN="examples/two_stage_opamp/generated"
SYNTH="$GEN/assignment_synthesis"
mkdir -p "$GEN" "$SYNTH"

python -m openams.cli.validate_metadata \
  --specs "$INPUT/specs.yaml" \
  --rules "$INPUT/design_rules.yaml" \
  --simulation "$INPUT/simulation.yaml"

python -m openams.cli.compile_design_rules \
  --rules "$INPUT/design_rules.yaml" \
  --output "$GEN/design_rules.compiled.yaml" \
  --report "$GEN/design_rule_validation.json"

python -m openams.cli.extract_topology \
  --netlist "$INPUT/netlist.spice" \
  --output "$GEN/topology.json"

python -m openams.cli.compile_design_intent \
  --netlist "$INPUT/netlist.spice" \
  --intent "$INPUT/design_intent.yaml" \
  --rules "$INPUT/design_rules.yaml" \
  --topology-output "$GEN/topology.intent.json" \
  --expanded-output "$GEN/design_intent.expanded.yaml"

python -m openams.cli.build_valid_assignments \
  --expanded-rules "$GEN/design_intent.expanded.yaml" \
  --output-dir "$SYNTH" \
  --report-json "$SYNTH/synthesis_report.json"

echo "[PASS] Assignment synthesis and route classification completed."

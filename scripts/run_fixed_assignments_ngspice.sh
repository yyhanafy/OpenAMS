#!/usr/bin/env bash
set -euo pipefail

ROOT="${OPENAMS_ROOT:-$HOME/AMS-Tutorial/openams}"
ASSIGNMENTS_DIR="${ASSIGNMENTS_DIR:-$ROOT/runtime/two_stage_opamp_fixed_assignments}"
RUN_DIR="${RUN_DIR:-$ROOT/runtime/two_stage_opamp_fixed_assignments/ngspice_results}"
MANIFEST="${MANIFEST:-$ROOT/runtime/two_stage_opamp_fixed_assignments/simulation_manifest.json}"
BACKEND="${BACKEND:-ngspice}"
JOBS="${JOBS:-1}"

cd "$ROOT"
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

if [[ ! -d "$ASSIGNMENTS_DIR" ]]; then
  echo "[FAIL] assignments directory not found: $ASSIGNMENTS_DIR" >&2
  exit 2
fi
if [[ ! -f "$MANIFEST" ]]; then
  echo "[FAIL] simulation manifest not found: $MANIFEST" >&2
  echo "       Copy simulation_manifest.json there or set MANIFEST=/path/to/file" >&2
  exit 2
fi
if ! command -v ngspice >/dev/null 2>&1; then
  echo "[FAIL] ngspice is not on PATH" >&2
  exit 2
fi
if [[ -z "${SKY130_LIB:-}" ]]; then
  DEFAULT_SKY130_LIB="$HOME/pdks/open_pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice"
  if [[ -f "$DEFAULT_SKY130_LIB" ]]; then
    export SKY130_LIB="$DEFAULT_SKY130_LIB"
  else
    echo "[FAIL] SKY130_LIB is unset and default library was not found:" >&2
    echo "       $DEFAULT_SKY130_LIB" >&2
    exit 2
  fi
fi

mkdir -p "$RUN_DIR"
cp -f "$MANIFEST" "$RUN_DIR/simulation_manifest.used.json"

HELP="$(python -m openams.cli.run_fixed_assignments --help 2>&1)" || {
  echo "[FAIL] openams.cli.run_fixed_assignments is unavailable" >&2
  exit 3
}

pick_option() {
  local candidate
  for candidate in "$@"; do
    if grep -q -- "$candidate" <<<"$HELP"; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

ASSIGN_OPT="$(pick_option --assignments-dir --assignments --input-dir)" || {
  echo "[FAIL] Cannot identify assignments option from run_fixed_assignments --help" >&2
  printf '%s\n' "$HELP" >&2
  exit 3
}
MANIFEST_OPT="$(pick_option --manifest --simulation-manifest --simulation)" || {
  echo "[FAIL] Cannot identify manifest option from run_fixed_assignments --help" >&2
  printf '%s\n' "$HELP" >&2
  exit 3
}
OUTPUT_OPT="$(pick_option --output-dir --run-dir --output)" || {
  echo "[FAIL] Cannot identify output option from run_fixed_assignments --help" >&2
  printf '%s\n' "$HELP" >&2
  exit 3
}

CMD=(python -m openams.cli.run_fixed_assignments
  "$ASSIGN_OPT" "$ASSIGNMENTS_DIR"
  "$MANIFEST_OPT" "$MANIFEST"
  "$OUTPUT_OPT" "$RUN_DIR")

if BACKEND_OPT="$(pick_option --backend)"; then
  CMD+=("$BACKEND_OPT" "$BACKEND")
fi
if JOBS_OPT="$(pick_option --jobs --workers --max-workers)"; then
  CMD+=("$JOBS_OPT" "$JOBS")
fi

printf '[INFO] ROOT=%s\n' "$ROOT"
printf '[INFO] ASSIGNMENTS_DIR=%s\n' "$ASSIGNMENTS_DIR"
printf '[INFO] RUN_DIR=%s\n' "$RUN_DIR"
printf '[INFO] MANIFEST=%s\n' "$MANIFEST"
printf '[INFO] SKY130_LIB=%s\n' "$SKY130_LIB"
printf '[INFO] command:'
printf ' %q' "${CMD[@]}"
printf '\n'

"${CMD[@]}" 2>&1 | tee "$RUN_DIR/run_fixed_assignments.log"

python - "$ASSIGNMENTS_DIR" "$RUN_DIR" <<'PY'
from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

assignments_dir = Path(sys.argv[1])
run_dir = Path(sys.argv[2])


def flatten(obj: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(obj, dict):
        for key, value in obj.items():
            child = f"{prefix}.{key}" if prefix else str(key)
            out.update(flatten(value, child))
    elif isinstance(obj, list):
        if all(not isinstance(x, (dict, list)) for x in obj):
            out[prefix] = ";".join(str(x) for x in obj)
    else:
        out[prefix] = obj
    return out


def first(flat: dict[str, Any], names: list[str], default: Any = "") -> Any:
    for name in names:
        if name in flat and flat[name] not in (None, ""):
            return flat[name]
    for key, value in flat.items():
        leaf = key.rsplit(".", 1)[-1]
        if leaf in names and value not in (None, ""):
            return value
    return default


def load_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def assignment_id_from_path(path: Path) -> str:
    for part in reversed(path.parts):
        if part.startswith(("assignment_", "candidate_")):
            return part
    return path.parent.name

# Load assignment values from CSV and JSON artifacts.
assignments: dict[str, dict[str, Any]] = {}
for p in assignments_dir.rglob("*.csv"):
    try:
        with p.open(newline="") as f:
            for row in csv.DictReader(f):
                aid = row.get("assignment_id") or row.get("full_assignment_id") or row.get("candidate_id")
                if aid:
                    assignments.setdefault(str(aid), {}).update(row)
    except Exception:
        pass
for p in assignments_dir.rglob("*.json"):
    data = load_json(p)
    if not data:
        continue
    flat = flatten(data)
    aid = first(flat, ["assignment_id", "full_assignment_id", "candidate_id"], "")
    if not aid and p.stem.startswith(("assignment_", "candidate_")):
        aid = p.stem
    if aid:
        assignments.setdefault(str(aid), {}).update(flat)

# Load one or more result JSON files per assignment.
result_files = []
for pattern in ("result.json", "results.json", "metrics.json", "summary.json", "simulation_result.json"):
    result_files.extend(run_dir.rglob(pattern))

results: dict[str, dict[str, Any]] = {}
for p in sorted(set(result_files)):
    data = load_json(p)
    if not data:
        continue
    flat = flatten(data)
    aid = str(first(flat, ["assignment_id", "full_assignment_id", "candidate_id"], ""))
    if not aid:
        aid = assignment_id_from_path(p)
    results.setdefault(aid, {}).update(flat)
    results[aid]["result_file"] = str(p)

all_ids = sorted(set(assignments) | set(results))
rows: list[dict[str, Any]] = []
for aid in all_ids:
    af = assignments.get(aid, {})
    rf = results.get(aid, {})
    merged = {**af, **rf}
    row = {
        "assignment_id": aid,
        "dc_status": first(merged, ["dc_status", "dc.status", "dc_pass", "dc_valid", "valid_dc"], ""),
        "ac_status": first(merged, ["ac_status", "ac.status", "ac_pass", "ac_valid"], ""),
        "overall_status": first(merged, ["status", "overall_status", "spec_status", "passed"], ""),
        "failure_reasons": first(merged, ["failure_reasons", "failures", "reasons", "reason"], ""),
        "vout_dc_v": first(merged, ["vout_dc", "vout_dc_v", "dc.vout_dc"], ""),
        "supply_current_a": first(merged, ["supply_current_a", "supply_current", "idd_a", "dc.supply_current_a"], ""),
        "power_w": first(merged, ["power_w", "power", "dc.power_w"], ""),
        "gain_db": first(merged, ["gain_db", "dc_gain_db", "ac.gain_db"], ""),
        "ugb_hz": first(merged, ["ugb_hz", "unity_gain_hz", "unity_gain_bandwidth_hz", "ac.ugb_hz"], ""),
        "phase_margin_deg": first(merged, ["phase_margin_deg", "pm_deg", "phase_margin", "ac.phase_margin_deg"], ""),
        "vbias_v": first(merged, ["vbias_v", "vbias"], ""),
        "c_miller_f": first(merged, ["c_miller", "c_miller_f", "cc", "cc_f"], ""),
        "w_m1_um": first(merged, ["w_m1_um", "w1_um", "w_input_um"], ""),
        "w_m2_um": first(merged, ["w_m2_um", "w2_um"], ""),
        "w_m3_um": first(merged, ["w_m3_um", "w3_um", "w_load_um"], ""),
        "w_m4_um": first(merged, ["w_m4_um", "w4_um"], ""),
        "w_m5_um": first(merged, ["w_m5_um", "w5_um", "w_tail_um"], ""),
        "w_m6_um": first(merged, ["w_m6_um", "w6_um", "w_stage2_um"], ""),
        "w_m7_um": first(merged, ["w_m7_um", "w7_um", "w_sink_um"], ""),
        "result_file": rf.get("result_file", ""),
    }
    # Preserve useful assignment columns not already normalized.
    for key, value in af.items():
        leaf = key.rsplit(".", 1)[-1]
        if leaf not in row and leaf not in {"assignment_id", "full_assignment_id"}:
            row[leaf] = value
    rows.append(row)

preferred = [
    "assignment_id", "dc_status", "ac_status", "overall_status", "failure_reasons",
    "vout_dc_v", "supply_current_a", "power_w", "gain_db", "ugb_hz",
    "phase_margin_deg", "vbias_v", "c_miller_f", "w_m1_um", "w_m2_um",
    "w_m3_um", "w_m4_um", "w_m5_um", "w_m6_um", "w_m7_um", "result_file",
]
extras = sorted({k for row in rows for k in row} - set(preferred))
fields = preferred + extras

summary_csv = run_dir / "fixed_assignment_ac_dc_summary.csv"
with summary_csv.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

# Also create a compact optimizer-compatible metrics table.
comparison_fields = [
    "assignment_id", "dc_status", "ac_status", "overall_status", "failure_reasons",
    "gain_db", "ugb_hz", "phase_margin_deg", "power_w", "vout_dc_v",
    "vbias_v", "c_miller_f", "w_m1_um", "w_m2_um", "w_m3_um", "w_m4_um",
    "w_m5_um", "w_m6_um", "w_m7_um",
]
comparison_csv = run_dir / "optimizer_comparison_table.csv"
with comparison_csv.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=comparison_fields, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)

counts = {
    "assignment_count": len(all_ids),
    "result_json_count": len(set(result_files)),
    "summary_csv": str(summary_csv),
    "optimizer_comparison_csv": str(comparison_csv),
}
(run_dir / "postprocess_report.json").write_text(json.dumps(counts, indent=2) + "\n")

print(f"[PASS] wrote {summary_csv}")
print(f"[PASS] wrote {comparison_csv}")
print(f"[INFO] assignments={len(all_ids)} result_json_files={len(set(result_files))}")
PY

cat <<EOF

[PASS] Fixed-assignment ngspice run completed.

Main files to inspect:
  $RUN_DIR/fixed_assignment_ac_dc_summary.csv
  $RUN_DIR/optimizer_comparison_table.csv
  $RUN_DIR/run_fixed_assignments.log
  $RUN_DIR/postprocess_report.json

Per-assignment decks, logs, operating-point data, and JSON results remain under:
  $RUN_DIR
EOF

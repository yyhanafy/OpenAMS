#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="runtime/cleanup_backups/scan_dependency_pilot_${STAMP}"
mkdir -p "$BACKUP"
PATHS=(
  "src/openams/synthesis/two_stage_dependency_search.py"
  "src/openams/technology/continuous_device_primitives.py"
  "tools/validation/run_two_stage_dependency_pilot.py"
  "scripts/run_two_stage_dependency_pilot.sh"
  "tests/technology/test_continuous_device_primitives.py"
  "examples/two_stage_opamp/generated/assignment_synthesis/dependency_ordered_pilot"
)
for path in "${PATHS[@]}"; do
  if [[ -e "$path" ]]; then
    mkdir -p "$BACKUP/$(dirname "$path")"
    cp -a "$path" "$BACKUP/$path"
    rm -rf "$path"
    echo "[REMOVED] $path"
  fi
done
tar -czf "${BACKUP}.tgz" -C "$(dirname "$BACKUP")" "$(basename "$BACKUP")"
echo "[PASS] scan-based pilot archived: ${BACKUP}.tgz"

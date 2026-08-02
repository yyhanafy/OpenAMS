#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="runtime/cleanup_backups/mlp_least_squares_${STAMP}"
mkdir -p "$BACKUP"
MANIFEST="$BACKUP/manifest.txt"
: > "$MANIFEST"

PATHS=(
  "src/openams/synthesis/mlp_continuous_two_stage.py"
  "tools/validation/diagnose_mlp_continuous_point.py"
  "tools/validation/diagnose_mlp_kcl_point.py"
  "tools/validation/run_mlp_continuous_grid_pilot.py"
  "scripts/run_mlp_continuous_grid_pilot.sh"
  "runtime/mlp_residual_diagnostics"
  "runtime/mlp_kcl_diagnostics"
  "examples/two_stage_opamp/generated/assignment_synthesis/mlp_continuous_pilot"
)

for p in "${PATHS[@]}"; do
  if [[ -e "$p" ]]; then
    echo "$p" >> "$MANIFEST"
    mkdir -p "$BACKUP/$(dirname "$p")"
    cp -a "$p" "$BACKUP/$p"
  fi
done

if [[ -s "$MANIFEST" ]]; then
  ARCHIVE="${BACKUP}.tgz"
  tar -czf "$ARCHIVE" -C "$(dirname "$BACKUP")" "$(basename "$BACKUP")"
  echo "archive: $ARCHIVE"
fi

for p in "${PATHS[@]}"; do
  rm -rf "$p"
done

echo "===== OPENAMS CLEANUP ====="
echo "backup: $BACKUP"
echo "removed:"
if [[ -s "$MANIFEST" ]]; then sed 's/^/  - /' "$MANIFEST"; else echo "  none"; fi
echo "[PASS] obsolete least-squares experiment removed"
